"""Forecast soil moisture between available Sentinel-1 observations."""

import argparse
import json
from dataclasses import replace
from datetime import datetime, timedelta
from itertools import pairwise
from statistics import median

import ee
import numpy as np
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from ML.soil_moisture import earth_engine as sar
from ML.soil_moisture.open_meteo import (
    ARCHIVE_URL,
    DAY,
    FORECAST_URL,
    HOUR,
    UTC,
    WeatherError,
    load_hourly_weather,
)
from ML.soil_moisture.project_config import earth_engine_project

WEATHER_COLUMNS = ("precipitation", "et0_fao_evapotranspiration", "temperature_2m")
MOISTURE = "soil_moisture_0_to_7cm"


def overpass_after(acquisition, recent_passes, now):
    days = sorted({passed.date() for passed in recent_passes if passed <= acquisition})
    intervals = [(end - start).days for start, end in pairwise(days)]
    # Ignore split scenes and long catalog gaps when estimating a repeat cycle.
    comparable = [gap for gap in intervals if 5 <= gap <= 13]
    repeat_days = 12 if comparable and median(comparable) >= 9 else 6
    next_pass = acquisition + timedelta(days=repeat_days)
    while next_pass <= now:
        next_pass += timedelta(days=repeat_days)
    return next_pass, repeat_days


def sar_anchor(config, now, model_asset):
    fields = sar.load_fields(config.fields_geojson)
    footprint = fields.geometry(maxError=1)
    latest_scenes = sar.sentinel_scenes(
        (now - 45 * DAY).isoformat(), now.isoformat(), config.orbit_pass
    ).filterBounds(footprint)
    if config.relative_orbit is not None:
        latest_scenes = latest_scenes.filter(
            ee.Filter.eq("relativeOrbitNumber_start", config.relative_orbit)
        )
    full_coverage = sar.scenes_covering_fields(latest_scenes, footprint)
    counts = ee.Dictionary(
        {"available": latest_scenes.size(), "full_coverage": full_coverage.size()}
    ).getInfo()
    if not counts["available"]:
        raise ValueError("Brak scen Sentinel-1 nad polami z ostatnich 45 dni.")
    candidates = full_coverage if counts["full_coverage"] else latest_scenes
    scene = ee.Image(candidates.sort("system:time_start", False).first())
    properties = (
        scene.toDictionary(
            ["system:time_start", "relativeOrbitNumber_start", "platform_number"]
        )
        .set("weather_coordinates", footprint.centroid(maxError=1).coordinates())
        .getInfo()
    )
    acquisition = datetime.fromtimestamp(properties["system:time_start"] / 1000, UTC)
    orbit = properties["relativeOrbitNumber_start"]
    same_orbit = candidates.filter(ee.Filter.eq("relativeOrbitNumber_start", orbit))
    passes = [
        datetime.fromtimestamp(timestamp / 1000, UTC)
        for timestamp in same_orbit.aggregate_array("system:time_start").getInfo()
    ]

    if model_asset:
        forest = ee.Classifier.load(model_asset)
    else:
        history_end = acquisition.date() - 14 * DAY
        training_config = replace(
            config,
            start=(history_end - 120 * DAY).isoformat(),
            end=history_end.isoformat(),
            relative_orbit=orbit,
        )
        region = footprint.bounds(maxError=1).buffer(sar.FIELD_TRAINING_BUFFER_METERS)
        _, paired, _ = sar.matched_scenes(training_config, region, footprint)
        if not paired.size().getInfo():
            raise ValueError(
                "Brak historycznych par SAR i ERA5-Land do treningu modelu."
            )
        forest = sar.train_forest(sar.samples_for(paired, region, config.min_coverage))

    radar = sar.radar_bands(scene)
    moisture_band = "anchor_m3_m3"
    image = sar.radar_features(radar).classify(forest, moisture_band)
    per_field = image.reduceRegions(
        collection=fields,
        reducer=ee.Reducer.mean().setOutputs([moisture_band]),
        crs=radar.select("VV").projection(),
        tileScale=4,
    )
    result = (
        per_field.map(
            lambda field: ee.Feature(
                None, field.toDictionary(["field_id", moisture_band])
            )
        )
        .sort("field_id")
        .getInfo()
    )
    readings = {
        int(row["properties"]["field_id"]): row["properties"].get(moisture_band)
        for row in result["features"]
    }
    return (
        acquisition,
        passes,
        orbit,
        properties.get("platform_number"),
        properties["weather_coordinates"],
        readings,
    )


def load_weather(url, coordinates, variables, **time_range):
    return load_hourly_weather(
        url,
        tuple(round(coordinate, 2) for coordinate in coordinates),
        variables,
        **time_range,
    )


def advance(model, moisture, weather, start, end):
    rain_total = evaporation_total = 0.0
    while start < end:
        hour_end = start.replace(minute=0, second=0, microsecond=0) + HOUR
        boundary = min(hour_end, end)
        fraction = (boundary - start) / HOUR
        if hour_end not in weather:
            raise WeatherError(
                f"Brak danych pogodowych na godzinę {hour_end.isoformat()}."
            )
        rain, evaporation, temperature = weather[hour_end][: len(WEATHER_COLUMNS)]
        drivers = np.broadcast_to((rain, evaporation, temperature), (len(moisture), 3))
        features = np.column_stack((moisture, drivers))
        moisture = np.clip(moisture + fraction * model.predict(features), 0.0, 1.0)
        rain_total += fraction * rain
        evaporation_total += fraction * evaporation
        start = boundary
    return moisture, rain_total, evaporation_total


