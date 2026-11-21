"""Train the Sentinel-1 soil moisture model and export it through Earth Engine."""

import argparse
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import ee

if __package__:
    from .field_geometry import read_field_features
    from .project_config import earth_engine_project
else:
    from field_geometry import read_field_features
    from project_config import earth_engine_project

TARGET = "volumetric_soil_water_layer_1"
FEATURES = ["VV", "VH", "VV_minus_VH"]
PREDICTION = "soil_moisture_m3_m3"
RASTER_TASK_NAME = "sentinel1_soil_moisture"
NODATA = -9999
FIELD_TRAINING_BUFFER_METERS = 15_000
FIELD_STATISTICS = ["mean_m3_m3", "min_m3_m3", "max_m3_m3", "valid_pixels"]


@dataclass(frozen=True)
class SoilMoistureConfig:
    start: str = "2025-04-01"
    test_start: str = "2025-07-01"
    end: str = "2025-08-01"
    bounds: tuple[float, float, float, float] | None = None
    fields_geojson: Path | None = None
    orbit_pass: str = "ASCENDING"
    relative_orbit: int | None = None
    min_coverage: float = 0.8
    drive_folder: str = "soil_moisture"
    export_model_asset: str | None = None
    export_tree_raster: bool = False
    raster_export_name: str = RASTER_TASK_NAME
    coarse_training_inputs: bool = False


def load_fields(path=None, *, orchard_id=None):
    fields = []
    for index, record in enumerate(
        read_field_features(path, orchard_id=orchard_id), start=1
    ):
        try:
            boundary = ee.Geometry(record["geometry"], proj="EPSG:4326", geodesic=False)
        except ee.EEException as error:
            raise ValueError(f"Nieprawidłowe współrzędne pola nr {index}.") from error
        properties = record["properties"]
        crop_id = properties.get("cropID")
        field_data = {"field_id": index}
        if isinstance(crop_id, (str, int, float)):
            field_data["crop_id"] = crop_id
        if orchard_id := properties.get("orchard_id"):
            field_data["orchard_id"] = orchard_id
        fields.append(ee.Feature(boundary, field_data))
    return ee.FeatureCollection(fields)


def sentinel_scenes(start, end, orbit_pass):
    return (
        ee.ImageCollection("COPERNICUS/S1_GRD")
        .filterDate(start, end)
        .filter(ee.Filter.eq("instrumentMode", "IW"))
        .filter(ee.Filter.eq("orbitProperties_pass", orbit_pass))
        .filter(ee.Filter.eq("resolution_meters", 10))
        .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
        .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VH"))
    )


def scenes_covering_fields(sentinel, footprint):
    return sentinel.map(
        lambda scene: scene.set(
            "covers_all_fields", scene.geometry().contains(footprint, maxError=1)
        )
    ).filter(ee.Filter.eq("covers_all_fields", True))


def matched_scenes(args, region, map_footprint):
    sentinel = sentinel_scenes(args.start, args.end, args.orbit_pass)
    orbits = sentinel.filterBounds(region).aggregate_histogram(
        "relativeOrbitNumber_start"
    )
    if args.relative_orbit is not None:
        sentinel = sentinel.filter(
            ee.Filter.eq("relativeOrbitNumber_start", args.relative_orbit)
        )
    era5 = (
        ee.ImageCollection("ECMWF/ERA5_LAND/HOURLY")
        .filterDate(
            ee.Date(args.start).advance(-1, "hour"),
            ee.Date(args.end).advance(1, "hour"),
        )
        .select(TARGET)
    )
    time_match = ee.Filter.maxDifference(
        difference=30 * 60 * 1000,
        leftField="system:time_start",
        rightField="system:time_start",
    )
    paired = ee.ImageCollection(
        ee.Join.saveBest("era5_image", "time_difference_ms").apply(
            sentinel.filterBounds(region), era5, time_match
        )
    )
    return sentinel.filterBounds(map_footprint), paired, orbits


def radar_bands(scene):
    radar = scene.select(["VV", "VH"])
    return radar.updateMask(radar.mask().reduce(ee.Reducer.min()))


