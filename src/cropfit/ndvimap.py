"""Greenness maps: Sentinel-2 NDVI at 10 m for the surroundings of every plot (a square of +-HALF_M around
the plot centre), one small GeoTIFF per plot and clear Sentinel-2 date of plot_vi_timeseries.

plot_vi_timeseries holds one number per plot and date (the 40 m plot); these chips show the same scenes as
images, so the plot can be compared with the fields around it. Pixels the scene's own mask calls cloud,
shadow or snow are nodata. Stored as one uint8 band: 0 = nodata, 1..201 = NDVI -1..1 in steps of 0.01.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from . import satellite, stac
from .config import RAW

MAP_DIR = RAW / "imagery" / "s2_ndvi"
HALF_M = 1000.0
COLLECTION = satellite.SENSORS["sentinel2"]["collection"]


def encode(ndvi: np.ndarray, valid: np.ndarray) -> np.ndarray:
    code = np.rint((np.clip(np.nan_to_num(ndvi), -1, 1) + 1) * 100) + 1
    return np.where(valid, code, 0).astype(np.uint8)


def decode(code: np.ndarray) -> np.ndarray:
    """uint8 codes -> NDVI as float, NaN where nodata."""
    c = np.asarray(code, dtype=float)
    return np.where(c > 0, (c - 1) / 100 - 1, np.nan)


def chip_path(plot_id: str, date) -> Path:
    return MAP_DIR / plot_id / f"{plot_id}_s2ndvi_{pd.Timestamp(date):%Y%m%d}.tif"


def wanted(ts: pd.DataFrame) -> pd.DataFrame:
    """The plot-dates that get a map: clear Sentinel-2 observations (plotID, date, item_id)."""
    w = ts[(ts["sensor"] == "sentinel2") & ts["clear"]]
    return w[["plotID", "date", "item_id"]].reset_index(drop=True)


def _items(ids: list[str]) -> dict:
    """STAC items by id (the scene ids are already known from the time series: no spatial search)."""
    out = {}
    for i in range(0, len(ids), 100):
        for attempt in range(4):
            try:
                out.update({it.id: it for it in stac.catalog().search(collections=[COLLECTION], ids=ids[i:i + 100]).items()})
                break
            except Exception:  # noqa: BLE001
                if attempt == 3:
                    raise
    return out


def _scene(item, jobs: list[dict], half_m: float) -> list[dict]:
    """Write the chips of one scene. jobs: dicts with plotID, lat, lon, date."""
    import rasterio
    from rasterio.windows import Window, bounds as window_bounds, from_bounds, transform as window_transform
    crs = item.properties.get("proj:code") or f"EPSG:{item.properties['proj:epsg']}"
    rows = []
    with rasterio.Env(**stac.GDAL_ENV):
        with rasterio.open(stac.sign(item.assets["B04"].href)) as red_ds, \
                rasterio.open(stac.sign(item.assets["B08"].href)) as nir_ds, \
                rasterio.open(stac.sign(item.assets["SCL"].href)) as scl_ds:
            for p in jobs:
                x, y = stac.to_xy(p["lon"], p["lat"], crs)
                (c, r, w, h), _ = stac.footprint_window(red_ds.transform, x, y, half_m)
                win = Window(c, r, w, h)
                red_dn = red_ds.read(1, window=win, boundless=True, fill_value=0)
                nir_dn = nir_ds.read(1, window=win, boundless=True, fill_value=0)
                # the mask is at 20 m: read the same ground extent, resampled (nearest) to the 10 m grid
                scl = scl_ds.read(1, window=from_bounds(*window_bounds(win, red_ds.transform), transform=scl_ds.transform),
                                  out_shape=(h, w), boundless=True, fill_value=0)
                red = satellite.to_reflectance("sentinel2", red_dn, item.properties)
                nir = satellite.to_reflectance("sentinel2", nir_dn, item.properties)
                den = nir + red
                valid = np.isfinite(den) & (den > 0) & satellite.clear_mask("sentinel2", scl)
                ndvi = np.where(valid, (nir - red) / np.where(valid, den, 1), np.nan)
                f = chip_path(p["plotID"], p["date"])
                stac.save_chip(f, encode(ndvi, valid), window_transform(win, red_ds.transform), crs, nodata=0)
                rows.append(dict(plotID=p["plotID"], date=p["date"], item_id=item.id, valid_frac=float(valid.mean()),
                                 chip=str(f.relative_to(RAW.parent.parent))))
    return rows


def fetch(geom: pd.DataFrame, ts: pd.DataFrame, half_m: float = HALF_M, workers: int = 8,
          limit: int | None = None) -> tuple[pd.DataFrame, list[str]]:
    """Write every wanted chip that is not on disk yet (so a re-run only fetches what is missing).
    limit: at most this many scenes, for a trial run. Returns (rows of the new chips, ids of failed scenes)."""
    centre = geom.set_index("plotID")[["lat", "lon"]].to_dict("index")
    todo: dict[str, list[dict]] = {}
    for r in wanted(ts).itertuples():
        if r.plotID in centre and not chip_path(r.plotID, r.date).exists():
            todo.setdefault(r.item_id, []).append(dict(plotID=r.plotID, date=r.date, **centre[r.plotID]))
    ids = sorted(todo)[:limit]
    items = _items(ids)

    def one(iid):
        if iid not in items:
            return (iid, "NotInCatalogue")
        last = None
        for _ in range(3):
            try:
                return _scene(items[iid], todo[iid], half_m)
            except Exception as e:  # noqa: BLE001
                last = e
        return (iid, type(last).__name__)

    with ThreadPoolExecutor(workers) as ex:
        res = list(ex.map(one, ids))
    rows = pd.DataFrame([r for chunk in res if isinstance(chunk, list) for r in chunk])
    return rows, [r for r in res if isinstance(r, tuple)]
