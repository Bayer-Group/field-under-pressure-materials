"""Build plots.parquet, plot_crop_history.parquet, plot_climate_yearly.parquet and plot_weather_daily.parquet
for the plots of the event registry (run scripts/01_build_events.py first).

Network: SSURGO (SDA), Daymet, CDL (Planetary Computer); all cached or small. CSB crops (2018-2025) are merged
into the crop history when data/processed/plot_csb.parquet exists (scripts/04_build_fields.py)."""
from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cropfit import cdl, daymet, events, ssurgo  # noqa: E402
from cropfit.config import PROCESSED, RESOURCES  # noqa: E402

START, END = 2008, 2025


def load_plots() -> pd.DataFrame:
    """Plots that have sampling events (not the outdated NLCD 2001 'cultivatedCrops' label)."""
    g = events.load_geometry()
    return (g.rename(columns={"plotID": "unit_id"}).assign(unit_type="plot")
            [["unit_id", "unit_type", "site", "lat", "lon"]].reset_index(drop=True))


def safe(fn, *a, default=None, label=""):
    try:
        return fn(*a)
    except Exception as e:  # never let one plot block the rest
        print(f"FAIL {label}: {type(e).__name__}: {e}", flush=True)
        return default


def main():
    plots = load_plots()
    print(len(plots), "plots", plots.site.value_counts().to_dict(), flush=True)
    recs = plots.to_dict("records")

    def soil(r):
        return safe(ssurgo.plot_soil, r["lat"], r["lon"], default={}, label=f"soil {r['unit_id']}")

    def clim(r):
        def go():
            df = daymet.fetch_daymet(r["lat"], r["lon"], START - 1, END)
            yc = daymet.yearly_climate(df)
            yc = yc[(yc.year >= START) & (yc.year <= END)]
            full = df.groupby("year")["yday"].max()
            yc = yc[yc.year.map(full) >= 365]
            f = daymet.summarise_yearly(yc)
            f["climate_years_used"] = f"{int(yc.year.min())}-{int(yc.year.max())}"
            return f, yc, df
        return safe(go, default=({}, pd.DataFrame(), pd.DataFrame()), label=f"climate {r['unit_id']}")

    with ThreadPoolExecutor(4) as ex:
        soils = list(ex.map(soil, recs))
    print("soil done", flush=True)
    with ThreadPoolExecutor(4) as ex:
        clims = list(ex.map(clim, recs))
    print("climate done", flush=True)

    hist = cdl.cdl_history_many({r["unit_id"]: (r["lat"], r["lon"]) for r in recs}, range(2008, 2022), workers=6)
    hist.to_parquet(PROCESSED / "plot_crop_history.parquet", index=False)
    print("cdl done", flush=True)

    yearly, daily = [], []
    for r, (f, yc, df) in zip(recs, clims):
        if len(yc):
            yc = yc.copy()
            yc.insert(0, "unit_id", r["unit_id"])
            yearly.append(yc)
        if len(df):
            daily.append(df[["date", "tmax", "tmin", "prcp"]].assign(unit_id=r["unit_id"]))
    if yearly:
        pd.concat(yearly).to_parquet(PROCESSED / "plot_climate_yearly.parquet", index=False)
    if daily:  # daily series, needed for weather windows relative to each sampling date
        pd.concat(daily).to_parquet(PROCESSED / "plot_weather_daily.parquet", index=False)

    rows = []
    for r, s, (f, _, _) in zip(recs, soils, clims):
        row = {**r, **s, **f}
        row["water_supply_summer_mm"] = row.get("prcp_apr_sep_mm", np.nan) + row.get("awc100_mm", np.nan)
        row["water_supply_winter_mm"] = row.get("prcp_oct_jun_mm", np.nan) + row.get("awc100_mm", np.nan)
        rows.append(row)
    out = pd.DataFrame(rows)
    h = hist.pivot(index="unit_id", columns="year", values="crop_group")
    for y in range(2008, 2026):
        out[f"crop_{y}"] = out["unit_id"].map(h[y]) if y in h.columns else np.nan
        if y > 2021:
            out[f"crop_{y}"] = np.nan
    out["history_source"] = "cdl"
    csb_file = PROCESSED / "plot_csb.parquet"
    if csb_file.exists():  # CSB gives 2018-2025; CDL stays the source where both exist
        c = pd.read_parquet(csb_file).set_index("plotID")
        for y in range(2018, 2026):
            if f"crop_{y}" in c:
                cdl_ok = out[f"crop_{y}"].notna() & (out[f"crop_{y}"] != "unknown")
                out[f"crop_{y}"] = out[f"crop_{y}"].where(cdl_ok, out["unit_id"].map(c[f"crop_{y}"]))
        out["history_source"] = np.where(out["unit_id"].isin(c.index[c["CSBID"].notna()]), "csb+cdl", "cdl")
    else:
        print("no plot_csb.parquet: crop history ends in 2021 (CDL only)", flush=True)
    for k in range(1, 6):
        out[f"crop_t{k}"] = out[f"crop_{2026 - k}"]
    out.to_parquet(PROCESSED / "plots.parquet", index=False)
    print("wrote", out.shape, flush=True)


if __name__ == "__main__":
    main()
