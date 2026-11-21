# -*- coding: utf-8 -*-
"""
Client and parser for the farmer-input contract (issues #11 and #14).

This module has no QGIS imports, so it can run in a worker thread (QgsTask.run)
and be checked outside QGIS. It reads the saved fields from ``GET /fields`` (or
a JSON file with the same shape) and turns them into flat rows that
``farmer_layers`` puts on the map.

Contract: FARMER_INPUT_CONTRACT.md. Geometry is GeoJSON in lon/lat (EPSG:4326),
dates are ``YYYY-MM-DD``. Missing values stay empty; nothing is invented.
"""

import datetime
import json
import urllib.error
import urllib.request

DEFAULT_BASE_URL = "https://34-118-11-71.nip.io/api/v1"
USER_AGENT = "PyQgisFastApiBridge/1.0"


class FarmerDataError(Exception):
    """Error with a stable code, so the UI can tell an outage from an empty result."""

    def __init__(self, code, message, fields=None, status=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.fields = fields or []
        self.status = status

    def describe(self):
        text = f"[{self.code}] {self.message}"
        if self.status:
            text += f" (HTTP {self.status})"
        for item in self.fields:
            text += f"\n   - {item.get('path', '?')}: {item.get('message', '')}"
        return text


class FarmerData:
    """Parsed result: parcels, crop areas and warnings about skipped or incomplete data."""

    def __init__(self):
        self.parcels = []       # dicts with GeoJSON geometry and attributes
        self.crop_areas = []    # dicts with GeoJSON geometry and attributes
        self.warnings = []
        self.data_status = None
        self.field_count = 0


def fetch_fields(base_url=DEFAULT_BASE_URL, timeout=8):
    """GET {base_url}/fields. Raises FarmerDataError; an empty list is not an error."""
    url = base_url.rstrip("/") + "/fields"
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise _error_from_http(exc) from exc
    except (urllib.error.URLError, OSError) as exc:
        raise FarmerDataError(
            "SERVICE_UNAVAILABLE", f"Cannot reach {url}: {exc}"
        ) from exc
    return _decode_json(body, url)


def load_fields_file(path):
    """Read a JSON file with the same shape as the GET /fields response."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            body = handle.read()
    except OSError as exc:
        raise FarmerDataError("FILE_ERROR", f"Cannot read {path}: {exc}") from exc
    return _decode_json(body, path)


def _decode_json(body, origin):
    try:
        return json.loads(body)
    except ValueError as exc:
        raise FarmerDataError(
            "INVALID_RESPONSE", f"{origin} did not return valid JSON: {exc}"
        ) from exc


def _error_from_http(exc):
    """Map an HTTP error to the contract's {error: {code, message, fields}} shape."""
    try:
        payload = json.loads(exc.read().decode("utf-8"))
        error = payload.get("error", {})
        return FarmerDataError(
            error.get("code", f"HTTP_{exc.code}"),
            error.get("message", exc.reason),
            fields=error.get("fields"),
            status=exc.code,
        )
    except Exception:
        return FarmerDataError(f"HTTP_{exc.code}", str(exc.reason), status=exc.code)


def parse_fields(payload):
    """Turn a ``{"fields": [...], "data_status": ...}`` payload into FarmerData."""
    result = FarmerData()
    if not isinstance(payload, dict) or not isinstance(payload.get("fields"), list):
        raise FarmerDataError(
            "INVALID_RESPONSE", 'Expected an object with a "fields" list.'
        )
    result.data_status = payload.get("data_status")
    result.field_count = len(payload["fields"])
    if result.data_status is None:
        result.warnings.append('Response has no "data_status"; source is not labelled.')

    seen_parcels = set()
    for field in payload["fields"]:
        field_id = _text(field.get("field_id"))
        parcel = field.get("parcel") or {}
        parcel_id = _text(parcel.get("parcel_id"))
        field_status = field.get("data_status") or result.data_status

        if parcel_id not in seen_parcels:
            if _valid_polygon(parcel.get("geometry")):
                seen_parcels.add(parcel_id)
                result.parcels.append({
                    "geometry": parcel["geometry"],
                    "attributes": {
                        "parcel_id": parcel_id,
                        "parcel_number": _text(parcel.get("parcel_number")),
                        "field_id": field_id,
                        "data_status": _text(field_status),
                    },
                })
            else:
                result.warnings.append(
                    f"Field {field_id}: parcel {parcel_id} has no valid polygon; skipped."
                )

        for area in field.get("crop_areas") or []:
            row = _crop_area_row(field_id, parcel, area, field_status, result.warnings)
            if row:
                result.crop_areas.append(row)

        if not field.get("crop_areas"):
            result.warnings.append(f"Field {field_id} has no crop areas.")

    return result


def _crop_area_row(field_id, parcel, area, field_status, warnings):
    area_id = _text(area.get("crop_area_id"))
    if not _valid_polygon(area.get("geometry")):
        warnings.append(f"Field {field_id}: crop area {area_id} has no valid polygon; skipped.")
        return None

    crop = area.get("crop") or {}
    farmer_crop = crop.get("farmer_crop_id")
    map_crop = crop.get("map_crop_id")
    issues = []

    if not farmer_crop:
        issues.append("farmer_crop missing")

    sowing = area.get("sowing_date")
    if not sowing:
        issues.append("sowing_date missing")
    elif not _is_iso_date(sowing):
        issues.append(f"sowing_date invalid ({sowing})")
        sowing = None

    sprays = area.get("past_sprays") or []
    spray_dates = []
    for index, spray in enumerate(sprays):
        date_text = spray.get("date")
        days = spray.get("protection_duration_days")
        if not _is_iso_date(date_text):
            issues.append(f"spray[{index}] date invalid")
        else:
            spray_dates.append(date_text)
        if not isinstance(days, int) or days <= 0:
            issues.append(f"spray[{index}] protection_duration_days invalid")

    return {
        "geometry": area["geometry"],
        "attributes": {
            "field_id": field_id,
            "crop_area_id": area_id,
            "parcel_id": _text(parcel.get("parcel_id")),
            "parcel_number": _text(parcel.get("parcel_number")),
            "farmer_crop_id": _text(farmer_crop),
            "map_crop_id": _text(map_crop),
            # Farmer and map values stay separate; this flag only compares them.
            "crop_differs": bool(farmer_crop and map_crop and farmer_crop != map_crop),
            "sowing_date": sowing,
            "spray_count": len(sprays),
            "last_spray_date": max(spray_dates) if spray_dates else None,
            "past_sprays": json.dumps(sprays, ensure_ascii=False),
            "data_issues": "; ".join(issues),
            "data_status": _text(field_status),
        },
    }


def geojson_to_wkt(geometry):
    """Polygon / MultiPolygon GeoJSON to WKT (lon lat order)."""

    def ring(points):
        return "(" + ", ".join(f"{p[0]} {p[1]}" for p in points) + ")"

    def polygon(rings):
        return "(" + ", ".join(ring(r) for r in rings) + ")"

    if geometry["type"] == "Polygon":
        return "POLYGON " + polygon(geometry["coordinates"])
    return "MULTIPOLYGON (" + ", ".join(polygon(p) for p in geometry["coordinates"]) + ")"


def _valid_polygon(geometry):
    """Closed rings with at least four positions; Polygon or MultiPolygon only."""
    if not isinstance(geometry, dict):
        return False
    kind = geometry.get("type")
    coords = geometry.get("coordinates")
    if kind == "Polygon":
        polygons = [coords]
    elif kind == "MultiPolygon":
        polygons = coords
    else:
        return False
    try:
        for rings in polygons:
            if not rings:
                return False
            for points in rings:
                if len(points) < 4 or points[0] != points[-1]:
                    return False
                for point in points:
                    float(point[0])
                    float(point[1])
    except (TypeError, ValueError, IndexError):
        return False
    return True


def _is_iso_date(value):
    if not isinstance(value, str):
        return False
    try:
        datetime.date.fromisoformat(value)
        return True
    except ValueError:
        return False


def _text(value):
    return None if value is None else str(value)
