"""Persist orchard weather with per-document atomic, repeatable updates."""

from datetime import datetime
from typing import TYPE_CHECKING

from bson import ObjectId
from pymongo import ASCENDING, UpdateOne
from pymongo.database import Database

if TYPE_CHECKING:
    from .open_meteo import CurrentWeather, WeatherPoint


def _write_if(fields: dict, condition: dict) -> list[dict]:
    # Match on identity alone. Check freshness inside the update so a stale
    # write still matches the existing document instead of trying to insert it.
    return [
        {
            "$replaceWith": {
                "$mergeObjects": [
                    "$$ROOT",
                    {"$cond": [condition, {"$literal": fields}, {}]},
                ]
            }
        }
    ]


def _newer_request(fetched_at: datetime) -> dict:
    return {"$lt": [{"$ifNull": ["$fetched_at", None]}, fetched_at]}


class WeatherRepository:
    """Write current, historical, and forecast data to the shared database."""

    def __init__(self, db: Database) -> None:
        self._current = db["weather_current"]
        self._history = db["weather_history"]
        self._forecast = db["weather_forecast"]

    def ensure_indexes(self) -> None:
        self._history.create_index(
            [("orchard_id", ASCENDING), ("valid_at", ASCENDING)], unique=True
        )

    def save_current(
        self,
        orchard_id: ObjectId | str,
        current: "CurrentWeather",
        fetched_at: datetime,
    ) -> None:
        fields = {
            "valid_at": current.valid_at,
            "interval_seconds": current.interval_seconds,
            "values": current.values,
            "units": current.units,
            "fetched_at": fetched_at,
        }
        is_fresh = {
            "$and": [
                _newer_request(fetched_at),
                {"$lte": [{"$ifNull": ["$valid_at", None]}, current.valid_at]},
            ]
        }
        self._current.update_one(
            {"_id": orchard_id}, _write_if(fields, is_fresh), upsert=True
        )

    def save_history(
        self,
        orchard_id: ObjectId | str,
        points: list["WeatherPoint"],
        units: dict[str, str],
        fetched_at: datetime,
    ) -> None:
        if not points:
            return

        is_fresh = _newer_request(fetched_at)
        updates = [
            UpdateOne(
                {"orchard_id": orchard_id, "valid_at": point.valid_at},
                _write_if(
                    {"values": point.values, "units": units, "fetched_at": fetched_at},
                    is_fresh,
                ),
                upsert=True,
            )
            for point in points
        ]
        self._history.bulk_write(updates, ordered=False)

    def save_forecast(
        self,
        orchard_id: ObjectId | str,
        points: list["WeatherPoint"],
        units: dict[str, str],
        fetched_at: datetime,
    ) -> None:
        fields = {
            "points": [
                {"valid_at": point.valid_at, "values": point.values} for point in points
            ],
            "units": units,
            "fetched_at": fetched_at,
        }
        self._forecast.update_one(
            {"_id": orchard_id}, _write_if(fields, _newer_request(fetched_at)), upsert=True
        )
