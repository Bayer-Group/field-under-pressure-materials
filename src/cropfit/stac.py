"""Shared raster access: Planetary Computer catalogue, windowed reads over a plot footprint, chips, manifests.

The spatial operator used everywhere: a square footprint (centre +- half_m, in the raster's CRS) is read as a
small window and every pixel gets a weight = the fraction of the pixel lying inside the footprint. Statistics
are weighted by it, so a 30 m pixel half outside a 40 m plot counts half.
"""
from __future__ import annotations

import math
import time
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from .config import RAW

STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"
GDAL_ENV = dict(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_MAX_RETRY="4", GDAL_HTTP_RETRY_DELAY="1",
                CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif,.TIF,.tiff", GDAL_HTTP_MULTIRANGE="YES",
                GDAL_HTTP_MERGE_CONSECUTIVE_RANGES="YES", VSI_CACHE="TRUE")


@lru_cache
def catalog():
    import planetary_computer as pc
    import pystac_client
    return pystac_client.Client.open(STAC, modifier=pc.sign_inplace)


def search(collection: str, lon: float, lat: float, datetime: str | None = None, query: dict | None = None,
           retries: int = 4) -> list:
    """All items of a collection covering a point (signed), with retries."""
    for attempt in range(retries):
        try:
            s = catalog().search(collections=[collection], intersects={"type": "Point", "coordinates": [lon, lat]},
                                 datetime=datetime, query=query, limit=250)
            return list(s.items())
        except Exception:  # noqa: BLE001
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)
    return []


def sign(href: str) -> str:
    """Fresh signed URL (tokens expire within the hour, long fetches must re-sign: any old token is dropped)."""
    import planetary_computer as pc
    return pc.sign(href.split("?")[0])


def to_xy(lon, lat, crs):
    from pyproj import Transformer
    return Transformer.from_crs("EPSG:4326", crs, always_xy=True).transform(lon, lat)


def footprint_window(transform, x: float, y: float, half_m: float):
    """(col_off, row_off, width, height) of the pixels touching the square, and their weights (height, width):
    fraction of each pixel inside the square. transform: north-up affine of the raster; x, y in its CRS."""
    inv = ~transform
    c0, r0 = inv * (x - half_m, y + half_m)
    c1, r1 = inv * (x + half_m, y - half_m)
    ci0, ri0 = math.floor(c0), math.floor(r0)
    ci1, ri1 = math.ceil(c1), math.ceil(r1)
    cols = np.arange(ci0, ci1)
    rows = np.arange(ri0, ri1)
    ox = np.clip(np.minimum(cols + 1, c1) - np.maximum(cols, c0), 0, None)
    oy = np.clip(np.minimum(rows + 1, r1) - np.maximum(rows, r0), 0, None)
    return (ci0, ri0, ci1 - ci0, ri1 - ri0), np.outer(oy, ox)


def read_footprint(ds, x: float, y: float, half_m: float, indexes=None):
    """Read the footprint window from an open rasterio dataset. Returns (array, weights); array is
    (bands, h, w) or (h, w) for a single index. Pixels outside the raster read as 0 with weight kept, so
    callers must treat the nodata value as invalid."""
    from rasterio.windows import Window
    (c, r, w, h), wts = footprint_window(ds.transform, x, y, half_m)
    arr = ds.read(indexes, window=Window(c, r, w, h), boundless=True, fill_value=0)
    return arr, wts


def wmean(a: np.ndarray, w: np.ndarray, valid: np.ndarray | None = None) -> float:
    """Weighted mean of a over pixels where valid; NaN when no valid weight."""
    a = np.asarray(a, dtype=float)
    m = np.isfinite(a) if valid is None else (valid & np.isfinite(a))
    tot = float((w * m).sum())
    return float((np.where(m, a, 0) * w).sum() / tot) if tot > 0 else float("nan")


def wstd(a: np.ndarray, w: np.ndarray, valid: np.ndarray | None = None) -> float:
    a = np.asarray(a, dtype=float)
    m = np.isfinite(a) if valid is None else (valid & np.isfinite(a))
    tot = float((w * m).sum())
    if tot <= 0:
        return float("nan")
    mu = (np.where(m, a, 0) * w).sum() / tot
    return float(math.sqrt((np.where(m, (a - mu) ** 2, 0) * w).sum() / tot))


def majority(a: np.ndarray, w: np.ndarray) -> tuple[int, float]:
    """Class with the largest weighted area and its share."""
    tot: dict[int, float] = {}
    for v, wt in zip(np.asarray(a).ravel(), w.ravel()):
        tot[int(v)] = tot.get(int(v), 0.0) + float(wt)
    code, wt = max(tot.items(), key=lambda kv: kv[1])
    return code, wt / sum(tot.values())


def save_chip(path: Path, arr: np.ndarray, transform, crs, nodata=None) -> None:
    """Write a small GeoTIFF (bands, h, w), deflate-compressed, atomically."""
    import os
    import rasterio
    path.parent.mkdir(parents=True, exist_ok=True)
    arr = arr if arr.ndim == 3 else arr[None]
    tmp = path.with_name(path.name + ".part")
    with rasterio.open(tmp, "w", driver="GTiff", height=arr.shape[1], width=arr.shape[2], count=arr.shape[0],
                       dtype=arr.dtype, crs=crs, transform=transform, compress="deflate", nodata=nodata) as dst:
        dst.write(arr)
    os.replace(tmp, path)


def save_preview(path: Path, rgb: np.ndarray, box: tuple[float, float, float, float] | None = None,
                 points=None) -> None:
    """PNG preview of an (h, w, 3) uint8 image; box = plot square in pixel coords (c0, r0, c1, r1),
    points = [(col, row)] core positions, both drawn on top."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    path.parent.mkdir(parents=True, exist_ok=True)
    fig = plt.figure(figsize=(4, 4), dpi=120)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.imshow(rgb, interpolation="nearest")
    if box:
        c0, r0, c1, r1 = box
        ax.plot([c0, c1, c1, c0, c0], [r0, r0, r1, r1, r0], color="yellow", lw=1.2)
    if points:
        ax.scatter([p[0] for p in points], [p[1] for p in points], s=10, c="red", edgecolors="white", linewidths=0.4)
    ax.set_xlim(0, rgb.shape[1]); ax.set_ylim(rgb.shape[0], 0)
    ax.axis("off")
    fig.savefig(path)
    plt.close(fig)


def write_manifest(modality: str, rows: pd.DataFrame) -> Path:
    """Record what a fetch used: data/raw/<modality>/manifest.parquet (rows replaced per call, fetched_at added)."""
    d = RAW / modality
    d.mkdir(parents=True, exist_ok=True)
    rows = rows.copy()
    rows["fetched_at"] = pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds")
    p = d / "manifest.parquet"
    rows.to_parquet(p, index=False)
    return p
