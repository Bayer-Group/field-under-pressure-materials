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
lin = neon.its_genus_lineage(raw)  # genus -> phylum, class (for the GUI's fungi composition view)
lin.to_parquet(PROCESSED / "its_genus_lineage.parquet", index=False)
print("its_genus_lineage", len(lin), "genera")

# ---- chemistry
t = {os.path.basename(f)[:-8]: pd.read_parquet(f) for f in glob.glob(str(R / "DP1.10086.001" / "sls_*.parquet"))}
chem = neon.build_chem(t)
chem.to_parquet(PROCESSED / "neon_chem.parquet", index=False)
print("neon_chem", len(chem))

# ---- inorganic N and net N transformation rates (same product, ntr_* tables)
t.update({os.path.basename(f)[:-8]: pd.read_parquet(f) for f in glob.glob(str(R / "DP1.10086.001" / "ntr_*.parquet"))})
if {"ntr_externalLab", "ntr_internalLab", "sls_soilMoisture"} <= set(t):
    inorg = neon.build_inorganic_n(t)
    inorg.to_parquet(PROCESSED / "neon_inorganic_n.parquet", index=False)
    print("neon_inorganic_n", len(inorg), "plot-dates,", int(inorg.n_pairs.gt(0).sum()), "with rates")

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

# ---- management events, baseline soil pits, plant cover (products fetched on request, skipped when absent)
plots = sorted(set(chem.plotID) | set(core.plotID))
f = R / "DP1.10111.001" / "sim_eventData.parquet"
if f.exists():
    mgmt = neon.build_management(pd.read_parquet(f), plots)
    mgmt.to_parquet(PROCESSED / "neon_management_events.parquet", index=False)
    print("neon_management_events", len(mgmt), mgmt.type.value_counts().to_dict())
    # crop of the year as reported by the farm: species of the harvest events of that calendar year
    h = mgmt[(mgmt.type == "harvest") & mgmt.what.notna()].assign(year=lambda d: d.date.dt.year)
    rep = (h.groupby(["plotID", "year"]).agg(crop_species=("what", lambda s: "; ".join(sorted(set(s)))),
                                             harvest_date=("date", "max"), n_reports=("what", "size")).reset_index())
    rep.to_parquet(PROCESSED / "neon_crop_reported.parquet", index=False)
    print("neon_crop_reported", len(rep), "plot-years")
d = R / "DP1.10047.001"
if (d / "spc_biogeochem.parquet").exists():
    base = neon.build_soil_baseline({os.path.basename(x)[:-8]: pd.read_parquet(x) for x in glob.glob(str(d / "spc_*.parquet"))})
    base = base[base.plotID.isin(plots)]
    base.to_parquet(PROCESSED / "neon_soil_baseline.parquet", index=False)
    print("neon_soil_baseline", len(base), "plots")
f = R / "DP1.10058.001" / "div_1m2Data.parquet"
if f.exists():
    cover = neon.build_plant_cover(pd.read_parquet(f))
    cover = cover[cover.plotID.isin(plots)]
    cover.to_parquet(PROCESSED / "neon_plant_cover.parquet", index=False)
    print("neon_plant_cover", len(cover), "plot-surveys on", cover.plotID.nunique(), "plots")
