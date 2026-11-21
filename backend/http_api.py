"""Serve the stored orchard temperature series consumed by the UI."""

from datetime import datetime, timedelta, timezone
from itertools import groupby
from math import isfinite
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from bson import ObjectId
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pymongo.database import Database

_UTC = timezone.utc
_EPOCH = datetime(1970, 1, 1, tzinfo=_UTC)
# History window, bucket size and display format for each UI preset.
_RANGES = {
    "24h": (timedelta(hours=24), timedelta(hours=1), "%H:%M"),
    "7d": (timedelta(days=7), timedelta(hours=12), "%d.%m"),
    "30d": (timedelta(days=30), timedelta(days=1), "%d.%m"),
    "90d": (timedelta(days=90), timedelta(days=2), "%d.%m"),
    "1y": (timedelta(days=365), timedelta(days=7), "%d.%m.%y"),
}


def _temperature_samples(documents):
    for document in documents:
        temperature = document.get("values", {}).get("temperature_2m")
        if (
            isinstance(temperature, bool)
            or not isinstance(temperature, (int, float))
            or not isfinite(temperature)
        ):
            continue

        valid_at = document["valid_at"]
        if valid_at.tzinfo is None:
            # PyMongo decodes dates as naive UTC unless tz_aware is enabled.
            valid_at = valid_at.replace(tzinfo=_UTC)
        yield valid_at.astimezone(_UTC), temperature


def _points(documents, step: timedelta, label_format: str, label_timezone) -> list[dict]:
    points = []
    samples = _temperature_samples(documents)
    for _, group in groupby(samples, key=lambda sample: (sample[0] - _EPOCH) // step):
        first_time, first_temperature = next(group)
        low = high = first_temperature
        for _, temperature in group:
            low = min(low, temperature)
            high = max(high, temperature)
        points.append(
            {
                "timestamp": first_time.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                "label": first_time.astimezone(label_timezone).strftime(label_format),
                "minTempC": low,
                "maxTempC": high,
            }
        )
    return points


def create_app(db: Database, *, lifespan=None) -> FastAPI:
    """Create a read-only weather API backed by the MongoDB synchronization cache."""
    try:
        label_timezone = ZoneInfo("Europe/Warsaw")
    except ZoneInfoNotFoundError:
        label_timezone = _UTC

    app = FastAPI(title="Orchard weather", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Accept"],
    )

    @app.get("/api/v1/weather/temperature")
    def temperature_series(
        orchard_id: str | None = Query(default=None, alias="orchardId"),
        period: str | None = Query(default=None, alias="range"),
    ) -> dict:
        if orchard_id is None or not ObjectId.is_valid(orchard_id):
            raise HTTPException(status_code=400, detail="orchardId must be a MongoDB ObjectId")
        if period not in _RANGES:
            raise HTTPException(status_code=400, detail="range must be 24h, 7d, 30d, 90d or 1y")

        identifier = ObjectId(orchard_id)
        if db["Orchard"].find_one({"_id": identifier}, {"_id": 1}) is None:
            raise HTTPException(status_code=404, detail="Orchard not found")

        window, step, label_format = _RANGES[period]
        end = datetime.now(_UTC)
        documents = db["weather_history"].find(
            {"orchard_id": identifier, "valid_at": {"$gte": end - window, "$lt": end}},
            {"_id": 0, "valid_at": 1, "values.temperature_2m": 1},
        ).sort("valid_at", 1)
        return {
            "orchardId": str(identifier),
            "range": period,
            "unit": "C",
            "points": _points(documents, step, label_format, label_timezone),
        }

    return app
