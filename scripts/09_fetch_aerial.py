"""Fetch aerial photos for every plot of the event registry: NAIP and the NEON airborne camera.
Writes chips + previews under data/raw/imagery/<source>/<plot>/ and data/processed/plot_aerial.parquet.

Usage: 09_fetch_aerial.py [naip] [aop] [--retry PLOT:YYYY-MM ...]   (default: both; aop needs the NEON token)
A source that ran replaces its own rows in plot_aerial.parquet; the other source's rows are kept.
--retry refetches only the named NEON camera chips (and those with empty statistics) and keeps the rest.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import pandas as pd
from cropfit import aerial, events, stac
from cropfit.config import PROCESSED

if __name__ == "__main__":
    which = [a for a in sys.argv[1:] if a in ("naip", "aop")] or ["naip", "aop"]
    geom = events.load_geometry()
    out = PROCESSED / "plot_aerial.parquet"
    have = pd.read_parquet(out) if out.exists() else pd.DataFrame(columns=["source"])
    retry = None
    if "--retry" in sys.argv:
        which = ["aop"]
        retry = {tuple(a.split(":")) for a in sys.argv[sys.argv.index("--retry") + 1:] if ":" in a}
        bad = have[(have["source"] == "neon_aop_camera") & have["exg_mean"].isna()]
        retry |= {(r.plotID, f"{r.date:%Y-%m}") for r in bad.itertuples()}
        print(f"retrying {len(retry)} NEON camera chips", flush=True)
    for w in which:
        rows, failed = aerial.fetch_naip(geom) if w == "naip" else aerial.fetch_aop_camera(geom, only=retry)
        src = "naip" if w == "naip" else "neon_aop_camera"
        if retry is not None and len(rows):      # keep every chip that was not retried
            old = have[have["source"] == src]
            redone = set(zip(rows["plotID"], rows["date"]))
            rows = pd.concat([old[[k not in redone for k in zip(old["plotID"], old["date"])]], rows], ignore_index=True)
        print(f"{src}: {len(rows)} plot-flights, {len(failed)} failed", flush=True)
        for f in failed[:10]:
            print("   FAILED", *f)
        if len(rows):
            stac.write_manifest(f"imagery/{src}", rows[["plotID", "source", "date", "item_id", "gsd_m"]])
            have = pd.concat([have[have["source"] != src], rows], ignore_index=True)
    have = have.sort_values(["plotID", "date", "source"]).reset_index(drop=True)
    have.to_parquet(out, index=False)
    print(have.groupby(["source", have["date"].dt.year]).size().unstack(0).fillna(0).astype(int).to_string())
