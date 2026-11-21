"""Blocking sync functions executed in the child processes."""

import atexit
from datetime import datetime, timezone as dt_timezone

from bson import ObjectId
from pymongo import MongoClient

from .open_meteo import OpenMeteoClient
from .repository import WeatherRepository

_repository: WeatherRepository | None = None


def initialize_worker(mongo_uri: str, database_name: str) -> None:
    """Create and reuse a MongoDB client within this worker process."""
    global _repository
    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5_000, timeoutMS=15_000)
    atexit.register(client.close)
    _repository = WeatherRepository(client[database_name])


def _worker_repository() -> WeatherRepository:
    if _repository is None:
        raise RuntimeError("The weather worker has not been initialized")
    return _repository


def refresh_current(
    orchard_id: ObjectId | str, latitude: float, longitude: float, timezone: str
) -> int:
    repository = _worker_repository()
    fetched_at = datetime.now(dt_timezone.utc)
    current, points, hourly_units = OpenMeteoClient().fetch_current_and_hourly(
        latitude, longitude, timezone
    )
    repository.save_history(orchard_id, points, hourly_units, fetched_at)
    repository.save_current(orchard_id, current, fetched_at)
    return 1 + len(points)


def refresh_daily(
    orchard_id: ObjectId | str,
    latitude: float,
    longitude: float,
    timezone: str,
    forecast_days: int,
    history_days: int,
) -> int:
    repository = _worker_repository()
    fetched_at = datetime.now(dt_timezone.utc)
    hourly = OpenMeteoClient().fetch_hourly(
        latitude,
        longitude,
        timezone,
        past_days=history_days,
        forecast_days=forecast_days,
        include_daily=True,
    )
    past = [point for point in hourly.points if point.valid_at < hourly.forecast_start]
    forecast = [point for point in hourly.points if point.valid_at >= hourly.forecast_start]
    repository.save_history(orchard_id, past, hourly.units, fetched_at)
    repository.save_daily(orchard_id, hourly.days, hourly.daily_units, fetched_at)
    repository.save_forecast(orchard_id, forecast, hourly.units, fetched_at)
    return len(hourly.points) + len(hourly.days)


def backfill_history(
    orchard_id: ObjectId | str, latitude: float, longitude: float, timezone: str, days: int
) -> int:
    repository = _worker_repository()
    fetched_at = datetime.now(dt_timezone.utc)
    hourly = OpenMeteoClient().fetch_hourly(
        latitude, longitude, timezone, past_days=days, forecast_days=1, include_daily=True
    )
    past = [point for point in hourly.points if point.valid_at < hourly.forecast_start]
    past_days = [day for day in hourly.days if not day.is_forecast]
    repository.save_history(orchard_id, past, hourly.units, fetched_at)
    repository.save_daily(orchard_id, past_days, hourly.daily_units, fetched_at)
    return len(past) + len(past_days)
