#!/usr/bin/env python3
"""Mock farmers for the demo: users, fields and sprays built from scenarios, so that the map shows a realistic, colourful picture.

    export LOAD_DB_DSN="postgresql://user:password@localhost:5433/dbname"      # the same variable as the loader
    python scripts/generate_mock_farmers.py --farmers 60 --password demo --seed 1

Needs the curated weather features and `curated.septoria_cell_day` (scripts/build_curated.py weather, cells). Steps:

1. The demo day (data time) is chosen: the day with the most grid cells of class `high` (override with --day YYYY-MM-DD), and the
   demo clock is pinned to it (serve.demo_time), so "today" in the app shows that day.
2. Farmers have profiles: large (10-16 crop areas clustered around one place), medium (4-7), small (1-3) and scattered (4-6 crop
   areas at different places, mixed crops). Places are grid cells chosen by their class on the demo day (about 35 % high, 40 % medium,
   25 % low), so the map has red, amber and green fields. Crop areas are rectangles of about 2-25 ha placed on pixels of the
   farmer's crop in the 2024 CTY crop map (maize and soy on their own pixels; a few farmers say wheat where the map says otherwise);
   they never overlap and the crop map inside must be dominated by the crop expected there.
3. Sprays relative to the demo day: some just sprayed (still protected), some expired (red again), some in April.
4. Every crop area is refreshed (crop map, field context, risk assessment) and the logins are written (`analyst` and
   farmer001, farmer002, ... with the given password, demo only; the analyst gets a random password unless --analyst-password).

Dates are written in the time of the data; the serve views shift them. Repeatable: only rows with data_status = 'mock' and the demo
users are replaced; real input is never touched.
"""
from __future__ import annotations

import argparse
import os
import random
import secrets
import sys
import tomllib
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from backend.app.core.security import hash_password  # noqa: E402
from backend.app.domain import septoria  # noqa: E402
from refresh_crop_area import refresh, refresh_crop_map  # noqa: E402

CODES = {"wheat": 1110, "maize": 1130, "soy": 1420}
NEAR = """
WITH p AS (
    SELECT ST_SetSRID(ST_MakePoint(%(x)s + (random() * 2 - 1) * %(r)s, %(y)s + (random() * 2 - 1) * %(r)s), 4326) AS g
    FROM generate_series(1, %(n)s)
)
SELECT DISTINCT ON (ST_AsText(g)) ST_X(g), ST_Y(g)
FROM p JOIN raw.cropland_cty t ON t.year = 2024 AND ST_Intersects(t.rast::geometry, p.g)
WHERE ST_Value(t.rast, 1, p.g) = %(code)s
LIMIT %(want)s
"""
RECTANGLE = """
SELECT ST_AsEWKT(ST_Transform(ST_Rotate(
    ST_MakeEnvelope(ST_X(c) - %(w)s / 2, ST_Y(c) - %(h)s / 2, ST_X(c) + %(w)s / 2, ST_Y(c) + %(h)s / 2, 2180),
    %(angle)s, c), 4326))
FROM (SELECT ST_Transform(ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326), 2180) AS c) x
"""
OVERLAPS = "SELECT EXISTS (SELECT 1 FROM app.crop_area WHERE geom && ST_GeomFromEWKT(%(g)s) AND ST_Intersects(geom, ST_GeomFromEWKT(%(g)s)))"
PROFILES = [  # name, share of farmers, fields (min, max), sites, cluster radius (deg), field side (m), crops
    ("large", 0.08, (10, 16), 1, 0.05, (230, 500), [("wheat", 90), ("maize", 6), ("soy", 4)]),
    ("medium", 0.25, (4, 7), 1, 0.04, (180, 420), [("wheat", 85), ("maize", 10), ("soy", 5)]),
    ("small", 0.45, (1, 3), 1, 0.02, (130, 300), [("wheat", 88), ("maize", 8), ("soy", 4)]),
    ("scattered", 0.22, (4, 6), 4, 0.02, (150, 380), [("wheat", 55), ("maize", 25), ("soy", 20)]),
]
SITE_CLASS_WEIGHTS = [("high", 35), ("medium", 40), ("low", 25)]


