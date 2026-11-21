"""Fetch and validate weather for one orchard point from Open-Meteo."""

import json
from dataclasses import dataclass
from datetime import datetime, timezone as datetime_timezone
from http.client import HTTPException
from math import isfinite
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen


FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
MODEL = "ecmwf_ifs"
CURRENT_FIELDS = (
    "temperature_2m", "relative_humidity_2m", "rain", "showers", "snowfall",
    "weather_code", "cloud_cover",
)
HOURLY_FIELDS = (
    "snowfall", "showers", "rain", "precipitation", "relative_humidity_2m",
    "temperature_2m", "snow_depth",
)

WeatherValue = int | float | None


class OpenMeteoError(Exception):
    """The provider could not supply a usable response."""


@dataclass(frozen=True)
class WeatherPoint:
    valid_at: datetime
    values: dict[str, WeatherValue]


@dataclass(frozen=True)
class CurrentWeather:
    valid_at: datetime
    interval_seconds: int
    values: dict[str, WeatherValue]
    units: dict[str, str]


@dataclass(frozen=True)
class HourlyWeather:
    timezone: str
    points: list[WeatherPoint]
    units: dict[str, str]
    forecast_start: datetime


class OpenMeteoClient:
    """Read model data for one coordinate pair and decode timestamps as UTC."""

    def __init__(self, timeout_seconds: float = 15) -> None:
        if not isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("The Open-Meteo timeout must be positive and finite")
        self.timeout_seconds = timeout_seconds

    def fetch_current(
        self, latitude: float, longitude: float, timezone: str
    ) -> CurrentWeather:
        data = self._fetch(latitude, longitude, timezone, {
            "current": ",".join(CURRENT_FIELDS),
            "forecast_days": 1,
        })
        current = _response_object(data, "current")
        interval = current.get("interval")
        if type(interval) is not int or interval <= 0:
            raise OpenMeteoError("Invalid current interval in the Open-Meteo response")
        missing_fields = set(CURRENT_FIELDS).difference(current)
        if missing_fields:
            raise OpenMeteoError(f"Missing current fields: {', '.join(sorted(missing_fields))}")

        return CurrentWeather(
            valid_at=_timestamp(current.get("time")),
            interval_seconds=interval,
            values={field: _weather_value(current[field], field) for field in CURRENT_FIELDS},
            units=_units(data, "current_units", CURRENT_FIELDS),
        )

    def fetch_hourly(
        self, latitude: float, longitude: float, timezone: str, *,
        past_days: int, forecast_days: int,
    ) -> HourlyWeather:
        if type(past_days) is not int or not 0 <= past_days <= 92:
            raise ValueError("past_days must be an integer between 0 and 92")
        if type(forecast_days) is not int or not 1 <= forecast_days <= 15:
            raise ValueError("forecast_days must be an integer between 1 and 15")
        data = self._fetch(latitude, longitude, timezone, {
            "hourly": ",".join(HOURLY_FIELDS),
            "past_days": past_days,
            "forecast_days": forecast_days,
        })
        hourly = _response_object(data, "hourly")
        timestamps = hourly.get("time")
        expected_hours = 24 * (past_days + forecast_days)
        if not isinstance(timestamps, list) or len(timestamps) != expected_hours:
            raise OpenMeteoError("Unexpected number of hours in the Open-Meteo response")
        if any(type(timestamp) is not int for timestamp in timestamps):
            raise OpenMeteoError("Expected hourly Unix timestamps in the Open-Meteo response")
        if any(right - left != 3600 for left, right in zip(timestamps, timestamps[1:])):
            raise OpenMeteoError("Non-contiguous hourly timestamps in the Open-Meteo response")

        series = {}
        for field in HOURLY_FIELDS:
            values = hourly.get(field)
            if not isinstance(values, list) or len(values) != expected_hours:
                raise OpenMeteoError(f"Hourly series for {field} does not match the timestamps")
            series[field] = values

        points = [
            WeatherPoint(
                valid_at=_timestamp(timestamp),
                values={field: _weather_value(series[field][index], field) for field in HOURLY_FIELDS},
            )
            for index, timestamp in enumerate(timestamps)
        ]
        response_timezone = data.get("timezone")
        if not isinstance(response_timezone, str) or not response_timezone:
            raise OpenMeteoError("Missing timezone in the Open-Meteo response")

        # The API uses the offset at request time for the whole response, including day boundaries.
        return HourlyWeather(
            timezone=response_timezone,
            points=points,
            units=_units(data, "hourly_units", HOURLY_FIELDS),
            forecast_start=points[past_days * 24].valid_at,
        )

    def _fetch(
        self, latitude: float, longitude: float, timezone: str, parameters: dict[str, str | int]
    ) -> dict:
        if type(latitude) not in (int, float) or not -90 <= latitude <= 90:
            raise ValueError("latitude must be a number between -90 and 90")
        if type(longitude) not in (int, float) or not -180 <= longitude <= 180:
            raise ValueError("longitude must be a number between -180 and 180")
        if not isinstance(timezone, str) or not timezone.strip():
            raise ValueError("timezone must be a non-empty timezone name or 'auto'")

        query = urlencode({
            "latitude": latitude,
            "longitude": longitude,
            "timezone": timezone,
            "models": MODEL,
            "timeformat": "unixtime",
            **parameters,
        })
        try:
            with urlopen(f"{FORECAST_URL}?{query}", timeout=self.timeout_seconds) as response:
                data = json.load(response)
        except HTTPError as error:
            raise OpenMeteoError(f"Open-Meteo returned HTTP {error.code}") from error
        except (OSError, HTTPException) as error:
            raise OpenMeteoError(f"Open-Meteo request failed: {error}") from error
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise OpenMeteoError("Open-Meteo returned invalid JSON") from error

        if not isinstance(data, dict) or data.get("error"):
            raise OpenMeteoError("Open-Meteo did not return a weather object for the requested point")
        return data


def _response_object(data: dict, key: str) -> dict:
    value = data.get(key)
    if not isinstance(value, dict):
        raise OpenMeteoError(f"Missing {key} object in the Open-Meteo response")
    return value


def _timestamp(value: object) -> datetime:
    if type(value) is not int:
        raise OpenMeteoError("Expected a Unix timestamp in the Open-Meteo response")
    try:
        return datetime.fromtimestamp(value, tz=datetime_timezone.utc)
    except (ValueError, OverflowError, OSError) as error:
        raise OpenMeteoError("Invalid Unix timestamp in the Open-Meteo response") from error


def _weather_value(value: object, field: str) -> WeatherValue:
    if value is None or type(value) is int or (type(value) is float and isfinite(value)):
        return value
    raise OpenMeteoError(f"Invalid value for {field} in the Open-Meteo response")


def _units(data: dict, key: str, fields: tuple[str, ...]) -> dict[str, str]:
    source = _response_object(data, key)
    units = {}
    for field in fields:
        unit = source.get(field)
        if not isinstance(unit, str) or not unit:
            raise OpenMeteoError(f"Missing unit for {field} in the Open-Meteo response")
        units[field] = unit
    return units
