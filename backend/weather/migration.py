"""Copy legacy weather collections into existing Orchard documents."""

from pymongo.database import Database

from .open_meteo import CurrentWeather, WeatherPoint
from .repository import WeatherRepository


def migrate_weather(db: Database, repository: WeatherRepository) -> tuple[int, int, int]:
    """Replay prior records with their original timestamps. Safe to run again."""
    current_count = forecast_count = history_count = 0
    for orchard in db["Orchard"].find({}, {"_id": 1}):
        orchard_id = orchard["_id"]
        current = db["weather_current"].find_one({"_id": orchard_id})
        if current:
            repository.save_current(
                orchard_id,
                CurrentWeather(
                    valid_at=current["valid_at"],
                    interval_seconds=current["interval_seconds"],
                    values=current["values"],
                    units=current["units"],
                ),
                current["fetched_at"],
            )
            current_count += 1

        forecast = db["weather_forecast"].find_one({"_id": orchard_id})
        if forecast:
            repository.save_forecast(
                orchard_id,
                [WeatherPoint(row["valid_at"], row["values"]) for row in forecast["points"]],
                forecast["units"],
                forecast["fetched_at"],
            )
            forecast_count += len(forecast["points"])

        batches = {}
        for row in db["weather_history"].find({"orchard_id": orchard_id}):
            key = (row["fetched_at"], tuple(sorted(row["units"].items())))
            batches.setdefault(key, []).append(WeatherPoint(row["valid_at"], row["values"]))
            history_count += 1
        for (fetched_at, units), points in batches.items():
            repository.save_history(orchard_id, points, dict(units), fetched_at)

    return current_count, forecast_count, history_count
