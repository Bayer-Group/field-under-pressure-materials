"""
Daily weather features for one weather grid cell over a season.

Every feature for day D is a trailing value (a sum or mean over days <= D), so assessing day D never
looks at weather after D: the "as of that day" rule of the contract holds for every row, even though
the season is computed in one pass. Coming days (after today) append the forecast issued today to
the weather observed up to today (load_forecast). Weather is read only through the platform helpers
(`.observed(as_of=...)`, `.current(as_of=...)`).
"""

from __future__ import annotations

from datetime import date, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from core.models import WeatherDaily, WeatherForecastDaily, WeatherHourly

LOCAL_TZ = ZoneInfo("Europe/Warsaw")
WET_RH = 95.0        # % relative humidity counted as wet leaves (leaf wetness proxy), team assumption
HUMID_RH = 85.0      # % counted as humid
RAIN_WET_MM = 0.2    # mm/h counted as rain
LOOKBACK_DAYS = 45   # weather loaded before the first assessed day, for trailing windows

DAILY_COLS = [
    "date", "avg_temperature", "min_temperature", "max_temperature", "avg_relative_humidity",
    "total_precipitation", "imerg_total_precipitation", "eto", "avg_wind_speed",
    "avg_soil_temperature_level_1", "min_soil_temperature_level_1", "avg_soil_moisture_level_1",
    "avg_snow_depth",
]
HOURLY_COLS = ["utc_time", "temperature", "dew_point_temperature", "relative_humidity", "precipitation", "imerg_precipitation"]


def load_daily(grid_id: str, start: date, end: date) -> pd.DataFrame:
    qs = (WeatherDaily.objects.observed(as_of=end)
          .filter(grid_id=grid_id, date__gte=start - timedelta(days=LOOKBACK_DAYS))
          .order_by("date").values(*DAILY_COLS))
    df = pd.DataFrame.from_records(qs, columns=DAILY_COLS)
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").astype(float)
    # The weather packages carry no precipitation; it comes from IMERG (satellite). Use the weather
    # model's value when present, else IMERG. Engine code reads "precip".
    df["precip"] = df["total_precipitation"].fillna(df["imerg_total_precipitation"])
    return df


def load_forecast(grid_id: str, issued_on: date) -> pd.DataFrame:
    """
    The daily forecast issued on `issued_on` (the next 7 days), with the same columns as load_daily so the
    coming days can be appended to the observed weather. There is no IMERG forecast: "precip" is the
    forecast's own total_precipitation (the demo seed fills it from the observed day's IMERG value).
    """
    cols = [c for c in DAILY_COLS if not c.startswith("imerg_")]
    qs = (WeatherForecastDaily.objects.current(as_of=issued_on).filter(grid_id=grid_id)
          .order_by("date").values(*cols))
    df = pd.DataFrame.from_records(qs, columns=cols)
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").astype(float)
    df["imerg_total_precipitation"] = np.nan
    df["precip"] = df["total_precipitation"]
    return df[[c for c in DAILY_COLS if c != "date"] + ["precip"]]


def load_hourly(grid_id: str, start: date, end: date) -> pd.DataFrame:
    qs = (WeatherHourly.objects.observed(as_of=end)
          .filter(grid_id=grid_id, date__gte=start - timedelta(days=LOOKBACK_DAYS))
          .order_by("utc_time").values(*HOURLY_COLS))
    df = pd.DataFrame.from_records(qs, columns=HOURLY_COLS)
    if df.empty:
        return df
    df["local"] = pd.to_datetime(df["utc_time"], utc=True).dt.tz_convert(LOCAL_TZ)
    df["date"] = pd.to_datetime(df["local"].dt.date)
    df["precip"] = df["precipitation"].fillna(df["imerg_precipitation"])
    return df


def hourly_moisture(h: pd.DataFrame, kind: str) -> pd.Series:
    rh = h["relative_humidity"]
    rain = h["precip"].fillna(0) >= RAIN_WET_MM
    if kind == "wet":
        return (rh >= WET_RH) | rain
    if kind == "humid":
        return (rh >= HUMID_RH) | rain
    if kind == "rh90":  # potato late blight (Smith-type periods): RH >= 90 % or rain
        return (rh >= 90) | rain
    if kind == "mild":
        return (rh >= 50) & (rh < 95) & ~rain
    raise ValueError(kind)


def daily_moisture_estimate(d: pd.DataFrame, kind: str) -> pd.Series:
    """Fallback when no hourly data: share of the day that is wet/humid, estimated from daily values."""
    rh = d["avg_relative_humidity"]
    if kind == "wet":
        share = ((rh - 82) / 15).clip(0, 1)
    elif kind == "humid":
        share = ((rh - 65) / 20).clip(0, 1)
    elif kind == "rh90":
        share = ((rh - 75) / 17).clip(0, 1)
    else:
        share = ((rh >= 50) & (d["precip"].fillna(0) < 1)).astype(float)
    return share


def condition_hours(daily: pd.DataFrame, hourly: pd.DataFrame, tmin: float, tmax: float, kind: str) -> tuple[pd.Series, pd.Series]:
    """
    Hours per day with temperature in [tmin, tmax] and the moisture condition.
    Returns (hours per day, flag per day: True where estimated from daily data because hourly is missing).
    """
    idx = daily.index
    if not hourly.empty:
        ok = hourly["temperature"].between(tmin, tmax) & hourly_moisture(hourly, kind)
        per_day = ok.groupby(hourly["date"]).sum().astype(float).reindex(idx)
        n_hours = hourly.groupby("date").size().reindex(idx).fillna(0)
    else:
        per_day = pd.Series(np.nan, index=idx)
        n_hours = pd.Series(0, index=idx)
    estimated = n_hours < 20
    if estimated.any():
        t = daily["avg_temperature"]
        in_range = ((t >= tmin) & (t <= tmax)).astype(float)
        est = 24 * in_range * daily_moisture_estimate(daily, kind)
        per_day = per_day.where(~estimated, est)
    return per_day.fillna(0), estimated


def trailing_sum(s: pd.Series, days: int) -> pd.Series:
    return s.rolling(f"{days}D", min_periods=1).sum()


def trailing_mean(s: pd.Series, days: int) -> pd.Series:
    return s.rolling(f"{days}D", min_periods=1).mean()
