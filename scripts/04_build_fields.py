"""Build data/processed/fields.parquet (CSB fields + SSURGO + Daymet) and plot_csb.parquet."""
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import geopandas as gpd
import numpy as np
import pandas as pd

from cropfit import csb, fields
from cropfit.config import PROCESSED, RESOURCES

MIN_HA = 2.0


def build_fields() -> gpd.GeoDataFrame:
    parts = []
    for site in csb.SITES:
        f = csb.load_window_fields(site)
        f = f[f["area_ha"] >= MIN_HA].reset_index(drop=True)
        print(site, "fields >=2ha:", len(f), flush=True)
        parts.append(fields.add_soil(f, site))
    g = pd.concat(parts, ignore_index=True)
    g = gpd.GeoDataFrame(g, geometry="geometry", crs="EPSG:5070")

    # climate on a 2 km grid
    try:
        from cropfit import daymet
        snaps = [daymet.snap_to_grid(a, b, 2.0) for a, b in zip(g["lat"], g["lon"])]
        g["grid_lat"], g["grid_lon"] = [s[0] for s in snaps], [s[1] for s in snaps]
        pts = sorted(set(snaps))
        print("daymet grid points:", len(pts), flush=True)

        def one(p):
            for _ in range(3):
                try:
                    return p, daymet.climate_features(p[0], p[1], 2008, 2025)
                except Exception as e:  # noqa: BLE001
                    err = e
                    time.sleep(3)
            print("daymet failed", p, err, flush=True)
            return p, {}

        with ThreadPoolExecutor(4) as ex:
            res = dict(ex.map(one, pts))
        clim = pd.DataFrame([{"grid_lat": p[0], "grid_lon": p[1], **v} for p, v in res.items()])
        g = g.merge(clim, on=["grid_lat", "grid_lon"], how="left")
        g["water_supply_summer_mm"] = g["prcp_apr_sep_mm"] + g["awc100_mm"]
        g["water_supply_winter_mm"] = g["prcp_oct_jun_mm"] + g["awc100_mm"]
    except ImportError:
        print("daymet module missing: written without climate")

    g["geometry"] = g.geometry.simplify(10, preserve_topology=True)
    g = g.to_crs("EPSG:4326")
    g.to_parquet(PROCESSED / "fields.parquet")
    return g


def build_plot_csb() -> pd.DataFrame:
    p = pd.read_csv(RESOURCES / "neon_soil_plots_landcover.csv")
    p = p[(p["site"].isin(csb.SITES)) & (p["nlcd"] == "cultivatedCrops")].copy()
    p["plotID"] = p["plot"].str.replace(".basePlot.bgc", "", regex=False)
    rows = []
    for _, r in p.iterrows():
        d = csb.plot_to_csb(r["lat"], r["lon"]) or {}
        row = {"plotID": r["plotID"], "site": r["site"], "lat": r["lat"], "lon": r["lon"],
               "CSBID": d.get("CSBID")}
        for y in csb.YEARS:
            row[f"crop_{y}"] = d.get(f"crop_{y}")
        rows.append(row)
    df = pd.DataFrame(rows)
    df.to_parquet(PROCESSED / "plot_csb.parquet")
    return df


if __name__ == "__main__":
    g = build_fields()
    print(g.groupby("site").size())
    for s, x in g.groupby("site"):
        print(s, x["crop_2025"].value_counts().head(8).to_dict())
    pc = build_plot_csb()
    print("plots:", len(pc), "in CSB:", pc["CSBID"].notna().sum())
    cols = ["plotID", "CSBID"] + [f"crop_{y}" for y in csb.YEARS]
    print(pc[cols].to_string())
