"""Aerial photos of every plot: NAIP (USDA, 0.3-1 m, R G B NIR, every 2-3 years; Planetary Computer, keyless)
and the NEON airborne camera mosaic DP3.30010.001 (10 cm, R G B; NEON API, token).

Per plot and flight: statistics inside the plot square, a GeoTIFF chip of the plot with surrounding context
and a PNG preview with the plot square drawn in. Values are camera digital numbers, not calibrated
reflectance: compare greenness within one flight (between plots, within a plot), not between flights.
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from . import stac
from .config import RAW

IMG_DIR = RAW / "imagery"
UTM = {"STER": "EPSG:32613", "KONA": "EPSG:32614"}       # NEON AOP tiles are in the site's UTM zone
AOP_CAMERA = "DP3.30010.001"


def pixel_stats(arr: np.ndarray, w: np.ndarray) -> dict:
    """arr: (bands, h, w) with R, G, B[, NIR]. Excess-green index on chromatic coordinates (works without
    NIR) and, with a 4th band, NDVI; weighted mean and spread inside the footprint. Spread = patchiness."""
    a = arr.astype(float)
    valid = a.sum(axis=0) > 0
    s = np.where(valid, a[:3].sum(axis=0), np.nan)
    exg = (2 * a[1] - a[0] - a[2]) / s
    out = dict(exg_mean=stac.wmean(exg, w, valid), exg_std=stac.wstd(exg, w, valid),
               green_frac=stac.wmean((exg > 0.05).astype(float), w, valid),
               brightness=stac.wmean(a[:3].mean(axis=0), w, valid),
               valid_frac=float((w * valid).sum() / w.sum()) if w.sum() else np.nan)
    if a.shape[0] >= 4:
        den = a[3] + a[0]
        ndvi = np.where(den > 0, (a[3] - a[0]) / np.where(den > 0, den, 1), np.nan)
        out.update(ndvi_mean=stac.wmean(ndvi, w, valid), ndvi_std=stac.wstd(ndvi, w, valid))
    else:
        out.update(ndvi_mean=np.nan, ndvi_std=np.nan)
    return out


def _chip(ds, x: float, y: float, half_m: float, context_m: float, max_px: int, stem: Path) -> dict:
    """Footprint statistics at native resolution + context chip (GeoTIFF and PNG) from an open dataset."""
    from rasterio.transform import from_origin
    from rasterio.windows import Window
    idx = list(range(1, min(ds.count, 4) + 1))
    arr, w = stac.read_footprint(ds, x, y, half_m, idx)
    st = pixel_stats(arr, w)
    (c, r, wd, ht), _ = stac.footprint_window(ds.transform, x, y, context_m)
    scale = max(1.0, max(wd, ht) / max_px)
    oh, ow = int(round(ht / scale)), int(round(wd / scale))
    chip = ds.read(idx, window=Window(c, r, wd, ht), out_shape=(len(idx), oh, ow), boundless=True, fill_value=0)
    res = abs(ds.transform.a) * wd / ow
    x0, y0 = ds.transform * (c, r)
    stac.save_chip(stem.with_suffix(".tif"), chip, from_origin(x0, y0, res, res), ds.crs, nodata=0)
    box = ((x - half_m - x0) / res, (y0 - (y + half_m)) / res, (x + half_m - x0) / res, (y0 - (y - half_m)) / res)
    stac.save_preview(stem.with_suffix(".png"), np.moveaxis(chip[:3], 0, -1), box=box)
    st.update(gsd_m=abs(ds.transform.a), chip=str(stem.with_suffix(".tif").relative_to(RAW.parent.parent)),
              preview=str(stem.with_suffix(".png").relative_to(RAW.parent.parent)))
    return st


# ---------------------------------------------------------------- NAIP
def fetch_naip(geom: pd.DataFrame, workers: int = 8, context_m: float = 500.0, max_px: int = 1600):
    """One row per plot and NAIP flight (all years on Planetary Computer). Returns (rows, failures).
    The chip covers 1 km around the plot (as the greenness maps do), at up to 1600 px (0.6 m or coarser)."""
    import rasterio
    jobs = []
    for p in geom.to_dict("records"):
        seen = set()
        for it in sorted(stac.search("naip", p["lon"], p["lat"]), key=lambda i: i.datetime):
            d = pd.Timestamp(it.datetime).tz_localize(None).normalize()
            if d in seen:           # neighbouring quads overlap: one image per flight day is enough
                continue
            seen.add(d)
            jobs.append((p, it, d))

    def one(job):
        p, it, d = job
        stem = IMG_DIR / "naip" / p["plotID"] / f"{p['plotID']}_naip_{d:%Y%m%d}"
        try:
            with rasterio.Env(**stac.GDAL_ENV):
                with rasterio.open(stac.sign(it.assets["image"].href)) as ds:
                    x, y = stac.to_xy(p["lon"], p["lat"], ds.crs)
                    st = _chip(ds, x, y, p["half_m"], context_m, max_px, stem)
            return dict(plotID=p["plotID"], source="naip", date=d, date_precision="day", item_id=it.id, **st)
        except Exception as e:  # noqa: BLE001
            return (f"{p['plotID']} {it.id}", type(e).__name__)

    return _run(one, jobs, workers)


# ---------------------------------------------------------------- NEON airborne camera
def aop_months(site: str, dpid: str = AOP_CAMERA) -> list[str]:
    from . import http
    r = http.get(f"https://data.neonscience.org/api/v0/products/{dpid}")
    return next((s["availableMonths"] for s in r.json()["data"]["siteCodes"] if s["siteCode"] == site), [])


def aop_files(site: str, month: str, dpid: str = AOP_CAMERA) -> list[dict]:
    """Files of one site-month (name, url, size); URLs are short-lived, list right before reading."""
    from . import http, neon
    tok = neon.get_token()
    r = http.get(f"https://data.neonscience.org/api/v0/data/{dpid}/{site}/{month}",
                 headers={"X-API-Token": tok} if tok else {})
    return r.json()["data"]["files"]


def fetch_aop_camera(geom: pd.DataFrame, years=None, workers: int = 6, context_m: float = 60.0,
                     max_px: int = 480, only=None):
    """One row per plot and NEON flight campaign. The tile holding the plot centre is read remotely (only the
    rows needed), never downloaded whole. NEON publishes the campaign month, not the flight day:
    date = first of that month, date_precision = 'month'. only: optional set of (plotID, 'YYYY-MM') to fetch,
    for retrying single chips. A plot can lie outside a campaign's flight box: then there is no tile, no row."""
    import rasterio
    jobs = []
    for site, sub in geom.groupby("site"):
        for month in aop_months(site):
            if years and int(month[:4]) not in set(years):
                continue
            files = {f["name"]: f["url"] for f in aop_files(site, month) if f["name"].endswith("_image.tif")}
            for p in sub.to_dict("records"):
                x, y = stac.to_xy(p["lon"], p["lat"], UTM[site])
                suffix = f"_{int(x // 1000 * 1000)}_{int(y // 1000 * 1000)}_image.tif"
                name = next((n for n in files if n.endswith(suffix)), None)
                if name and (only is None or (p["plotID"], month) in only):
                    jobs.append((p, month, name, files[name], x, y))

    def one(job):
        p, month, name, url, x, y = job
        stem = IMG_DIR / "neon_aop_camera" / p["plotID"] / f"{p['plotID']}_aop_{month.replace('-', '')}"
        try:
            with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_MAX_RETRY="4",
                              GDAL_HTTP_RETRY_DELAY="1", GDAL_HTTP_MERGE_CONSECUTIVE_RANGES="YES"):
                with rasterio.open(url) as ds:
                    st = _chip(ds, x, y, p["half_m"], context_m, max_px, stem)
            campaign = re.match(r"(\d{4}_[A-Z]{4}_\d+)", name)
            return dict(plotID=p["plotID"], source="neon_aop_camera", date=pd.Timestamp(month + "-01"),
                        date_precision="month", item_id=campaign.group(1) if campaign else name, **st)
        except Exception as e:  # noqa: BLE001
            return (f"{p['plotID']} {name}", type(e).__name__)

    return _run(one, jobs, workers)


def _run(one, jobs, workers):
    with ThreadPoolExecutor(workers) as ex:
        res = list(ex.map(one, jobs))
    rows = pd.DataFrame([r for r in res if isinstance(r, dict)])
    return rows, [r for r in res if not isinstance(r, dict)]
