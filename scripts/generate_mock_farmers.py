#!/usr/bin/env python3
"""Mock farmers for the demo: users, fields inside wheat pixels of the crop map, sowing dates, sprays, and their results.

    export LOAD_DB_DSN="postgresql://user:password@localhost:5433/dbname"      # the same variable as the loader
    python scripts/generate_mock_farmers.py --farmers 50 --areas 2 --password demo --seed 1

Creates users farmer001, farmer002, ... and the analyst (login `analyst`), all with the given password, each farmer with `--areas`
crop areas (about 2-20 ha rectangles placed on 2024 CTY wheat pixels of Mazowieckie, so the crop map agrees with the farmer's crop for
most of them; some farmers pick maize or soy). Winter wheat is sown in the autumn before the season (data time); about a third of the
areas have one spray in April-June. Then every crop area is refreshed (crop map, field context, risk assessment).
Dates are written in the time of the data; the serve views shift them. Repeatable: only rows with data_status = 'mock' and the demo
users are replaced; real input is never touched.
"""
from __future__ import annotations

import argparse
import os
import random
import sys
import tomllib
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from backend.app.core.security import hash_password  # noqa: E402
from refresh_crop_area import refresh  # noqa: E402
from backend.app.domain import septoria  # noqa: E402

WHEAT = 1110
POINTS = """
WITH cells AS (         -- only the cells that have weather (the grid covers the whole country, the weather only Mazowieckie)
    SELECT c.lon, c.lat, c.geom FROM raw.grid_cell c
    WHERE c.grid_id IN (SELECT grid_id FROM curated.vegetation_resumption)
),
box AS (SELECT min(lon) x0, max(lon) x1, min(lat) y0, max(lat) y1 FROM cells),
p AS (
    SELECT ST_SetSRID(ST_MakePoint(x0 + random() * (x1 - x0), y0 + random() * (y1 - y0)), 4326) AS g
    FROM box, generate_series(1, %(n)s)
)
SELECT DISTINCT ON (ST_AsText(g)) ST_X(g) AS lon, ST_Y(g) AS lat
FROM p
JOIN raw.cropland_cty t ON t.year = 2024 AND ST_Intersects(t.rast::geometry, p.g)
WHERE ST_Value(t.rast, 1, p.g) = %(wheat)s
  AND EXISTS (SELECT 1 FROM cells c WHERE c.geom && ST_Expand(p.g, 0.02))             -- a cell with weather within ~2 km
LIMIT %(want)s
"""
RECTANGLE = """
SELECT ST_AsEWKT(ST_Transform(ST_Rotate(
    ST_MakeEnvelope(ST_X(c) - %(w)s / 2, ST_Y(c) - %(h)s / 2, ST_X(c) + %(w)s / 2, ST_Y(c) + %(h)s / 2, 2180),
    %(angle)s, c), 4326))
FROM (SELECT ST_Transform(ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326), 2180) AS c) x
"""


def wheat_points(cur, want: int) -> list[tuple[float, float]]:
    found: list[tuple[float, float]] = []
    while len(found) < want:
        cur.execute(POINTS, {"n": 4000, "wheat": WHEAT, "want": want - len(found)})
        found += [(r[0], r[1]) for r in cur.fetchall()]
    return found[:want]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--farmers", type=int, default=20)
    ap.add_argument("--areas", type=int, default=2, help="crop areas per farmer")
    ap.add_argument("--password", default="demo", help="password of every demo user (demo only)")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--from", dest="d0", type=date.fromisoformat, default=date(2024, 4, 1))
    ap.add_argument("--to", dest="d1", type=date.fromisoformat, default=date(2024, 6, 30))
    ap.add_argument("--config", type=Path, default=ROOT / "config" / "septoria.toml")
    ap.add_argument("--dsn", help="connection string (default: env LOAD_DB_DSN)")
    a = ap.parse_args(argv)
    dsn = a.dsn or os.environ.get("LOAD_DB_DSN")
    if not dsn:
        sys.exit("no connection string: set env LOAD_DB_DSN or pass --dsn")
    import psycopg
    rnd = random.Random(a.seed)
    with open(a.config, "rb") as fh:
        rules = septoria.Rules.from_config(tomllib.load(fh))
    pw_hash = hash_password(a.password)                    # one salt for all demo users is enough for a demonstration
    with psycopg.connect(dsn) as con:
        cur = con.cursor()
        cur.execute("DELETE FROM app.field WHERE data_status = 'mock'")
        cur.execute("DELETE FROM app.demo_user")
        cur.execute("INSERT INTO app.demo_user (login, password_hash, owner_id, role, display_name) "
                    "VALUES ('analyst', %s, 'analyst', 'analyst', 'Analyst')", (pw_hash,))
        con.commit()
        points = iter(wheat_points(cur, a.farmers * a.areas))
        total = 0
        for i in range(1, a.farmers + 1):
            owner = f"farmer-{i:03d}"
            cur.execute("INSERT INTO app.demo_user (login, password_hash, owner_id, role, display_name) "
                        "VALUES (%s, %s, %s, 'farmer', %s)", (f"farmer{i:03d}", pw_hash, owner, f"Farmer {i:03d}"))
            for k in range(1, a.areas + 1):
                lon, lat = next(points)
                cur.execute(RECTANGLE, {"lon": lon, "lat": lat, "w": rnd.uniform(150, 500), "h": rnd.uniform(150, 500),
                                        "angle": rnd.uniform(0, 3.14159)})
                ewkt = cur.fetchone()[0]
                fid, cid = f"f-{owner}-{k}", f"ca-{owner}-{k}"
                crop = rnd.choices(["wheat", "maize", "soy"], weights=[85, 10, 5])[0]
                sowing = date(2023, 9, 20) + timedelta(days=rnd.randint(0, 35))
                cur.execute("INSERT INTO app.field (field_id, name, owner_id, data_status) VALUES (%s, %s, %s, 'mock')",
                            (fid, f"Field {chr(64 + k)}", owner))
                cur.execute("INSERT INTO app.crop_area (crop_area_id, field_id, geom, farmer_crop_id, sowing_date) "
                            "VALUES (%s, %s, ST_GeomFromEWKT(%s), %s, %s)", (cid, fid, ewkt, crop, sowing))
                if rnd.random() < 0.33:
                    cur.execute("INSERT INTO app.spray (crop_area_id, spray_date, protection_duration_days) VALUES (%s, %s, %s)",
                                (cid, date(2024, 4, 10) + timedelta(days=rnd.randint(0, 60)), rnd.choice([10, 14])))
                refresh(con, cid, a.d0, a.d1, rules, "created")
                total += 1
            con.commit()
            print(f"{owner}: {a.areas} crop area(s)", flush=True)
    print(f"done: {a.farmers} farmers, {total} crop areas, analyst login 'analyst'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
