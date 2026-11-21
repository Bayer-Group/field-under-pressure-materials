"""Fetch greenness maps (Sentinel-2 NDVI, 10 m, 1 km around each plot) for every clear Sentinel-2 date of
plot_vi_timeseries. Writes chips under data/raw/imagery/s2_ndvi/<plot>/ and data/processed/plot_ndvi_maps.parquet.

Usage: 13_fetch_ndvi_maps.py [--workers N] [--limit N_SCENES]      (after 08_fetch_satellite.py)
Network (Planetary Computer, keyless). Resumable: chips already on disk are not fetched again.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import pandas as pd
from cropfit import events, ndvimap
from cropfit.config import PROCESSED, ROOT

if __name__ == "__main__":
    args = sys.argv[1:]
    workers = int(args[args.index("--workers") + 1]) if "--workers" in args else 8
    limit = int(args[args.index("--limit") + 1]) if "--limit" in args else None
    ts = pd.read_parquet(PROCESSED / "plot_vi_timeseries.parquet")
    out = PROCESSED / "plot_ndvi_maps.parquet"
    have = pd.read_parquet(out) if out.exists() else pd.DataFrame(columns=["plotID", "date", "chip"])
    rows, failed = ndvimap.fetch(events.load_geometry(), ts, workers=workers, limit=limit)
    print(f"{len(rows)} new maps; {len(failed)} scenes failed{' (re-run to retry)' if failed else ''}", flush=True)
    for f in failed[:10]:
        print("   FAILED", *f)
    allrows = pd.concat([have, rows], ignore_index=True).drop_duplicates(["plotID", "date"], keep="last")
    allrows = allrows[allrows["chip"].map(lambda c: (ROOT / c).exists())]
    allrows = allrows.sort_values(["plotID", "date"]).reset_index(drop=True)
    allrows.to_parquet(out, index=False)
    n_want = len(ndvimap.wanted(ts))
    print(f"plot_ndvi_maps: {len(allrows)} of {n_want} wanted maps on {allrows.plotID.nunique()} plots")
