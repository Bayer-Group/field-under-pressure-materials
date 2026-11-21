#!/usr/bin/env python3
"""Crop risk index for one NEON site-year, per plot-unit and crop, from ITS fungal genera and USDA host records.
Needs the KB (scripts/12_build_kb.py) and its_core_genus.parquet (scripts/02b_build_neon_features.py).

Usage:
  .venv/bin/python scripts/13_crop_risk.py --site STER --year 2022
  .venv/bin/python scripts/13_crop_risk.py --site STER --year 2025 --min-unit-reads 3000 --out-dir DIR

Score: risk(unit, crop) = sum_g A(unit, g) * H(g, crop)
- A: percentile (0-1, mid-rank) of genus g's share in the unit among the reference units (same site, same ITS
  product, all years, depth-OK for g, unit itself included). Not-detected genera get their mid-rank percentile;
  genera the unit is too shallow to detect are skipped as insufficient_depth.
- H: share of the genus's documented USDA species that have host records on the crop (record = can infect).
Only genera that pass the FungalTraits filter are scored; oomycetes are excluded. .001 and .002 NEON ITS products
are never mixed in one score.

Outputs (out-dir, default data/processed/):
- crop_risk_<SITE>_<YEAR>_summary.parquet        one row per unit x crop: risk_index, status, top genus, depth
- crop_risk_<SITE>_<YEAR>_contributions.parquet  one row per unit x crop x genus that contributes
- crop_risk_<SITE>_<YEAR>_skipped.parquet        genus x unit that could not be scored, with reason
- crop_risk_<SITE>_<YEAR>.json                   everything above plus metadata (parameters, KB versions, caveats)
If no ITS data exist for the site-year, nothing is written and the reason is printed.

Caveats: relative abundance at genus level (not species, not absolute quantity); a host record means the fungus
can infect the crop, not that it does in these plots; fungi only; the index is relative, not a probability of
disease. Status strings (e.g. insufficient_depth, no_knowledge) replace the index where a unit or crop cannot be scored.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import pandas as pd  # noqa: E402
from cropfit import risk  # noqa: E402
from cropfit.config import PROCESSED  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description="Compute the crop risk index for one NEON site-year.")
    ap.add_argument("--site", required=True, type=lambda s: s.upper(), help="NEON site code, e.g. STER")
    ap.add_argument("--year", required=True, type=int, help="sampling year, e.g. 2022")
    ap.add_argument("--min-unit-reads", type=int, default=2000, help="minimum ITS reads per unit (default 2000)")
    ap.add_argument("--min-expected-reads", type=float, default=3.0,
                    help="minimum expected reads for a genus to be called detectable (default 3.0)")
    ap.add_argument("--min-reference", type=int, default=10, help="minimum reference units (default 10)")
    ap.add_argument("--out-dir", type=Path, default=PROCESSED, help="output directory (default data/processed)")
    args = ap.parse_args()

    result = risk.compute_crop_risk(args.site, args.year, min_unit_reads=args.min_unit_reads,
                                    min_expected_reads=args.min_expected_reads, min_reference=args.min_reference)
    if result.empty:
        print(result.metadata["reason"])
        return

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = f"crop_risk_{result.site}_{result.year}"
    result.summary.to_parquet(out / f"{stem}_summary.parquet", index=False)
    result.contributions.to_parquet(out / f"{stem}_contributions.parquet", index=False)
    result.skipped.to_parquet(out / f"{stem}_skipped.parquet", index=False)
    (out / f"{stem}.json").write_text(
        json.dumps(result.to_dict(), allow_nan=False, indent=1, ensure_ascii=False), encoding="utf-8")

    s = result.summary
    print(f"{result.site} {result.year}: {s['unit_id'].nunique()} units x {s['crop'].nunique()} crops "
          f"({', '.join(result.metadata['products'])}) -> {out}")
    # risk_index where scored, otherwise the status string (e.g. no_knowledge, insufficient_depth)
    cell = s["risk_index"].map(lambda v: f"{v:.3f}" if pd.notna(v) else None)
    cell = cell.fillna(s["status"].astype(str))
    table = s.assign(cell=cell).pivot_table(index="unit_id", columns="crop", values="cell", aggfunc="first")
    pd.set_option("display.width", 250, "display.max_columns", 50)
    print(table.to_string())
    if len(result.skipped):
        print("skipped (genus x unit) by reason:")
        for reason, n in result.skipped["reason"].value_counts().items():
            print(f"  {reason}: {n}")
    print("relative risk index, not a probability of disease")


if __name__ == "__main__":
    main()
