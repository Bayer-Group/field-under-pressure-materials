"""Read orchard geometry and trees and publish layouts from the frontend."""

import os
from pathlib import Path
from struct import unpack_from
from threading import Lock

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pymongo.database import Database
from pyproj import Geod, Transformer

from .orchard_layout import (
    OrchardLayout, layout_rows, object_id, orchard_document, polygons, save_layout, trees_in_layout,
)

_ROOT = Path(__file__).resolve().parents[1]
_DEMO_ORCHARD = "6b01933c1dc02a368703a020"
_WGS84 = Geod(ellps="WGS84")
_TO_LAS = Transformer.from_crs("EPSG:4326", "EPSG:2180", always_xy=True)
_SPECIES = {
    "Malus domestica": ("Jabłoń domowa", "Apple", "pome", 3.5, "#ef4444"),
    "Pyrus communis": ("Grusza pospolita", "Pear", "pome", 3.8, "#84cc16"),
    "Prunus avium": ("Czereśnia ptasia", "Sweet Cherry", "stone", 4.5, "#e11d48"),
    "Prunus armeniaca": ("Morela pospolita", "Apricot", "stone", 4.2, "#f97316"),
    "Juglans regia": ("Orzech włoski", "Walnut", "nut", 7.0, "#8b5cf6"),
}


def _name(orchard: dict) -> str:
    identifier = str(orchard["_id"])
    return orchard.get("name") or ("Grojec A" if identifier == _DEMO_ORCHARD else f"Orchard {identifier}")


def _center(orchard: dict) -> dict:
    point = orchard.get("centroid") or orchard.get("center") or {}
    lng, lat = point.get("long", point.get("lng")), point.get("lat")
    if lng is None or lat is None:
        raise HTTPException(422, "The orchard needs a GPS center")
    return {"lat": lat, "lng": lng}


def _ring_area(ring: list) -> tuple[float, float]:
    area, length = _WGS84.polygon_area_perimeter([p[0] for p in ring], [p[1] for p in ring])
    return abs(area), length


def _boundary(orchard: dict) -> tuple[list[dict], float, float]:
    parts = polygons(orchard.get("geometry", {}))
    if not parts:
        raise HTTPException(422, "The orchard needs a GPS boundary")
    ring = max((part[0] for part in parts), key=lambda exterior: _ring_area(exterior)[0])
    area = perimeter = 0.0
    for exterior, *holes in parts:
        part_area, part_length = _ring_area(exterior)
        area += part_area
        perimeter += part_length
        for hole in holes:
            hole_area, hole_length = _ring_area(hole)
            area -= hole_area
            perimeter += hole_length
    return [{"lat": position[1], "lng": position[0]} for position in ring], area, perimeter


def _las_file(orchard_id: ObjectId) -> Path | None:
    configured = os.environ.get("ORCHARD_LAS_DIR")
    roots = [Path(configured)] if configured else [_ROOT / "ui/public/las", _ROOT / "data/point-clouds"]
    names = [f"{orchard_id}.las"]
    if str(orchard_id) == _DEMO_ORCHARD:
        names.append("grojec.las")
    return next((root / name for root in roots for name in names if (root / name).is_file()), None)


def _projection_origin(orchard: dict, path: Path | None) -> tuple[float, float]:
    if path is not None:
        with path.open("rb") as artifact:
            header = artifact.read(227)
        if header[:4] != b"LASF" or len(header) < 227:
            raise HTTPException(422, "Invalid LAS header")
        max_x, min_x, max_y, min_y = unpack_from("<4d", header, 179)
        return (min_x + max_x) / 2, (min_y + max_y) / 2
    center = _center(orchard)
    return _TO_LAS.transform(center["lng"], center["lat"])


def _status(score: float | None) -> str | None:
    if score is None:
        return None
    return next(label for limit, label in ((15, "dead"), (45, "poor"), (72, "moderate"), (100, "healthy")) if score <= limit)


