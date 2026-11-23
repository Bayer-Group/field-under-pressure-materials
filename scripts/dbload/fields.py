"""Farmer fields from a GeoJSON file -> `field` rows (EWKT) and polygons for the cropland raster."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Field:
    field_id: str
    name: str | None
    geometry: dict          # GeoJSON Polygon / MultiPolygon, EPSG:4326
    ewkt: str
    bounds: tuple[float, float, float, float]   # minx, miny, maxx, maxy


def _fmt(v: float) -> str:
    return f"{v:.9f}".rstrip("0").rstrip(".")


def _ring(ring) -> str:
    return "(" + ", ".join(f"{_fmt(p[0])} {_fmt(p[1])}" for p in ring) + ")"


def to_ewkt(g: dict) -> str:
    if g["type"] == "Polygon":
        return "SRID=4326;POLYGON(" + ", ".join(_ring(r) for r in g["coordinates"]) + ")"
    if g["type"] == "MultiPolygon":
        polys = ("(" + ", ".join(_ring(r) for r in poly) + ")" for poly in g["coordinates"])
        return "SRID=4326;MULTIPOLYGON(" + ", ".join(polys) + ")"
    raise ValueError(f"unsupported geometry type {g['type']!r}")


def _bounds(g: dict) -> tuple[float, float, float, float]:
    pts = []
    polys = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
    for poly in polys:
        for ring in poly:
            pts.extend(ring)
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def load_fields(path: Path) -> list[Field]:
    """Accepts a FeatureCollection, a single Feature or a bare geometry (WGS84, as RFC 7946 requires).

    field_id = properties.field_id | properties.id | feature.id | properties.name | 'field-<n>'."""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if doc.get("type") == "FeatureCollection":
        feats = doc["features"]
    elif doc.get("type") == "Feature":
        feats = [doc]
    else:
        feats = [{"type": "Feature", "properties": {}, "geometry": doc}]
    out: list[Field] = []
    seen: set[str] = set()
    for n, f in enumerate(feats, 1):
        props = f.get("properties") or {}
        fid = next((str(v) for v in (props.get("field_id"), props.get("id"), f.get("id"), props.get("name"))
                    if v not in (None, "")), f"field-{n}")
        if fid in seen:
            raise ValueError(f"{path}: duplicate field_id {fid!r}")
        seen.add(fid)
        g = f.get("geometry")
        if not g or g.get("type") not in ("Polygon", "MultiPolygon"):
            raise ValueError(f"{path}: field {fid!r} is not a Polygon/MultiPolygon "
                             f"(got {g and g.get('type')!r}); the `field` table only accepts polygons")
        name = props.get("name")
        out.append(Field(fid, None if name in (None, "") else str(name), g, to_ewkt(g), _bounds(g)))
    return out
