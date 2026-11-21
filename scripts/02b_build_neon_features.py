"""Rebuild all NEON processed tables from data/raw/neon/ (no network)."""
import glob
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import pandas as pd
from cropfit import neon
from cropfit.config import PROCESSED, RAW

R = RAW / "neon"

# ---- ITS
raw = neon.load_its_raw()          # DP1.10081.002 + .001, one run per DNA sample, .002 preferred
core = neon.build_its_core(raw)    # per core, all cores (QC flag kept)
core.to_parquet(PROCESSED / "its_core_genus.parquet", index=False)
print("its_core_genus", len(core), "rows,", core.dnaSampleID.nunique(), "cores,",
      core.groupby("product").dnaSampleID.nunique().to_dict())
pool = neon.pooling_map()
pool.to_parquet(PROCESSED / "neon_metagenome_pooling.parquet", index=False)
print("neon_metagenome_pooling", len(pool), "cores in", pool.genomicsSampleID.nunique(), "composites")
g = neon.build_its_genus(raw)      # plot-date, QC-passing cores, mean of per-core shares
p = raw["dnaSampleID"].map(neon.parse_sample_id)
cores = raw[p.map(bool)].drop_duplicates("dnaSampleID").copy()
cores["plotID"] = p[cores.index].map(lambda d: d["plotID"])
cores["collectDate"] = p[cores.index].map(lambda d: d["date"].date())
cores["_bt"] = (cores["sequenceCountQF"] == "Below threshold").astype(float)
bt = cores.groupby(["plotID", "collectDate"])["_bt"].mean().rename("its_below_threshold_share").reset_index()
g = g.merge(bt, on=["plotID", "collectDate"], how="left")
g.to_parquet(PROCESSED / "its_genus.parquet", index=False)
ts = neon.plot_its_timeseries(g)
ts = ts.merge(bt, on=["plotID", "collectDate"], how="left")
ts.to_parquet(PROCESSED / "plot_its_timeseries.parquet", index=False)
neon.plot_its_latest(ts).to_parquet(PROCESSED / "plot_its.parquet", index=False)
print("its_genus", len(g), "timeseries", len(ts), "plot_its", ts.plotID.nunique())

# ---- chemistry
t = {os.path.basename(f)[:-8]: pd.read_parquet(f) for f in glob.glob(str(R / "DP1.10086.001" / "sls_*.parquet"))}
chem = neon.build_chem(t)
chem.to_parquet(PROCESSED / "neon_chem.parquet", index=False)
print("neon_chem", len(chem))

# ---- qPCR
q = pd.read_parquet(R / "DP1.10109.001" / "mga_soilGroupAbundances.parquet")
q["collectDate"] = pd.to_datetime(q.collectDate).dt.tz_localize(None).dt.normalize()
q["meanCopyNumber"] = pd.to_numeric(q.meanCopyNumber, errors="coerce")
w = q[q.targetTaxonGroup.isin(["fungi", "bacteria", "archaea"])].pivot_table(
    index=["siteID", "plotID", "collectDate", "dnaSampleID"], columns="targetTaxonGroup",
    values="meanCopyNumber", aggfunc="mean").reset_index()
for c in ("fungi", "bacteria", "archaea"):
    if c not in w:
        w[c] = float("nan")
out = w.groupby(["siteID", "plotID", "collectDate"]).agg(
    fungal_copies=("fungi", "mean"), bacterial_copies=("bacteria", "mean"), archaeal_copies=("archaea", "mean"),
    n_cores=("dnaSampleID", "nunique"), n_cores_fungal=("fungi", "count")).reset_index().rename(columns={"siteID": "site"})
out["unit"] = "gene copies per ng extracted DNA (NEON meanCopyNumber, numberPerNanogram; NOT per g soil)"
out["collectDate"] = out.collectDate.dt.date
out.to_parquet(PROCESSED / "neon_qpcr.parquet", index=False)
print("neon_qpcr", len(out))
