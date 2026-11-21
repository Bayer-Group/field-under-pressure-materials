"""Export one row per genus to annotate, to data/processed/microbe_taxa.csv.

Reads data/processed/taxa_lineage.parquet (Bacteria/Archaea genus rows from the metagenomes), data/processed/its_genus.parquet
and data/processed/its_genus_lineage.parquet (NEON ITS fungal genera). Columns: domain, genus, phylum, class, reads, n_samples,
abundance_rank (1 = most reads within the group; Bacteria+Archaea form one group, Fungi another). Placeholder names
(unclassified*, *Incertae_sedis*, empty) are dropped. The output feeds the LLM annotation described in
rules/microbe_annotation_prompt.md. Run from the repo root: .venv/bin/python scripts/17_export_microbe_taxa.py
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import pandas as pd  # noqa: E402

from cropfit.config import PROCESSED  # noqa: E402

OUT = PROCESSED / "microbe_taxa.csv"
COLUMNS = ["domain", "genus", "phylum", "class", "reads", "n_samples", "abundance_rank"]


def is_placeholder(v) -> bool:
    if v is None or pd.isna(v):
        return True
    s = str(v).strip()
    return s == "" or "Incertae_sedis" in s or s.lower().startswith("unclassified")


def clean_tax(s: pd.Series) -> pd.Series:
    return s.where(~s.map(is_placeholder), "")


def bacteria_archaea() -> pd.DataFrame:
    t = pd.read_parquet(PROCESSED / "taxa_lineage.parquet")
    t = t[(t["rank"] == "genus") & t["domain"].isin(["Bacteria", "Archaea"])]
    t = t[~t["name"].map(is_placeholder)].copy()
    t["phylum"] = clean_tax(t["phylum"].astype("string").fillna(""))
    t["reads"] = t["reads"].astype("int64")
    g = t.groupby(["domain", "name"], as_index=False).agg(
        phylum=("phylum", lambda x: next((v for v in x if v), "")),
        reads=("reads", "sum"),
    )
    n = t[t["reads"] > 0].groupby(["domain", "name"])["metagenome_key"].nunique().rename("n_samples")
    g = g.merge(n, on=["domain", "name"], how="left")
    g["n_samples"] = g["n_samples"].fillna(0).astype("int64")
    g["class"] = ""
    return g.rename(columns={"name": "genus"})


def fungi() -> pd.DataFrame:
    f = pd.read_parquet(PROCESSED / "its_genus.parquet")
    f = f[~f["genus"].map(is_placeholder)].copy()
    f["reads"] = f["reads"].round().astype("int64")
    lin = pd.read_parquet(PROCESSED / "its_genus_lineage.parquet")[["genus", "phylum", "class"]]
    lin = lin.drop_duplicates("genus")
    lin["phylum"] = clean_tax(lin["phylum"].astype("string").fillna(""))
    lin["class"] = clean_tax(lin["class"].astype("string").fillna(""))
    g = f.groupby("genus", as_index=False)["reads"].sum()
    pos = f[f["reads"] > 0].groupby("genus")[["plotID", "collectDate"]].apply(
        lambda d: len(d.drop_duplicates())
    )
    g["n_samples"] = g["genus"].map(pos).fillna(0).astype("int64")
    g = g.merge(lin, on="genus", how="left")
    g["phylum"] = g["phylum"].fillna("")
    g["class"] = g["class"].fillna("")
    g["domain"] = "Fungi"
    return g


def add_rank(df: pd.DataFrame) -> pd.DataFrame:
    df = df[df["reads"] > 0].copy()
    df["group"] = (df["domain"] == "Fungi").astype(int)
    df = df.sort_values(["group", "reads", "genus"], ascending=[True, False, True])
    df["abundance_rank"] = df.groupby("group").cumcount() + 1
    df = df.sort_values(["group", "abundance_rank"])
    return df[COLUMNS].reset_index(drop=True)


if __name__ == "__main__":
    out = add_rank(pd.concat([bacteria_archaea(), fungi()], ignore_index=True))
    out["reads"] = out["reads"].astype("int64")
    out["n_samples"] = out["n_samples"].astype("int64")
    out["abundance_rank"] = out["abundance_rank"].astype("int64")
    dup = out.duplicated(["domain", "genus"]).sum()
    assert dup == 0, f"{dup} duplicate (domain, genus) rows"
    out.to_csv(OUT, index=False)
    print(f"wrote {OUT} ({len(out)} rows)")

    for label, grp in [("Bacteria/Archaea", out[out["domain"] != "Fungi"]), ("Fungi", out[out["domain"] == "Fungi"])]:
        counts = grp["domain"].value_counts().to_dict()
        total = grp["reads"].sum()
        cum = grp["reads"].cumsum() / total
        cov = {p: int((cum < p / 100).sum() + 1) for p in (80, 95, 99)}
        print(f"{label}: {len(grp)} genera {counts}; genera covering 80/95/99% of reads: "
              f"{cov[80]} / {cov[95]} / {cov[99]}")
