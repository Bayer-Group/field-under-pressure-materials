"""Scan the event table for associations between microbiome columns and environmental columns, of any shape
(monotonic or with an optimum), within site x year batches. Offline, ~ a few minutes.

Writes data/processed/association_scan.parquet; method and reading guide in cropfit/assoc.py.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import pandas as pd
from cropfit import assoc
from cropfit.config import PROCESSED

if __name__ == "__main__":
    t = pd.read_parquet(PROCESSED / "event_table.parquet")
    res = assoc.scan(t)
    res.to_parquet(PROCESSED / "association_scan.parquet", index=False)
    print(f"{len(res)} pairs tested ({len(assoc.responses(t))} responses x {len(assoc.predictors(t))} predictors, 3 scopes)")
    print(res.groupby("scope").agg(pairs=("p", "size"), q05=("q", lambda q: int((q < 0.05).sum())),
                                   q10=("q", lambda q: int((q < 0.10).sum())),
                                   humps=("shape", lambda s: int((s == "hump").sum()))).to_string())
    cols = ["scope", "response", "predictor", "timing", "n_adj", "rho_adj", "dcor_adj", "p", "q", "shape", "turning_point",
            "rho_within_plot"]
    pd.set_option("display.width", 250, "display.max_colwidth", 46)
    print(res[cols].head(25).round(3).to_string(index=False))
