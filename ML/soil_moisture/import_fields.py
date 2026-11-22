"""Import field boundaries from GeoJSON into MongoDB Orchard."""

import argparse
import hashlib
import json
from pathlib import Path

from bson import ObjectId
from pymongo import UpdateOne
from pymongo.errors import PyMongoError

if __package__:
    from .field_geometry import (
        COLLECTION,
        mongo_client,
        mongo_database,
        read_field_features,
    )
else:
    from field_geometry import (
        COLLECTION,
        mongo_client,
        mongo_database,
        read_field_features,
    )


def import_fields(path):
    features = read_field_features(path)
    fields = {}
    for feature in features:
        geometry = feature["geometry"]
        properties = feature["properties"]
        encoded = json.dumps(geometry, sort_keys=True).encode("utf-8")
        # Stable ObjectIds let repeat imports skip these records without touching edits.
        field_id = ObjectId(
            hashlib.sha256(b"Orchard GeoJSON import:" + encoded).digest()[:12]
        )
        fields.setdefault(
            field_id,
            {
                "geometry": geometry,
                "cropID": properties.get("cropID"),
                "properties": properties,
            },
        )

    with mongo_client() as client:
        collection = mongo_database(client)[COLLECTION]
        result = collection.bulk_write(
            [
                UpdateOne({"_id": field_id}, {"$setOnInsert": field}, upsert=True)
                for field_id, field in fields.items()
            ],
            ordered=False,
        )
        return (
            collection.full_name,
            result.upserted_count,
            len(features) - result.upserted_count,
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fields-geojson",
        type=Path,
        default=Path(__file__).resolve().parent / "data" / "fields.geojson",
        help="Plik GeoJSON z granicami pól w WGS 84.",
    )
    args = parser.parse_args()
    try:
        collection, added, skipped = import_fields(args.fields_geojson)
    except (OSError, ValueError) as error:
        parser.exit(1, f"Błąd importu: {error}\n")
    except PyMongoError as error:
        parser.exit(1, f"Błąd zapisu do MongoDB ({type(error).__name__}).\n")
    print(f"{collection} — dodano: {added}, pominięto: {skipped}.")


if __name__ == "__main__":
    main()
