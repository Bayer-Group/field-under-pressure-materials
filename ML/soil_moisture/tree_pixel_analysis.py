"""Assign Sentinel-1 pixels, weather and solar data to trees in MongoDB."""

import argparse
import json
import math
import os
from datetime import date, datetime
from hashlib import sha256
from pathlib import Path

import numpy as np
import rasterio
from astral import Observer
from pymongo import UpdateOne
from pymongo.errors import PyMongoError
from rasterio.errors import RasterioError
from rasterio.warp import transform
from rasterio.windows import Window
from shapely.geometry import Point, shape
from shapely.ops import unary_union

from ML.soil_moisture import forecast
from ML.soil_moisture import solar_intensity_calc as solar
from ML.soil_moisture.field_geometry import (
    geojson_features,
    mongo_client,
    mongo_database,
    orchard_ids,
)

OUTPUT_COLLECTION = "TreePixelAnalysis"
BANDS = ("vv_db", "vh_db", "soil_moisture_m3_m3")


def key(*parts):
    return sha256(json.dumps(parts, separators=(",", ":")).encode()).hexdigest()


def load_orchard(database, orchard_id):
    orchards = list(
        database.Orchard.find(
            {"_id": {"$in": orchard_ids(orchard_id)}}, {"geometry": 1}
        )
    )
    if len(orchards) != 1:
        raise ValueError(
            "Podany identyfikator musi wskazywać dokładnie jeden rekord Orchard."
        )
    orchard = orchards[0]
    features = geojson_features(orchard.get("geometry"), "Orchard.geometry")
    boundary = unary_union([shape(feature["geometry"]) for feature in features])
    trees = list(
        database.Tree.find(
            {"orchardId": {"$in": [orchard["_id"], str(orchard["_id"])]}},
            {"geometry": 1, "geo": 1, "species": 1},
        ).sort("_id", 1)
    )
    if not trees:
        raise ValueError("Brak drzew w Tree z orchardId wskazującym podane pole.")
    return boundary, trees


def tree_positions(trees, boundary):
    positions, failures = {}, {}
    for tree in trees:
        tree_id = str(tree["_id"])
        geometry = tree.get("geometry") or {}
        geo = tree.get("geo") or {}
        coordinates = (
            geometry.get("coordinates")
            if isinstance(geometry, dict) and geometry.get("type") == "Point"
            else [geo.get("lng"), geo.get("lat")]
            if isinstance(geo, dict)
            else None
        )
        if not (
            isinstance(coordinates, (tuple, list))
            and len(coordinates) >= 2
            and all(
                isinstance(coord, (int, float))
                and not isinstance(coord, bool)
                and math.isfinite(coord)
                for coord in coordinates[:2]
            )
            and -180 <= coordinates[0] <= 180
            and -90 <= coordinates[1] <= 90
        ):
            failures[tree_id] = "invalid_coordinates"
            continue
        position = tuple(coordinates[:2])
        if not boundary.covers(Point(position)):
            failures[tree_id] = "outside_orchard"
            continue
        positions[tree_id] = position
    return positions, failures


def sample_pixels(path, scene_id, acquired_at, positions):
    pixels, assignments = {}, {}
    with rasterio.open(path) as raster:
        if not raster.crs or raster.count not in (1, 3):
            raise ValueError(
                "GeoTIFF wymaga CRS i jednego pasma wilgotności lub trzech pasm VV, VH, wilgotność."
            )
        if not positions:
            return pixels, assignments
        xs, ys = transform(
            "EPSG:4326", raster.crs, *zip(*positions.values(), strict=True)
        )
        crs = raster.crs.to_string()
        grid_transform = list(raster.transform)[:6]
        for tree_id, x, y in zip(positions, xs, ys, strict=True):
            row, col = raster.index(x, y)
            if not (0 <= row < raster.height and 0 <= col < raster.width):
                assignments[tree_id] = ("outside_raster", None)
                continue
            cell = (row, col)
            if cell not in pixels:
                raw = raster.read(window=Window(col, row, 1, 1), masked=True)[:, 0, 0]
                values = {
                    name: float(value)
                    for name, value in zip(BANDS[-raster.count :], raw, strict=True)
                    if not np.ma.is_masked(value)
                    and math.isfinite(value)
                    and value != -9999
                }
                estimate = values.pop(BANDS[-1], None)
                pixels[cell] = {
                    "id": key(
                        scene_id, acquired_at.isoformat(), crs, grid_transform, row, col
                    ),
                    "row": row,
                    "column": col,
                    "crs": crs,
                    "transform": grid_transform,
                    "center_xy": list(raster.xy(row, col)),
                    "radar": values,
                    "soil_moisture_estimate_m3_m3": (
                        estimate
                        if estimate is not None and 0 <= estimate <= 1
                        else None
                    ),
                }
            pixel = pixels[cell]
            status = (
                "sampled"
                if pixel["soil_moisture_estimate_m3_m3"] is not None
                else "no_soil_data"
            )
            assignments[tree_id] = (status, pixel)
    return pixels, assignments


