"""Read hourly weather series for the soil moisture and solar models."""

import math
from datetime import datetime, timedelta, timezone

import requests

UTC = timezone.utc  # noqa: UP017 - datetime.UTC requires Python 3.11.
HOUR = timedelta(hours=1)
DAY = timedelta(days=1)
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


class WeatherError(RuntimeError):
    """Weather data are unavailable or incomplete."""


def load_hourly_weather(url, coordinates, variables, *, timeout=(5, 45), **time_range):
    lon, lat = coordinates
    try:
        response = requests.get(
            url,
            params={
                "latitude": lat,
                "longitude": lon,
                "hourly": ",".join(variables),
                "timezone": "GMT",
                **time_range,
            },
            timeout=timeout,
        )
        response.raise_for_status()
        hourly = response.json()["hourly"]
        rows = zip(
            hourly["time"], *(hourly[column] for column in variables), strict=True
        )
        return {
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
