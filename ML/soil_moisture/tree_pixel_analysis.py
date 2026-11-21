"""Save raster, weather and solar results for fields and trees in MongoDB."""

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
from ML.soil_moisture.raster_sampling import analyze_raster
from ML.soil_moisture.soil_parameters import DEPTHS_CM

OUTPUT_COLLECTION = "TreePixelAnalysis"
BANDS = ("vv_db", "vh_db", "soil_moisture_m3_m3")
LAYER_FIELDS = {
    "moisture": "soil_moisture",
    "ndvi": "ndvi",
    "ph": "soil_parameters.ph",
    "texture": "soil_parameters.texture",
}
LAYER_LIMITS = {"moisture": (0, 1), "ndvi": (-1, 1), "ph": (0, 14), "texture": (1, 12)}


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
            {"geometry": 1, "geo": 1, "coordinates": 1, "species": 1},
        ).sort("_id", 1)
    )
    return orchard["_id"], boundary, trees


def tree_coordinates(tree):
    for source in (tree.get("geometry"), tree.get("coordinates"), tree.get("geo")):
        if isinstance(source, dict):
            coordinates = (
                source.get("coordinates")
                if source.get("type") == "Point"
                else (source.get("lng"), source.get("lat"))
            )
        else:
            coordinates = source
        if (
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
            return tuple(coordinates[:2])
    return None


def tree_positions(trees, boundary):
    positions, failures = {}, {}
    for tree in trees:
        tree_id = str(tree["_id"])
        position = tree_coordinates(tree)
        if position is None:
            failures[tree_id] = "invalid_coordinates"
            continue
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
    model, validation, weather = forecast.projection_inputs(
        coordinates, anchor, now, days
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


class FieldAnalysis:
    def __init__(self, database, args, *, run_id=None):
        self.database = database
        self.args = args
        self.run_id = run_id
        self.orchard_id, self.boundary, self.trees = load_orchard(
            database, args.orchard_id
        )
        self.positions, self.failures = tree_positions(self.trees, self.boundary)
        self.pixels, self.assignments = {}, {}
        self.statistics, self.readings = {}, {}
        self.context = None
        self.predictions, self.forecast_error = {}, None

    def collect(self, kind, path):
        is_soil = kind in ("ph", "texture")
        stats, readings = analyze_raster(
            path,
            self.boundary,
            {} if kind == "moisture" else self.positions,
            limits=LAYER_LIMITS[kind],
            categorical=kind == "texture",
            all_touched=is_soil,
            last_band=kind == "moisture",
        )
        if kind == "moisture":
            self.pixels, self.assignments = sample_pixels(
                path, self.args.scene_id, self.args.acquired_at, self.positions
            )
            stats["mean_m3_m3"] = stats.pop("mean")
            stats["scene_id"] = self.args.scene_id
            stats["acquired_at_utc"] = self.args.acquired_at
        elif is_soil and self.args.soil_depth_cm is not None:
            stats["depth_cm"] = self.args.soil_depth_cm
        self.statistics[kind] = stats
        self.readings[kind] = readings

    def context_and_forecast(self, now):
        point = self.boundary.representative_point()
        coordinates = (point.x, point.y)
        self.context = orchard_context(self.args.date, coordinates)
        if "moisture" in self.statistics:
            try:
                self.predictions = predict_pixels(
                    self.pixels,
                    coordinates,
                    self.args.acquired_at,
                    now,
                    self.args.forecast_days,
                )
            except forecast.WeatherError as error:
                self.forecast_error = str(error)

    def orchard_fields(self):
        fields = {LAYER_FIELDS[kind]: stats for kind, stats in self.statistics.items()}
        if self.context is not None:
            local_date = self.context["date_local"]
            fields["weather"] = {"date_local": local_date, **self.context["weather"]}
            fields["solar_intensity"] = {
                "date_local": local_date,
                "timezone": self.context["timezone"],
                **self.context["solar"],
            }
        return fields

    def preview(self):
        values = self.orchard_fields()
        soil = {
            kind: values.pop(LAYER_FIELDS[kind])
            for kind in ("ph", "texture")
            if LAYER_FIELDS[kind] in values
        }
        if soil:
            values["soil_parameters"] = soil
        return {"run_id": self.run_id, **values}

    def save_orchard(self):
        if self.run_id is not None:
            update = {"$set": {"analysis": self.preview()}}
        else:
            update = {
                "$set": {
                    f"analysis.{name}": value
                    for name, value in self.orchard_fields().items()
                },
                "$unset": {"analysis.run_id": ""},
            }
        result = self.database.Orchard.update_one({"_id": self.orchard_id}, update)
        if result.matched_count != 1:
            raise OSError("Rekord Orchard został usunięty podczas analizy.")

    def save_trees(self, now, kinds):
        collection = self.database[OUTPUT_COLLECTION]
        operations = []
        counts = {}
        orchard = str(self.orchard_id)
        for tree in self.trees:
            tree_id = str(tree["_id"])
            position = self.positions.get(tree_id)
            status, pixel = self.assignments.get(
                tree_id, (self.failures.get(tree_id, "pending"), None)
            )
            pixel_id = pixel["id"] if pixel else None
            counts[status] = counts.get(status, 0) + 1
            row = {
                "orchard_id": orchard,
                "tree_id": tree_id,
                "species": tree.get("species"),
                "tree_coordinates_lon_lat": list(position) if position else None,
                "scene_id": self.args.scene_id,
                "acquired_at_utc": self.args.acquired_at,
            }
            if self.run_id is not None:
                observation_id = key(orchard, tree_id, self.run_id)
                row["analysis_run_id"] = self.run_id
            else:
                observation_id = key(
                    orchard,
                    tree_id,
                    self.args.scene_id,
                    self.args.acquired_at.isoformat(),
                    self.args.date.isoformat(),
                )
            if "moisture" in kinds:
                row.update(sample_status=status, pixel_id=pixel_id, pixel=pixel)
            elif tree_id in self.failures:
                row["sample_status"] = status
            for kind in kinds:
                if kind == "moisture":
                    continue
                row[f"layers.{LAYER_FIELDS[kind]}"] = {
                    "raster": self.statistics[kind]["raster"],
                    "value": self.readings[kind][tree_id] if position else None,
                }
                if "depth_cm" in self.statistics[kind]:
                    row[f"layers.{LAYER_FIELDS[kind]}"]["depth_cm"] = self.statistics[
                        kind
                    ]["depth_cm"]
            if self.context is not None:
                row["context"] = self.context
                if pixel_id in self.predictions:
                    row["soil_moisture_forecast"] = self.predictions[pixel_id]
                elif self.args.forecast_days and "moisture" in self.statistics:
                    row["soil_moisture_forecast"] = {
                        "status": "unavailable"
                        if self.forecast_error
                        else "no_soil_data",
                        "issued_at_utc": now,
                    }
            operations.append(
                UpdateOne({"_id": observation_id}, {"$set": row}, upsert=True)
            )
        if operations:
            collection.bulk_write(operations, ordered=False)
        return {
            "collection": collection.full_name,
            "trees": len(self.trees),
            "pixels": len(self.pixels),
            "sample_status": counts,
            "forecasted_pixels": len(self.predictions),
            "forecast_error": self.forecast_error,
        }


def analyze(database, args, now):
    analysis = FieldAnalysis(database, args)
    for kind, path in (
        ("moisture", args.raster),
        ("ndvi", args.ndvi_raster),
        ("ph", args.soil_ph_raster),
        ("texture", args.soil_texture_raster),
    ):
        if path is not None:
            analysis.collect(kind, path)
    analysis.context_and_forecast(now)
    summary = analysis.save_trees(now, analysis.statistics)
    analysis.save_orchard()
    return {
        **summary,
        "weather_status": analysis.context["weather"]["status"],
        "solar_status": analysis.context["solar"]["status"],
        "orchard_analysis": analysis.orchard_fields(),
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
    parser.add_argument("--ndvi-raster", type=Path)
    parser.add_argument("--soil-ph-raster", type=Path)
    parser.add_argument("--soil-texture-raster", type=Path)
    parser.add_argument("--soil-depth-cm", type=int, choices=DEPTHS_CM)
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
    print(json.dumps(summary, indent=2, default=datetime.isoformat))


if __name__ == "__main__":
    main()
