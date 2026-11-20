#!/usr/bin/env python3
"""Load data/raw (and the farmer's fields) into the existing PostGIS schema `fup`.

    $env:LOAD_DB_DSN = "postgresql://user:password@host:5432/dbname"      # PowerShell
    python scripts/load_db.py --dry-run                                   # show the plan, no database access
    python scripts/load_db.py --limit-files 1                             # smoke test: one file per dataset
    python scripts/load_db.py --voiv opolskie --months 4-9                # a slice of hourly weather
    python scripts/load_db.py --fields fields.geojson                     # + field and field_crop_share

Loads ONLY rows into existing tables (grid_cell, weather_hourly, field, field_crop_share) and records
each file in ingest_log, so a re-run skips what is already loaded. It never creates or alters schema.
Dates are loaded as in the source; any time shift is applied later, in the database.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dbload.backends import get_backend                      # noqa: E402
from dbload.config import ROOT, Settings, parse_months       # noqa: E402
from dbload.pipeline import Pipeline, order_datasets         # noqa: E402


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", default=str(ROOT / "config" / "load_db.toml"))
    p.add_argument("--backend", help="database backend (default from config: postgis)")
    p.add_argument("--dsn", help="connection string; prefer env LOAD_DB_DSN so it stays out of shell history")
    p.add_argument("--schema", help="PostgreSQL schema holding the tables (default from config; the DDL uses fup)")
    p.add_argument("--table-map", help="logical=real pairs, e.g. weather_hourly=fup.weather_hourly (adds to config [tables])")
    p.add_argument("--datasets", help="comma list of: grid_cell, weather_hourly, field, field_crop_share")
    p.add_argument("--mode", choices=["resume", "replace"], default="resume",
                   help="resume = skip files already in ingest_log (default); replace = DELETE all rows of the "
                        "selected tables first, then reload")
    p.add_argument("--years", help="comma list of years, e.g. 2024")
    p.add_argument("--voiv", help="comma list of voivodeship slugs, e.g. opolskie,slaskie (weather_hourly)")
    p.add_argument("--months", help="weather_hourly month filter, e.g. 4-9 or 4,5,9")
    p.add_argument("--fields", help="GeoJSON with the farmer's fields (Polygon/MultiPolygon, WGS84)")
    p.add_argument("--fields-source", help="text stored in field.source (default: the file name)")
    p.add_argument("--limit-files", type=int, help="dev: first N source files per dataset")
    p.add_argument("--dry-run", action="store_true", help="print the plan; no database access")
    p.add_argument("--validate-only", action="store_true")
    p.add_argument("--no-validate", action="store_true")
    return p.parse_args(argv)


def build_settings(a: argparse.Namespace) -> Settings:
    s = Settings.from_toml(Path(a.config))
    if a.backend:
        s.backend = a.backend
    if a.dsn:
        s.dsn = a.dsn
    if a.schema:
        s.db_options["schema"] = a.schema
    if a.table_map:
        s.table_map.update(dict(x.split("=", 1) for x in a.table_map.split(",") if "=" in x))
    if a.datasets:
        s.datasets = tuple(x.strip() for x in a.datasets.split(",") if x.strip())
    s.mode = a.mode
    s.years = {int(y) for y in a.years.split(",")} if a.years else None
    s.voiv = {v.strip() for v in a.voiv.split(",")} if a.voiv else None
    s.months = parse_months(a.months)
    if a.fields:
        s.fields = Path(a.fields).resolve()
    if a.fields_source:
        s.fields_source = a.fields_source
    s.limit_files, s.dry_run = a.limit_files, a.dry_run
    s.validate_only, s.no_validate = a.validate_only, a.no_validate
    return s


def main(argv=None) -> int:
    s = build_settings(parse_args(argv))
    order_datasets(s.selected)                                   # fail fast on typos
    if s.dry_run:
        Pipeline(s, None).dry_run()
        return 0
    backend = get_backend(s.backend, s.resolved_dsn(), aliases=s.table_map, **s.db_options)
    return Pipeline(s, backend).run()


if __name__ == "__main__":
    sys.exit(main())
