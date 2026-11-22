"""KEGG module completeness for every NMDC metagenome, using all its KEGG genes (not only the KO panel).

Network once (KEGG REST: module hierarchy + 583 definitions, cached under data/cache/kegg/), then offline.
Needs data/processed/ko_counts_all.parquet (scripts/05_build_biology.py).

Writes data/processed/
  kegg_modules.parquet              module, name, class_a/b/c (e.g. Pathway modules / Energy metabolism /
                                    Nitrogen metabolism), definition, n_steps
  kegg_module_completeness.parquet  metagenome_key, module, steps_found, n_steps, completeness (0-1),
                                    missing_steps (the definition text of each missing step), via_alias
                                    (current KEGG IDs satisfied only through an older, ambiguous ID)

A step counts as present with one KO copy. Completeness of shallow metagenomes mostly reflects how little was
assembled (see metagenomes.ko_depth_ok), not what the soil lacks.

Run from the repo root: .venv/bin/python scripts/19_build_kegg_modules.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import pandas as pd  # noqa: E402

from cropfit import kegg  # noqa: E402
from cropfit.config import PROCESSED  # noqa: E402

if __name__ == "__main__":
    modules = kegg.module_table()
    modules.to_parquet(PROCESSED / "kegg_modules.parquet", index=False)
    print(f"kegg_modules: {len(modules)} modules ({modules['class_a'].value_counts().to_dict()})")

    ko = pd.read_parquet(PROCESSED / "ko_counts_all.parquet")
    ko = ko[ko["count"] > 0]
    parts = []
    for key, g in ko.groupby("metagenome_key"):
        s = kegg.score_sample(modules, set(g["ko"]))
        s.insert(0, "metagenome_key", key)
        parts.append(s)
    comp = pd.concat(parts, ignore_index=True)
    comp.to_parquet(PROCESSED / "kegg_module_completeness.parquet", index=False)

    mg = pd.read_parquet(PROCESSED / "metagenomes.parquet").set_index("metagenome_key")
    full = comp[comp["completeness"] == 1].groupby("metagenome_key").size()
    summary = mg.join(full.rename("complete_modules")).groupby(["site", "year"]).agg(
        metagenomes=("complete_modules", "size"), deep=("ko_depth_ok", "sum"),
        complete_modules_median=("complete_modules", "median"))
    print(f"kegg_module_completeness: {len(comp)} rows for {comp['metagenome_key'].nunique()} metagenomes")
    print(summary.to_string())
