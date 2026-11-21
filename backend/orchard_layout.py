"""Validate and save the GPS layout produced by the orchard editor."""

from datetime import datetime, timezone
from hashlib import sha256
from typing import Annotated

from bson import ObjectId
from fastapi import HTTPException
from pydantic import BaseModel, Field
from pymongo import UpdateOne
from pymongo.database import Database
from pymongo.errors import BulkWriteError


class GeoCoord(BaseModel):
    lat: Annotated[float, Field(strict=True, ge=-90, le=90)]
    lng: Annotated[float, Field(strict=True, ge=-180, le=180)]


class LayoutTree(BaseModel):
    client_id: Annotated[str, Field(alias="_id", min_length=1, max_length=128)]
    orchardId: str
    coordinates: GeoCoord
    healthIndex: Annotated[float | None, Field(ge=0, le=100)] = None
    species: str


class LayoutRow(BaseModel):
    id: Annotated[str, Field(min_length=1, max_length=128)]
    label: str
    start: GeoCoord
    end: GeoCoord
    averageSpacingMeters: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    treeIds: list[str]


class OrchardLayout(BaseModel):
    orchardId: str
    orchardRows: list[LayoutRow]
    trees: list[LayoutTree]


def object_id(value: str | None, name: str) -> ObjectId:
    if value is None or not ObjectId.is_valid(value):
        raise HTTPException(400, f"{name} must be a MongoDB ObjectId")
    return ObjectId(value)


def orchard_document(db: Database, identifier: ObjectId, projection: dict | None = None) -> dict:
    orchard = db.Orchard.find_one({"_id": identifier}, projection or {"environmentalData": 0})
    if orchard is None:
        raise HTTPException(404, "Orchard not found")
    return orchard


def polygons(geometry: dict) -> list:
    if geometry.get("type") == "MultiPolygon":
        return geometry["coordinates"]
    if geometry.get("type") == "Polygon":
        return [geometry["coordinates"]]
    return []


def _within_ring(point: GeoCoord, ring: list) -> bool:
    x, y = point.lng, point.lat
    inside = False
    for first, second in zip(ring, ring[1:] + ring[:1]):
        x1, y1 = first[:2]
        x2, y2 = second[:2]
        cross = (x - x1) * (y2 - y1) - (y - y1) * (x2 - x1)
        if abs(cross) < 1e-14 and min(x1, x2) <= x <= max(x1, x2) and min(y1, y2) <= y <= max(y1, y2):
            return True
        if (y1 > y) != (y2 > y) and x < x1 + (x2 - x1) * (y - y1) / (y2 - y1):
            inside = not inside
    return inside


def _inside_orchard(point: GeoCoord, rings: list) -> bool:
    return any(
        _within_ring(point, exterior) and not any(_within_ring(point, hole) for hole in holes)
        for exterior, *holes in rings
    )


def layout_rows(orchard: dict) -> list[dict]:
    return [
        {**row, "treeIds": [str(identifier) for identifier in row["treeIds"]]}
        for row in orchard.get("rows", [])
    ]


def trees_in_layout(db: Database, orchard: dict) -> list[dict]:
    owner = {"orchardId": orchard["_id"]}
    if "layoutTreeIds" in orchard:
        owner["_id"] = {"$in": orchard["layoutTreeIds"]}
    else:
        owner["layoutManaged"] = {"$ne": True}
    return list(db.Tree.find(owner, {"weather_current": 0}).sort("_id", 1))


def _tree_ids(db: Database, orchard_id: ObjectId, client_ids: set[str]) -> dict[str, ObjectId]:
    candidates = [ObjectId(key) for key in client_ids if ObjectId.is_valid(key)]
    existing = set(db.Tree.distinct("_id", {"orchardId": orchard_id, "_id": {"$in": candidates}}))
    mapped = {}
    for key in client_ids:
        candidate = ObjectId(key) if ObjectId.is_valid(key) else None
        if candidate in existing:
            mapped[key] = candidate
        else:
            digest = sha256(f"{orchard_id}:{key}".encode()).digest()
            mapped[key] = ObjectId(digest[:12])
    return mapped


