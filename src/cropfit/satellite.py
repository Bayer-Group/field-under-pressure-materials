"""Satellite greenness time series per plot: Sentinel-2 L2A (10-20 m, 2015+) and Landsat 8/9 Collection 2
Level 2 (30 m, 2013+) from Microsoft Planetary Computer (keyless).

One observation = one scene over one plot: surface reflectance averaged over the plot footprint (area-weighted
pixels, see stac.py), the share of the footprint the scene's own mask calls clear, and vegetation indices.
Only observations with clear_frac >= CLEAR_MIN should be used; nothing is interpolated here.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from . import stac
from .config import RAW, light_filter

SAT_DIR = RAW / "satellite"
CLEAR_MIN = 0.99
START = "2013-01-01"

SENSORS = {
    "sentinel2": dict(collection="sentinel-2-l2a", query=None,
                      bands={"blue": "B02", "red": "B04", "rededge": "B05", "nir": "B08", "swir1": "B11"},
                      mask="SCL"),
    "landsat": dict(collection="landsat-c2-l2", query={"platform": {"in": ["landsat-8", "landsat-9"]}},
                    bands={"blue": "blue", "red": "red", "nir": "nir08", "swir1": "swir16"}, mask="qa_pixel"),
}
S2_CLEAR = (4, 5, 6, 7)          # vegetation, bare soil, water, unclassified (not cloud/shadow/cirrus/snow)


def to_reflectance(sensor: str, dn, item_props: dict):
    """Digital numbers -> surface reflectance (0-1). 0 is nodata for both sensors."""
    dn = np.asarray(dn, dtype=float)
    if sensor == "sentinel2":
        # processing baseline 04.00+ (from 25 Jan 2022) stores reflectance + 1000
        off = 1000.0 if str(item_props.get("s2:processing_baseline", "0")) >= "04.00" else 0.0
        r = (dn - off) / 10000.0
    else:
        r = dn * 0.0000275 - 0.2
    return np.where(dn > 0, r, np.nan)


def clear_mask(sensor: str, m: np.ndarray) -> np.ndarray:
    """True where the scene's quality layer says the pixel is usable."""
    m = np.asarray(m)
    if sensor == "sentinel2":
        return np.isin(m, S2_CLEAR)
    m = m.astype(np.uint16)                     # Landsat QA_PIXEL bits
    bad = (m & 0b11111) != 0                    # fill, dilated cloud, cirrus, cloud, cloud shadow
    snow = (m & (1 << 5)) != 0
    return ~bad & ~snow & (m != 0)


def indices(b: dict) -> dict:
    """Vegetation and soil indices from mean band reflectances (missing bands give NaN)."""
    g = lambda k: b.get(k, np.nan)  # noqa: E731
    blue, red, nir, sw, re = g("blue"), g("red"), g("nir"), g("swir1"), g("rededge")

    def nd(a, c):
        return (a - c) / (a + c) if np.isfinite(a + c) and (a + c) != 0 else np.nan
    evi_den = nir + 6 * red - 7.5 * blue + 1
    return dict(ndvi=nd(nir, red), evi=2.5 * (nir - red) / evi_den if np.isfinite(evi_den) and evi_den != 0 else np.nan,
                ndmi=nd(nir, sw), ndre=nd(nir, re), bare_soil_index=nd(sw + red, nir + blue))


def _scene(sensor: str, item, plots: list[dict]) -> pd.DataFrame:
    """Read one scene for all plots that it covers. plots: dicts with plotID, lat, lon, half_m."""
    import rasterio
    cfg = SENSORS[sensor]
    crs = item.properties.get("proj:code") or f"EPSG:{item.properties['proj:epsg']}"
    xy = {p["plotID"]: stac.to_xy(p["lon"], p["lat"], crs) for p in plots}
    vals: dict[str, dict] = {p["plotID"]: {} for p in plots}
    with rasterio.Env(**stac.GDAL_ENV):
        with rasterio.open(stac.sign(item.assets[cfg["mask"]].href)) as ds:
            for p in plots:
                m, w = stac.read_footprint(ds, *xy[p["plotID"]], p["half_m"], 1)
                tot = float(w.sum())
                vals[p["plotID"]]["clear_frac"] = float((w * clear_mask(sensor, m)).sum() / tot) if tot else np.nan
        for name, asset in cfg["bands"].items():
            with rasterio.open(stac.sign(item.assets[asset].href)) as ds:
                for p in plots:
                    a, w = stac.read_footprint(ds, *xy[p["plotID"]], p["half_m"], 1)
                    vals[p["plotID"]][name] = stac.wmean(to_reflectance(sensor, a, item.properties), w)
    rows = []
    for p in plots:
        v = vals[p["plotID"]]
        rows.append(dict(plotID=p["plotID"], date=pd.Timestamp(item.datetime).tz_localize(None).normalize(),
                         sensor=sensor, platform=item.properties.get("platform"), item_id=item.id,
                         scene_cloud_pct=item.properties.get("eo:cloud_cover"), clear_frac=v["clear_frac"],
                         **{k: v.get(k, np.nan) for k in ("blue", "red", "rededge", "nir", "swir1")},
                         **indices(v)))
    return pd.DataFrame(rows)


def scene_index(sensor: str, geom: pd.DataFrame, start: str = START, end: str | None = None) -> dict:
    """item_id -> (item, [plot dicts]) for all scenes covering each plot centre."""
    cfg = SENSORS[sensor]
    end = end or pd.Timestamp.now().strftime("%Y-%m-%d")
    out: dict = {}
    for p in geom.to_dict("records"):
        for it in stac.search(cfg["collection"], p["lon"], p["lat"], datetime=f"{start}/{end}", query=cfg["query"]):
            out.setdefault(it.id, (it, []))[1].append(p)
    return out


