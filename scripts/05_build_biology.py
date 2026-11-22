#!/usr/bin/env python3
"""Build soil-DNA (NMDC) tables from data/nmdc into data/processed/."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cropfit import nmdc as N  # noqa: E402
from cropfit.config import PROCESSED, RULES  # noqa: E402


def main() -> None:
    samples = N.load_samples()
    paths = N.object_paths()
    panel = N.load_panel()
    print(f"panel source: {'rules/ko_panel.csv' if (RULES / 'ko_panel.csv').exists() else 'built-in default'}")
    for c in N.CHEM_COLS:
        samples[c] = pd.to_numeric(samples[c], errors="coerce")

    # ---- metagenomes
    g = samples.groupby("metagenome_key")
    mg = g.agg(site=("site", "first"), plotID=("plotID", "first"), date=("date", "max"),
               n_biosamples=("name", "size"), biosample_names=("name", lambda x: "|".join(sorted(x))),
               **{v: (k, "mean") for k, v in N.CHEM_COLS.items()}).reset_index()
    mg["year"] = mg["date"].str[:4].astype(int)

    ko_rows, all_rows, kraken_info, tax_rows, lin_rows = [], [], {}, [], []
    panel_kos = set(panel["ko"])
    markers = list(panel.loc[panel["function_group"] == "marker", "ko"])
    stats = {}
    for key in mg["metagenome_key"]:
        files = paths.get(key, {})
        kofile = files.get("Annotation KEGG Orthology")
        if kofile:
            c = N.parse_ko_counts(kofile)
            n = sum(c.values())
            mm = float(np.mean([c.get(k, 0) for k in markers]))
            stats[key] = (n, mm)
            all_rows += [(key, k, v) for k, v in c.items()]
            for r in panel.itertuples():
                cnt = c.get(r.ko, 0)
                ko_rows.append((key, r.ko, r.gene, r.function_group, cnt,
                                cnt / mm if mm > 0 else np.nan, cnt / n * 1e6 if n else np.nan))
        kfile = files.get("Kraken2 Classification Report")
        if kfile:
            rep = N.parse_kraken_report(kfile)
            kraken_info[key] = N.kraken_summary(rep)
            kg = N.kraken_genus(rep); kg["source"] = "kraken2"; kg["metagenome_key"] = key
            tax_rows.append(kg)
            kl = N.kraken_lineage(rep); kl.insert(0, "metagenome_key", key)
            lin_rows.append(kl)
        gfile = files.get("GOTTCHA2 Report Full")
        if gfile:
            gg = N.gottcha_genus(gfile); gg["source"] = "gottcha2"; gg["metagenome_key"] = key
            tax_rows.append(gg)

    mg["n_ko_genes"] = mg["metagenome_key"].map(lambda k: stats.get(k, (np.nan, np.nan))[0])
    mg["marker_mean"] = mg["metagenome_key"].map(lambda k: stats.get(k, (np.nan, np.nan))[1])
    mg["ko_depth_ok"] = [N.depth_gate(a, b) for a, b in zip(mg["n_ko_genes"], mg["marker_mean"])]
    for col in ("kraken_total_reads", "kraken_bacteria_reads", "kraken_unclassified_pct"):
        mg[col] = mg["metagenome_key"].map(lambda k, col=col: kraken_info.get(k, {}).get(col, np.nan))
    mg["has_kraken"] = mg["metagenome_key"].isin(kraken_info)
    mg = mg.sort_values(["site", "plotID", "date"]).reset_index(drop=True)

    ko_panel = pd.DataFrame(ko_rows, columns=["metagenome_key", "ko", "gene", "function_group",
                                              "count", "per_genome_eq", "per_million"])
    ko_all = pd.DataFrame(all_rows, columns=["metagenome_key", "ko", "count"])
    taxa = pd.concat(tax_rows, ignore_index=True)[
        ["metagenome_key", "source", "genus", "reads", "pct_of_bacteria", "filtered"]]
    mg.to_parquet(PROCESSED / "metagenomes.parquet", index=False)
    ko_panel.to_parquet(PROCESSED / "ko_panel.parquet", index=False)
    ko_all.to_parquet(PROCESSED / "ko_counts_all.parquet", index=False)
    taxa.to_parquet(PROCESSED / "taxa_genus.parquet", index=False)
    lineage = pd.concat(lin_rows, ignore_index=True)
    lineage.to_parquet(PROCESSED / "taxa_lineage.parquet", index=False)

    # ---- per-metagenome metrics (time series) and plot_biology (latest)
    ts = mg[["metagenome_key", "site", "plotID", "year", "date", "ko_depth_ok", "has_kraken"]].copy()
    ts = ts.rename(columns={"date": "bio_metagenome_date", "ko_depth_ok": "bio_ko_depth_ok"})
    ok = ts["bio_ko_depth_ok"]
    gsum = (ko_panel.groupby(["metagenome_key", "function_group"])["per_genome_eq"].sum(min_count=1)
            .unstack())
    gcount = (ko_panel.groupby(["metagenome_key", "function_group"])["count"].sum().unstack())
    MIN_GROUP_GENES = 20  # per site-year, summed over depth-ok metagenomes
    for grp in N.BIO_GROUPS:
        raw = ts["metagenome_key"].map(gsum[grp]) if grp in gsum else pd.Series(np.nan, index=ts.index)
        cnt = ts["metagenome_key"].map(gcount[grp]) if grp in gcount else pd.Series(0, index=ts.index)
        ts[f"bio_raw_{grp}"] = raw
        ts[f"bio_count_{grp}"] = cnt.fillna(0)
        # Gate: a percentile among ties of zeros (or a handful of genes) is meaningless.
        status = pd.Series("insufficient_depth", index=ts.index)
        usable = pd.Series(False, index=ts.index)
        for _, idx in ts[ok].groupby(["site", "year"]).groups.items():
            tot = ts.loc[idx, f"bio_count_{grp}"].sum()
            if tot == 0:
                status.loc[idx] = "not_detected"
            elif tot < MIN_GROUP_GENES or ts.loc[idx, f"bio_raw_{grp}"].nunique() < 2:
                status.loc[idx] = "too_few_genes"
            else:
                status.loc[idx] = "ok"
                usable.loc[idx] = True
        ts[f"bio_status_{grp}"] = status
        ts[f"bio_pct_{grp}"], n = N.pct_within(ts, f"bio_raw_{grp}", mask=ok & usable)
        ts[f"bio_pct_n_{grp}"] = n
    ts["bio_pct_n"] = ts[f"bio_pct_n_{N.BIO_GROUPS[0]}"]
    ts = ts.drop(columns=[f"bio_pct_n_{x}" for x in N.BIO_GROUPS])
    kg = taxa[taxa["source"] == "kraken2"].pivot_table(index="metagenome_key", columns="genus",
                                                       values="pct_of_bacteria", aggfunc="sum")
    for ge in N.BIO_GENERA:
        share = ts["metagenome_key"].map(kg[ge]) if ge in kg else pd.Series(np.nan, index=ts.index)
        share = share.fillna(0.0).where(ts["has_kraken"])
        ts[f"bio_genus_share_{ge}"] = share
        ts[f"bio_genus_pct_{ge}"], _ = N.pct_within(ts, f"bio_genus_share_{ge}", mask=ts["has_kraken"])
    ts = ts.drop(columns=["has_kraken"])
    ts.to_parquet(PROCESSED / "plot_biology_timeseries.parquet", index=False)

    have = ts[ts["metagenome_key"].isin(set(kraken_info) | set(stats))]
    latest = have.sort_values("bio_metagenome_date").groupby("plotID").tail(1).sort_values("plotID")
    latest.to_parquet(PROCESSED / "plot_biology.parquet", index=False)

    # ---- summary
    print(mg.groupby(["site", "year"]).agg(n=("metagenome_key", "size"), depth_ok=("ko_depth_ok", "sum")))
    print(f"wrote {len(mg)} metagenomes, {len(ko_panel)} panel rows, {len(ko_all)} all-KO rows, "
          f"{len(taxa)} taxa rows, {len(lineage)} lineage rows, {len(latest)} plots")


if __name__ == "__main__":
    main()
