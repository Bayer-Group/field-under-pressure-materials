"""Who carries which function: NMDC KEGG genes joined to NMDC gene phylogeny, one metagenome at a time.

Both NMDC files come from the same annotation run (workflow "wfmgan") and use the same gene IDs:
  ko.tsv               gene id, IMG gene OID, KO:Kxxxxx, % identity, ... (one row per KEGG-annotated gene)
  gene_phylogeny.tsv   gene id, closest reference gene OID, its genome OID, % identity, lineage
                       ("Bacteria;Actinomycetota;Actinomycetes;...;genus;species;strain")
The lineage is that of the *closest reference genome*, not a classification of the soil organism: at the typical
60-80 % protein identity it is reliable at phylum or class level and only a hint at genus level. The identity is
kept so every statement can say how close the match was.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

RANKS = ["domain", "phylum", "class", "order", "family", "genus"]


def read_ko(path: Path) -> pd.DataFrame:
    """gene -> KO (one row per KEGG-annotated gene; a gene with several KO rows keeps each)."""
    ko = pd.read_csv(path, sep="\t", header=None, usecols=[0, 2], names=["gene", "ko"], dtype=str)
    ko["ko"] = ko["ko"].str.replace("KO:", "", regex=False)
    return ko


def read_phylogeny(path: Path) -> pd.DataFrame:
    """gene -> % identity and lineage split into ranks (missing ranks are empty)."""
    gp = pd.read_csv(path, sep="\t", header=None, usecols=[0, 3, 4], names=["gene", "identity", "lineage"],
                     dtype={"gene": str, "lineage": str})
    gp["identity"] = pd.to_numeric(gp["identity"], errors="coerce")
    parts = gp["lineage"].fillna("").str.split(";", expand=True)
    for i, r in enumerate(RANKS):
        gp[r] = parts[i].fillna("").str.strip() if i in parts else ""
    return gp.drop(columns="lineage")


def ko_taxa(ko_path: Path, phylogeny_path: Path) -> pd.DataFrame:
    """Per KO x lineage (domain..genus): number of genes and median % identity to the closest reference."""
    j = read_ko(ko_path).merge(read_phylogeny(phylogeny_path), on="gene", how="left")
    for r in RANKS:
        j[r] = j[r].fillna("")
    return (j.groupby(["ko"] + RANKS, as_index=False)
            .agg(n_genes=("gene", "size"), identity_median=("identity", "median")))
