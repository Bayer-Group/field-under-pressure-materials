"""USDA Crop Sequence Boundaries (CSB 2018-2025) clipped to the two analysis windows."""
from __future__ import annotations

import re
import time
import zipfile
from functools import lru_cache

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
from pyproj import Transformer
from shapely.geometry import Point, box

from .cdl import crop_group
from .config import PROCESSED, RAW, regions, window_bbox

CSB_DIR = RAW / "csb"
CSB_ZIP = CSB_DIR / "NationalCSB_2018-2025_rev23.zip"
GDB_NAME = "CSB1825.gdb"
YEARS = list(range(2018, 2026))
SITES = ["STER", "KONA"]


def clip_path(site: str):
    return PROCESSED / f"csb_raw_{site}.parquet"


def _year_cols(cols) -> dict[int, str]:
    """Find per-year CDL code columns (R18..R25, CDL2018.., CDL18.., Y2018.., etc.)."""
    out = {}
    for c in cols:
        m = re.fullmatch(r"(?:R|CDL|Y|CDL_|CROP_?)?(20\d\d|\d\d)", str(c), flags=re.I)
        if m:
            y = int(m.group(1))
            y = y + 2000 if y < 100 else y
            if y in YEARS:
                out[y] = c
    return out


def window_bbox_5070(site: str, crs) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = window_bbox(site)
    t = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    xs, ys = zip(*[t.transform(x, y) for x, y in [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]])
    return min(xs), min(ys), max(xs), max(ys)


def clip_csb_to_windows(src: str | None = None) -> dict[str, float]:
    """Read CSB straight from the zip (/vsizip) or an unzipped gdb; save raw clipped parquet per site.
    Returns seconds per site."""
    src = src or f"/vsizip/{CSB_ZIP}/{GDB_NAME}"
    layers = pyogrio.list_layers(src)
    layer = str(layers[0][0]) if len(layers) == 1 else next(
        str(l[0]) for l in layers if "csb" in str(l[0]).lower())
    info = pyogrio.read_info(src, layer=layer)
    crs = info["crs"]
    times = {}
    for site in SITES:
        t = time.time()
        gdf = pyogrio.read_dataframe(src, layer=layer, bbox=window_bbox_5070(site, crs))
        gdf = gdf.to_crs("EPSG:5070")
        gdf.to_parquet(clip_path(site))
        times[site] = time.time() - t
    return times


def _prep(gdf: gpd.GeoDataFrame, site: str) -> gpd.GeoDataFrame:
    gdf = gdf.copy()
    ycols = _year_cols(gdf.columns)
    missing = [y for y in YEARS if y not in ycols]
    if missing:
        raise ValueError(f"CSB year columns missing for {missing}; columns={list(gdf.columns)}")
    id_col = next(c for c in gdf.columns if c.upper() == "CSBID")
    area_col = next((c for c in gdf.columns if c.upper() in ("CSBACRES", "ACRES")), None)
    out = gdf[[id_col]].rename(columns={id_col: "CSBID"})
    out["CSBID"] = out["CSBID"].astype(str)
    out["unit_id"] = "CSB_" + out["CSBID"]
    out["unit_type"] = "field"
    out["site"] = site
    out["area_ha"] = gdf.geometry.area / 1e4
    if area_col:
        out["csb_acres"] = pd.to_numeric(gdf[area_col], errors="coerce")
    for c in gdf.columns:
        if c.upper() in ("STATEFIPS", "CNTYFIPS", "CNTY", "STATEASD", "ASD", "CSBYEARS"):
            out[c.lower()] = gdf[c].values
    for y in YEARS:
        codes = pd.to_numeric(gdf[ycols[y]], errors="coerce")
        out[f"cdl_{y}"] = codes.values
        out[f"crop_{y}"] = [crop_group(int(v)) if pd.notna(v) else "unknown" for v in codes]
    for t in range(1, 6):
        out[f"crop_t{t}"] = out[f"crop_{2026 - t}"]
    out["geometry"] = gdf.geometry.values
    out = gpd.GeoDataFrame(out, geometry="geometry", crs="EPSG:5070")
    c = out.geometry.centroid
    ll = gpd.GeoSeries(c, crs="EPSG:5070").to_crs("EPSG:4326")
    out["lat"], out["lon"] = ll.y.values, ll.x.values
    out["history_source"] = "csb"
    return out


@lru_cache
def load_window_fields(site: str) -> gpd.GeoDataFrame:
    """CSB fields in the window (EPSG:5070 geometry, full resolution, clipped to the window box)."""
    p = clip_path(site)
    if not p.exists():
        clip_csb_to_windows()
    gdf = gpd.read_parquet(p)
    x0, y0, x1, y1 = window_bbox(site)
    w = gpd.GeoSeries([box(x0, y0, x1, y1)], crs="EPSG:4326").to_crs("EPSG:5070").iloc[0]
    gdf = gdf[gdf.intersects(w)].copy()
    gdf["geometry"] = gdf.geometry.intersection(w)
    gdf = gdf[~gdf.geometry.is_empty]
    return _prep(gdf, site)


def plot_to_csb(lat: float, lon: float) -> dict | None:
    """Point-in-polygon over the clipped window layers. Returns CSBID + crop_2018..crop_2025, or None."""
    x, y = Transformer.from_crs("EPSG:4326", "EPSG:5070", always_xy=True).transform(lon, lat)
    pt = Point(x, y)
    for site in SITES:
        if not clip_path(site).exists():
            continue
        f = load_window_fields(site)
        hit = f[f.geometry.contains(pt)]
        if len(hit):
            r = hit.iloc[0]
            d = {"CSBID": r["CSBID"], "csb_site": site}
            d.update({f"crop_{yr}": r[f"crop_{yr}"] for yr in YEARS})
            return d
    return None