def radar_features(radar):
    difference = radar.select("VV").subtract(radar.select("VH"))
    return radar.addBands(difference.rename("VV_minus_VH"))


def samples_for_scene(scene, region, min_coverage, *, coarse_training_inputs=False):
    scene = ee.Image(scene)
    label = ee.Image(scene.get("era5_image")).select(TARGET)
    label_grid = label.projection()
    vv = scene.select("VV")
    intermediate_grid = vv.projection().atScale(200)
    if coarse_training_inputs:
        # Read the SAR pyramid at 200 m before aggregating to ERA5-Land cells.
        # The 10 m prediction uses the original image and never enters this reduction.
        radar = radar_bands(scene.select(["VV", "VH"]).reproject(intermediate_grid))
    else:
        radar = radar_bands(scene)
    vv = radar.select("VV")
    coverage = vv.mask().unmask(0, False).rename("radar_coverage")
    inputs = radar.addBands(coverage)
    if not coarse_training_inputs:
        inputs = inputs.reduceResolution(ee.Reducer.mean(), maxPixels=4096).reproject(
            intermediate_grid
        )
    averaged = inputs.reduceResolution(ee.Reducer.mean(), maxPixels=8192).reproject(
        label_grid
    )
    inputs = radar_features(averaged.select(["VV", "VH"])).updateMask(
        averaged.select("radar_coverage").gte(min_coverage)
    )
    valid_label = label.updateMask(label.gte(0).And(label.lte(1)))
    return inputs.addBands(valid_label).sample(
        region=region, projection=label_grid, tileScale=4, geometries=False
    )


def samples_for(collection, region, min_coverage, *, coarse_training_inputs=False):
    scene_list = collection.toList(collection.size())
    tables = scene_list.map(
        lambda scene: samples_for_scene(
            scene, region, min_coverage, coarse_training_inputs=coarse_training_inputs
        )
    )
    return ee.FeatureCollection(tables).flatten()


def train_forest(samples):
    return (
        ee.Classifier.smileRandomForest(numberOfTrees=100, minLeafPopulation=3, seed=42)
        .setOutputMode("REGRESSION")
        .train(features=samples, classProperty=TARGET, inputProperties=FEATURES)
    )


def evaluate_model(predictions, training_mean):
    def residuals(feature):
        observed = ee.Number(feature.get(TARGET))
        residual = ee.Number(feature.get(PREDICTION)).subtract(observed)
        baseline_residual = training_mean.subtract(observed)
        return feature.set(
            {
                "absolute_error": residual.abs(),
                "squared_error": residual.pow(2),
                "baseline_absolute_error": baseline_residual.abs(),
                "baseline_squared_error": baseline_residual.pow(2),
            }
        )

    evaluated = predictions.map(residuals)
    return {
        "mae_m3_m3": evaluated.aggregate_mean("absolute_error"),
        "rmse_m3_m3": ee.Number(evaluated.aggregate_mean("squared_error")).sqrt(),
        "baseline_mae_m3_m3": evaluated.aggregate_mean("baseline_absolute_error"),
        "baseline_rmse_m3_m3": ee.Number(
            evaluated.aggregate_mean("baseline_squared_error")
        ).sqrt(),
    }


def field_summary_task(prediction, fields, scene, grid, drive_folder):
    reducer = (
        ee.Reducer.mean()
        .unweighted()
        .combine(ee.Reducer.minMax().unweighted(), sharedInputs=True)
        .combine(ee.Reducer.count(), sharedInputs=False)
        .setOutputs(FIELD_STATISTICS)
    )
    # A separate count input keeps the named outputs independent of band prefixes.
    summary = prediction.addBands(prediction.rename("count_input")).reduceRegions(
        collection=fields,
        reducer=reducer,
        crs=grid["crs"],
        crsTransform=grid["transform"],
        tileScale=4,
    )
    scene_utc = scene.date().format("yyyy-MM-dd'T'HH:mm:ss'Z'", "UTC")

    def add_metadata(field):
        count = field.get("valid_pixels")
        return field.set(
            {
                "scene_utc": scene_utc,
                "valid_pixels": ee.Algorithms.If(count, count, 0),
            }
        )

    return ee.batch.Export.table.toDrive(
        collection=summary.map(add_metadata).sort("field_id"),
        description="sentinel1_soil_moisture_fields",
        folder=drive_folder,
        fileFormat="CSV",
        selectors=["field_id", "orchard_id", "crop_id", "scene_utc", *FIELD_STATISTICS],
    )