def save_layout(db: Database, identifier: ObjectId, layout: OrchardLayout) -> dict:
    """Write the tree records first, then publish a consistent row index on the orchard."""
    if object_id(layout.orchardId, "orchardId") != identifier:
        raise HTTPException(422, "The body orchardId must match the URL")
    orchard = orchard_document(
        db, identifier, {"geometry": 1, "layoutTreeIds": 1, "environmentalData.current": 1}
    )
    current = {tree["_id"] for tree in trees_in_layout(db, orchard)}
    area = polygons(orchard.get("geometry", {}))
    if not area:
        raise HTTPException(422, "The orchard needs a valid boundary")

    clients = {tree.client_id: tree for tree in layout.trees}
    row_ids = {row.id for row in layout.orchardRows}
    if len(clients) != len(layout.trees) or len(row_ids) != len(layout.orchardRows):
        raise HTTPException(422, "Tree and row IDs must be unique")
    if any(object_id(tree.orchardId, "tree.orchardId") != identifier for tree in layout.trees):
        raise HTTPException(422, "Every tree must belong to the orchard in the URL")
    if any(not _inside_orchard(tree.coordinates, area) for tree in layout.trees):
        raise HTTPException(422, "Every tree must be inside its orchard boundary")

    species = {key: object_id(tree.species, "tree.species") for key, tree in clients.items()}
    species_ids = set(species.values())
    known_species = set(db.CropPref.distinct("_id", {"_id": {"$in": list(species_ids)}}))
    if known_species != species_ids:
        raise HTTPException(422, "A tree refers to an unknown species")

    referenced = [key for row in layout.orchardRows for key in row.treeIds]
    if len(referenced) != len(set(referenced)):
        raise HTTPException(422, "A tree can appear in only one row")
    mapped = _tree_ids(db, identifier, set(clients) | set(referenced))
    if len(set(mapped.values())) != len(mapped):
        raise HTTPException(422, "Tree IDs must refer to different documents")
    if any(key not in clients and mapped[key] not in current for key in referenced):
        raise HTTPException(422, "A row refers to a tree that is not in this orchard layout")
    snapshots = orchard.get("environmentalData", {}).get("current", [])
    writes = []
    for key, tree in clients.items():
        fields = {"coordinates": tree.coordinates.model_dump(), "species": species[key]}
        if tree.healthIndex is not None:
            fields["healthIndex"] = tree.healthIndex
        on_insert = {"layoutManaged": True}
        if tree.healthIndex is None:
            on_insert["healthIndex"] = None
        if snapshots:
            on_insert["weather_current"] = {"orchard_id": identifier, **snapshots[0]}
        writes.append(
            UpdateOne(
                {"_id": mapped[key], "orchardId": identifier},
                {"$set": fields, "$setOnInsert": on_insert},
                upsert=True,
            )
        )
    if writes:
        try:
            db.Tree.bulk_write(writes)
        except BulkWriteError as error:
            if any(detail["code"] == 11000 for detail in error.details.get("writeErrors", [])):
                raise HTTPException(409, "A tree ID is already owned by another orchard") from error
            raise

    rows = [
        {**row.model_dump(), "treeIds": [mapped[key] for key in row.treeIds]}
        for row in layout.orchardRows
    ]
    active = list(dict.fromkeys(mapped[key] for key in referenced + list(clients)))
    now = datetime.now(timezone.utc)
    published = db.Orchard.update_one(
        {"_id": identifier},
        {"$set": {"rows": rows, "layoutTreeIds": active, "layoutUpdatedAt": now}},
    )
    if not published.matched_count:
        raise HTTPException(404, "Orchard not found")
    persisted = {
        tree["_id"]: tree for tree in db.Tree.find(
            {"_id": {"$in": [mapped[key] for key in clients]}, "orchardId": identifier},
            {"coordinates": 1, "healthIndex": 1, "species": 1},
        )
    }
    trees = [
        {
            "_id": str(tree["_id"]),
            "orchardId": str(identifier),
            "coordinates": tree["coordinates"],
            "healthIndex": tree.get("healthIndex"),
            "species": str(tree["species"]),
        }
        for tree in (persisted[mapped[key]] for key in clients)
    ]
    return {
        "orchardId": str(identifier),
        "savedRowsCount": len(rows),
        "savedTreesCount": len(trees),
        "updatedAt": now.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "orchard": {"_id": str(identifier), "rows": layout_rows({"rows": rows})},
        "trees": trees,
    }
