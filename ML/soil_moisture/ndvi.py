"""Export a cloud-masked Sentinel-2 NDVI composite for the selected fields."""

import argparse
from datetime import date
from pathlib import Path

import ee

from ML.soil_moisture.earth_engine import geotiff_task, load_fields
from ML.soil_moisture.project_config import earth_engine_project

SENTINEL2 = "COPERNICUS/S2_SR_HARMONIZED"
NDVI_BAND = "ndvi"


def scene_ndvi(scene):
    scl = scene.select("SCL")
    # Keep vegetation, bare ground and water. Exclude cloud, shadow, snow and low-quality classes.
    clear = scl.gte(4).And(scl.lte(6))
    return scene.normalizedDifference(["B8", "B4"]).rename(NDVI_BAND).updateMask(clear)


def create_task(
    start,
    end,
    max_cloud_percent,
    fields_geojson,
    drive_folder,
    *,
    orchard_id=None,
    export_tag=None,
):
    fields = load_fields(fields_geojson, orchard_id=orchard_id)
    footprint = fields.geometry(maxError=1)
    scenes = (
        ee.ImageCollection(SENTINEL2)
        .filterBounds(footprint)
        .filterDate(start.isoformat(), end.isoformat())
        .filter(ee.Filter.lte("CLOUDY_PIXEL_PERCENTAGE", max_cloud_percent))
    )
    count = scenes.size().getInfo()
    if not count:
        raise ValueError(
            "Brak scen Sentinel-2 dla wybranych pól, dat i progu zachmurzenia."
        )
    reference = ee.Image(scenes.sort("system:time_start").first())
    grid = reference.select("B8").projection().getInfo()
    ndvi = scenes.map(scene_ndvi).median().toFloat().clipToCollection(fields)
    return geotiff_task(
        ndvi,
        footprint.bounds(maxError=1),
        grid,
        name=f"{export_tag}_ndvi"
        if export_tag
        else f"sentinel2_ndvi_{start:%Y%m%d}_{end:%Y%m%d}",
        folder=drive_folder,
    ), count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project", help="Override the configured Google Cloud project."
    )
    parser.add_argument(
        "--fields-geojson",
        type=Path,
        help="Optional WGS 84 GeoJSON instead of MongoDB Orchard.",
    )
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument(
        "--end", type=date.fromisoformat, required=True, help="Exclusive end date."
    )
    parser.add_argument("--max-cloud-percent", type=float, default=20)
    parser.add_argument("--drive-folder", default="ndvi")
    args = parser.parse_args()
    if args.start >= args.end:
        parser.error("Data początkowa musi być wcześniejsza niż data końcowa.")
    if not 0 <= args.max_cloud_percent <= 100:
        parser.error("--max-cloud-percent musi być w zakresie od 0 do 100.")

    try:
        ee.Initialize(project=earth_engine_project(args.project))
        task, count = create_task(
            args.start,
            args.end,
            args.max_cloud_percent,
            args.fields_geojson,
            args.drive_folder,
        )
        print(f"Sceny Sentinel-2 uwzględnione w kompozycji: {count}", flush=True)
        task.start()
        print(f"{task.config['description']}: {task.id}", flush=True)
    except (ee.EEException, OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
