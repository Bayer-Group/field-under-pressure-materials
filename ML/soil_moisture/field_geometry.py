"""Load field boundaries from Orchard or an explicitly supplied GeoJSON file."""

import json
import os

from bson import ObjectId
from pymongo import MongoClient
from pymongo.errors import PyMongoError

COLLECTION = "Orchard"
DEFAULT_DATABASE = "field_under_pressure"
POLYGON_TYPES = {"Polygon", "MultiPolygon"}


def geojson_features(document, source):
    if not isinstance(document, dict) or "type" not in document:
        raise ValueError(f"{source}: oczekiwano obiektu GeoJSON.")
    records = (
        document.get("features")
        if document.get("type") == "FeatureCollection"
        else [document]
    )
    if not records or not isinstance(records, list):
        raise ValueError(f"{source}: brak pól w GeoJSON.")

    features = []
    for index, record in enumerate(records, start=1):
        if not isinstance(record, dict) or "type" not in record:
            raise ValueError(f"{source}: nieprawidłowy obiekt pola nr {index}.")
        is_feature = record.get("type") == "Feature"
        geometry = record.get("geometry") if is_feature else record
        if (
            not isinstance(geometry, dict)
            or geometry.get("type") not in POLYGON_TYPES
            or not geometry.get("coordinates")
        ):
            raise ValueError(
                f"{source}: pole nr {index} musi mieć geometrię Polygon lub MultiPolygon."
            )

        geometry_type = geometry["type"]
        coordinates = geometry["coordinates"]
        polygons = [coordinates] if geometry_type == "Polygon" else coordinates
        try:
            # Earth Engine needs horizontal coordinates. GeoJSON can include Z.
            planar = [
                [[position[:2] for position in ring] for ring in polygon]
                for polygon in polygons
            ]
        except TypeError as error:
            raise ValueError(
                f"{source}: niewłaściwe współrzędne pola nr {index}."
            ) from error
        properties = record.get("properties") if is_feature else None
        features.append(
            {
                "geometry": {
                    "type": geometry_type,
                    "coordinates": planar[0] if geometry_type == "Polygon" else planar,
                },
                "properties": properties.copy() if isinstance(properties, dict) else {},
            }
        )
    return features


def mongo_client():
    uri = os.getenv("MONGO_URI", "").strip()
    if uri:
        return MongoClient(uri, serverSelectionTimeoutMS=5000)
    return MongoClient(
        host=os.getenv("MONGO_HOST", "127.0.0.1"),
        port=int(os.getenv("MONGO_PORT", "27017")),
        username=os.getenv("MONGO_ROOT_USER") or None,
        password=os.getenv("MONGO_ROOT_PASSWORD") or None,
        authSource="admin",
        serverSelectionTimeoutMS=5000,
    )


def mongo_database(client):
    name = os.getenv("MONGO_DB", "").strip()
    return client[name] if name else client.get_default_database(DEFAULT_DATABASE)


def orchard_ids(value):
    return [value, ObjectId(value)] if ObjectId.is_valid(value) else [value]


def read_field_features(path=None):
    if path is not None:
        with path.open(encoding="utf-8-sig") as stream:
            return geojson_features(json.load(stream), str(path))

    query = {"geometry": {"$exists": True, "$ne": None}}
    selected = os.getenv("MONGO_ORCHARD_ID", "").strip()
    if selected:
        query["_id"] = {"$in": orchard_ids(selected)}

    fields = []
    try:
        with mongo_client() as client:
            docs = (
                mongo_database(client)[COLLECTION]
                .find(query, {"geometry": 1, "cropID": 1})
                .sort("_id", 1)
            )
            for doc in docs:
                source = f"{COLLECTION}.geometry (rekord {doc['_id']})"
                features = geojson_features(doc["geometry"], source)
                for feature in features:
                    properties = feature["properties"]
                    properties["orchard_id"] = str(doc["_id"])
                    properties.setdefault("cropID", doc.get("cropID"))
                fields.extend(features)
    except PyMongoError as error:
        raise OSError("Nie udało się odczytać kolekcji Orchard w MongoDB.") from error

    if not fields:
        scope = "dla wybranego rekordu" if selected else "w żadnym rekordzie"
        raise ValueError(f"Brak geometrii pól w Orchard.geometry {scope}.")
    return fields
