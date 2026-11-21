"""E3 (approximate): fungal qPCR copies x ITS genus relative abundance, Fusarium & Macrophomina, per plot-date."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from cropfit.config import OUTPUTS, PROCESSED

out = OUTPUTS / "e3"; out.mkdir(parents=True, exist_ok=True)
its = pd.read_parquet(PROCESSED / "its_genus.parquet")
its = its[its.genus.isin(["Fusarium", "Macrophomina"])].copy()
its["collectDate"] = pd.to_datetime(its.collectDate)
q = pd.read_parquet(PROCESSED / "neon_qpcr.parquet")
q["collectDate"] = pd.to_datetime(q.collectDate)
q = q[q.fungal_copies.notna()]

rows = []
for _, r in its[its.genus == "Fusarium"].drop_duplicates(["plotID", "collectDate"]).iterrows():
    c = q[q.plotID == r.plotID].copy()
    c["dd"] = (c.collectDate - r.collectDate).abs().dt.days
    c = c[c.dd <= 3].sort_values("dd")
    if len(c):
        rows.append(dict(site=r.site, plotID=r.plotID, its_date=r.collectDate, qpcr_date=c.iloc[0].collectDate,
                         day_offset=int(c.iloc[0].dd), fungal_copies=c.iloc[0].fungal_copies))
m = pd.DataFrame(rows)
n_its = its.drop_duplicates(["plotID", "collectDate"]).shape[0]
print(f"ITS plot-dates {n_its}; matched to qPCR (<=3 d): {len(m)}; exact same day: {(m.day_offset==0).sum() if len(m) else 0}")
if m.empty:
    sys.exit("no ITS/qPCR matches")
t = m.merge(its.rename(columns={"collectDate": "its_date"}), on=["site", "plotID", "its_date"])
t["approx_genus_load"] = t.fungal_copies * t.rel_abund_pct / 100
t = t[["site", "plotID", "its_date", "qpcr_date", "day_offset", "genus", "reads", "total_reads", "rel_abund_pct",
       "fungal_copies", "approx_genus_load"]]
t["unit"] = "ITS copies per ng DNA x relative share (approximate)"
t.to_csv(out / "e3_table.csv", index=False)
print(t.groupby(["site", "genus"]).approx_genus_load.describe().round(1).to_string())

fig, ax = plt.subplots(1, 2, figsize=(10, 4.2))
for g, a in zip(["Fusarium", "Macrophomina"], ax):
    s = t[(t.genus == g) & (t.site == "STER")]
    a.scatter(s.rel_abund_pct, s.approx_genus_load.clip(lower=0.01), c="#1f77b4", alpha=.7)
    a.set_yscale("symlog", linthresh=1)
    a.set_title(f"{g}  (n={len(s)} plot-dates, STER {s.its_date.dt.year.min() if len(s) else ''}-{s.its_date.dt.year.max() if len(s) else ''})")
    a.set_xlabel("relative abundance in ITS fungal reads (%)")
    a.set_ylabel("approx. load = fungal ITS copies/ng DNA x share")
fig.suptitle("Approximate; ITS copy number varies across taxa; relative x total", fontsize=10, color="firebrick")
fig.tight_layout()
fig.savefig(out / "fig_e3_scaled.png", dpi=150)