def fetch(sensor: str, geom: pd.DataFrame, workers: int = 12, start: str = START, end: str | None = None,
          max_scene_cloud: float = 95.0) -> tuple[pd.DataFrame, list[str]]:
    """All observations of one sensor for the plots in geom. Each scene's result is stored under
    data/raw/satellite/<sensor>/<item_id>.parquet, so a re-run only reads scenes it does not have yet.
    Returns (observations, ids of scenes that failed)."""
    d = SAT_DIR / sensor
    d.mkdir(parents=True, exist_ok=True)
    idx = scene_index(sensor, geom, start, end)
    todo = {k: v for k, v in idx.items()
            if (v[0].properties.get("eo:cloud_cover") or 0) <= max_scene_cloud}

    def one(kv):
        iid, (item, plots) = kv
        f = d / f"{iid}.parquet"
        if f.exists():
            have = pd.read_parquet(f)
            if {p["plotID"] for p in plots} <= set(have["plotID"]):
                return have
        last = None
        for _ in range(3):
            try:
                df = _scene(sensor, item, plots)
                tmp = f.with_name(f.name + ".part")
                df.to_parquet(tmp, index=False)
                tmp.replace(f)
                return df
            except Exception as e:  # noqa: BLE001
                last = e
        return (iid, type(last).__name__)

    with ThreadPoolExecutor(workers) as ex:
        res = list(ex.map(one, todo.items()))
    ok = [r for r in res if isinstance(r, pd.DataFrame)]
    failed = [r[0] for r in res if not isinstance(r, pd.DataFrame)]
    stac.write_manifest(f"satellite/{sensor}", pd.DataFrame(
        [dict(source="planetary-computer", collection=SENSORS[sensor]["collection"], item_id=k,
              datetime=str(v[0].datetime), n_plots=len(v[1]), read=k not in set(failed)) for k, v in todo.items()]))
    obs = pd.concat(ok, ignore_index=True) if ok else pd.DataFrame()
    return obs, failed


def load_observations() -> pd.DataFrame:
    """All stored scene results of all sensors (in light mode only its plots)."""
    files = sorted(f for s in SENSORS for f in (SAT_DIR / s).glob("*.parquet") if f.name != "manifest.parquet")
    obs = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True) if files else pd.DataFrame()
    return light_filter(obs).reset_index(drop=True)


def timeseries(obs: pd.DataFrame) -> pd.DataFrame:
    """Tidy plot x date x sensor table; when two scenes of a sensor cover a plot on one day the clearer one
    is kept. Adds `clear` (clear_frac >= CLEAR_MIN and a valid NDVI)."""
    # ties (same clear share) go to the lexically last scene id, i.e. the latest processing: never file order
    o = (obs.sort_values(["clear_frac", "item_id"], ascending=[False, False], kind="stable")
         .drop_duplicates(["plotID", "date", "sensor"]))
    o = o.assign(clear=(o["clear_frac"] >= CLEAR_MIN) & o["ndvi"].notna())
    return o.sort_values(["plotID", "date", "sensor"]).reset_index(drop=True)


def season_metrics(ts: pd.DataFrame, min_obs: int = 6) -> pd.DataFrame:
    """Per plot and calendar year, from clear observations of both sensors (1 Apr - 31 Oct = growing season):
    n_clear, ndvi_peak and peak_doy (after a 3-observation running median, so one bad scene cannot make the
    peak), ndvi_mean_gs, ndvi_integral_gs (NDVI x days), greenup_doy / senescence_doy (first and last day
    above half of the seasonal amplitude), bare_share_gs (share of growing-season observations with
    NDVI < 0.2). Metrics other than n_clear are NaN with fewer than min_obs growing-season observations.
    A calendar year cuts winter crops in two: autumn growth of winter wheat belongs to the year before."""
    c = ts[ts["clear"]].copy()
    c["year"], c["doy"] = c["date"].dt.year, c["date"].dt.day_of_year
    rows = []
    for (plot, year), g in c.groupby(["plotID", "year"]):
        g = g.groupby("doy", as_index=False)["ndvi"].mean().sort_values("doy")
        gs = g[(g["doy"] >= 91) & (g["doy"] <= 304)]
        row = dict(plotID=plot, year=int(year), n_clear=len(g), n_clear_gs=len(gs))
        if len(gs) >= min_obs:
            sm = gs["ndvi"].rolling(3, center=True, min_periods=1).median().values
            doy = gs["doy"].values.astype(float)
            k = int(np.argmax(sm))
            base = float(np.percentile(sm, 10))
            half = base + 0.5 * (sm[k] - base)
            above = np.where(sm >= half)[0]
            row.update(ndvi_peak=float(sm[k]), peak_doy=float(doy[sm >= sm[k] - 1e-9].mean()),  # centre of the plateau
                       ndvi_mean_gs=float(gs["ndvi"].mean()),
                       ndvi_integral_gs=float(np.trapezoid(sm, doy)), ndvi_amplitude=float(sm[k] - base),
                       greenup_doy=float(doy[above[0]]), senescence_doy=float(doy[above[-1]]),
                       bare_share_gs=float((gs["ndvi"] < 0.2).mean()))
        rows.append(row)
    return pd.DataFrame(rows)
