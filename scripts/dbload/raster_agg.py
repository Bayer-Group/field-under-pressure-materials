"""Cropland raster (CLMS CTY, 10 m) -> class pixel counts inside each field polygon."""
from __future__ import annotations

import math
from collections import Counter
from pathlib import Path

import numpy as np
import rasterio
from rasterio.features import geometry_mask
from rasterio.merge import merge
from rasterio.warp import transform_geom
from rasterio.windows import Window, bounds as window_bounds

from .fields import Field


def _geometry_bounds(geom: dict) -> tuple[float, float, float, float]:
    polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
    pts = [p for poly in polys for ring in poly for p in ring]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def field_class_counts(tifs: list[Path], fields: list[Field], log=print) -> dict[str, Counter]:
    """{field_id: Counter({class_code: pixel_count})}. A pixel belongs to a field when its centre is inside the polygon.

    The CTY tiles come from a metric tile grid reprojected to degrees: their bounding boxes overlap and the padding is
    0 (the same value as "No cropland", with no nodata tag). Summing the pixels of every tile that touches a field would
    count that padding. So for each field the tiles are first mosaicked (the larger value wins, so real data beats
    padding) onto the pixel grid of the first tile that touches it, and only then counted. Every code present is counted
    (0 = no cropland or outside every tile, 65535 = outside area), so the shares computed from these counts add up to 1.
    All tiles must share one coordinate reference system."""
    counts: dict[str, Counter] = {}
    datasets = [rasterio.open(t) for t in tifs]
    try:
        crs = datasets[0].crs if datasets else None
        for ds in datasets:
            if ds.crs != crs:
                raise ValueError(f"cropland tiles have different CRS ({crs} and {ds.crs}); reproject them first")
        geographic_4326 = crs is None or crs.to_epsg() == 4326
        for f in fields:
            if geographic_4326:
                geom, (x0, y0, x1, y1) = f.geometry, f.bounds
            else:
                geom = transform_geom("EPSG:4326", crs, f.geometry)
                x0, y0, x1, y1 = _geometry_bounds(geom)
            touching = [ds for ds in datasets
                        if not (x1 < ds.bounds.left or x0 > ds.bounds.right or y1 < ds.bounds.bottom or y0 > ds.bounds.top)]
            if not touching:
                continue
            ref = touching[0]                       # snap the mosaic to this tile's pixel grid (exact source pixels)
            w = ref.window(x0, y0, x1, y1)
            c0, r0 = math.floor(w.col_off), math.floor(w.row_off)
            c1, r1 = math.ceil(w.col_off + w.width) + 1, math.ceil(w.row_off + w.height) + 1
            bounds = window_bounds(Window(c0, r0, c1 - c0, r1 - r0), ref.transform)
            arr, transform = merge(touching, bounds=bounds, method="max", res=ref.res)
            inside = geometry_mask([geom], out_shape=arr.shape[1:], transform=transform, invert=True)
            vals = arr[0][inside]
            if vals.size:
                codes, n = np.unique(vals, return_counts=True)
                counts.setdefault(f.field_id, Counter()).update(dict(zip(codes.tolist(), n.tolist())))
        log(f"    cropland: {len(fields)} field(s) counted over {len(tifs)} tile(s)")
    finally:
        for ds in datasets:
            ds.close()
    return counts
