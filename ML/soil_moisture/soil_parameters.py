"""Export OpenLandMap soil pH and USDA texture classes for the selected fields."""

import argparse
from pathlib import Path

import ee

from ML.soil_moisture.earth_engine import geotiff_task, load_fields
from ML.soil_moisture.project_config import earth_engine_project

SOIL_PH = "OpenLandMap/SOL/SOL_PH-H2O_USDA-4C1A2A_M/v02"
SOIL_TEXTURE = "OpenLandMap/SOL/SOL_TEXTURE-CLASS_USDA-TT_M/v02"
DEPTHS_CM = (0, 10, 30, 60, 100, 200)
EXPORT_PADDING_METERS = 250


def create_tasks(
    depth_cm, fields_geojson, drive_folder, *, orchard_id=None, export_tag=None
):
    if depth_cm not in DEPTHS_CM:
        raise ValueError(f"Niedostępna głębokość OpenLandMap: {depth_cm} cm.")
    fields = load_fields(fields_geojson, orchard_id=orchard_id)
    # Include native pixels that intersect a field even if their centers fall outside it.
    coverage = fields.reduceToImage(["field_id"], ee.Reducer.count()).gt(0)
    region = (
        fields.geometry(maxError=1)
        .bounds(maxError=1)
        .buffer(EXPORT_PADDING_METERS, maxError=1)
        .bounds(maxError=1)
    )
    band = f"b{depth_cm}"
    ph = ee.Image(SOIL_PH).select(band).multiply(0.1).rename("soil_ph").toFloat()
    texture = ee.Image(SOIL_TEXTURE).select(band).rename("soil_texture").toInt16()
    return [
        geotiff_task(
            image.updateMask(coverage),
            region,
            image.projection().getInfo(),
            name=f"{export_tag}_{name}"
            if export_tag
            else f"openlandmap_{name}_{depth_cm}cm",
            folder=drive_folder,
        )
        for name, image in (("soil_ph", ph), ("soil_texture", texture))
    ]


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
    parser.add_argument("--depth-cm", type=int, choices=DEPTHS_CM, default=0)
    parser.add_argument("--drive-folder", default="soil_parameters")
    args = parser.parse_args()
    try:
        ee.Initialize(project=earth_engine_project(args.project))
        for task in create_tasks(args.depth_cm, args.fields_geojson, args.drive_folder):
            task.start()
            print(f"{task.config['description']}: {task.id}", flush=True)
    except (ee.EEException, OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
