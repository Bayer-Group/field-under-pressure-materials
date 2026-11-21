"""Run a daily weather-driven analysis on an already exported SAR grid."""

import hashlib
import json
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from statistics import mean
from tempfile import TemporaryDirectory

import numpy as np
from astral import Observer
from fastapi import HTTPException
from rasterio.errors import RasterioError
from rasterio.features import geometry_mask
from rasterio.io import MemoryFile
from rasterio.warp import transform_geom
from shapely.geometry import shape
from shapely.ops import unary_union

from backend.raster_exports import download_raster, find_saved_raster, local_raster
from ML.soil_moisture import forecast
from ML.soil_moisture.earth_engine import NODATA
from ML.soil_moisture.field_geometry import geojson_features
from ML.soil_moisture.open_meteo import DAY, FORECAST_URL, UTC, WeatherError
from ML.soil_moisture.solar_intensity_calc import (
    RADIATION_BAND,
    WARSAW,
    completed_day_hours,
    summarize_energy,
)

DAYS_AHEAD = 3
SOURCE = "Open-Meteo Weather Forecast"
CONTEXT_COLUMNS = (
    *forecast.WEATHER_COLUMNS,
    RADIATION_BAND,
    "relative_humidity_2m",
    "wind_speed_10m",
    "cloud_cover",
)


def utc_stamp(stamp):
    return stamp.replace(tzinfo=UTC) if stamp.tzinfo is None else stamp.astimezone(UTC)


def issue_hour(day, requested_hour=None):
    now = datetime.now(UTC)
    today = now.astimezone(WARSAW).date()
    if not today <= day <= today + DAYS_AHEAD * DAY:
        raise HTTPException(422, "Wybierz datę od dzisiaj do trzech dni naprzód.")
    hour = now.replace(minute=0, second=0, microsecond=0)
    if requested_hour is None:
        return hour
    candidate = utc_stamp(requested_hour)
    if candidate not in (hour, hour - forecast.HOUR):
        raise HTTPException(409, "Odśwież analizę, aby wczytać aktualną prognozę.")
    return candidate


@lru_cache(maxsize=32)
def context_hours(coordinates, issued):
    # The UTC dates include the previous UTC evening at the start of a Warsaw day.
    return forecast.load_weather(
        FORECAST_URL,
        coordinates,
        CONTEXT_COLUMNS,
        past_days=1,
        forecast_days=DAYS_AHEAD + 2,
    )


def daily_context(day, coordinates, issued):
    hours = completed_day_hours(day)
    try:
        hourly = context_hours(coordinates, issued)
        rows = [hourly[hour] for hour in hours]
    except (WeatherError, KeyError):
        return {}, {}
    rain, et0, temperature, radiation, humidity, wind, cloud = zip(*rows, strict=True)
    weather = {
        "date_local": day.isoformat(),
        "source": SOURCE,
        "precipitation_mm": sum(rain),
        "reference_et0_mm": sum(et0),
        "mean_temperature_c": mean(temperature),
        "mean_humidity_percent": mean(humidity),
        "mean_wind_km_h": mean(wind),
        "mean_cloud_percent": mean(cloud),
    }
    observer = Observer(longitude=coordinates[0], latitude=coordinates[1])
    try:
        solar = summarize_energy(
            day, observer, hours, sum(max(0, item) for item in radiation), SOURCE
        )
    except ValueError:
        solar = {}
    return weather, solar


@lru_cache(maxsize=8)
def anchor_raster(credentials, filename, database=None):
    if raster := local_raster(database, filename):
        with raster:
            return raster.read()
    if credentials is None:
        raise ValueError("Brak zapisanego rastra i dostępu do Google Drive.")
    file = find_saved_raster(credentials, filename)
    with TemporaryDirectory(prefix="field-forecast-") as folder:
        return download_raster(credentials, file, Path(folder)).read_bytes()


@lru_cache(maxsize=16)
def weather_model(coordinates, anchor, issued):
    return forecast.projection_inputs(coordinates, anchor, issued, DAYS_AHEAD)


