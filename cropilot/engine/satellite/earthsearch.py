"""
Per-scene NDVI for a small bounding box, read straight from the public Sentinel-2 L2A COGs indexed by
Element 84 Earth Search (no account, no full-scene download: only the window is fetched).

    scenes = read_ndvi_window(bbox=(17.66, 50.34, 17.70, 50.367), start="2024-09-01", end="2025-08-31")
    scenes.dates      # array of ISO dates, one per usable scene
    scenes.ndvi       # float32 [scene, row, col], NaN where cloudy / snow / no data
    scenes.transform  # affine transform of the window grid (UTM of the Sentinel-2 tile)
    scenes.crs        # e.g. "EPSG:32633"
"""

from __future__ import annotations

import os
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

os.environ.setdefault("AWS_NO_SIGN_REQUEST", "YES")
os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("GDAL_HTTP_MERGE_CONSECUTIVE_RANGES", "YES")
os.environ.setdefault("GDAL_HTTP_MAX_RETRY", "4")
os.environ.setdefault("GDAL_HTTP_RETRY_DELAY", "1")

import numpy as np
import rasterio
import rasterio.windows
from affine import Affine
from rasterio.enums import Resampling
from rasterio.warp import transform_bounds

STAC_URL = "https://earth-search.aws.element84.com/v1"
COLLECTION = "sentinel-2-l2a"
# Scene classification (SCL) classes kept as clear ground: 4 vegetation, 5 not vegetated.
CLEAR_SCL = (4, 5)
# A scene whose clear pixels have a median NDVI below this is treated as snow / frost the SCL missed.
SNOW_MEDIAN_NDVI = 0.08
MAX_SCENE_CLOUD = 80  # percent, scene-level pre-filter; pixels are masked individually anyway


@dataclass
class NdviScenes:
    dates: np.ndarray       # [n] ISO date strings
    ndvi: np.ndarray        # [n, h, w] float32
    clear_share: np.ndarray  # [n] share of window pixels that are clear
    transform: Affine
    crs: str
    tile: str


def _usable(item) -> bool:
    """Skip scenes whose radiometry is ambiguous: baseline >= 04.00 without the BOA offset harmonized."""
    baseline = float(item.properties.get("s2:processing_baseline", "0") or 0)
    applied = item.properties.get("earthsearch:boa_offset_applied")
    return baseline < 4.0 or bool(applied)


def search_items(bbox, start: str, end: str, tile: str | None = None):
    """Earth Search items over bbox; one per date, all from one MGRS tile (the most frequent one)."""
    from pystac_client import Client

    query = {"eo:cloud_cover": {"lt": MAX_SCENE_CLOUD}}
    if tile:
        query["grid:code"] = {"eq": f"MGRS-{tile}"}
    items = list(Client.open(STAC_URL).search(
        collections=[COLLECTION], bbox=list(bbox), datetime=f"{start}/{end}", query=query,
    ).items())
    items = [i for i in items if _usable(i)]
    if not items:
        return None, []
    tile = tile or Counter(i.properties.get("grid:code", "") for i in items).most_common(1)[0][0].removeprefix("MGRS-")
    by_date = {}
    for it in sorted(items, key=lambda i: str(i.properties.get("s2:processing_baseline", ""))):
        if it.properties.get("grid:code") == f"MGRS-{tile}":
            by_date[it.datetime.date()] = it  # the latest processing baseline wins
    return tile, [by_date[d] for d in sorted(by_date)]


def _read_item(item, bbox):
    with rasterio.open(item.assets["red"].href) as src:
        win = rasterio.windows.from_bounds(*transform_bounds("EPSG:4326", src.crs, *bbox), transform=src.transform)
        win = win.round_offsets().round_lengths()
        red = src.read(1, window=win, boundless=True, fill_value=0).astype("float32")
        transform = rasterio.windows.transform(win, src.transform)
        crs = src.crs.to_string()
    with rasterio.open(item.assets["nir"].href) as src:
        nir = src.read(1, window=win, boundless=True, fill_value=0).astype("float32")
    with rasterio.open(item.assets["scl"].href) as src:
        w20 = rasterio.windows.from_bounds(*transform_bounds("EPSG:4326", src.crs, *bbox), transform=src.transform)
        scl = src.read(1, window=w20, out_shape=red.shape, resampling=Resampling.nearest, boundless=True, fill_value=0)
    with np.errstate(all="ignore"):
        ndvi = (nir - red) / (nir + red)
    ndvi[~np.isin(scl, CLEAR_SCL) | ((nir + red) <= 0) | (np.abs(ndvi) > 1)] = np.nan
    return item.datetime.date().isoformat(), ndvi, transform, crs


def read_ndvi_window(bbox, start: str, end: str, tile: str | None = None, threads: int = 8) -> NdviScenes | None:
    """All usable scenes for bbox (W, S, E N in degrees) between start and end, NDVI per pixel."""
    tile, items = search_items(bbox, start, end, tile)
    if not items:
        return None
    with ThreadPoolExecutor(threads) as ex:
        res = list(ex.map(lambda it: _read_item(it, bbox), items))
    h = min(r[1].shape[0] for r in res)
    w = min(r[1].shape[1] for r in res)
    dates, stack = [], []
    for d, ndvi, _, _ in res:
        ndvi = ndvi[:h, :w]
        clear = np.isfinite(ndvi)
        if not clear.any():
            continue
        if np.nanmedian(ndvi) < SNOW_MEDIAN_NDVI:  # snow / frost the SCL did not catch
            continue
        dates.append(d)
        stack.append(ndvi)
    if not stack:
        return None
    stack = np.stack(stack)
    return NdviScenes(
        dates=np.array(dates), ndvi=stack, clear_share=np.isfinite(stack).mean(axis=(1, 2)),
        transform=res[0][2], crs=res[0][3], tile=tile,
    )