def fit_weather_model(history):
    samples = []
    for stamp, row in sorted(history.items()):
        previous = history.get(stamp - HOUR)
        if previous is not None and 0 <= previous[-1] <= 1 and 0 <= row[-1] <= 1:
            samples.append(([previous[-1], *row[:-1]], row[-1] - previous[-1], stamp))
    if len(samples) < 48:
        raise WeatherError("Za mało kompletnych danych historycznych do treningu.")

    split = len(samples) * 4 // 5
    features, changes, timestamps = zip(*samples)
    model = make_pipeline(StandardScaler(), Ridge(alpha=1.0))
    model.fit(features[:split], changes[:split])
    errors, persistence = [], []
    for start in timestamps[split:]:
        if start.hour != 0 or start + DAY not in history:
            continue
        initial, expected = history[start][-1], history[start + DAY][-1]
        if not (0 <= initial <= 1 and 0 <= expected <= 1):
            continue
        try:
            result, _, _ = advance(
                model, np.array([initial]), history, start, start + DAY
            )
        except WeatherError:
            continue
        errors.append(abs(float(result[0]) - expected))
        persistence.append(abs(initial - expected))
    validation = {
        "windows_24h": len(errors),
        "mae_24h_m3_m3": float(np.mean(errors)) if errors else None,
        "persistence_mae_24h_m3_m3": float(np.mean(persistence)) if errors else None,
    }
    return model.fit(features, changes), validation


def projection_inputs(coordinates, anchor, now, days):
    history_end = min(now.date() - 7 * DAY, anchor.date() - DAY)
    history = load_weather(
        ARCHIVE_URL,
        coordinates,
        (*WEATHER_COLUMNS, MOISTURE),
        start_date=(history_end - 180 * DAY).isoformat(),
        end_date=history_end.isoformat(),
        models="era5_seamless",
    )
    model, validation = fit_weather_model(history)
    weather = load_weather(
        FORECAST_URL,
        coordinates,
        WEATHER_COLUMNS,
        past_days=(now.date() - anchor.date()).days,
        forecast_days=days + 2,
    )
    return model, validation, weather


def forecast_fields(config=None, *, model_asset=None, now=None):
    config = config or sar.SoilMoistureConfig()
    now = (now or datetime.now(UTC)).astimezone(UTC).replace(microsecond=0)
    anchor, passes, orbit, platform, coordinates, readings = sar_anchor(
        config, now, model_asset
    )
    next_pass, repeat_days = overpass_after(anchor, passes, now)
    field_ids = [field_id for field_id, value in readings.items() if value is not None]
    if not field_ids:
        raise ValueError("Scena Sentinel-1 nie zawiera ważnych pikseli na żadnym polu.")

    history_end = min(now.date() - 7 * DAY, anchor.date() - DAY)
    historical = load_weather(
        ARCHIVE_URL,
        coordinates,
        (*WEATHER_COLUMNS, MOISTURE),
        start_date=(history_end - 180 * DAY).isoformat(),
        end_date=history_end.isoformat(),
        models="era5_seamless",
    )
    model, validation = fit_weather_model(historical)
    weather = load_weather(
        FORECAST_URL,
        coordinates,
        WEATHER_COLUMNS,
        past_days=(now.date() - anchor.date()).days,
        forecast_days=(next_pass.date() - now.date()).days + 2,
    )

    values = np.array([readings[field_id] for field_id in field_ids])
    forecasts = {field_id: [] for field_id in field_ids}
    previous, forecast_time = anchor, now
    while True:
        values, rain, evaporation = advance(
            model, values, weather, previous, forecast_time
        )
        for field_id, value in zip(field_ids, values, strict=True):
            forecasts[field_id].append(
                {
                    "valid_at_utc": forecast_time.isoformat(),
                    "moisture_m3_m3": round(float(value), 5),
                    "precipitation_mm": round(rain, 2),
                    "reference_et0_mm": round(evaporation, 2),
                }
            )
        if forecast_time == next_pass:
            break
        previous = forecast_time
        midnight = (previous + DAY).replace(hour=0, minute=0, second=0)
        forecast_time = min(midnight, next_pass)

    return {
        "issued_at_utc": now.isoformat(),
        "sar_acquired_at_utc": anchor.isoformat(),
        "sar_relative_orbit": orbit,
        "sar_platform": platform,
        "estimated_repeat_days": repeat_days,
        "estimated_next_overpass_utc": next_pass.isoformat(),
        "weather_source": "Open-Meteo",
        "historical_weather_validation": validation,
        "fields": [
            {
                "field_id": field_id,
                "sar_moisture_m3_m3": value,
                "forecasts": forecasts.get(field_id, []),
            }
            for field_id, value in readings.items()
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project", help="Override the configured Google Cloud project."
    )
    parser.add_argument(
        "--model-asset", help="Optional Earth Engine asset for the trained forest."
    )
    parser.add_argument("--relative-orbit", type=int)
    parser.add_argument(
        "--pass",
        dest="orbit_pass",
        choices=("ASCENDING", "DESCENDING"),
        default="ASCENDING",
    )
    args = parser.parse_args()
    try:
        ee.Initialize(project=earth_engine_project(args.project))
        forecast = forecast_fields(
            sar.SoilMoistureConfig(
                orbit_pass=args.orbit_pass, relative_orbit=args.relative_orbit
            ),
            model_asset=args.model_asset,
        )
        print(json.dumps(forecast, indent=2))
    except (ee.EEException, WeatherError, OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