@lru_cache(maxsize=16)
def project_raster(credentials, filename, coordinates, geometry, anchor, day, issued, database=None):
    # Keep the source grid so tree pixel row/column indices also index the forecast.
    with (
        MemoryFile(anchor_raster(credentials, filename, database)) as source,
        source.open() as raster,
    ):
        if not raster.crs or raster.count not in (1, 3):
            raise ValueError("Raster bazowy wilgotności musi mieć CRS i 1 lub 3 pasma.")
        observed = raster.read(raster.count, masked=True)
        in_field = geometry_mask(
            [
                transform_geom("EPSG:4326", raster.crs, feature["geometry"])
                for feature in json.loads(geometry)
            ],
            out_shape=observed.shape,
            transform=raster.transform,
            invert=True,
        )
        valid = (
            in_field
            & ~np.ma.getmaskarray(observed)
            & np.isfinite(observed.data)
            & (observed.data >= 0)
            & (observed.data <= 1)
        )
        if not np.any(valid):
            raise ValueError("Raster bazowy nie zawiera ważnych pikseli pola.")
        grid = {
            "crs": raster.crs,
            "transform": raster.transform,
            "width": raster.width,
            "height": raster.height,
        }
    model, validation, weather = weather_model(coordinates, anchor, issued)
    target = completed_day_hours(day)[-1]
    projected, _, _ = forecast.advance(
        model, observed.data[valid], weather, anchor, target
    )
    values = np.full(observed.shape, NODATA, dtype=np.float32)
    values[valid] = projected
    with MemoryFile() as output:
        with output.open(
            driver="GTiff",
            count=1,
            dtype="float32",
            nodata=NODATA,
            compress="deflate",
            **grid,
        ) as raster:
            raster.write(values, 1)
        contents = output.read()
    token = hashlib.sha256(
        f"{filename}:{day}:{issued.isoformat()}".encode()
    ).hexdigest()[:12]
    return {
        "mean_m3_m3": float(np.mean(values[valid], dtype=float)),
        "valid_pixels": int(np.count_nonzero(valid)),
        "raster": f"soil_moisture_forecast_{day}_{token}.tif",
        "valid_at_utc": target,
        "validation": validation,
    }, contents


def evaluate_day(orchard, analysis, day, issued, credentials, database=None):
    features = geojson_features(orchard.get("geometry"), "Orchard.geometry")
    center = orchard.get("centroid") or {}
    if center.get("long") is not None and center.get("lat") is not None:
        coordinates = (center["long"], center["lat"])
    else:
        point = unary_union([shape(feature["geometry"]) for feature in features]).representative_point()
        coordinates = (point.x, point.y)
    weather, solar = daily_context(day, coordinates, issued)
    baseline = analysis.get("soil_moisture") or {}
    stamp, filename = baseline.get("acquired_at_utc"), baseline.get("raster")
    anchor = utc_stamp(stamp) if isinstance(stamp, datetime) else None
    result = {
        "date_local": day.isoformat(),
        "issued_at_utc": issued,
        "weather": weather,
        "solar": solar,
        "anchor_at_utc": anchor,
        "moisture": {},
        "raster_bytes": None,
        "moisture_status": "missing_sar",
    }
    if not anchor or not filename:
        return result
    if not 0 <= (issued.date() - anchor.date()).days <= 92:
        result["moisture_status"] = "stale_sar"
        return result
    if credentials is None and database is None:
        result["moisture_status"] = "unavailable"
        return result
    try:
        metrics, contents = project_raster(
            credentials,
            filename,
            coordinates,
            json.dumps(features, sort_keys=True),
            anchor,
            day,
            issued,
            database,
        )
    except (WeatherError, ValueError, HTTPException, RasterioError):
        result["moisture_status"] = "unavailable"
        return result
    result.update(
        moisture={**metrics, "acquired_at_utc": anchor},
        raster_bytes=contents,
        moisture_status="available",
    )
    return result


def forecast_pixels(contents):
    if contents is None:
        return None
    with MemoryFile(contents) as source, source.open() as raster:
        return raster.read(1)


def value_at_pixel(values, pixel):
    row, col = pixel.get("row"), pixel.get("column")
    if values is None or not isinstance(row, int) or not isinstance(col, int):
        return None
    if 0 <= row < values.shape[0] and 0 <= col < values.shape[1]:
        value = float(values[row, col])
        if 0 <= value <= 1:
            return value
    return None
