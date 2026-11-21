"""Read hourly weather series for the soil moisture and solar models."""

import json
import math
from datetime import datetime, timedelta, timezone
from hashlib import sha256

import requests
from pymongo.errors import PyMongoError

from ML.soil_moisture.field_geometry import mongo_client, mongo_database

UTC = timezone.utc
HOUR = timedelta(hours=1)
DAY = timedelta(days=1)
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


class WeatherError(RuntimeError):
    """Weather data are unavailable or incomplete."""


def load_hourly_weather(url, coordinates, variables, *, timeout=(5, 45), **time_range):
    lon, lat = coordinates
    parameters = {
        "latitude": lat, "longitude": lon, "hourly": ",".join(variables),
        "timezone": "GMT", **time_range,
    }
    key = sha256(json.dumps([url, parameters], sort_keys=True).encode()).hexdigest()
    lifetime = timedelta(days=7) if url == ARCHIVE_URL else HOUR
    now = datetime.now(UTC)
    try:
        with mongo_client() as client:
            cached = mongo_database(client).MLWeatherCache.find_one({
                "_id": key, "fetched_at": {"$gte": now - lifetime},
            })
        if cached:
            return {
                row["time"].replace(tzinfo=UTC): tuple(row["values"])
                for row in cached["rows"]
            }
    except PyMongoError:
        pass
    try:
        response = requests.get(
            url,
            params=parameters,
            timeout=timeout,
        )
        response.raise_for_status()
        hourly = response.json()["hourly"]
        rows = zip(
            hourly["time"], *(hourly[column] for column in variables), strict=True
        )
        result = {
            datetime.fromisoformat(timestamp).replace(tzinfo=UTC): tuple(
                map(float, values)
            )
            for timestamp, *values in rows
            if all(value is not None and math.isfinite(value) for value in values)
        }
    except (requests.RequestException, KeyError, TypeError, ValueError) as error:
        raise WeatherError(
            "Nie udało się odczytać danych godzinowych Open-Meteo."
        ) from error
    try:
        with mongo_client() as client:
            cache = mongo_database(client).MLWeatherCache
            cache.create_index("expires_at", expireAfterSeconds=0)
            cache.replace_one(
                {"_id": key},
                {
                    "_id": key, "source": url, "parameters": parameters,
                    "fetched_at": now, "expires_at": now + lifetime,
                    "rows": [{"time": stamp, "values": list(values)} for stamp, values in result.items()],
                },
                upsert=True,
            )
    except PyMongoError:
        pass
    return result
