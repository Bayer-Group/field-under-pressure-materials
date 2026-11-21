#!/usr/bin/env python3
"""Build the knowledge bases for crop risk: FungalTraits genus lifestyles and USDA ARS Fungus-Host species x host.

Usage:
  .venv/bin/python scripts/14_build_kb.py                              # use cached raw files, download if missing
  .venv/bin/python scripts/14_build_kb.py --refresh                    # re-download both raw files
  .venv/bin/python scripts/14_build_kb.py --fungaltraits-file PATH     # use a local FungalTraits xlsx/csv copy

Sources and licences:
- FungalTraits: Polme et al. 2020, Fungal Diversity 105:1-16, Table S1 (genus level), Springer ESM xlsx.
  The licence of the article is NOT verified. The raw file stays local (data/raw/kb/fungaltraits/, gitignored)
  and is never committed.
- USDA ARS U.S. National Fungus Collections Fungus-Host Dataset, Ag Data Commons DOI 10.15482/USDA.ADC/1524414,
  snapshot 2021-11-05 (Fungus-Host-Data_20211105.csv). U.S. Public Domain. The live fungi.ars.usda.gov API needs
  a site-internal key and is not used.
Downloads are ~1 MB (FungalTraits) and ~179 MB (USDA). Each raw file has a manifest.json entry (url, retrieved_utc,
bytes, sha256, source_version).

Outputs (data/processed/):
- kb_fungaltraits_genus.parquet   genus lifestyle table with the filter that decides which genera are scored
- kb_genus_crop_host.parquet      genus x crop host evidence (H in risk = sum_g A*H)
- kb_usda_species_crop.parquet    species x crop host records behind the genus table
- kb_meta.json                    sources, build time, rule-file hashes, row counts

Caveats: host records mean "can infect" (documented host), not "does infect here". Rule files
(rules/genus_synonyms.csv, rules/crop_host_taxa.csv) are hashed into kb_meta.json.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cropfit import kb  # noqa: E402
from cropfit.config import PROCESSED  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the FungalTraits and USDA fungus-host knowledge bases.")
    ap.add_argument("--refresh", action="store_true", help="re-download the raw source files")
    ap.add_argument("--fungaltraits-file", type=Path, metavar="PATH",
                    help="use this local copy of the FungalTraits xlsx/csv instead of downloading")
    args = ap.parse_args()

    meta = kb.build_kb(refresh=args.refresh, fungaltraits_file=args.fungaltraits_file)

    print("sources:")
    for name, src in meta["sources"].items():
        sha = (src.get("sha256") or "")[:12]
        print(f"  {name}: file={src.get('file')} source_version={src.get('source_version')} "
              f"retrieved_utc={src.get('retrieved_utc')} bytes={src.get('bytes')} sha256={sha}")
    print("counts:")
    for k, v in meta["counts"].items():
        print(f"  {k}: {v}")
    print("outputs:")
    for f in (kb.GENERA_TABLE, kb.HOST_TABLE, kb.SPECIES_CROP_TABLE, kb.META_FILE):
        print(f"  {PROCESSED / f}")


if __name__ == "__main__":
    main()
