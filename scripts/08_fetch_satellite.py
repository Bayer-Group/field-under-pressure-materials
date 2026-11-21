"""Fetch Sentinel-2 and Landsat observations for every plot of the event registry and build
plot_vi_timeseries.parquet (plot x date x sensor) and plot_season.parquet (plot x year).

Usage: 08_fetch_satellite.py [sentinel2] [landsat] [--workers N]
Network (Planetary Computer, keyless). Resumable: each scene is stored once under data/raw/satellite/.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cropfit import events, satellite
from cropfit.config import PROCESSED

if __name__ == "__main__":
    args = sys.argv[1:]
    workers = int(args[args.index("--workers") + 1]) if "--workers" in args else 12
    sensors = [a for a in args if a in satellite.SENSORS] or list(satellite.SENSORS)
    geom = events.load_geometry()
    for s in sensors:
        obs, failed = satellite.fetch(s, geom, workers=workers)
        print(f"{s}: {len(obs)} plot-observations from {obs.item_id.nunique() if len(obs) else 0} scenes; "
              f"{len(failed)} scenes failed{' (re-run to retry)' if failed else ''}", flush=True)
    ts = satellite.timeseries(satellite.load_observations())
    ts.to_parquet(PROCESSED / "plot_vi_timeseries.parquet", index=False)
    season = satellite.season_metrics(ts)
    season.to_parquet(PROCESSED / "plot_season.parquet", index=False)
    print(f"plot_vi_timeseries: {len(ts)} rows, {int(ts.clear.sum())} clear; plot_season: {len(season)} plot-years")
    print(ts[ts.clear].groupby(["sensor", ts.date.dt.year]).size().unstack(0).fillna(0).astype(int).to_string())
