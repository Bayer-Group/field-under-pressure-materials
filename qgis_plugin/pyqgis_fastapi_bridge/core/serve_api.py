# -*- coding: utf-8 -*-
"""
Client and parser for the read contract (docs/serve_read_contract.md, issue #49).

Pure Python (no QGIS imports) so it can be unit-tested. The API is a thin SELECT over the
views of schema serve; this module only reads it:

  POST /sandbox {"mode"}          token for a visitor (farmer role, copy of a ready farm), no password
  POST /login {login, password}   token for a development or analyst account
  GET  /clock                     the shown "today" (dates are already shifted for the demo)
  GET  /me/crop-areas             FeatureCollection of crop areas with today's class
  GET  /crop-areas/{id}           one crop area with soil and crop-map context
  GET  /crop-areas/{id}/risk      one row per day (from, to)
  GET  /crop-areas/{id}/changes   when and why the class, status or conditions_met changed
  GET  /grid/risk?date=           FeatureCollection of 4 km cells (squares) for one day, analyst only

Dates in the answers are never converted here. Fields can be null; null stays None (never 0).
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from .farmer_fields import FarmerDataError

USER_AGENT = "FieldUnderPressure-QGIS/0.2"
DEFAULT_BASE_URL = "https://34-118-11-71.nip.io/api/v1"

SANDBOX_PATH = "/sandbox"
LOGIN_PATH = "/login"
CLOCK_PATH = "/clock"
CROP_AREA_PATH = "/me/crop-areas"
CROP_AREA_DETAIL_PATH = "/crop-areas/{id}"
CROP_AREA_RISK_PATH = "/crop-areas/{id}/risk"
CROP_AREA_CHANGES_PATH = "/crop-areas/{id}/changes"
GRID_RISK_PATH = "/grid/risk"
GRID_SURFACE_PATH = "/grid/risk/surface"

RISK_CLASSES = ("low", "medium", "high")

# Layers the plugin can load from the API, in the order shown in the panel.
# (id, title, request, role needed or None, available). A new serve view = one more line here
# (and a parser/layer builder if its shape is new). Soil, weather and the crop map come back when the API has them (issue #12).
API_LAYERS = [
    ("crop_areas", "Crop areas with today's risk", "GET /me/crop-areas + /crop-areas/{id} (soil)", None, True),
    ("grid_surface", "Septoria weather conditions: heatmap (date)", "GET /grid/risk, smoothed raster of wet-run hours H", "analyst", True),
    ("grid_cells", "Septoria weather conditions: 4 km cells (date)", "GET /grid/risk, exact values per cell", "analyst", True),
]
DEFAULT_LAYERS = ("crop_areas",)

# Details are read per crop area; above this number only the first ones get the soil context
# (the analyst sees every farm) and the rest can be read with the risk-history button.
DETAIL_LIMIT = 120
DETAIL_WORKERS = 6

# (name, kind) - kind is one of: text, int, real, bool, date
# serve.crop_area_today (GET /me/crop-areas)
CROP_AREA_FIELDS = [
    ("crop_area_id", "text"),
    ("field_id", "text"),
    ("owner_id", "text"),
    ("field_name", "text"),
    ("farmer_crop_id", "text"),
    ("date", "date"),
    ("risk_class", "text"),
    ("status", "text"),
    ("conditions_met", "bool"),
    ("h_hours", "int"),
    ("growth_stage_zone", "text"),
    ("protected_until", "date"),
]

# serve.crop_area (GET /crop-areas/{id}): the context added to the attribute table
CROP_AREA_DETAIL_FIELDS = [
    ("data_status", "text"),
    ("sowing_date", "date"),
    ("bbch_override", "int"),
    ("soil_texture", "text"),
    ("soil_ph", "real"),
    ("soil_clay", "real"),
    ("soil_sand", "real"),
    ("soil_silt", "real"),
    ("soil_om", "real"),
    ("soil_cec", "real"),
    ("soil_bulk_density", "real"),
    ("soil_coverage", "real"),
    ("map_crop_class_code", "text"),
    ("farmer_class_code", "text"),
    ("crop_differs", "bool"),
]

# serve.grid_risk_daily (GET /grid/risk)
GRID_FIELDS = [
    ("grid_id", "text"),
    ("date", "date"),
    ("risk_class", "text"),
    ("uncertain", "bool"),
    ("h_low", "int"),
    ("h_high", "int"),
    ("coverage", "real"),
]

# serve.risk_daily (GET /crop-areas/{id}/risk), one row per day
RISK_DAY_FIELDS = [
    ("date", "date"),
    ("risk_class", "text"),
    ("status", "text"),
    ("conditions_met", "bool"),
    ("h_hours", "int"),
    ("h_low", "int"),
    ("h_high", "int"),
    ("coverage", "real"),
    ("protected_until", "date"),
    ("growth_stage_zone", "text"),
    ("growth_stage_source", "text"),
    ("gdd_since_resumption", "real"),
    ("reasons", "text"),
    ("model_version", "text"),
]


class ServeData:
    """Parsed answer: rows (GeoJSON geometry + attributes), warnings and the data label."""

    def __init__(self, kind, fields):
        self.kind = kind            # "crop_areas" or "grid"
        self.fields = list(fields)
        self.rows = []
        self.warnings = []
        self.data_status = None     # "mock" / "replay" / "live" when the source says so
        self.dates = set()
        self.geometry_type = None   # "Polygon", "MultiPolygon" or "Point", from the features
        self.details_missing = 0    # crop areas without the context of GET /crop-areas/{id}
        self.limited = None         # (area label, kept, received) when limited to an area


# ----- HTTP -----

def _request(base_url, path, params=None, token=None, body=None, method="GET", timeout=20):
    url = base_url.rstrip("/") + path
    if params:
        query = {k: v for k, v in params.items() if v is not None}
        if query:
            url += "?" + urllib.parse.urlencode(query)
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            text = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise _http_error(exc, path) from exc
    except (urllib.error.URLError, OSError) as exc:
        raise FarmerDataError("SERVICE_UNAVAILABLE", f"Cannot reach {url}: {exc}") from exc
    try:
        return json.loads(text) if text else None
    except ValueError as exc:
        raise FarmerDataError("INVALID_RESPONSE", f"{url} did not return valid JSON: {exc}") from exc


_HINTS = {
    401: "No or expired token: start a sandbox or log in again.",
    403: "This needs another role (the grid is for the analyst).",
    404: "Not found (or a crop area of somebody else).",
    429: "Too many requests; wait a moment.",
    503: "The API is busy or read-only.",
}


def _http_error(exc, path):
    """FastAPI answers {"detail": "..."}; keep the status and add a short hint."""
    detail = None
    try:
        payload = json.loads(exc.read().decode("utf-8"))
        detail = payload.get("detail") if isinstance(payload, dict) else None
        if isinstance(detail, list):        # validation errors (422)
            detail = "; ".join(str(d.get("msg", d)) if isinstance(d, dict) else str(d) for d in detail)
    except Exception:
        pass
    message = f"{exc.code} {detail or exc.reason} ({path})"
    hint = "Check the login and the password." if (exc.code == 401 and path == LOGIN_PATH) else _HINTS.get(exc.code)
    if hint:
        message += " - " + hint
    return FarmerDataError(f"HTTP_{exc.code}", message, status=exc.code)


def fetch(base_url, path, params=None, token=None, timeout=20):
    """GET {base_url}{path}. Raises FarmerDataError with a stable code."""
    return _request(base_url, path, params=params, token=token, timeout=timeout)


def fetch_surface_asc(base_url, token, date, dest_dir, timeout=60):
    """GET /grid/risk/surface?format=asc&value=hours: the heatmap as an ESRI ASCII Grid (EPSG:4326).

    Saved in dest_dir; returns the path. Raises FarmerDataError (analyst role, a day without data...).
    """
    query = urllib.parse.urlencode({k: v for k, v in {"format": "asc", "value": "hours", "date": date}.items() if v})
    url = base_url.rstrip("/") + GRID_SURFACE_PATH + "?" + query
    headers = {"User-Agent": USER_AGENT, "Accept": "text/plain, */*"}
    if token:
        headers["Authorization"] = "Bearer " + token
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        raise _http_error(exc, GRID_SURFACE_PATH) from exc
    except (urllib.error.URLError, OSError) as exc:
        raise FarmerDataError("SERVICE_UNAVAILABLE", f"Cannot reach {url}: {exc}") from exc
    if not body.lstrip().lower().startswith(b"ncols"):
        raise FarmerDataError("INVALID_RESPONSE", f"{url} did not return an ESRI ASCII Grid.")
    path = os.path.join(dest_dir, f"risk_surface_hours_{date or 'today'}.asc")
    with open(path, "wb") as fh:
        fh.write(body)
    return path


def start_sandbox(base_url, mode="mock"):
    """POST /sandbox. Returns {token, owner_id, role, mode, expires_in, ...}."""
    answer = _request(base_url, SANDBOX_PATH, body={"mode": mode}, method="POST")
    return _session(answer, "sandbox")


def login(base_url, login_name, password):
    """POST /login. Returns {token, owner_id, role, expires_in, ...}."""
    answer = _request(base_url, LOGIN_PATH, body={"login": login_name, "password": password}, method="POST")
    return _session(answer, "login")


def _session(answer, what):
    if not isinstance(answer, dict) or not answer.get("token"):
        raise FarmerDataError("INVALID_RESPONSE", f"The {what} answer has no token.")
    return answer


def get_clock(base_url):
    """GET /clock -> {"today": "YYYY-MM-DD", "mode": ...} (the shown today)."""
    answer = _request(base_url, CLOCK_PATH)
    if not isinstance(answer, dict) or not answer.get("today"):
        raise FarmerDataError("INVALID_RESPONSE", "GET /clock has no 'today'.")
    return answer


def load_file(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            body = handle.read()
    except OSError as exc:
        raise FarmerDataError("FILE_ERROR", f"Cannot read {path}: {exc}") from exc
    try:
        return json.loads(body)
    except ValueError as exc:
        raise FarmerDataError("INVALID_RESPONSE", f"{path} is not valid JSON: {exc}") from exc


# ----- crop areas -----

def bbox_param(bbox):
    """(xmin, ymin, xmax, ymax) in EPSG:4326 -> "xmin,ymin,xmax,ymax" for ?bbox= (None stays None)."""
    if not bbox:
        return None
    return ",".join(f"{v:.6f}" for v in bbox)


def keep_rows(data, predicate, area_label):
    """Keep only the rows whose GeoJSON geometry passes predicate (the limit to an area)."""
    before = len(data.rows)
    data.rows = [row for row in data.rows if predicate(row["geometry"])]
    data.dates = {r["attributes"]["date"] for r in data.rows if r["attributes"].get("date")}
    data.limited = (area_label, len(data.rows), before)
    return data


def parse_crop_areas(payload):
    return _parse(payload, "crop_areas", CROP_AREA_FIELDS, ("Polygon", "MultiPolygon"), "crop_area_id")


def add_details(data, base_url, token, limit=DETAIL_LIMIT, workers=DETAIL_WORKERS):
    """Add the soil and crop-map context of GET /crop-areas/{id} to every row (in place).

    Missing details stay None. The data label comes from the fields (serve.crop_area.data_status):
    "mock" if any crop area is mock, because mock data must never be shown as real.
    """
    known = {name for name, _kind in data.fields}
    data.fields += [f for f in CROP_AREA_DETAIL_FIELDS if f[0] not in known]
    rows = data.rows[:limit]

    def one(row):
        path = CROP_AREA_DETAIL_PATH.format(id=urllib.parse.quote(row["attributes"]["crop_area_id"], safe=""))
        try:
            feature = fetch(base_url, path, token=token)
            return row, (feature or {}).get("properties") or {}, None
        except FarmerDataError as exc:
            return row, None, exc

    statuses = set()
    errors = 0
    if rows:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for row, props, error in pool.map(one, rows):
                if props is None:
                    errors += 1
                    if errors <= 3:
                        data.warnings.append(f"{row['attributes']['crop_area_id']}: no details ({error.message}).")
                    continue
                for name, kind in CROP_AREA_DETAIL_FIELDS:
                    row["attributes"][name] = _convert(props.get(name), kind)
                if props.get("data_status"):
                    statuses.add(props["data_status"])
    for row in data.rows:
        for name, _kind in CROP_AREA_DETAIL_FIELDS:
            row["attributes"].setdefault(name, None)
    data.details_missing = errors + max(0, len(data.rows) - limit)
    if errors > 3:
        data.warnings.append(f"... no details for {errors} crop areas in total.")
    if len(data.rows) > limit:
        data.warnings.append(
            f"Soil context read for the first {limit} of {len(data.rows)} crop areas; "
            "use the risk history of a selected crop area for the others."
        )
    if data.data_status is None and statuses:
        data.data_status = "mock" if "mock" in statuses else sorted(statuses)[0]
    return data


def fetch_history(base_url, token, crop_area_id, date_from=None, date_to=None):
    """Rows of GET /crop-areas/{id}/risk (converted) and GET /crop-areas/{id}/changes (as returned)."""
    quoted = urllib.parse.quote(crop_area_id, safe="")
    days = fetch(base_url, CROP_AREA_RISK_PATH.format(id=quoted),
                 {"from": date_from, "to": date_to}, token=token) or []
    changes = fetch(base_url, CROP_AREA_CHANGES_PATH.format(id=quoted), token=token) or []
    if not isinstance(days, list) or not isinstance(changes, list):
        raise FarmerDataError("INVALID_RESPONSE", "Expected lists from /risk and /changes.")
    rows = []
    for day in days:
        if not isinstance(day, dict):
            continue
        attributes = {}
        for name, kind in RISK_DAY_FIELDS:
            value = day.get(name)
            if name == "reasons" and value is not None and not isinstance(value, str):
                value = json.dumps(value, ensure_ascii=False, sort_keys=True)
            attributes[name] = _convert(value, kind)
        rows.append(attributes)
    return rows, changes


# ----- grid -----

def parse_grid_risk(payload):
    # The API sends 4 km squares (Polygon); the early mock used cell centres (Point). Both are read.
    return _parse(payload, "grid", GRID_FIELDS, ("Polygon", "Point"), "grid_id")


# ----- shared parsing -----

def _parse(payload, kind, fields, geometry_types, id_field):
    if not isinstance(payload, dict) or payload.get("type") != "FeatureCollection":
        raise FarmerDataError("INVALID_RESPONSE", "Expected a GeoJSON FeatureCollection.")
    features = payload.get("features")
    if not isinstance(features, list):
        raise FarmerDataError("INVALID_RESPONSE", "The FeatureCollection has no 'features' list.")

    data = ServeData(kind, fields)
    data.data_status = payload.get("data_status")      # optional extension (used by the mock files)
    point_mode = None
    for index, feature in enumerate(features):
        props = feature.get("properties") if isinstance(feature, dict) else None
        geometry = feature.get("geometry") if isinstance(feature, dict) else None
        label = (props or {}).get(id_field) or f"feature {index}"
        if not isinstance(props, dict) or not props.get(id_field):
            data.warnings.append(f"Skipped feature {index}: no {id_field}.")
            continue
        found = geometry.get("type") if isinstance(geometry, dict) else None
        is_point = found == "Point"
        if found not in geometry_types or (point_mode is not None and is_point != point_mode) \
                or not _valid_geometry(geometry):
            data.warnings.append(f"Skipped {label}: geometry is not a valid {' or '.join(geometry_types)}.")
            continue
        point_mode = is_point
        if data.geometry_type is None or found == "MultiPolygon":
            data.geometry_type = found
        attributes = {name: _convert(props.get(name), kind_name) for name, kind_name in fields}
        risk = attributes.get("risk_class")
        if risk is not None and risk not in RISK_CLASSES:
            data.warnings.append(f"{label}: unknown risk_class '{risk}' shown as not assessed.")
            attributes["risk_class"] = None
        if attributes.get("date"):
            data.dates.add(attributes["date"])
        data.rows.append({"geometry": geometry, "attributes": attributes})
    return data


def _valid_geometry(geometry):
    kind = geometry.get("type")
    coords = geometry.get("coordinates")
    try:
        if kind == "Point":
            float(coords[0]), float(coords[1])
            return True
        polygons = [coords] if kind == "Polygon" else coords
        if not polygons:
            return False
        for rings in polygons:
            if not rings:
                return False
            for ring in rings:
                if len(ring) < 4 or ring[0] != ring[-1]:
                    return False
                for point in ring:
                    float(point[0]), float(point[1])
        return True
    except (TypeError, ValueError, IndexError):
        return False


def _convert(value, kind):
    """JSON null stays None (never 0). Wrong types become None rather than a wrong value."""
    if value is None or value == "":
        return None
    try:
        if kind == "int":
            return int(value)
        if kind == "real":
            return float(value)
        if kind == "bool":
            return bool(value) if isinstance(value, bool) else None
        return str(value)  # text and date (ISO strings; the layer builder parses dates)
    except (TypeError, ValueError):
        return None
