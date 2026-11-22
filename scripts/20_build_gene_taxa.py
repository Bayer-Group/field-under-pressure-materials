"""Who carries which KEGG function, per metagenome: KEGG genes joined to NMDC gene phylogeny (offline).

Needs the NMDC gene phylogeny files: scripts/pull_nmdc_cropland.py --types kraken2 gottcha2 ko annotation_stats qc
gene_phylogeny (keep the default types in the list: the pipeline only sees files selected in the last pull).

Writes data/processed/ko_taxa.parquet: metagenome_key, ko, domain, phylum, class, order, family, genus,
n_genes, identity_median (median % protein identity to the closest reference genome; see cropfit.gene_taxa).

Run from the repo root: .venv/bin/python scripts/20_build_gene_taxa.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import pandas as pd  # noqa: E402

from cropfit import gene_taxa, nmdc  # noqa: E402
from cropfit.config import PROCESSED  # noqa: E402

KO, GP = "Annotation KEGG Orthology", "Gene Phylogeny tsv"

if __name__ == "__main__":
    paths = nmdc.object_paths()
    parts, missing = [], []
    for key, files in sorted(paths.items()):
        if KO not in files or GP not in files:
            missing.append(key)
            continue
        t = gene_taxa.ko_taxa(files[KO], files[GP])
        t.insert(0, "metagenome_key", key)
        parts.append(t)
        print(f"  {key}: {int(t['n_genes'].sum()):,} genes, {t['ko'].nunique():,} KOs", flush=True)
    out = pd.concat(parts, ignore_index=True)
    out.to_parquet(PROCESSED / "ko_taxa.parquet", index=False)
    with_lineage = out.loc[out["domain"] != "", "n_genes"].sum() / out["n_genes"].sum()
    print(f"ko_taxa: {len(out):,} rows, {out['metagenome_key'].nunique()} metagenomes, "
          f"{with_lineage:.1%} of genes with a lineage; skipped (no KO or phylogeny file): {len(missing)}")