def _render_trees(db: Database, orchard: dict) -> list[dict]:
    trees = trees_in_layout(db, orchard)
    if not trees:
        return []
    placements = {
        str(identifier): (row["id"], row["label"], index)
        for row in orchard.get("rows", [])
        for index, identifier in enumerate(row["treeIds"], start=1)
    }
    order = {identifier: index for index, identifier in enumerate(placements)}
    trees.sort(key=lambda tree: order.get(str(tree["_id"]), len(order)))
    origin_x, origin_y = _projection_origin(orchard, _las_file(orchard["_id"]))
    result = []
    for tree in trees:
        identifier = str(tree["_id"])
        geo = tree["coordinates"]
        easting, northing = _TO_LAS.transform(geo["lng"], geo["lat"])
        row_id, label, index = placements.get(identifier, ("", "", 0))
        value = tree.get("healthIndex")
        score = value if type(value) in (float, int) and 0 <= value <= 100 else None
        result.append(
            {
                "id": identifier,
                "rowId": row_id,
                "rowLabel": label,
                "indexInRow": index,
                "position": {"x": easting - origin_x, "y": 0.0, "z": origin_y - northing},
                "geo": geo,
                "heightMeters": tree.get("heightMeters", 3.0),
                "canopyRadiusMeters": tree.get("canopyRadiusMeters", 1.0),
                "healthIndex": score,
                "healthScore": score,
                "healthStatus": _status(score),
                "species": str(tree["species"]),
            }
        )
    return result


def create_orchard_router(db: Database) -> APIRouter:
    router = APIRouter(prefix="/api/v1")
    # Layout saves publish their row index after writing the individual tree documents.
    # The application serves one ASGI worker, so serialize competing saves in this process.
    layout_lock = Lock()

    @router.get("/orchard/trees")
    def orchard_trees(orchard_id: str | None = Query(default=None, alias="orchardId")) -> list[dict]:
        orchard = orchard_document(db, object_id(orchard_id, "orchardId"))
        return _render_trees(db, orchard)

    @router.get("/orchard/scene")
    def orchard_scene(orchard_id: str | None = Query(default=None, alias="orchardId")) -> dict:
        orchard = orchard_document(db, object_id(orchard_id, "orchardId"))
        boundary, _, _ = _boundary(orchard)
        identifier = str(orchard["_id"])
        origin = {"x": 0, "y": 0, "z": 0}
        return {
            "orchardId": identifier,
            "orchardName": _name(orchard),
            "boundaryGeo": boundary,
            "rowsGeo": [
                {key: row[key] for key in ("id", "label", "start", "end")}
                for row in orchard.get("rows", [])
            ],
            "trees": _render_trees(db, orchard),
            "rowLines": [],
            "pointCloud": {
                "orchardId": identifier, "pointCount": 0, "positions": [], "colors": [],
                "bounds": {"min": origin, "max": origin},
            },
        }

    @router.get("/orchards/{orchard_id}/point-cloud.las")
    def orchard_las(orchard_id: str) -> FileResponse:
        identifier = object_id(orchard_id, "orchardId")
        orchard_document(db, identifier)
        path = _las_file(identifier)
        if path is None:
            raise HTTPException(404, "No LAS file for this orchard")
        return FileResponse(path, media_type="application/octet-stream", filename=path.name, content_disposition_type="inline")

    @router.get("/orchards/{orchard_id}")
    def orchard_boundary(orchard_id: str) -> dict:
        orchard = orchard_document(db, object_id(orchard_id, "orchardId"))
        boundary, area, length = _boundary(orchard)
        area = orchard.get("shapeAreaM2") or orchard.get("shapeArea") or area
        length = orchard.get("shapeLengthM") or orchard.get("shapeLength") or length
        return {
            "_id": str(orchard["_id"]),
            "name": _name(orchard),
            "locationLabel": orchard.get("locationLabel") or "WGS 84 (EPSG:4326)",
            "geometry": boundary,
            "center": _center(orchard),
            "areaHectares": area / 10_000,
            "shapeAreaM2": area,
            "shapeLengthM": length,
            "rows": layout_rows(orchard),
        }

    @router.get("/crop-prefs")
    def crop_preferences() -> list[dict]:
        result = []
        for doc in db.CropPref.find({}).sort("species", 1):
            scientific = doc.get("scientificName") or doc["species"]
            names = _SPECIES.get(scientific, (scientific, scientific, "pome", 3.5, "#64748b"))
            result.append(
                {
                    "_id": str(doc["_id"]),
                    "scientificName": scientific,
                    "code": doc.get("code") or "-".join(scientific.lower().split()),
                    "namePl": doc.get("namePl") or names[0],
                    "nameEn": doc.get("nameEn") or names[1],
                    "variety": doc.get("variety") or scientific,
                    "category": doc.get("category") or names[2],
                    "recommendedSpacingMeters": doc.get("recommendedSpacingMeters") or names[3],
                    "colorHex": doc.get("colorHex") or names[4],
                }
            )
        return result

    @router.post("/orchards/{orchard_id}/layout")
    def post_layout(orchard_id: str, payload: OrchardLayout) -> dict:
        identifier = object_id(orchard_id, "orchardId")
        with layout_lock:
            return save_layout(db, identifier, payload)

    return router
