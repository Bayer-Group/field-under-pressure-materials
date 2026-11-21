#!/usr/bin/env python3
"""Example farmers for the demo (version 3): easy to take in on a phone, realistic, colourful on the demo day.

    export LOAD_DB_DSN="postgresql://user:password@localhost:5433/dbname"      # the same variable as the loader
    python scripts/generate_mock_farmers.py --farmers 100 --seed 1
    python scripts/generate_mock_farmers.py --farmers 6 --dry-run        # try it, nothing is saved

What it makes (every number below is a target, see the options):

* **Farmers** `farmer-001` ... (login `farmer001`, password `demo001`: the same word and the number of the login, easy to say aloud),
  mostly with 3 fields (2 to 5, almost never 1). A field is one cadastral parcel from GUGiK ULDK (cached in app.parcel) or, for about
  one field in ten, two neighbouring parcels merged into one crop area. Crop areas are the whole parcel, not inset: saving them needs
  no "gap" confirmation.
* **Compact farms**: the fields of a farm lie within a few kilometres (one cluster); about 15 % of the farmers have a second cluster
  8 to 15 km away. The clusters are placed where the weather cells around differ in class on the demo day, so a farm shows more than
  one colour.
* **Mostly wheat** (about 90 % of the crop areas); now and then maize or soy, never split and never merged.
* **Some parcels split into 2 or 3 crop areas** (a parcelling by the farmer): only part of the fields of a farm and mostly the larger
  parcels, at most 3 pieces, and never a piece too small to tap on a phone (at least 0.3 ha and 28 m across). A parcel is cut ACROSS
  its long axis (a thin strip is never cut lengthwise).
* **Sprays that follow how septoria is controlled in winter wheat**: T1 at BBCH 31-32 (late April), T2 on the flag leaf BBCH 37-39
  (about three weeks later, mid May), a spray protects 14 to 21 days; the farm sprays its fields one after another, a few days apart.
  Programs: two sprays, only an early one (protection over), only a late one, a farm that is halfway through the fields (some sprayed,
  some not yet), and no spray. All the sprays are before the demo day.
* **Names that read well**: the place of the parcel plus a compass direction in the farm, for example "Dąbrówka płn.".
* Everything in ONE transaction: the public API keeps showing the old farms until the end, and nothing changes when it fails.
  Only the example farmers are replaced (the sandboxes of visitors and the analyst are not touched).

Dates are written in the time of the data (2024); the serve views shift them. Needs `curated.septoria_cell_day` (build_curated.py cells).
"""
from __future__ import annotations

import argparse
import math
import os
import random
import re
import statistics
import sys
import time
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from backend.app.core.security import hash_password  # noqa: E402
from backend.app.ingestion.uldk_connector import UldkError  # noqa: E402
from backend.app.services.parcels import find_by_xy  # noqa: E402
from refresh_crop_area import refresh, refresh_crop_map, load_rules  # noqa: E402

CODES = {"wheat": 1110, "maize": 1130, "soy": 1420}
MIN_PIECE_HA, MIN_PIECE_RADIUS_M = 0.3, 14.0          # a piece must be tappable on a phone: at least 0.3 ha and 28 m across
FIELDS_WEIGHTS = {1: 1, 2: 10, 3: 62, 4: 21, 5: 6}     # fields per farmer
DIRECTIONS = ["płn.", "płn.-wsch.", "wsch.", "płd.-wsch.", "płd.", "płd.-zach.", "zach.", "płn.-zach."]

