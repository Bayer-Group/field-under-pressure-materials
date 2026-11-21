"""Fetch and validate weather for one orchard point from Open-Meteo."""

import json
import ssl
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone as datetime_timezone
from http.client import HTTPException
from math import isfinite
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen

try:
    import certifi
except ImportError:
    certifi = None

_SSL_CONTEXT = (
    ssl.create_default_context(cafile=certifi.where())
    if certifi is not None
    else ssl.create_default_context()
)


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
DAILY_FIELDS = (
    "temperature_2m_min", "temperature_2m_max", "relative_humidity_2m_mean",
    "precipitation_sum", "rain_sum", "showers_sum", "snowfall_sum", "snow_depth_max",
)

WeatherValue = int | float | None


class OpenMeteoError(Exception):
    """The provider could not supply a usable response."""


@dataclass(frozen=True)
class WeatherPoint:
    valid_at: datetime
    values: dict[str, WeatherValue]


@dataclass(frozen=True)
class WeatherDay:
    date: str
    valid_at: datetime
    values: dict[str, WeatherValue]
    is_forecast: bool


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
    days: list[WeatherDay] = field(default_factory=list)
    daily_units: dict[str, str] = field(default_factory=dict)


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
        return _current_weather(data)

    def fetch_current_and_hourly(
        self, latitude: float, longitude: float, timezone: str
    ) -> tuple[CurrentWeather, list[WeatherPoint], dict[str, str]]:
        """Fetch current conditions and hourly points through the current time."""
        past_hours = 24
        forecast_hours = 1
        data = self._fetch(latitude, longitude, timezone, {
            "current": ",".join(CURRENT_FIELDS),
            "hourly": ",".join(HOURLY_FIELDS),
            "past_hours": past_hours,
            "forecast_hours": forecast_hours,
        })
        current = _current_weather(data)
        points = _series_rows(data, "hourly", HOURLY_FIELDS, past_hours + forecast_hours, 3600)
        completed = [point for point in points if point.valid_at <= current.valid_at]
        if not completed:
            raise OpenMeteoError("No hourly timestamps at or before the current weather time")
        return current, completed, _units(data, "hourly_units", HOURLY_FIELDS)

    def fetch_hourly(
        self, latitude: float, longitude: float, timezone: str, *,
        past_days: int, forecast_days: int, include_daily: bool = False,
    ) -> HourlyWeather:
        if type(past_days) is not int or not 0 <= past_days <= 92:
            raise ValueError("past_days must be an integer between 0 and 92")
        if type(forecast_days) is not int or not 1 <= forecast_days <= 15:
            raise ValueError("forecast_days must be an integer between 1 and 15")
        parameters: dict[str, str | int] = {
            "hourly": ",".join(HOURLY_FIELDS),
            "past_days": past_days,
            "forecast_days": forecast_days,
        }
        if include_daily:
            parameters["daily"] = ",".join(DAILY_FIELDS)
        data = self._fetch(latitude, longitude, timezone, parameters)
        total_days = past_days + forecast_days
        points = _series_rows(data, "hourly", HOURLY_FIELDS, total_days * 24, 3600)

        response_timezone = data.get("timezone")
        if not isinstance(response_timezone, str) or not response_timezone:
            raise OpenMeteoError("Missing timezone in the Open-Meteo response")

        days = []
        daily_units = {}
        if include_daily:
            days = _daily_weather(data, points, past_days, total_days)
            daily_units = _units(data, "daily_units", DAILY_FIELDS)

        # The API uses the offset at request time for the whole response, including day boundaries.
        return HourlyWeather(
            timezone=response_timezone,
            points=points,
            units=_units(data, "hourly_units", HOURLY_FIELDS),
            forecast_start=points[past_days * 24].valid_at,
            days=days,
            daily_units=daily_units,
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
            with urlopen(
                f"{FORECAST_URL}?{query}", timeout=self.timeout_seconds, context=_SSL_CONTEXT
            ) as response:
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


def _current_weather(data: dict) -> CurrentWeather:
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


def _series_rows(
    data: dict, key: str, fields: tuple[str, ...], count: int, step_seconds: int
) -> list[WeatherPoint]:
    source = _response_object(data, key)
    timestamps = source.get("time")
    if not isinstance(timestamps, list) or len(timestamps) != count:
        raise OpenMeteoError(f"Unexpected number of {key} timestamps in the Open-Meteo response")
    if any(type(timestamp) is not int for timestamp in timestamps):
        raise OpenMeteoError(f"Expected {key} Unix timestamps in the Open-Meteo response")
    if any(right - left != step_seconds for left, right in zip(timestamps, timestamps[1:])):
        raise OpenMeteoError(f"Non-contiguous {key} timestamps in the Open-Meteo response")

    for field in fields:
        values = source.get(field)
        if not isinstance(values, list) or len(values) != count:
            raise OpenMeteoError(f"{key.capitalize()} series for {field} does not match the timestamps")
    return [
        WeatherPoint(
            valid_at=_timestamp(timestamp),
            values={field: _weather_value(source[field][index], field) for field in fields},
        )
        for index, timestamp in enumerate(timestamps)
    ]


def _daily_weather(
    data: dict, hourly: list[WeatherPoint], past_days: int, total_days: int
) -> list[WeatherDay]:
    daily = _series_rows(data, "daily", DAILY_FIELDS, total_days, 86_400)
    if any(day.valid_at != hour.valid_at for day, hour in zip(daily, hourly[::24])):
        raise OpenMeteoError("Daily and hourly timestamps have different day boundaries")
    offset_seconds = data.get("utc_offset_seconds")
    if type(offset_seconds) is not int or not -86_400 < offset_seconds < 86_400:
        raise OpenMeteoError("Invalid UTC offset in the Open-Meteo response")
    offset = datetime_timezone(timedelta(seconds=offset_seconds))
    return [
        WeatherDay(
            date=point.valid_at.astimezone(offset).date().isoformat(),
            valid_at=point.valid_at,
            values=point.values,
            is_forecast=index >= past_days,
        )
        for index, point in enumerate(daily)
    ]


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
