#!/usr/bin/env python3
"""Refresh the curated results of one crop area (or all): crop map, field context and septoria risk assessment.

    export LOAD_DB_DSN="postgresql://user:password@localhost:5433/dbname"      # the same variable as the loader
    python scripts/refresh_crop_area.py --crop-area area-demo-1
    python scripts/refresh_crop_area.py --all --from 2024-04-01 --to 2024-06-30

The logic is backend/app/services/crop_area_refresh.py (the API uses the same code when a farmer saves a crop area).
Repeatable: for each crop area everything is deleted and rewritten in one transaction.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app.services.crop_area_refresh import (  # noqa: E402,F401  (re-exported for scripts/generate_mock_farmers.py)
    CROP_MAP_YEAR, refresh, refresh_crop_map, refresh_field_context, refresh_risk, load_rules)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--crop-area", help="crop_area_id to refresh")
    g.add_argument("--all", action="store_true", help="every crop area in app.crop_area")
    ap.add_argument("--from", dest="d0", type=date.fromisoformat, default=date(2024, 4, 1))
    ap.add_argument("--to", dest="d1", type=date.fromisoformat, default=date(2024, 6, 30))
    ap.add_argument("--config", type=Path, default=ROOT / "config" / "septoria.toml")
    ap.add_argument("--dsn", help="connection string (default: env LOAD_DB_DSN)")
    a = ap.parse_args(argv)
    dsn = a.dsn or os.environ.get("LOAD_DB_DSN")
    if not dsn:
        sys.exit("no connection string: set env LOAD_DB_DSN or pass --dsn")
    import psycopg
    rules = load_rules(a.config)
    with psycopg.connect(dsn) as con:
        if a.all:
            with con.cursor() as cur:
                cur.execute("SELECT crop_area_id FROM app.crop_area ORDER BY 1")
                ids = [r[0] for r in cur.fetchall()]
        else:
            ids = [a.crop_area]
        for cid in ids:
            print(refresh(con, cid, a.d0, a.d1, rules))
    return 0


if __name__ == "__main__":
    sys.exit(main())