NEAR = """
WITH p AS (
    SELECT ST_SetSRID(ST_MakePoint(%(x)s + (random() * 2 - 1) * %(rx)s, %(y)s + (random() * 2 - 1) * %(ry)s), 4326) AS g
    FROM generate_series(1, %(n)s)
)
SELECT DISTINCT ON (ST_AsText(g)) ST_X(g), ST_Y(g)
FROM p JOIN raw.cropland_cty t ON t.year = 2024 AND ST_Intersects(t.rast::geometry, p.g)
WHERE ST_Value(t.rast, 1, p.g) = %(code)s
LIMIT %(want)s
"""
METRICS = """
SELECT ST_Area(ST_Transform(geom, 2180)) / 10000 AS ha, GeometryType(geom) AS gt, ST_NumInteriorRings(geom) AS holes,
       (ST_MaximumInscribedCircle(ST_Transform(geom, 2180))).radius AS r, ST_AsEWKT(geom) AS ewkt,
       ST_X(ST_Centroid(geom)) AS lon, ST_Y(ST_Centroid(geom)) AS lat, region, commune
FROM app.parcel WHERE parcel_id = %s
"""
NEIGHBOURS = """
SELECT b.parcel_id FROM app.parcel a JOIN app.parcel b ON b.parcel_id <> a.parcel_id AND ST_Touches(a.geom, b.geom)
WHERE a.parcel_id = %s AND ST_Length(ST_Transform(ST_Intersection(a.geom, b.geom), 2180)) > 20 ORDER BY b.parcel_id
"""
UNION = """
SELECT ST_AsEWKT(g), GeometryType(g), ST_Area(ST_Transform(g, 2180)) / 10000 FROM
    (SELECT ST_Union(geom) AS g FROM app.parcel WHERE parcel_id = ANY(%s)) x
"""


# ---------------------------------------------------------------- the parcels
class Parcels:
    """Finds cadastral parcels under points (GUGiK ULDK, cached in app.parcel) and describes them."""

    def __init__(self, con, pcon):
        self.con, self.pcon = con, pcon
        self.used: set[str] = set()                        # parcels already in a field of this run
        self.failures = 0

    def at(self, lon: float, lat: float):
        try:
            found = find_by_xy(self.pcon, lon, lat)
            self.pcon.commit()
        except UldkError:
            self.pcon.rollback()
            self.failures += 1
            if self.failures >= 8:
                sys.exit("GUGiK ULDK does not answer (8 failures in a row); try again later")
            return None
        self.failures = 0
        time.sleep(0.04)                                   # be gentle with the public service
        return found[0]["parcel_id"] if found else None

    def describe(self, parcel_id: str) -> dict | None:
        cur = self.con.cursor()
        cur.execute(METRICS, (parcel_id,))
        r = cur.fetchone()
        if not r:
            return None
        ha, gt, holes, radius, ewkt, lon, lat, region, commune = r
        return {"id": parcel_id, "ha": ha, "single": gt == "POLYGON" and not holes, "radius": radius, "ewkt": ewkt,
                "lon": lon, "lat": lat, "region": region, "commune": commune}

    def neighbours(self, parcel: dict) -> list[str]:
        """The parcels that share at least 20 m of boundary with this one: from the cache, else by probing around it."""
        cur = self.con.cursor()
        cur.execute(NEIGHBOURS, (parcel["id"],))
        found = [r[0] for r in cur.fetchall()]
        if found:
            return found
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):                      # ULDK at points just beyond the four sides
            self.at(parcel["lon"] + dx * 0.0011, parcel["lat"] + dy * 0.0009)
        cur.execute(NEIGHBOURS, (parcel["id"],))
        return [r[0] for r in cur.fetchall()]

    def union(self, ids: list[str]):
        cur = self.con.cursor()
        cur.execute(UNION, (ids,))
        ewkt, gt, ha = cur.fetchone()
        return (ewkt, ha) if gt == "POLYGON" else (None, 0.0)


