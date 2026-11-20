"""Cropland raster (CLMS CTY, 10 m) -> class pixel counts inside each field polygon."""
from __future__ import annotations

import math
from collections import Counter
from pathlib import Path

import numpy as np
import rasterio
from rasterio.features import geometry_mask
from rasterio.warp import transform_geom
from rasterio.windows import Window, from_bounds

from .fields import Field


def _geometry_bounds(geom: dict) -> tuple[float, float, float, float]:
    polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
    pts = [p for poly in polys for ring in poly for p in ring]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def field_class_counts(tifs: list[Path], fields: list[Field], log=print) -> dict[str, Counter]:
    """{field_id: Counter({class_code: pixel_count})}. A pixel belongs to a field when its centre is
    inside the polygon. Fields spanning several tiles are summed. Every code present is counted
    (0 = no cropland, 65535 = outside area), so shares computed from these counts add up to 1."""
    counts: dict[str, Counter] = {}
    for ti, tif in enumerate(tifs, 1):
        with rasterio.open(tif) as src:
            geographic_4326 = src.crs is None or src.crs.to_epsg() == 4326
            left, bottom, right, top = src.bounds
            for f in fields:
                if geographic_4326:
                    geom, (x0, y0, x1, y1) = f.geometry, f.bounds
                else:
                    geom = transform_geom("EPSG:4326", src.crs, f.geometry)
                    x0, y0, x1, y1 = _geometry_bounds(geom)
                if x1 < left or x0 > right or y1 < bottom or y0 > top:
                    continue
                w = from_bounds(x0, y0, x1, y1, transform=src.transform)
                c0, r0 = max(0, math.floor(w.col_off)), max(0, math.floor(w.row_off))
                c1 = min(src.width, math.ceil(w.col_off + w.width) + 1)
                r1 = min(src.height, math.ceil(w.row_off + w.height) + 1)
                if c1 <= c0 or r1 <= r0:
                    continue
                win = Window(c0, r0, c1 - c0, r1 - r0)
                arr = src.read(1, window=win)
                inside = geometry_mask([geom], out_shape=arr.shape, transform=src.window_transform(win), invert=True)
                vals = arr[inside]
                if vals.size:
                    codes, n = np.unique(vals, return_counts=True)
                    counts.setdefault(f.field_id, Counter()).update(dict(zip(codes.tolist(), n.tolist())))
        log(f"    cropland tile {ti}/{len(tifs)} {tif.name}")
    return counts
