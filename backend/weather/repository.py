"""Persist orchard weather with per-document atomic, repeatable updates."""

from datetime import datetime
from typing import TYPE_CHECKING

from bson import ObjectId
from pymongo import ASCENDING, ReturnDocument, UpdateOne
from pymongo.database import Database

if TYPE_CHECKING:
    from .open_meteo import CurrentWeather, WeatherDay, WeatherPoint

_CURRENT = "environmentalData.current"
_HISTORY = "environmentalData.history"
_FORECAST = "environmentalData.forecast"


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


def _newer_request(fetched_at: datetime, field: str = "$fetched_at") -> dict:
    return {"$lt": [{"$ifNull": [field, None]}, fetched_at]}


def _fresh_current(valid_at: datetime, fetched_at: datetime, previous: str) -> dict:
    return {
        "$and": [
            _newer_request(fetched_at, f"{previous}.fetched_at"),
            {"$lte": [{"$ifNull": [f"{previous}.valid_at", None]}, valid_at]},
        ]
    }


def _replace_snapshot(path: str, rows: list[dict], condition: dict) -> list[dict]:
    saved = {"$ifNull": [f"${path}", []]}
    return [
        {
            "$set": {
                path: {
                    "$let": {
                        "vars": {"previous": {"$arrayElemAt": [saved, 0]}},
                        "in": {"$cond": [condition, {"$literal": rows}, saved]},
                    }
                }
            }
        }
    ]


def _point_rows(
    points: list["WeatherPoint"], units: dict[str, str], fetched_at: datetime
) -> list[dict]:
    return [
        {"valid_at": point.valid_at, "values": point.values, "units": units, "fetched_at": fetched_at}
        for point in points
    ]


def _history_by_time(points: dict, key: dict, value: str | dict) -> dict:
    return {
        "$arrayToObject": {
            "$map": {"input": points, "as": "point", "in": {"k": key, "v": value}}
        }
    }


def _merge_history(rows: list[dict], fetched_at: datetime) -> dict:
    # Use epoch milliseconds as keys while merging, then restore the sorted array.
    key = {"$toString": {"$toLong": "$$point.valid_at"}}
    existing = {"$getField": {"field": key, "input": "$$history"}}
    freshest_point = {
        "$let": {
            "vars": {"existing": existing},
            "in": {
                "$cond": [
                    _newer_request(fetched_at, "$$existing.fetched_at"),
                    "$$point",
                    "$$existing",
                ]
            },
        }
    }
    previous = _history_by_time({"$ifNull": [f"${_HISTORY}", []]}, key, "$$point")
    incoming = _history_by_time({"$literal": rows}, key, freshest_point)
    merged = {"$objectToArray": {"$mergeObjects": ["$$history", incoming]}}
    return {
        "$let": {
            "vars": {"history": previous},
            "in": {
                "$sortArray": {
                    "input": {"$map": {"input": merged, "in": "$$this.v"}},
                    "sortBy": {"valid_at": 1},
                }
            },
        }
    }


class WeatherRepository:
    """Write current, historical, and forecast data to the shared database."""

    def __init__(self, db: Database) -> None:
        self._orchards = db["Orchard"]
        self._daily = db["weather_daily"]
        self._trees = db["Tree"]

    def ensure_indexes(self) -> None:
        self._daily.create_index(
            [("orchard_id", ASCENDING), ("date", ASCENDING)], unique=True
        )
        self._trees.create_index("orchardId")

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
        updated = self._orchards.find_one_and_update(
            {"_id": orchard_id},
            _replace_snapshot(
                _CURRENT, [fields], _fresh_current(current.valid_at, fetched_at, "$$previous")
            ),
            projection={_CURRENT: 1, "_id": 0},
            return_document=ReturnDocument.AFTER,
        )
        if updated is None:
            return
        snapshot = updated["environmentalData"]["current"][0]
        condition = {
            "$or": [
                {
                    "$ne": [
                        {"$ifNull": ["$weather_current.orchard_id", None]},
                        {"$literal": orchard_id},
                    ]
                },
                _fresh_current(snapshot["valid_at"], snapshot["fetched_at"], "$weather_current"),
            ]
        }
        self._trees.update_many(
            {"orchardId": orchard_id},
            _write_if({"weather_current": {"orchard_id": orchard_id, **snapshot}}, condition),
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
        rows = _point_rows(points, units, fetched_at)
        self._orchards.update_one(
            {"_id": orchard_id},
            [{"$set": {_HISTORY: _merge_history(rows, fetched_at)}}],
        )

    def save_daily(
        self,
        orchard_id: ObjectId | str,
        days: list["WeatherDay"],
        units: dict[str, str],
        fetched_at: datetime,
    ) -> None:
        if not days:
            return

        is_fresh = _newer_request(fetched_at)
        was_forecast = {"$ifNull": ["$is_forecast", True]}
        # A completed day supersedes a forecast. Later forecasts cannot replace it.
        forecast_update = {"$and": [was_forecast, is_fresh]}
        historical_update = {"$or": [was_forecast, is_fresh]}
        updates = [
            UpdateOne(
                {"orchard_id": orchard_id, "date": day.date},
                _write_if(
                    {
                        "valid_at": day.valid_at,
                        "values": day.values,
                        "units": units,
                        "is_forecast": day.is_forecast,
                        "fetched_at": fetched_at,
                    },
                    forecast_update if day.is_forecast else historical_update,
                ),
                upsert=True,
            )
            for day in days
        ]
        self._daily.bulk_write(updates, ordered=False)

    def save_forecast(
        self,
        orchard_id: ObjectId | str,
        points: list["WeatherPoint"],
        units: dict[str, str],
        fetched_at: datetime,
    ) -> None:
        if not points:
            return
        self._orchards.update_one(
            {"_id": orchard_id},
            _replace_snapshot(
                _FORECAST,
                _point_rows(points, units, fetched_at),
                _newer_request(fetched_at, "$$previous.fetched_at"),
            ),
        )