def geotiff_task(image, region, grid, *, name, folder, description=None):
    return ee.batch.Export.image.toDrive(
        image=image.unmask(NODATA, False),
        description=description or name,
        fileNamePrefix=name,
        folder=folder,
        region=region,
        crs=grid["crs"],
        crsTransform=grid["transform"],
        maxPixels=1_000_000_000,
        fileFormat="GeoTIFF",
        formatOptions={"cloudOptimized": True, "noData": NODATA},
    )


def create_tasks(args):
    tasks, _ = create_exports(args)
    return tasks


def create_exports(args, *, orchard_id=None, export_tag=None):
    fields = load_fields(args.fields_geojson, orchard_id=orchard_id)
    map_footprint = fields.geometry(maxError=1)
    export_region = map_footprint.bounds(maxError=1)
    if args.bounds is None:
        region = export_region.buffer(FIELD_TRAINING_BUFFER_METERS)
    else:
        region = ee.Geometry.Rectangle(args.bounds, proj="EPSG:4326", geodesic=False)

    sentinel, paired, orbits = matched_scenes(args, region, map_footprint)
    train_scenes = paired.filterDate(args.start, args.test_start)
    test_scenes = paired.filterDate(args.test_start, args.end)
    full_coverage = scenes_covering_fields(sentinel, map_footprint)
    catalog = {
        "relative_orbits": orbits,
        "train_scenes": train_scenes.size(),
        "test_scenes": test_scenes.size(),
        "prediction_scenes": sentinel.size(),
        "full_coverage_scenes": full_coverage.size(),
    }
    scene_counts = ee.Dictionary(catalog).getInfo()
    print(json.dumps(scene_counts, indent=2), flush=True)
    if not scene_counts["train_scenes"] or not scene_counts["test_scenes"]:
        raise ValueError(
            "Brak dopasowanych scen w jednym z okresów. Sprawdź obszar, daty i orbitę."
        )
    if not scene_counts["prediction_scenes"]:
        raise ValueError(
            "Brak sceny Sentinel-1 obejmującej obszar mapy. Sprawdź daty i orbitę."
        )

    coarse_training_inputs = getattr(args, "coarse_training_inputs", False)
    train = samples_for(
        train_scenes,
        region,
        args.min_coverage,
        coarse_training_inputs=coarse_training_inputs,
    )
    test = samples_for(
        test_scenes,
        region,
        args.min_coverage,
        coarse_training_inputs=coarse_training_inputs,
    )
    forest = train_forest(train)
    metrics = evaluate_model(
        test.classify(forest, PREDICTION), ee.Number(train.aggregate_mean(TARGET))
    )
    report = {
        "train_scenes": scene_counts["train_scenes"],
        "test_scenes": scene_counts["test_scenes"],
        "train_samples": train.size(),
        "test_samples": test.size(),
        **metrics,
    }
    metrics_task = ee.batch.Export.table.toDrive(
        collection=ee.FeatureCollection([ee.Feature(None, report)]),
        description="sentinel1_soil_moisture_metrics",
        folder=args.drive_folder,
        fileFormat="CSV",
        selectors=list(report),
    )

    prediction_scenes = (
        full_coverage if scene_counts.get("full_coverage_scenes") else sentinel
    )
    latest = ee.Image(prediction_scenes.sort("system:time_start", False).first())
    radar = radar_bands(latest)
    grid = radar.select("VV").projection().getInfo()
    prediction = (
        radar_features(radar)
        .classify(forest, PREDICTION)
        .toFloat()
        .clipToCollection(fields)
    )
    raster_name = getattr(args, "raster_export_name", RASTER_TASK_NAME)
    map_task = geotiff_task(
        prediction,
        export_region,
        grid,
        name=raster_name,
        folder=args.drive_folder,
    )
    field_task = field_summary_task(prediction, fields, latest, grid, args.drive_folder)
    tasks = [metrics_task, map_task, field_task]
    tree_scene = None
    if args.export_tree_raster:
        scene_id, stamp = ee.List(
            [
                latest.get("system:index"),
                latest.date().format("yyyy-MM-dd'T'HH:mm:ss'Z'", "UTC"),
            ]
        ).getInfo()
        filename = (
            f"{export_tag}_soil_moisture" if export_tag else f"tree_pixels_{scene_id}"
        )
        tree_scene = {"scene_id": scene_id, "acquired_at": stamp, "name": filename}
        print(f"Tree raster: {filename}.tif (UTC: {stamp})", flush=True)
        tree_image = radar.clipToCollection(fields).addBands(prediction).toFloat()
        tasks.append(
            geotiff_task(
                tree_image,
                export_region,
                grid,
                name=filename,
                description="sentinel1_tree_pixels",
                folder=args.drive_folder,
            )
        )
    if args.export_model_asset:
        tasks.append(
            ee.batch.Export.classifier.toAsset(
                classifier=forest,
                description="sentinel1_soil_moisture_model",
                assetId=args.export_model_asset,
            )
        )
    return tasks, tree_scene


