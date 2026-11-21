"""USDA CDL crop history per point from Microsoft Planetary Computer (windowed COG reads)."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

import numpy as np
import pandas as pd

from . import stac
from .config import RULES

STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"
COLLECTION = "usda-cdl"
TYPE_PROP = "usda_cdl:type"  # == "cropland"; asset key "cropland"; CRS from "proj:code" (EPSG:5070)
EDGE_SHARE = 0.6
HALF_M = 20.0  # 40 x 40 m plot

# Fallback code -> crop group (used only if rules/cdl_codes.csv is missing)
FALLBACK = {1: "corn", 4: "sorghum", 5: "soybean", 6: "sunflower", 23: "spring_wheat",
            24: "winter_wheat", 26: "double_wheat_soy", 28: "barley_oats", 21: "barley_oats",
            29: "millet", 36: "alfalfa", 42: "dry_bean", 61: "fallow", 37: "grass_pasture",
            176: "grass_pasture"}
NONCROP = {0, 62, 63, 64, 65, 81, 82, 83, 87, 88, 92, 111, 112, 121, 122, 123, 124,
           131, 141, 142, 143, 152, 190, 195}


@lru_cache
def code_map() -> dict[int, str]:
    p = RULES / "cdl_codes.csv"
    if p.exists():
        df = pd.read_csv(p)
        gcol = next((c for c in df.columns if "group" in c.lower()), df.columns[-1])
        ccol = next((c for c in df.columns if c.lower() in ("code", "cdl_code", "value")), df.columns[0])
        return {int(a): str(b) for a, b in zip(df[ccol], df[gcol])}
    return {}


def crop_group(code: int) -> str:
    m = code_map()
    if m:
        return m.get(int(code), "other_crop")
    c = int(code)
    if c in FALLBACK:
        return FALLBACK[c]
    return "noncrop" if c in NONCROP else "other_crop"


def _items(lat: float, lon: float, years: tuple[int, ...]):
    items = stac.search(COLLECTION, lon, lat, query={TYPE_PROP: {"eq": "cropland"}})
    out = {}
    for it in items:
        y = int(it.properties["start_datetime"][:4])
        if y in years and "cropland" in it.assets:
            out[y] = it
    return out


def _read_year(item, lat, lon):
    """Majority class over the plot square (area-weighted pixels) and its share."""
    import rasterio
    href = stac.sign(item.assets["cropland"].href)
    crs = item.properties.get("proj:code", "EPSG:5070")
    x, y = stac.to_xy(lon, lat, crs)
    with rasterio.Env(**stac.GDAL_ENV):
        with rasterio.open(href) as ds:
            arr, w = stac.read_footprint(ds, x, y, HALF_M, 1)
    return stac.majority(arr, w)


def cdl_history(lat: float, lon: float, years=range(2008, 2022)) -> pd.DataFrame:
    """Majority CDL class in a 40x40 m window per year.
    Columns: year, cdl_code, crop_group, share, edge (share < 0.6), source ('cdl', or 'cdl_read_failed'
    when the raster could not be read, so a network failure is not mistaken for an unknown crop)."""
    years = tuple(years)
    items = _items(lat, lon, years)
    rows = []
    for y in years:
        it = items.get(y)
        if it is None:
            rows.append(dict(year=y, cdl_code=np.nan, crop_group="unknown", share=np.nan, edge=False, source="cdl"))
            continue
        try:
            code, share = _read_year(it, lat, lon)
            g = crop_group(code) if code != 0 else "unknown"
            rows.append(dict(year=y, cdl_code=code, crop_group=g, share=round(share, 3),
                             edge=bool(share < EDGE_SHARE), source="cdl"))
        except Exception:  # noqa: BLE001 - a failed read must not look like a real "unknown" crop
            rows.append(dict(year=y, cdl_code=np.nan, crop_group="unknown", share=np.nan, edge=False,
                             source="cdl_read_failed"))
    return pd.DataFrame(rows)


def cdl_history_many(points: dict[str, tuple[float, float]], years=range(2008, 2022), workers: int = 6) -> pd.DataFrame:
    """points: {unit_id: (lat, lon)} -> long frame with unit_id column."""
    def one(item):
        uid, (la, lo) = item
        d = cdl_history(la, lo, years)
        d.insert(0, "unit_id", uid)
        return d
    with ThreadPoolExecutor(workers) as ex:
        return pd.concat(list(ex.map(one, points.items())), ignore_index=True)