def split_pieces(cur, ewkt: str, k: int) -> list[dict] | None:
    """Cut a parcel into k pieces ACROSS its long axis (strips perpendicular to it, so a thin parcel is not cut lengthwise). Returns the
    pieces ({ewkt, ha}) or None when a piece would be too small to tap (area, width) or in more than one part."""
    cur.execute("SELECT ST_AsText(ST_OrientedEnvelope(ST_Transform(ST_GeomFromEWKT(%s), 2180)))", (ewkt,))
    pts = [tuple(float(v) for v in p.split()) for p in re.findall(r"(-?[\d.]+ -?[\d.]+)", cur.fetchone()[0])][:4]
    (x1, y1), (x2, y2), (x3, y3) = pts[0], pts[1], pts[2]
    e1, e2 = (x2 - x1, y2 - y1), (x3 - x2, y3 - y2)
    l1, l2 = math.hypot(*e1), math.hypot(*e2)
    u, length, width = ((e1[0] / l1, e1[1] / l1), l1, l2) if l1 >= l2 else ((e2[0] / l2, e2[1] / l2), l2, l1)
    v = (-u[1], u[0])
    cx, cy, half = (x1 + x3) / 2, (y1 + y3) / 2, width / 2 + 40
    out = []
    for i in range(k):
        t0 = -length / 2 + i * length / k - (40 if i == 0 else 0)
        t1 = -length / 2 + (i + 1) * length / k + (40 if i == k - 1 else 0)
        corners = [(cx + u[0] * t + v[0] * s, cy + u[1] * t + v[1] * s)
                   for t, s in ((t0, -half), (t1, -half), (t1, half), (t0, half), (t0, -half))]
        strip = "POLYGON((" + ", ".join(f"{x:.4f} {y:.4f}" for x, y in corners) + "))"
        cur.execute("SELECT ST_AsEWKT(ST_Transform(pc, 4326)), ST_Area(pc), (ST_MaximumInscribedCircle(pc)).radius, GeometryType(pc) FROM "
                    "(SELECT ST_CollectionExtract(ST_Intersection(ST_Transform(ST_GeomFromEWKT(%s), 2180), "
                    "ST_GeomFromText(%s, 2180)), 3) AS pc) x", (ewkt, strip))
        piece_ewkt, m2, radius, gt = cur.fetchone()
        if gt != "POLYGON" or m2 / 10000 < MIN_PIECE_HA or radius < MIN_PIECE_RADIUS_M:
            return None
        out.append({"ewkt": piece_ewkt, "ha": m2 / 10000})
    return out


def split_count(ha: float, rnd: random.Random) -> int:
    """How many pieces to try for a parcel of this size (1 = do not split): small parcels are left whole, larger ones are cut into 2,
    the largest into 3; never more."""
    if ha < 1.5:
        return 1
    if ha < 3:
        return 2 if rnd.random() < 0.12 else 1
    if ha < 6:
        return 2 if rnd.random() < 0.35 else 1
    if ha < 12:
        return (3 if ha >= 8 and rnd.random() < 0.4 else 2) if rnd.random() < 0.5 else 1
    return 3 if rnd.random() < 0.6 else 1


# ---------------------------------------------------------------- sprays that follow how septoria is controlled
def spray_plan(rnd: random.Random, kind: str, day: date, protection: int, field_idx: int, cutoff: int) -> list[tuple[date, int]]:
    """The sprays of one wheat field of a farm: a list of (date, protection days). T1 at BBCH 31-32 (late April), T2 on the flag leaf
    BBCH 37-39 (about three weeks later), never after the demo day."""
    t1 = date(2024, 4, 22) + timedelta(days=rnd.randint(0, 8))
    t2 = date(2024, 5, 10) + timedelta(days=rnd.randint(0, 12))
    off = timedelta(days=min(field_idx, 3) + rnd.randint(0, 1))                # the farm works through its fields one after another
    sprays: list[tuple[date, int]] = []
    if kind == "two":
        sprays = [(t1 + off, protection), (t2 + off, protection)]
    elif kind == "one_early":
        sprays = [(t1 + off + timedelta(days=rnd.randint(0, 4)), protection)]
    elif kind == "one_late":
        sprays = [(t2 + off, protection)]
    elif kind == "halfway":                                                    # T1 on all, T2 only on the fields done so far
        sprays = [(t1 + off, protection)]
        if field_idx < cutoff:
            sprays.append((date(2024, 5, 17) + timedelta(days=min(field_idx * 2, 6)), protection))
    return [(d, p) for d, p in sprays if d <= day]