def main():
    defaults = SoilMoistureConfig()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project", help="Override the configured Google Cloud project."
    )
    parser.add_argument(
        "--bounds",
        type=float,
        nargs=4,
        metavar=("WEST", "SOUTH", "EAST", "NORTH"),
        help="Training area. With field polygons, the map is clipped to the fields.",
    )
    parser.add_argument(
        "--fields-geojson",
        type=Path,
        default=defaults.fields_geojson,
        help="Optional WGS 84 GeoJSON override. By default read geometry from MongoDB Orchard.",
    )
    parser.add_argument("--start", default=defaults.start)
    parser.add_argument("--test-start", default=defaults.test_start)
    parser.add_argument("--end", default=defaults.end, help="Exclusive end date.")
    parser.add_argument(
        "--pass",
        dest="orbit_pass",
        choices=("ASCENDING", "DESCENDING"),
        default=defaults.orbit_pass,
    )
    parser.add_argument("--relative-orbit", type=int)
    parser.add_argument("--min-coverage", type=float, default=defaults.min_coverage)
    parser.add_argument("--drive-folder", default=defaults.drive_folder)
    parser.add_argument(
        "--export-model-asset", help="Earth Engine asset ID for the trained forest."
    )
    parser.add_argument(
        "--export-tree-raster",
        action="store_true",
        help="Also export VV, VH and the soil moisture estimate in one GeoTIFF.",
    )
    args = parser.parse_args()

    try:
        start, test_start, end = map(
            date.fromisoformat, (args.start, args.test_start, args.end)
        )
    except ValueError:
        parser.error("Daty podaj w formacie YYYY-MM-DD.")
    if not start < test_start < end:
        parser.error("Daty muszą spełniać warunek start < test-start < end.")
    args.start, args.test_start, args.end = (
        day.isoformat() for day in (start, test_start, end)
    )
    if args.bounds is not None:
        west, south, east, north = args.bounds
        if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
            parser.error(
                "Podaj poprawne granice obszaru w kolejności zachód południe wschód północ."
            )
    if not 0 <= args.min_coverage <= 1:
        parser.error("--min-coverage musi być w zakresie od 0 do 1.")

    try:
        ee.Initialize(project=earth_engine_project(args.project))
        print("Sprawdzam dostępność scen Sentinel-1 i ERA5-Land.", flush=True)
        for task in create_tasks(args):
            task.start()
            print(f"{task.config['description']}: {task.id}", flush=True)
    except (ee.EEException, OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
