# -*- coding: utf-8 -*-
"""
Catalog of backend data layers for the QGIS plugin (issue #14 follow-up).

No QGIS imports: runs in QgsTask.run() and can be checked outside QGIS.

The catalog is a JSON document ``{"layers": [...]}`` served at ``{base URL}/catalog`` or read
from a file. Each layer has ``id``, ``title``, ``kind`` (raster, vector or table), ``format``
(COG, GeoJSON, CSV, GeoPackage...) and ``href``. A relative ``href`` is resolved against the
catalog location. Optional: ``legend_qml``, ``temporal.time_field``, ``known_gaps``, ``note``,
``source``. NOTE: this catalog shape is a proposal and is not yet part of the agreed backend
contract; see qgis_plugin/DATA_LAYERS.md.
"""

import json
import os
import tempfile
import urllib.error
import urllib.parse
import urllib.request

from .farmer_fields import FarmerDataError as DataSourceError, USER_AGENT

KINDS = ("raster", "vector", "table")
LOCAL_EXTENSIONS = {
    ".tif": "raster", ".tiff": "raster",
    ".geojson": "vector", ".json": "vector", ".gpkg": "vector", ".shp": "vector",
    ".csv": "table",
}


class Catalog:
    def __init__(self):
        self.layers = []
        self.warnings = []
        self.simulation = None
        self.note = None


def is_remote(source):
    return source.lower().startswith(("http://", "https://"))


def fetch_catalog(base_url, timeout=8):
    """GET {base_url}/catalog. Raises DataSourceError; hrefs resolve against {base_url}/."""
    base = base_url.rstrip("/") + "/"
    url = base + "catalog"
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise DataSourceError(f"HTTP_{exc.code}", f"{url}: {exc.reason}", status=exc.code) from exc
    except (urllib.error.URLError, OSError) as exc:
        raise DataSourceError("SERVICE_UNAVAILABLE", f"Cannot reach {url}: {exc}") from exc
    return parse_catalog(_decode(body, url), base)


def load_catalog_file(path):
    """Read a catalog JSON file; relative hrefs resolve against its folder."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            body = handle.read()
    except OSError as exc:
        raise DataSourceError("FILE_ERROR", f"Cannot read {path}: {exc}") from exc
    return parse_catalog(_decode(body, path), os.path.dirname(os.path.abspath(path)))


def _decode(body, origin):
    try:
        return json.loads(body)
    except ValueError as exc:
        raise DataSourceError("INVALID_RESPONSE", f"{origin} is not valid JSON: {exc}") from exc


def parse_catalog(payload, origin):
    """Validate the catalog and resolve hrefs. Bad entries are skipped with a warning."""
    if not isinstance(payload, dict) or not isinstance(payload.get("layers"), list):
        raise DataSourceError("INVALID_RESPONSE", 'Expected an object with a "layers" list.')
    catalog = Catalog()
    catalog.simulation = payload.get("simulation")
    catalog.note = payload.get("note")
    seen = set()
    for index, item in enumerate(payload["layers"]):
        layer_id = item.get("id") if isinstance(item, dict) else None
        href = item.get("href") if isinstance(item, dict) else None
        if not layer_id or not href:
            catalog.warnings.append(f"Layer #{index} has no id or href; skipped.")
            continue
        if layer_id in seen:
            catalog.warnings.append(f"Duplicate layer id {layer_id}; skipped.")
            continue
        if item.get("kind") not in KINDS:
            catalog.warnings.append(f"Layer {layer_id}: unknown kind {item.get('kind')!r}; skipped.")
            continue
        seen.add(layer_id)
        catalog.layers.append({
            "id": layer_id,
            "title": item.get("title") or layer_id,
            "kind": item["kind"],
            "format": item.get("format", ""),
            "source": _resolve(href, origin),
            "legend_qml": _resolve(item["legend_qml"], origin) if item.get("legend_qml") else None,
            "time_field": (item.get("temporal") or {}).get("time_field"),
            "known_gaps": item.get("known_gaps") or [],
            "note": item.get("note"),
            "provenance": item.get("source"),
        })
    return catalog


def _resolve(href, origin):
    if is_remote(href) or os.path.isabs(href):
        return href
    if is_remote(origin):
        return urllib.parse.urljoin(origin, href)
    return os.path.normpath(os.path.join(origin, href))


def entry_from_local_file(path):
    """Entry for a file the user picked by hand; format comes from the extension."""
    extension = os.path.splitext(path)[1].lower()
    kind = LOCAL_EXTENSIONS.get(extension)
    if not kind:
        raise DataSourceError(
            "UNSUPPORTED_FILE", f"Unsupported file type {extension or '(none)'}: {os.path.basename(path)}"
        )
    return {
        "id": "local:" + os.path.abspath(path),
        "title": os.path.basename(path),
        "kind": kind,
        "format": extension.lstrip(".").upper(),
        "source": os.path.abspath(path),
        "legend_qml": None,
        "time_field": None,
        "known_gaps": [],
        "note": None,
        "provenance": "local file",
    }


def probe_source(source, timeout=8):
    """Check that a source can be read. Returns a warning text or None; raises on failure.

    Remote sources get a one-byte range request, which also shows whether the server supports
    HTTP Range (needed for reading Cloud Optimized GeoTIFFs without downloading them whole).
    """
    if not is_remote(source):
        if not os.path.exists(source):
            raise DataSourceError("FILE_ERROR", f"File not found: {source}")
        return None
    request = urllib.request.Request(
        source, headers={"User-Agent": USER_AGENT, "Range": "bytes=0-0"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = response.status
    except urllib.error.HTTPError as exc:
        raise DataSourceError(f"HTTP_{exc.code}", f"{source}: {exc.reason}", status=exc.code) from exc
    except (urllib.error.URLError, OSError) as exc:
        raise DataSourceError("SERVICE_UNAVAILABLE", f"Cannot reach {source}: {exc}") from exc
    if status != 206:
        return f"{source}: server ignored the Range request (HTTP {status}); large rasters may load slowly."
    return None


def fetch_to_temp(source, timeout=8):
    """Local path for a style file: the file itself, or a temporary copy of a remote one."""
    if not is_remote(source):
        if not os.path.exists(source):
            raise DataSourceError("FILE_ERROR", f"Style file not found: {source}")
        return source
    request = urllib.request.Request(source, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read()
    except urllib.error.HTTPError as exc:
        raise DataSourceError(f"HTTP_{exc.code}", f"{source}: {exc.reason}", status=exc.code) from exc
    except (urllib.error.URLError, OSError) as exc:
        raise DataSourceError("SERVICE_UNAVAILABLE", f"Cannot reach {source}: {exc}") from exc
    handle, path = tempfile.mkstemp(suffix=".qml")
    with os.fdopen(handle, "wb") as out:
        out.write(data)
    return path
