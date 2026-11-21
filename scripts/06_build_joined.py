#!/usr/bin/env python3
"""Join NMDC metagenomes (bacteria, genes), NEON ITS (fungi) and NEON soil chemistry, one row per metagenome.

Run after 02b_build_neon_features.py and 05_build_biology.py (offline).

A NEON metagenome is a composite of up to 3 cores; NMDC lists those cores as its biosamples
(`biosample_names`). Fungal ITS is per core, so each metagenome gets the MEAN of per-core genus shares over
exactly its own cores that pass NEON's read check (sequenceCountQF != "Below threshold"). The core list is
checked against NEON's pooling table (sls_metagenomicsPooling) in `pooling_check`.

Outputs (data/processed/):
- joined_metagenomes.parquet  one row per metagenome: metagenomes.parquet columns, pooling check, NEON chemistry
  (plot-date mean, +-3 days, prefix neon_), KO panel function groups per genome equivalent (ko_<group>),
  Kraken2 shares of bacterial genera (bac_share_<genus>), fungal coverage (n_fungal_cores_ok, fungal_products,
  fungal_reads) and fungal shares of neon.GENERA + Rhizoctonia_complex (fun_share_<genus>, % of fungal reads).
- joined_fungi_genus.parquet  long: metagenome_key, genus, rel_abund_pct (all genera, metagenomes with fungi).

Caveats: fungal_products mixes two NEON pipelines (.002 current, .001 old) that are not directly comparable;
gene groups are only meaningful where ko_depth_ok.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cropfit import neon, nmdc as N  # noqa: E402
from cropfit.config import PROCESSED  # noqa: E402


def main() -> None:
    mg = pd.read_parquet(PROCESSED / "metagenomes.parquet")
    cores = mg[["metagenome_key", "biosample_names"]].assign(
        soilSampleID=mg["biosample_names"].str.split("|")).explode("soilSampleID")[["metagenome_key", "soilSampleID"]]

    # ---- pooling check against NEON's own core -> composite table
    pool = pd.read_parquet(PROCESSED / "neon_metagenome_pooling.parquet")
    comp_cores = pool.groupby("genomicsSampleID")["soilSampleID"].agg(frozenset)
    c = cores.merge(pool[["soilSampleID", "genomicsSampleID"]], on="soilSampleID", how="left")

    def check(sub: pd.DataFrame) -> pd.Series:
        comps = set(sub["genomicsSampleID"].dropna())
        if not comps:
            return pd.Series({"genomicsSampleID": None, "pooling_check": "no_pooling_record"})
        if len(comps) == 1 and comp_cores[next(iter(comps))] == frozenset(sub["soilSampleID"]):
            return pd.Series({"genomicsSampleID": next(iter(comps)), "pooling_check": "match"})
        return pd.Series({"genomicsSampleID": ";".join(sorted(comps)), "pooling_check": "mismatch"})
    pc = c.groupby("metagenome_key")[["soilSampleID", "genomicsSampleID"]].apply(check).reset_index()
    out = mg.merge(pc, on="metagenome_key", how="left")

    # ---- NEON chemistry by plot + date (+-3 days)
    chem = pd.read_parquet(PROCESSED / "neon_chem.parquet")
    chem = chem.drop(columns=["site"]).rename(columns=lambda x: x if x == "plotID" else f"neon_{x}")
    out["_date"] = pd.to_datetime(out["date"]).astype("datetime64[ns]")
    chem["_cdate"] = pd.to_datetime(chem["neon_collectDate"]).astype("datetime64[ns]")
    out = pd.merge_asof(out.sort_values("_date"), chem.sort_values("_cdate"), left_on="_date",
                        right_on="_cdate", by="plotID", tolerance=pd.Timedelta("3D"), direction="nearest")
    out = out.drop(columns=["_date", "_cdate"])

    # ---- genes (KO panel groups) and bacterial genera
    panel = pd.read_parquet(PROCESSED / "ko_panel.parquet")
    grp = (panel.groupby(["metagenome_key", "function_group"])["per_genome_eq"].sum(min_count=1)
           .unstack().add_prefix("ko_"))
    out = out.merge(grp, left_on="metagenome_key", right_index=True, how="left")
    taxa = pd.read_parquet(PROCESSED / "taxa_genus.parquet")
    kg = (taxa[taxa["source"] == "kraken2"].pivot_table(index="metagenome_key", columns="genus",
                                                        values="pct_of_bacteria", aggfunc="sum"))
    for g in N.BIO_GENERA:
        out[f"bac_share_{g}"] = out["metagenome_key"].map(kg[g]).fillna(0.0) if g in kg else 0.0
        out.loc[~out["has_kraken"], f"bac_share_{g}"] = pd.NA

    # ---- fungi: mean per-core share over the metagenome's own QC-passing cores
    core = pd.read_parquet(PROCESSED / "its_core_genus.parquet")
    core_any = core.drop_duplicates("soilSampleID")[["soilSampleID", "dnaSampleID", "product",
                                                     "sequenceCountQF", "total_reads"]]
    ok_cores = core_any[core_any["sequenceCountQF"] != "Below threshold"]
    m_any = cores.merge(core_any, on="soilSampleID")
    m_ok = cores.merge(ok_cores, on="soilSampleID")
    cov = pd.DataFrame({
        "n_fungal_cores_any": m_any.groupby("metagenome_key")["soilSampleID"].nunique(),
        "n_fungal_cores_ok": m_ok.groupby("metagenome_key")["soilSampleID"].nunique(),
        "fungal_reads": m_ok.groupby("metagenome_key")["total_reads"].sum(),
        "fungal_products": m_ok.groupby("metagenome_key")["product"].agg(lambda s: ";".join(sorted(set(s)))),
    })
    out = out.merge(cov, left_on="metagenome_key", right_index=True, how="left")
    out[["n_fungal_cores_any", "n_fungal_cores_ok"]] = out[["n_fungal_cores_any", "n_fungal_cores_ok"]].fillna(0).astype(int)

    shares = core[core["soilSampleID"].isin(ok_cores["soilSampleID"])][["soilSampleID", "genus", "share_pct"]]
    sw = shares.pivot_table(index="soilSampleID", columns="genus", values="share_pct", aggfunc="sum", fill_value=0.0)
    fung = m_ok[["metagenome_key", "soilSampleID"]].merge(sw, left_on="soilSampleID", right_index=True)
    fung = fung.drop(columns="soilSampleID").groupby("metagenome_key").mean()  # equal weight per core
    long = (fung.reset_index().melt(id_vars="metagenome_key", var_name="genus", value_name="rel_abund_pct"))
    long = long[long["rel_abund_pct"] > 0].sort_values(["metagenome_key", "genus"]).reset_index(drop=True)
    for g in neon.GENERA:
        out[f"fun_share_{g}"] = out["metagenome_key"].map(fung[g]).fillna(0.0) if g in fung else 0.0
    out["fun_share_Rhizoctonia_complex"] = out[[f"fun_share_{g}" for g in neon.RHIZ]].sum(axis=1)
    no_fungi = out["n_fungal_cores_ok"] == 0
    out.loc[no_fungi, [c for c in out.columns if c.startswith("fun_share_")]] = pd.NA

    out = out.sort_values(["site", "plotID", "date"]).reset_index(drop=True)
    out.to_parquet(PROCESSED / "joined_metagenomes.parquet", index=False)
    long.to_parquet(PROCESSED / "joined_fungi_genus.parquet", index=False)

    s = out.assign(fungi=out["n_fungal_cores_ok"] > 0)
    print(s.groupby(["site", "year"]).agg(metagenomes=("metagenome_key", "size"), with_fungi=("fungi", "sum"),
                                          depth_ok=("ko_depth_ok", "sum"),
                                          depth_ok_and_fungi=("fungi", lambda x: (x & s.loc[x.index, "ko_depth_ok"]).sum())))
    print("pooling_check:", out["pooling_check"].value_counts(dropna=False).to_dict())
    print(f"wrote joined_metagenomes ({len(out)} x {out.shape[1]}), joined_fungi_genus ({len(long)} rows, "
          f"{long.metagenome_key.nunique()} metagenomes, {long.genus.nunique()} genera)")


if __name__ == "__main__":
    main()