def pick_day(cur) -> date:
    cur.execute("SELECT date FROM curated.septoria_cell_day WHERE date BETWEEN '2024-04-15' AND '2024-06-20' "
                "GROUP BY date ORDER BY count(*) FILTER (WHERE risk_class = 'high') DESC, date LIMIT 1")
    return cur.fetchone()[0]


def sites_by_class(cur, day: date) -> dict[str, list[tuple[float, float]]]:
    cur.execute("SELECT d.risk_class, g.lon, g.lat FROM curated.septoria_cell_day d JOIN raw.grid_cell g USING (grid_id) "
                "WHERE d.date = %s", (day,))
    out: dict[str, list] = {"high": [], "medium": [], "low": []}
    for cls, lon, lat in cur.fetchall():
        out[cls].append((lon, lat))
    return out


def points_near(cur, lon, lat, radius, crop, want) -> list[tuple[float, float]]:
    cur.execute(NEAR, {"x": lon, "y": lat, "r": radius, "n": 800, "code": CODES[crop], "want": want})
    return [(r[0], r[1]) for r in cur.fetchall()]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--farmers", type=int, default=60)
    ap.add_argument("--password", default="demo", help="password of every farmer demo user (demo only)")
    ap.add_argument("--analyst-password", help="password of the analyst (default: random, printed once)")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--day", type=date.fromisoformat, help="demo day in the time of the data (default: the day with most 'high' cells)")
    ap.add_argument("--no-pin", action="store_true", help="do not pin the demo clock to the demo day")
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
    analyst_pw = a.analyst_password or secrets.token_urlsafe(9)
    with psycopg.connect(dsn) as con:
        cur = con.cursor()
        cur.execute("SELECT setseed(%s)", ((a.seed % 1000) / 1000.0,))
        day = a.day or pick_day(cur)
        sites = sites_by_class(cur, day)
        print(f"demo day (data time): {day}; cells high/medium/low: "
              f"{len(sites['high'])}/{len(sites['medium'])}/{len(sites['low'])}", flush=True)
        cur.execute("DELETE FROM app.field WHERE data_status = 'mock'")
        cur.execute("DELETE FROM app.demo_user")
        cur.execute("INSERT INTO app.demo_user (login, password_hash, owner_id, role, display_name) "
                    "VALUES ('analyst', %s, 'analyst', 'analyst', 'Analyst')", (hash_password(analyst_pw),))
        con.commit()
        if not a.analyst_password:
            print(f"analyst password (random, shown once): {analyst_pw}", flush=True)

        plan = []
        for name, share, *_ in PROFILES:
            plan += [name] * max(1, round(share * a.farmers))
        rnd.shuffle(plan)
        plan = plan[:a.farmers] + [PROFILES[2][0]] * max(0, a.farmers - len(plan))
        profile = {p[0]: p for p in PROFILES}
        stats = {"areas": 0, "skipped": 0}
        cls_count = {}
        for i, pname in enumerate(plan, start=1):
            _, _, (fmin, fmax), n_sites, radius, (smin, smax), crops = profile[pname]
            owner = f"farmer-{i:03d}"
            cur.execute("INSERT INTO app.demo_user (login, password_hash, owner_id, role, display_name) "
                        "VALUES (%s, %s, %s, 'farmer', %s)", (f"farmer{i:03d}", pw_hash, owner, f"Farmer {i:03d}"))
            n_fields = rnd.randint(fmin, fmax)
            centres = []
            while len(centres) < n_sites:
                cls = rnd.choices([c for c, _ in SITE_CLASS_WEIGHTS], [w for _, w in SITE_CLASS_WEIGHTS])[0]
                if sites[cls]:
                    centres.append(rnd.choice(sites[cls]))
            made = 0
            for k in range(n_fields):
                lon0, lat0 = centres[k % n_sites]
                crop = rnd.choices([c for c, _ in crops], [w for _, w in crops])[0]
                # the farmer's crop is usually on its own pixels; a few say wheat where the map shows another crop
                raster_crop = crop if rnd.random() > 0.08 else "wheat"
                pts = points_near(cur, lon0, lat0, radius, raster_crop, 12) or points_near(cur, lon0, lat0, radius * 2, "wheat", 12)
                placed = False
                for lon, lat in pts:
                    cur.execute(RECTANGLE, {"lon": lon, "lat": lat, "w": rnd.uniform(smin, smax), "h": rnd.uniform(smin, smax),
                                            "angle": rnd.uniform(0, 3.14159)})
                    ewkt = cur.fetchone()[0]
                    cur.execute(OVERLAPS, {"g": ewkt})
                    if cur.fetchone()[0]:
                        continue
                    fid, cid = f"f-{owner}-{k + 1}", f"ca-{owner}-{k + 1}"
                    sowing = date(2023, 9, 20) + timedelta(days=rnd.randint(0, 35))
                    cur.execute("INSERT INTO app.field (field_id, name, owner_id, data_status) VALUES (%s, %s, %s, 'mock')",
                                (fid, f"Field {k + 1}", owner))
                    cur.execute("INSERT INTO app.crop_area (crop_area_id, field_id, geom, farmer_crop_id, sowing_date) "
                                "VALUES (%s, %s, ST_GeomFromEWKT(%s), %s, %s)", (cid, fid, ewkt, crop, sowing))
                    rows = refresh_crop_map(cur, cid)           # keep the place only if the crop map is dominated by the crop expected there
                    dominant = min(rows, key=lambda x: (-x[1], x[0]))[0] if rows else None
                    if dominant != CODES[raster_crop]:
                        cur.execute("DELETE FROM app.field WHERE field_id = %s", (fid,))
                        continue
                    r = rnd.random()
                    if crop == "wheat" and r < 0.15:        # just sprayed: protected on the demo day
                        spray = (day - timedelta(days=rnd.randint(2, 8)), rnd.choice([10, 14]))
                    elif crop == "wheat" and r < 0.25:      # protection expired: conditions apply again
                        spray = (day - timedelta(days=rnd.randint(18, 30)), 10)
                    elif crop == "wheat" and r < 0.33:      # an April spray
                        spray = (date(2024, 4, 5) + timedelta(days=rnd.randint(0, 14)), rnd.choice([10, 14]))
                    else:
                        spray = None
                    if spray:
                        cur.execute("INSERT INTO app.spray (crop_area_id, spray_date, protection_duration_days) VALUES (%s, %s, %s)",
                                    (cid, *spray))
                    refresh(con, cid, a.d0, a.d1, rules, "created")
                    placed = True
                    made += 1
                    break
                if not placed:
                    stats["skipped"] += 1
            stats["areas"] += made
            con.commit()
            print(f"{owner} ({pname}): {made} crop area(s)", flush=True)
        if not a.no_pin:
            cur.execute("UPDATE serve.demo_time SET mode = 'pinned', pinned_data_date = %s, updated_at = now() WHERE id = 1", (day,))
            con.commit()
        cur.execute("SELECT r.risk_class, r.status, r.conditions_met, count(*) FROM curated.risk_assessment r "
                    "WHERE r.date = %s GROUP BY 1, 2, 3 ORDER BY 4 DESC", (day,))
        print(f"done: {a.farmers} farmers, {stats['areas']} crop areas ({stats['skipped']} places skipped); "
              f"demo day {day}{'' if a.no_pin else ' (clock pinned)'}; picture on the demo day:")
        for cls, status, cm, n in cur.fetchall():
            print(f"  {n:4d}  class={cls or '-':6} status={status:17} conditions_met={cm}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
