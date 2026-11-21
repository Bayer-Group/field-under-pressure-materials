"""Chips as web-map overlays: a GeoTIFF chip (UTM) warped to Web Mercator, written as a PNG with transparent
nodata, plus its corner coordinates. A map library can then stretch the PNG between two corners.
Aerial photos keep their colours; greenness maps (ndvimap.py) are coloured with NDVI_RAMP.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import numpy as np

from . import ndvimap
from .config import CACHE

OVERLAY_DIR = CACHE / "gui_overlay"
WEB_MERCATOR = "EPSG:3857"
# NDVI -> colour. Keep in step with the legend in web/src/styles.css (.ndvi-legend).
NDVI_RAMP = [(-1.0, "#b8c4cc"), (-0.05, "#b8c4cc"), (0.0, "#a6763e"), (0.2, "#d9b36c"), (0.4, "#e9e08a"),
             (0.6, "#8cc45a"), (0.8, "#2f8f3a"), (1.0, "#0b5a24")]


def _grid(ds):
    """Target grid (transform, width, height) of the chip in Web Mercator. Deterministic for a given chip."""
    from rasterio.warp import calculate_default_transform
    return calculate_default_transform(ds.crs, WEB_MERCATOR, ds.width, ds.height, *ds.bounds)


def bounds_latlon(chip: Path) -> tuple[float, float, float, float]:
    """(south, west, north, east) in WGS84 of the warped overlay of this chip."""
    return _bounds(chip, chip.stat().st_mtime)


@lru_cache(maxsize=20000)
def _bounds(chip: Path, mtime: float) -> tuple[float, float, float, float]:
    import rasterio
    from rasterio.warp import transform_bounds
    with rasterio.open(chip) as ds:
        t, w, h = _grid(ds)
    west, north = t * (0, 0)
    east, south = t * (w, h)
    w84 = transform_bounds(WEB_MERCATOR, "EPSG:4326", west, south, east, north)
    return (w84[1], w84[0], w84[3], w84[2])


def _warp(chip: Path, bands: list[int], smooth: bool) -> np.ndarray:
    """The chip's bands on its Web Mercator grid, (bands, h, w) uint8, 0 where there is no data."""
    import rasterio
    from rasterio.warp import Resampling, reproject
    with rasterio.open(chip) as ds:
        t, w, h = _grid(ds)
        out = np.zeros((len(bands), h, w), dtype=np.uint8)
        reproject(ds.read(bands), out, src_transform=ds.transform, src_crs=ds.crs, dst_transform=t,
                  dst_crs=WEB_MERCATOR, resampling=Resampling.bilinear if smooth else Resampling.nearest,
                  src_nodata=0, dst_nodata=0)
    return out


def _cached_png(chip: Path, make_rgba) -> Path:
    """Path of the PNG for this chip; built on first use, rebuilt when the chip is newer."""
    out = OVERLAY_DIR / (chip.stem + ".png")
    if out.exists() and out.stat().st_mtime >= chip.stat().st_mtime:
        return out
    from PIL import Image
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".part")
    Image.fromarray(make_rgba(), "RGBA").save(tmp, "PNG")
    os.replace(tmp, out)
    return out


def overlay_png(chip: Path) -> Path:
    """An aerial photo chip (R, G, B first) as a warped RGBA PNG."""
    def rgba():
        rgb = _warp(chip, [1, 2, 3], smooth=True)
        return np.dstack([*rgb, np.where(rgb.sum(axis=0) > 0, 255, 0).astype(np.uint8)])
    return _cached_png(chip, rgba)


@lru_cache
def _ndvi_lut() -> np.ndarray:
    """(256, 4) uint8: colour of every stored code; code 0 (nodata) is transparent."""
    stops = [s for s, _ in NDVI_RAMP]
    rgb = np.array([[int(c[i:i + 2], 16) for i in (1, 3, 5)] for _, c in NDVI_RAMP], dtype=float)
    v = ndvimap.decode(np.arange(256).clip(0, 201))
    lut = np.stack([np.interp(v, stops, rgb[:, k]) for k in range(3)] + [np.full(256, 255.0)], axis=1)
    lut[0] = 0
    return np.rint(lut).astype(np.uint8)


def ndvi_png(chip: Path) -> Path:
    """A greenness map chip as a warped, coloured RGBA PNG (pixels kept sharp: no smoothing of values)."""
    return _cached_png(chip, lambda: _ndvi_lut()[_warp(chip, [1], smooth=False)[0]])


def ndvi_at(chip: Path, lat: float, lon: float) -> float | None:
    """NDVI of the pixel under a point; None outside the chip or where the scene was masked."""
    import rasterio
    from pyproj import Transformer
    with rasterio.open(chip) as ds:
        x, y = Transformer.from_crs("EPSG:4326", ds.crs, always_xy=True).transform(lon, lat)
        r, c = ds.index(x, y)
        if not (0 <= r < ds.height and 0 <= c < ds.width):
            return None
        v = ndvimap.decode(ds.read(1)[r, c])
    return float(v) if np.isfinite(v) else None
