"""Clip the yearly cropland rasters (48 PL tiles per year, ZIP) to one region as a compressed GeoTIFF.

    python engine/scripts/clip_cropland.py RAW_CROPLAND_DIR OUT_DIR [--bbox W S E N] [--years 2020 ...]

Reads tiles straight from the ZIPs (no full unzip), writes OUT_DIR/cropland_<year>.tif
(EPSG:4326, uint16, deflate, tiled). Default bbox covers Opolskie with a margin.
"""
import argparse
import zipfile
from pathlib import Path

import rasterio
from rasterio.merge import merge

OPOLSKIE_BBOX = (16.85, 49.95, 18.75, 51.25)


def clip_year(zip_path: Path, out_path: Path, bbox) -> None:
    w, s, e, n = bbox
    with zipfile.ZipFile(zip_path) as z:
        tifs = [i.filename for i in z.infolist() if i.filename.endswith(".tif")]
    srcs = []
    for name in tifs:
        src = rasterio.open(f"zip://{zip_path}!/{name}")
        b = src.bounds
        if b.left < e and b.right > w and b.bottom < n and b.top > s:
            srcs.append(src)
        else:
            src.close()
    mosaic, transform = merge(srcs, bounds=bbox)
    profile = srcs[0].profile | {
        "driver": "GTiff", "height": mosaic.shape[1], "width": mosaic.shape[2], "transform": transform,
        "compress": "deflate", "tiled": True, "blockxsize": 512, "blockysize": 512, "count": 1,
    }
    with rasterio.open(out_path, "w", **profile) as dst:
        dst.write(mosaic[0], 1)
    for src in srcs:
        src.close()
    print(f"{out_path.name}: {len(srcs)} tiles, {mosaic.shape[2]}x{mosaic.shape[1]} px")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("raw_dir", type=Path)
    p.add_argument("out_dir", type=Path)
    p.add_argument("--bbox", type=float, nargs=4, default=OPOLSKIE_BBOX)
    p.add_argument("--years", type=int, nargs="*", default=[2020, 2021, 2022, 2023, 2024])
    a = p.parse_args()
    a.out_dir.mkdir(parents=True, exist_ok=True)
    for year in a.years:
        clip_year(a.raw_dir / f"cropland_pl_4326_{year}.zip", a.out_dir / f"cropland_{year}.tif", tuple(a.bbox))


if __name__ == "__main__":
    main()
