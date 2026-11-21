#!/usr/bin/env python3
"""Fill in the names of the place (cadastral precinct, commune, county, voivodeship) of the parcels stored in app.parcel before
migration 007, from GUGiK ULDK.

    export LOAD_DB_DSN="postgresql://user:password@localhost:5433/dbname"      # the same variable as the loader
    python scripts/backfill_parcel_names.py

One request per parcel (about 0.25 s each), only for parcels without a commune; the geometry is not touched. Repeatable: a parcel
that got its names is skipped next time. Stops after 8 failures of the service in a row.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app.ingestion.uldk_connector import UldkConnector, UldkError  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dsn", help="connection string (default: env LOAD_DB_DSN)")
    ap.add_argument("--limit", type=int, default=0, help="at most this many parcels (default: all)")
    a = ap.parse_args(argv)
    dsn = a.dsn or os.environ.get("LOAD_DB_DSN")
    if not dsn:
        sys.exit("no connection string: set env LOAD_DB_DSN or pass --dsn")
    import psycopg
    done = missing = failures = 0
    with psycopg.connect(dsn) as con:
        ids = [r[0] for r in con.execute("SELECT parcel_id FROM app.parcel WHERE commune IS NULL AND source = 'uldk' ORDER BY parcel_id"
                                         + (f" LIMIT {int(a.limit)}" if a.limit else "")).fetchall()]
        print(f"{len(ids)} parcels without names", flush=True)
        for i, pid in enumerate(ids, 1):
            try:
                found = UldkConnector.lookup_by_number(pid)
                failures = 0
            except UldkError:
                failures += 1
                if failures >= 8:
                    sys.exit("GUGiK ULDK does not answer (8 failures in a row); run again later")
                continue
            hit = next((p for p in found if p["parcel_id"] == pid), None)
            if hit is None:
                missing += 1
                continue
            con.execute("UPDATE app.parcel SET region = %s, commune = %s, county = %s, voivodeship = %s WHERE parcel_id = %s",
                        (hit["region"], hit["commune"], hit["county"], hit["voivodeship"], pid))
            done += 1
            if i % 100 == 0:
                con.commit()
                print(f"  {i} / {len(ids)}", flush=True)
            time.sleep(0.05)                                  # be gentle with the public service
        con.commit()
    print(f"done: {done} updated, {missing} not found in ULDK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