def weather_summary(day, coordinates):
    hours = solar.completed_day_hours(day)
    dates = {
        "start_date": (hours[0] - forecast.HOUR).date().isoformat(),
        "end_date": hours[-1].date().isoformat(),
    }
    for url, source in (
        (forecast.ARCHIVE_URL, "Open-Meteo Historical Weather"),
        (forecast.FORECAST_URL, "Open-Meteo Weather Forecast"),
    ):
        try:
            weather = forecast.load_weather(
                url, coordinates, forecast.WEATHER_COLUMNS, **dates
            )
            rows = [weather[hour] for hour in hours]
        except (forecast.WeatherError, KeyError):
            continue
        rain, et0, temperature = zip(*rows, strict=True)
        return {
            "status": "available",
            "source": source,
            "precipitation_mm": sum(rain),
            "reference_et0_mm": sum(et0),
            "mean_temperature_c": sum(temperature) / len(temperature),
        }
    return {"status": "unavailable", "source": "Open-Meteo"}


def orchard_context(day, coordinates):
    observer = Observer(longitude=coordinates[0], latitude=coordinates[1])
    try:
        radiation = {"status": "available", **solar.solar_summary(day, observer)}
    except ValueError:
        radiation = {"status": "unavailable", "source": "Open-Meteo"}
    return {
        "date_local": day.isoformat(),
        "timezone": "Europe/Warsaw",
        "location": {"type": "Point", "coordinates": list(coordinates)},
        "weather": weather_summary(day, coordinates),
        "solar": radiation,
    }


def predict_pixels(pixels, coordinates, anchor, now, days):
    """Advance one soil-moisture value per occupied pixel using the existing weather model."""
    active = {
        pixel["id"]: pixel["soil_moisture_estimate_m3_m3"]
        for pixel in pixels.values()
        if pixel["soil_moisture_estimate_m3_m3"] is not None
    }
    if not active or not days:
        return {}
    history_end = min(now.date() - 7 * forecast.DAY, anchor.date() - forecast.DAY)
    history = forecast.load_weather(
        forecast.ARCHIVE_URL,
        coordinates,
        (*forecast.WEATHER_COLUMNS, forecast.MOISTURE),
        start_date=(history_end - 180 * forecast.DAY).isoformat(),
        end_date=history_end.isoformat(),
        models="era5_seamless",
    )
    model, validation = forecast.fit_weather_model(history)
    weather = forecast.load_weather(
        forecast.FORECAST_URL,
        coordinates,
        forecast.WEATHER_COLUMNS,
        past_days=(now.date() - anchor.date()).days,
        forecast_days=days + 2,
    )
    values = np.array(list(active.values()))
    series = {pixel_id: [] for pixel_id in active}
    previous = anchor
    for day in range(1, days + 1):
        target = now + day * forecast.DAY
        values, _, _ = forecast.advance(model, values, weather, previous, target)
        for pixel_id, value in zip(active, values, strict=True):
            series[pixel_id].append(
                {"valid_at_utc": target, "soil_moisture_m3_m3": round(float(value), 5)}
            )
        previous = target
    return {
        pixel_id: {
            "status": "available",
            "issued_at_utc": now,
            "anchor_pixel_id": pixel_id,
            "source": "Open-Meteo and Sentinel-1 soil moisture Ridge forecast",
            "validation": validation,
            "values": values,
        }
        for pixel_id, values in series.items()
    }


