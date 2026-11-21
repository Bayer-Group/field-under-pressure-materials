"""Sampling-event registry: the anchor every other dataset is linked to.

An event is one visit to a plot: (plotID, date). Biology (metagenomes, ITS) and soil chemistry of the same
visit share one event; visits of one plot at most EVENT_GAP_DAYS apart are the same event (a bout can take
a few days). The footprint of an event is the plot square; cores carry their own point inside it.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from pyproj import Transformer

from .config import PROCESSED, RAW, RESOURCES, light_filter

EVENT_GAP_DAYS = 3
PLOT_HALF_M = 20.0       # NEON base plot is 40 x 40 m
ALBERS = "EPSG:5070"


def assign_events(obs: pd.DataFrame, gap_days: int = EVENT_GAP_DAYS) -> pd.DataFrame:
    """obs: plotID, date (anything pd.to_datetime reads). Adds event_date (first day of the visit) and
    event_id = <plotID>_<YYYYMMDD>. A new event starts when a plot's next date is more than gap_days later."""
    o = obs.copy()
    o["date"] = pd.to_datetime(o["date"]).dt.tz_localize(None).dt.normalize()
    days = o[["plotID", "date"]].drop_duplicates().sort_values(["plotID", "date"])
    new = days.groupby("plotID")["date"].diff().dt.days.fillna(np.inf) > gap_days
    days["event_date"] = days["date"].where(new).groupby(days["plotID"]).ffill()
    days["event_id"] = days["plotID"] + "_" + days["event_date"].dt.strftime("%Y%m%d")
    return o.merge(days, on=["plotID", "date"], how="left")


def build_events(mg: pd.DataFrame, its: pd.DataFrame, chem: pd.DataFrame) -> pd.DataFrame:
    """One row per event from metagenomes (plotID, date), ITS plot-dates and chemistry plot-dates
    (plotID, collectDate). Columns: event_id, site, plotID, date, year, doy, has_metagenome, has_its,
    has_chem, n_metagenomes."""
    parts = [
        mg[["plotID", "date"]].assign(kind="metagenome"),
        its[["plotID", "collectDate"]].drop_duplicates().rename(columns={"collectDate": "date"}).assign(kind="its"),
        chem[["plotID", "collectDate"]].drop_duplicates().rename(columns={"collectDate": "date"}).assign(kind="chem"),
    ]
    o = assign_events(pd.concat(parts, ignore_index=True))
    g = o.groupby(["event_id", "plotID", "event_date"])["kind"]
    ev = g.agg(has_metagenome=lambda k: (k == "metagenome").any(), has_its=lambda k: (k == "its").any(),
               has_chem=lambda k: (k == "chem").any(), n_metagenomes=lambda k: int((k == "metagenome").sum())
               ).reset_index().rename(columns={"event_date": "date"})
    ev["site"] = ev["plotID"].str[:4]
    ev["year"] = ev["date"].dt.year
    ev["doy"] = ev["date"].dt.day_of_year
    cols = ["event_id", "site", "plotID", "date", "year", "doy", "has_metagenome", "has_its", "has_chem",
            "n_metagenomes"]
    return ev[cols].sort_values(["plotID", "date"]).reset_index(drop=True)


def plot_geometry(plot_ids, half_m: float = PLOT_HALF_M) -> pd.DataFrame:
    """Plot centroid (WGS84 and Albers metres) and half side for the given plots, from
    resources/neon_soil_plots_landcover.csv. The footprint is the square centroid +- half_m (assumed
    north-aligned; NEON plots are, to within the positional uncertainty that matters at >= 1 m pixels)."""
    r = pd.read_csv(RESOURCES / "neon_soil_plots_landcover.csv")
    r["plotID"] = r["plot"].str.replace(".basePlot.bgc", "", regex=False)
    r = r[r["plotID"].isin(set(plot_ids))].drop_duplicates("plotID")
    missing = sorted(set(plot_ids) - set(r["plotID"]))
    if missing:
        raise KeyError(f"plots without coordinates in resources: {missing}")
    x, y = Transformer.from_crs("EPSG:4326", ALBERS, always_xy=True).transform(r["lon"].values, r["lat"].values)
    out = r[["plotID", "site", "lat", "lon"]].rename(columns={"ptype": "plot_type"}).copy()
    out["plot_type"] = r["ptype"].values
    out["x_5070"], out["y_5070"], out["half_m"] = x, y, half_m
    return out.sort_values("plotID").reset_index(drop=True)


def core_points(cores: pd.DataFrame, geom: pd.DataFrame) -> pd.DataFrame:
    """Core positions from sls_soilCoreCollection. NEON reports the plot centroid as lat/lon for every core;
    the position inside the plot is coreCoordinateX/Y in metres from the south-west corner (0-40).
    Returns soilSampleID, plotID, date, core_x_m, core_y_m, lat, lon (NaN where NEON gives no offsets)."""
    c = cores[["sampleID", "plotID", "collectDate", "coreCoordinateX", "coreCoordinateY"]].copy()
    c = c.rename(columns={"sampleID": "soilSampleID", "coreCoordinateX": "core_x_m", "coreCoordinateY": "core_y_m"})
    c["date"] = pd.to_datetime(c["collectDate"]).dt.tz_localize(None).dt.normalize()
    c = c.dropna(subset=["soilSampleID"]).drop_duplicates("soilSampleID").merge(
        geom[["plotID", "x_5070", "y_5070", "half_m"]], on="plotID")
    x = c["x_5070"] - c["half_m"] + pd.to_numeric(c["core_x_m"], errors="coerce")
    y = c["y_5070"] - c["half_m"] + pd.to_numeric(c["core_y_m"], errors="coerce")
    lon, lat = Transformer.from_crs(ALBERS, "EPSG:4326", always_xy=True).transform(x.values, y.values)
    c["lat"], c["lon"] = lat, lon
    c.loc[x.isna() | y.isna(), ["lat", "lon"]] = np.nan
    return c[["soilSampleID", "plotID", "date", "core_x_m", "core_y_m", "lat", "lon"]].reset_index(drop=True)


def load_events() -> pd.DataFrame:
    return pd.read_parquet(PROCESSED / "events.parquet")


def load_geometry() -> pd.DataFrame:
    return pd.read_parquet(PROCESSED / "plot_geometry.parquet")


def build_all() -> dict[str, pd.DataFrame]:
    """Read the processed biology tables, write events / plot_geometry / event_cores to data/processed."""
    mg = pd.read_parquet(PROCESSED / "metagenomes.parquet")
    its = pd.read_parquet(PROCESSED / "its_genus.parquet")
    chem = pd.read_parquet(PROCESSED / "neon_chem.parquet")
    ev = light_filter(build_events(mg, its, chem)).reset_index(drop=True)   # light mode: its plots only
    geom = plot_geometry(ev["plotID"].unique())
    out = {"events": ev, "plot_geometry": geom}
    f = RAW / "neon" / "DP1.10086.001" / "sls_soilCoreCollection.parquet"
    if f.exists():
        cp = core_points(pd.read_parquet(f), geom)
        cp = assign_events(cp).drop(columns=["event_date"])
        out["event_cores"] = cp[cp["event_id"].isin(set(ev["event_id"]))].reset_index(drop=True)
    for name, df in out.items():
        df.to_parquet(PROCESSED / f"{name}.parquet", index=False)
    return out
