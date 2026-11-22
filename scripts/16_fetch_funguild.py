"""Download FUNGuild (fungal ecological guilds) and write data/processed/fungal_guilds.parquet.

Network once (about 7.5 MB, keyless), then cached under data/raw/kb/funguild/. Used by the GUI's soil-functions
view to describe what the fungi of a sample do. Run from the repo root: .venv/bin/python scripts/16_fetch_funguild.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import pandas as pd  # noqa: E402

from cropfit import funguild  # noqa: E402
from cropfit.config import PROCESSED  # noqa: E402

if __name__ == "__main__":
    t = funguild.fetch()
    print(f"fungal_guilds: {len(t)} genera; categories: {t['category'].value_counts().to_dict()}")
    its = PROCESSED / "its_genus.parquet"
    if its.exists():
        g = pd.read_parquet(its)
        g = g[g["genus"] != "unclassified_Fungi"]
        w = g.groupby("genus")["rel_abund_pct"].sum()
        hit = w.index.isin(t["genus"])
        print(f"NEON ITS genera: {len(w)}, with a guild: {hit.sum()} "
              f"({100 * w[hit].sum() / w.sum():.0f}% of their summed share)")