# ---------------------------------------------------------------- names
def compass(lon0: float, lat0: float, lon: float, lat: float) -> tuple[str, float]:
    dx, dy = (lon - lon0) * math.cos(math.radians(lat0)) * 111.32, (lat - lat0) * 110.57        # km
    return DIRECTIONS[int(((math.degrees(math.atan2(dx, dy)) + 360 + 22.5) % 360) // 45)], math.hypot(dx, dy)


def place_name(region: str | None, commune: str | None) -> str:
    commune = re.sub(r"\s*\(miasto\)$", "", (commune or "").strip())
    region = (region or "").strip()
    if region and not re.match(r"^\d+(-\d+)*$", region) and region.lower() != commune.lower():
        return region
    return commune or region or "Pole"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--farmers", type=int, default=100, help="how many farmers to make (default 100: enough for a room to get another farm each)")
    ap.add_argument("--start", type=int, default=1, help="the number of the first farmer (to add farmers after the ones already there)")
    ap.add_argument("--no-replace", action="store_true", help="do not delete the example farmers that exist (use with --start)")
    ap.add_argument("--commit-every", type=int, default=0, help="commit after every N farmers (default: one transaction for everything)")
    ap.add_argument("--password-word", default="demo", help="the password of farmerNNN is this word and NNN (default demo -> demo014)")
    ap.add_argument("--analyst-password", help="password of the analyst, created only if there is no analyst yet")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--day", type=date.fromisoformat, help="demo day in the time of the data (default: the day with most 'high' cells)")
    ap.add_argument("--no-pin", action="store_true", help="do not pin the demo clock to the demo day")
    ap.add_argument("--dry-run", action="store_true", help="do everything, then roll back: nothing is saved")
    ap.add_argument("--wheat-share", type=float, default=0.91)
    ap.add_argument("--second-cluster", type=float, default=0.15)
    ap.add_argument("--merged-share", type=float, default=0.10, help="share of the wheat fields that are two merged parcels")
    ap.add_argument("--from", dest="d0", type=date.fromisoformat, default=date(2024, 4, 1))
    ap.add_argument("--to", dest="d1", type=date.fromisoformat, default=date(2024, 6, 30))
    ap.add_argument("--config", type=Path, default=ROOT / "config" / "septoria.toml")
    ap.add_argument("--dsn", help="connection string (default: env LOAD_DB_DSN)")
    a = ap.parse_args(argv)
    dsn = a.dsn or os.environ.get("LOAD_DB_DSN")
    if not dsn:
        sys.exit("no connection string: set env LOAD_DB_DSN or pass --dsn")
    import psycopg
    from psycopg.rows import dict_row
    rnd = random.Random(a.seed)
    rules = load_rules(a.config)
    with psycopg.connect(dsn) as con, psycopg.connect(dsn, row_factory=dict_row) as pcon:     # con: one transaction; pcon: the parcels cache
        cur = con.cursor()
        cur.execute("SELECT setseed(%s)", ((a.seed % 1000) / 1000.0,))
        cur.execute("SELECT date FROM curated.septoria_cell_day WHERE date BETWEEN '2024-04-15' AND '2024-06-20' GROUP BY date "
                    "ORDER BY count(*) FILTER (WHERE risk_class = 'high') DESC, date LIMIT 1")
        day = a.day or cur.fetchone()[0]
        cur.execute("SELECT g.lon, g.lat, d.risk_class FROM curated.septoria_cell_day d JOIN raw.grid_cell g USING (grid_id) WHERE d.date = %s", (day,))
        cells = cur.fetchall()
        lon0, lat0 = min(c[0] for c in cells), min(c[1] for c in cells)
        lattice = {(round((lo - lon0) / 0.044), round((la - lat0) / 0.044)): cl for lo, la, cl in cells}
        mixed_by: dict[str, list] = {"high": [], "medium": [], "low": []}          # cells with a neighbour of another class, by own class
        for lo, la, cl in cells:
            if len({lattice.get((round((lo - lon0) / 0.044) + i, round((la - lat0) / 0.044) + j))
                    for i in (-1, 0, 1) for j in (-1, 0, 1)} - {None}) >= 2:
                mixed_by[cl].append((lo, la))
        mixed = [c for v in mixed_by.values() for c in v]
        print(f"demo day (data time): {day}; cells {len(cells)}, of them with a neighbour of another class: {len(mixed)}", flush=True)

        if not a.no_replace:
            cur.execute("DELETE FROM app.field WHERE data_status = 'mock' AND owner_id NOT LIKE 'sbx-%'")      # the example farmers only
            cur.execute("DELETE FROM app.demo_user WHERE role = 'farmer'")
        if a.analyst_password:
            cur.execute("INSERT INTO app.demo_user (login, password_hash, owner_id, role, display_name) VALUES "
                        "('analyst', %s, 'analyst', 'analyst', 'Analyst') ON CONFLICT (login) DO NOTHING", (hash_password(a.analyst_password),))

        parcels = Parcels(con, pcon)
        cur.execute("SELECT DISTINCT fp.parcel_id FROM app.field_parcel fp JOIN app.field f USING (field_id) WHERE f.owner_id NOT LIKE 'sbx-%'")
        parcels.used.update(r[0] for r in cur.fetchall())                      # parcels of the farmers that are already there
        stats: Counter = Counter()
        done = 0
        for n in range(a.start, a.start + a.farmers):
            owner = f"farmer-{n:03d}"
            snapshot = Counter(stats)
            for farmer_try in range(3):                                               # another place when fewer than 2 fields fit
                n_fields = rnd.choices(list(FIELDS_WEIGHTS), list(FIELDS_WEIGHTS.values()))[0]
                two = n_fields >= 3 and rnd.random() < a.second_cluster
                site_class = rnd.choices(["high", "medium", "low"], [35, 40, 25])[0]            # so that the map has red, amber and green farms
                site = rnd.choice(mixed_by[site_class] or mixed) if rnd.random() < 0.9 else rnd.choice([(c[0], c[1]) for c in cells])
                centres = [site]
                if two:
                    for _ in range(40):
                        lo, la = rnd.choice(mixed)
                        d = math.hypot((lo - site[0]) * math.cos(math.radians(site[1])) * 111.32, (la - site[1]) * 110.57)
                        if 8 <= d <= 15:
                            centres.append((lo, la))
                            break
                quota_split = 1 if n_fields <= 3 else 2
                crop_plan = ["wheat"] * n_fields                                          # decided once per field, not per attempt
                if rnd.random() < n_fields * (1 - a.wheat_share):                          # at most one field of another crop per farmer
                    crop_plan[rnd.randrange(n_fields)] = rnd.choices(["maize", "soy"], [70, 30])[0]
                splits = guard = attempts = 0
                fields: list[dict] = []
                while len(fields) < n_fields and guard < 60:
                    guard += 1
                    attempts += 1
                    slot = len(fields)
                    crop = crop_plan[slot] if (attempts <= 4 or crop_plan[slot] == "wheat") else "wheat"   # no such parcel here: wheat
                    centre = centres[0] if (len(centres) == 1 or slot < math.ceil(n_fields * 0.6)) else centres[1]
                    cur.execute(NEAR, {"x": centre[0], "y": centre[1], "rx": 0.035, "ry": 0.03, "n": 700, "code": CODES[crop], "want": 14})
                    cand: list[str] = []
                    for lon, lat in cur.fetchall():
                        pid = parcels.at(lon, lat)
                        if pid and pid not in parcels.used and pid not in cand:
                            cand.append(pid)
                    placed = None
                    for pid in cand:
                        pd = parcels.describe(pid)
                        parcels.used.add(pid)
                        if not pd or not pd["single"] or not (0.6 <= pd["ha"] <= 35) or pd["radius"] < 8:
                            continue
                        ids, ewkt, ha = [pid], pd["ewkt"], pd["ha"]
                        if crop == "wheat" and rnd.random() < a.merged_share:                 # two neighbouring parcels as one crop area
                            for nb in parcels.neighbours(pd):
                                nd = parcels.describe(nb)
                                if nd and nb not in parcels.used and nd["single"] and nd["ha"] >= 0.6:
                                    u_ewkt, u_ha = parcels.union([pid, nb])
                                    if u_ewkt and u_ha <= 35:
                                        ids, ewkt, ha = [pid, nb], u_ewkt, u_ha
                                        parcels.used.add(nb)
                                        break
                        fid = f"{owner}-p{len(fields) + 1}"
                        cur.execute("INSERT INTO app.field (field_id, name, owner_id, data_status) VALUES (%s, %s, %s, 'mock')", (fid, "tmp", owner))
                        for p_id in ids:
                            cur.execute("INSERT INTO app.field_parcel (field_id, parcel_id) VALUES (%s, %s)", (fid, p_id))
                        pieces = [{"ewkt": ewkt, "ha": ha}]
                        if len(ids) == 1 and crop == "wheat" and splits < quota_split:
                            for k in range(split_count(ha, rnd), 1, -1):                     # try k pieces, then fewer
                                got = split_pieces(cur, ewkt, k)
                                if got:
                                    pieces = got
                                    break
                        sowing = date(2023, 9, 25) + timedelta(days=rnd.randint(0, 25))

                        def put_areas(pcs, base=fid):
                            ids_ = []
                            for j, pc in enumerate(pcs):
                                cid = f"{base}{'abc'[j]}"
                                cur.execute("INSERT INTO app.crop_area (crop_area_id, field_id, geom, farmer_crop_id, sowing_date, sprays_confirmed) "
                                            "VALUES (%s, %s, ST_GeomFromEWKT(%s), %s, %s, true)", (cid, fid, pc["ewkt"], crop, sowing))
                                ids_.append(cid)
                            return ids_

                        def dominated(cs, crop=crop):
                            for c in cs:
                                rows = refresh_crop_map(cur, c)
                                if not rows or min(rows, key=lambda x: (-x[1], x[0]))[0] != CODES[crop]:
                                    return False
                            return True

                        cids = put_areas(pieces)
                        if not dominated(cids):
                            if len(pieces) > 1:                                              # the pieces failed: try the whole parcel
                                cur.execute("DELETE FROM app.crop_area WHERE field_id = %s", (fid,))
                                pieces = [{"ewkt": ewkt, "ha": ha}]
                                cids = put_areas(pieces)
                            if len(pieces) == 1 and not dominated(cids):
                                cur.execute("DELETE FROM app.field WHERE field_id = %s", (fid,))
                                continue
                        placed = {"fid": fid, "cids": cids, "crop": crop, "parcel": pd, "pieces": len(pieces), "merged": len(ids) > 1}
                        break
                    if placed:
                        attempts = 0
                        fields.append(placed)
                        splits += placed["pieces"] > 1
                        stats["merged"] += placed["merged"]
                        stats["split_fields"] += placed["pieces"] > 1
                        stats["areas"] += placed["pieces"]
                        stats["fields"] += 1
                        stats["nonwheat_areas"] += placed["pieces"] if placed["crop"] != "wheat" else 0

                if len(fields) >= 2:
                    break
                cur.execute("DELETE FROM app.field WHERE owner_id = %s", (owner,))
                stats.clear()
                stats.update(snapshot)
                stats["retried_farmers"] += 1
            if not fields:
                print(f"{owner}: no field found, skipped", flush=True)
                continue

            # sprays: one program for the farm, the fields one after another (a farm "halfway" has some fields not sprayed yet)
            kind = rnd.choices(["two", "one_early", "one_late", "halfway", "none"], [20, 30, 12, 20, 18])[0]
            protection = rnd.choice([14, 14, 21])
            wheat_fields = [f for f in fields if f["crop"] == "wheat"]
            cutoff = rnd.randint(1, len(wheat_fields) - 1) if (kind == "halfway" and len(wheat_fields) > 1) else max(1, len(wheat_fields))
            for i, f in enumerate(wheat_fields):
                plan = spray_plan(rnd, kind, day, protection, i, cutoff)
                for cid in f["cids"]:
                    for d, p in plan:
                        cur.execute("INSERT INTO app.spray (crop_area_id, spray_date, protection_duration_days) VALUES (%s, %s, %s)", (cid, d, p))
                    stats["sprays"] += len(plan)
            stats[f"program_{kind}"] += 1

            # names: the place of the parcel; when several fields of the farm are in one place, the direction among them
            by_place: dict[str, list] = defaultdict(list)
            for f in fields:
                by_place[place_name(f["parcel"]["region"], f["parcel"]["commune"])].append(f)
            for place, group in by_place.items():
                if len(group) == 1:
                    group[0]["name"] = place
                    continue
                gx, gy = statistics.mean(f["parcel"]["lon"] for f in group), statistics.mean(f["parcel"]["lat"] for f in group)
                taken: Counter = Counter()
                for i, f in enumerate(group, start=1):
                    direction, dist = compass(gx, gy, f["parcel"]["lon"], f["parcel"]["lat"])
                    label = f"{place} {direction}" if dist >= 0.12 else f"{place} {i}"
                    taken[label] += 1
                    f["name"] = label if taken[label] == 1 else f"{label} {taken[label]}"
            for f in fields:
                cur.execute("UPDATE app.field SET name = %s WHERE field_id = %s", (f["name"][:40], f["fid"]))
            places = Counter(place_name(f["parcel"]["region"], f["parcel"]["commune"]) for f in fields)
            cur.execute("INSERT INTO app.demo_user (login, password_hash, owner_id, role, display_name) VALUES (%s, %s, %s, 'farmer', %s)",
                        (f"farmer{n:03d}", hash_password(f"{a.password_word}{n:03d}"), owner,
                         f"Gospodarstwo {places.most_common(1)[0][0]} ({n:03d})"))
            for f in fields:
                for cid in f["cids"]:
                    refresh(con, cid, a.d0, a.d1, rules, "created")
            print(f"{owner}: {len(fields)} fields, {sum(f['pieces'] for f in fields)} crop areas, program {kind}"
                  f"{', two clusters' if len(centres) > 1 else ''}: {', '.join(f['name'] for f in fields)}", flush=True)
            done += 1
            if a.commit_every and not a.dry_run and done % a.commit_every == 0:
                con.commit()                                                           # these farmers are there for everybody now

        if not a.no_pin:
            cur.execute("UPDATE serve.demo_time SET mode = 'pinned', pinned_data_date = %s, updated_at = now() WHERE id = 1", (day,))
        cur.execute("SELECT r.status, r.risk_class, r.conditions_met, count(*) FROM curated.risk_assessment r "
                    "JOIN app.crop_area ca USING (crop_area_id) JOIN app.field f USING (field_id) "
                    "WHERE r.date = %s AND f.owner_id NOT LIKE 'sbx-%%' GROUP BY 1, 2, 3 ORDER BY 4 DESC", (day,))
        shown = cur.fetchall()
        if a.dry_run:
            con.rollback()
        print(f"\n{'DRY RUN (rolled back)' if a.dry_run else 'done'}: farmers {a.farmers}, fields {stats['fields']}, crop areas {stats['areas']}, "
              f"split fields {stats['split_fields']}, merged fields {stats['merged']}, sprays {stats['sprays']}, demo day {day}")
        print("programs:", {k.replace('program_', ''): v for k, v in stats.items() if k.startswith('program_')})
        print("picture of the crop areas on the demo day:")
        for status, cls, cm, n in shown:
            print(f"  {n:4d}  status={status:17} class={cls or '-':6} conditions_met={cm}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