def analyze(database, args, now):
    boundary, trees = load_orchard(database, args.orchard_id)
    positions, failures = tree_positions(trees, boundary)
    pixels, assignments = sample_pixels(
        args.raster, args.scene_id, args.acquired_at, positions
    )
    representative = boundary.representative_point()
    coordinates = (representative.x, representative.y)
    context = orchard_context(args.date, coordinates)
    predictions = {}
    forecast_error = None
    try:
        predictions = predict_pixels(
            pixels, coordinates, args.acquired_at, now, args.forecast_days
        )
    except forecast.WeatherError as error:
        forecast_error = str(error)

    collection = database[OUTPUT_COLLECTION]
    operations = []
    summary = {"trees": len(trees), "pixels": len(pixels), "sample_status": {}}
    for tree in trees:
        tree_id = str(tree["_id"])
        status, pixel = assignments.get(tree_id, (failures.get(tree_id), None))
        pixel_id = pixel["id"] if pixel else None
        summary["sample_status"][status] = summary["sample_status"].get(status, 0) + 1
        observation_id = key(
            args.orchard_id,
            tree_id,
            args.scene_id,
            args.acquired_at.isoformat(),
            args.date.isoformat(),
        )
        row = {
            "orchard_id": args.orchard_id,
            "tree_id": tree_id,
            "species": tree.get("species"),
            "tree_coordinates_lon_lat": list(positions[tree_id])
            if tree_id in positions
            else None,
            "scene_id": args.scene_id,
            "acquired_at_utc": args.acquired_at,
            "sample_status": status,
            "pixel_id": pixel_id,
            "pixel": pixel,
            "context": context,
        }
        if pixel_id in predictions:
            row["soil_moisture_forecast"] = predictions[pixel_id]
        elif args.forecast_days:
            row["soil_moisture_forecast"] = {
                "status": "unavailable" if forecast_error else "no_soil_data",
                "issued_at_utc": now,
            }
        operations.append(
            UpdateOne({"_id": observation_id}, {"$set": row}, upsert=True)
        )
    collection.bulk_write(operations, ordered=False)
    return {
        "collection": collection.full_name,
        **summary,
        "forecasted_pixels": len(predictions),
        "forecast_error": forecast_error,
        "weather_status": context["weather"]["status"],
        "solar_status": context["solar"]["status"],
    }


def acquisition_time(value):
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))  # noqa: FURB162 - Python 3.10 compatibility
    if stamp.tzinfo is None:
        raise argparse.ArgumentTypeError(
            "Podaj czas akwizycji ze strefą, np. 2025-07-28T16:40:00Z."
        )
    return stamp.astimezone(forecast.UTC)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--orchard-id", default=os.getenv("MONGO_ORCHARD_ID"))
    parser.add_argument("--raster", type=Path, required=True)
    parser.add_argument(
        "--scene-id", required=True, help="Identyfikator sceny Sentinel-1."
    )
    parser.add_argument("--acquired-at", type=acquisition_time, required=True)
    parser.add_argument(
        "--date",
        type=date.fromisoformat,
        help="Zakończona doba pogody i słońca. Domyślnie doba przed sceną.",
    )
    parser.add_argument(
        "--forecast-days", type=int, choices=range(15), default=0, metavar="0..14"
    )
    args = parser.parse_args()
    now = datetime.now(forecast.UTC).replace(microsecond=0)
    if not args.orchard_id:
        parser.error("Podaj --orchard-id lub ustaw MONGO_ORCHARD_ID.")
    if args.acquired_at > now:
        parser.error("Data akwizycji nie może być w przyszłości.")
    if args.forecast_days and (now.date() - args.acquired_at.date()).days > 92:
        parser.error(
            "Prognoza wymaga sceny z ostatnich 92 dni. Dla starszej sceny użyj --forecast-days 0."
        )
    scene_day = args.acquired_at.astimezone(solar.WARSAW).date()
    args.date = args.date or scene_day - forecast.DAY
    if args.date >= now.astimezone(solar.WARSAW).date():
        parser.error(
            "Pogoda i nasłonecznienie wymagają zakończonej doby Europe/Warsaw."
        )
    try:
        with mongo_client() as client:
            summary = analyze(mongo_database(client), args, now)
    except (OSError, ValueError, RasterioError) as error:
        parser.exit(1, f"{error}\n")
    except PyMongoError as error:
        parser.exit(1, f"Błąd MongoDB ({type(error).__name__}).\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
