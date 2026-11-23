#!/usr/bin/env python3
"""Verify the example farmers in the database against the criteria of the demo, and optionally write a map to look at.

    export LOAD_DB_DSN="postgresql://user:password@localhost:5433/dbname"
    python scripts/verify_mock_farmers.py                       # the checks
    python scripts/verify_mock_farmers.py --html data/_loader/mock_farms.html     # + a map (open it in a browser)

Hard criteria give FAIL (exit code 1); distributions that only need a look give WARN. Reads only. The criteria are the ones the farmers
were generated for (scripts/generate_mock_farmers.py): a few fields per farmer and almost never one, compact farms, mostly wheat, only
some parcels split into at most 3 tappable pieces cut across the long axis, crop areas inside their parcels and not overlapping, sprays
that follow a septoria programme before the demo day, readable names, logins with the number of the farmer, more than one colour in
a farm on the demo day.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import statistics
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app.core.security import verify_password  # noqa: E402

RESULT = {"fail": 0, "warn": 0}
EX = "f.owner_id LIKE 'farmer-%%' AND f.data_status = 'mock'"
COLOURS = {"protected": "#3b6fd4", "high": "#d73027", "medium": "#f0a830", "low": "#4f9a76", "grey": "#9a9a9a"}


def report(level: str, name: str, ok: bool, detail: str = "") -> None:
    tag = "OK  " if ok else ("FAIL" if level == "fail" else "WARN")
    if not ok:
        RESULT[level] += 1
    print(f"  {tag} {name}" + (f"  [{detail}]" if detail else ""))


def pct(n: int, total: int) -> float:
    return 100.0 * n / total if total else 0.0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dsn", help="connection string (default: env LOAD_DB_DSN)")
    ap.add_argument("--html", type=Path, help="write a map of the example farms to this file")
    ap.add_argument("--password-word", default="demo")
    a = ap.parse_args(argv)
    dsn = a.dsn or os.environ.get("LOAD_DB_DSN")
    if not dsn:
        sys.exit("no connection string: set env LOAD_DB_DSN or pass --dsn")
    import psycopg
    con = psycopg.connect(dsn)
    q = lambda sql, *args: con.execute(sql, args).fetchall()
    day = q("SELECT pinned_data_date FROM serve.demo_time WHERE id = 1")[0][0]

    farmers = {r[0]: r[1] for r in q(f"SELECT f.owner_id, count(*) FROM app.field f WHERE {EX} GROUP BY 1")}
    areas_per = {r[0]: r[1] for r in q(f"SELECT f.owner_id, count(*) FROM app.crop_area a JOIN app.field f USING (field_id) WHERE {EX} GROUP BY 1")}
    n = len(farmers)
    print(f"{n} example farmers, {sum(farmers.values())} fields, {sum(areas_per.values())} crop areas; demo day (data time) {day}\n")
    if not n:
        print("no example farmers")
        return 1

    print("== farmers and fields")
    dist = Counter(farmers.values())
    print("   fields per farmer:", dict(sorted(dist.items())), "| crop areas per farmer: mean %.1f, max %d" % (statistics.mean(areas_per.values()), max(areas_per.values())))
    report("fail", "almost no farmer with one field (at most 3 %)", pct(dist.get(1, 0), n) <= 3, f"{pct(dist.get(1, 0), n):.0f} %")
    report("warn", "about half of the farmers or more have exactly 3 fields (at least 45 %)", pct(dist.get(3, 0), n) >= 45,f"{pct(dist.get(3, 0), n):.0f} %")
    report("fail", "no more than 5 fields and 8 crop areas per farmer", max(farmers.values()) <= 5 and max(areas_per.values()) <= 8,
           f"max {max(farmers.values())} fields, {max(areas_per.values())} areas")
    report("fail", "enough farmers for a room (at least 90), every one with at least 2 crop areas", n >= 90 and min(areas_per.values()) >= 2, f"{n} farmers, min {min(areas_per.values())} areas")

    print("\n== crops")
    crops = Counter({r[0]: r[1] for r in q(f"SELECT a.farmer_crop_id, count(*) FROM app.crop_area a JOIN app.field f USING (field_id) WHERE {EX} GROUP BY 1")})
    total = sum(crops.values())
    print("   crop areas by crop:", dict(crops))
    report("fail", "less than 20 % not wheat", pct(total - crops["wheat"], total) < 20, f"{pct(total - crops['wheat'], total):.0f} % not wheat")
    report("warn", "about 10 % not wheat (5 to 15 %)", 5 <= pct(total - crops["wheat"], total) <= 15)
    bad = q(f"SELECT f.field_id FROM app.field f JOIN app.crop_area a USING (field_id) WHERE {EX} AND a.farmer_crop_id <> 'wheat' "
            "GROUP BY f.field_id HAVING count(*) > 1 OR (SELECT count(*) FROM app.field_parcel p WHERE p.field_id = f.field_id) > 1")
    report("fail", "a field of another crop is never split or merged", not bad, f"{len(bad)} exceptions")
    mismatch = q(f"SELECT count(*) FILTER (WHERE c.crop_differs), count(*) FROM curated.field_context c JOIN app.crop_area a USING (crop_area_id) JOIN app.field f USING (field_id) WHERE {EX}")[0]
    report("warn", "the crop map agrees with the farmer's crop on almost all crop areas (at most 8 % differ)", pct(mismatch[0], mismatch[1]) <= 8, f"{mismatch[0]} of {mismatch[1]}")

    print("\n== geometry: parcels, no overlaps, nothing outside")
    no_parcel = q(f"SELECT count(*) FROM app.field f WHERE {EX} AND NOT EXISTS (SELECT 1 FROM app.field_parcel p WHERE p.field_id = f.field_id)")[0][0]
    report("fail", "every field is linked to its parcels", no_parcel == 0, f"{no_parcel} without")
    unnamed = q(f"SELECT count(*) FROM app.field f JOIN app.field_parcel p USING (field_id) JOIN app.parcel c USING (parcel_id) WHERE {EX} AND c.commune IS NULL")[0][0]
    report("warn", "the parcels have names of their place", unnamed == 0, f"{unnamed} without")
    invalid = q(f"SELECT count(*) FROM app.crop_area a JOIN app.field f USING (field_id) WHERE {EX} AND NOT ST_IsValid(a.geom)")[0][0]
    report("fail", "all geometries are valid polygons", invalid == 0, f"{invalid} invalid")
    outside = q(f"""SELECT count(*) FROM (SELECT a.crop_area_id, ST_Area(ST_Transform(ST_Difference(a.geom, (SELECT ST_Union(p.geom) FROM app.field_parcel fp
        JOIN app.parcel p USING (parcel_id) WHERE fp.field_id = a.field_id)), 2180)) AS m2 FROM app.crop_area a JOIN app.field f USING (field_id) WHERE {EX}) x WHERE m2 > 5""")[0][0]   # under 5 m2: rounding of the cut
    report("fail", "every crop area lies inside the parcels of its field", outside == 0, f"{outside} stick out")
    holes = q(f"""SELECT count(*) FROM (SELECT f.field_id, ST_Area(ST_Transform(ST_Difference((SELECT ST_Union(p.geom) FROM app.field_parcel fp JOIN app.parcel p USING (parcel_id)
        WHERE fp.field_id = f.field_id), ST_Union(a.geom)), 2180)) AS m2 FROM app.field f JOIN app.crop_area a USING (field_id) WHERE {EX} GROUP BY f.field_id) x WHERE m2 > 5""")[0][0]
    report("fail", "the crop areas of a field cover its parcels (no gap to confirm)", holes == 0, f"{holes} fields with a gap")
    overlaps = q(f"""SELECT count(*) FROM app.crop_area a JOIN app.crop_area b ON a.crop_area_id < b.crop_area_id AND ST_Intersects(a.geom, b.geom)
        JOIN app.field fa ON fa.field_id = a.field_id JOIN app.field f ON f.field_id = b.field_id WHERE {EX} AND fa.owner_id NOT LIKE 'sbx-%%'
        AND ST_Area(ST_Transform(ST_Intersection(a.geom, b.geom), 2180)) > 0.5""")[0][0]
    report("fail", "no two crop areas overlap", overlaps == 0, f"{overlaps} pairs")

    print("\n== splitting of parcels")
    split_fields = q(f"SELECT f.field_id, f.owner_id, count(*) FROM app.field f JOIN app.crop_area a USING (field_id) WHERE {EX} GROUP BY 1, 2 HAVING count(*) > 1")
    n_fields = sum(farmers.values())
    print(f"   split fields: {len(split_fields)} of {n_fields} ({pct(len(split_fields), n_fields):.0f} %); pieces: {dict(Counter(r[2] for r in split_fields))}")
    report("fail", "at most 3 pieces per parcel", all(r[2] <= 3 for r in split_fields))
    report("warn", "only a part of the fields is split (3 to 30 %)", 3 <= pct(len(split_fields), n_fields) <= 30)
    per_farmer_split = Counter(r[1] for r in split_fields)
    report("fail", "no farmer has all its fields split", all(per_farmer_split[o] < farmers[o] for o in per_farmer_split) or not per_farmer_split)
    small = q(f"""SELECT count(*) FROM (SELECT a.crop_area_id, ST_Area(ST_Transform(a.geom, 2180)) / 10000 AS ha, (ST_MaximumInscribedCircle(ST_Transform(a.geom, 2180))).radius AS r
        FROM app.crop_area a JOIN app.field f USING (field_id) WHERE {EX} AND (SELECT count(*) FROM app.crop_area b WHERE b.field_id = a.field_id) > 1) x WHERE ha < 0.3 OR r < 14""")[0][0]
    report("fail", "every piece is tappable on a phone: at least 0.3 ha and 28 m across", small == 0, f"{small} too small")
    lengthwise = q(f"""WITH pieces AS (
          SELECT a.crop_area_id, a.field_id, ST_ExteriorRing(ST_OrientedEnvelope(ST_Transform(a.geom, 2180))) AS e FROM app.crop_area a
          JOIN app.field f USING (field_id) WHERE {EX} AND (SELECT count(*) FROM app.crop_area b WHERE b.field_id = a.field_id) > 1),
        parent AS (SELECT a.field_id, ST_ExteriorRing(ST_OrientedEnvelope(ST_Transform(ST_Union(a.geom), 2180))) AS e FROM app.crop_area a
          WHERE a.field_id IN (SELECT field_id FROM pieces) GROUP BY 1),
        dims AS (SELECT field_id, crop_area_id, GREATEST(ST_Distance(ST_PointN(e, 1), ST_PointN(e, 2)), ST_Distance(ST_PointN(e, 2), ST_PointN(e, 3))) AS l,
          LEAST(ST_Distance(ST_PointN(e, 1), ST_PointN(e, 2)), ST_Distance(ST_PointN(e, 2), ST_PointN(e, 3))) AS w FROM pieces),
        pdims AS (SELECT field_id, GREATEST(ST_Distance(ST_PointN(e, 1), ST_PointN(e, 2)), ST_Distance(ST_PointN(e, 2), ST_PointN(e, 3))) AS l,
          LEAST(ST_Distance(ST_PointN(e, 1), ST_PointN(e, 2)), ST_Distance(ST_PointN(e, 2), ST_PointN(e, 3))) AS w FROM parent)
        SELECT count(*) FROM dims d JOIN pdims p USING (field_id) WHERE p.l >= 2.5 * p.w AND d.l > 0.85 * p.l""")[0][0]
    report("fail", "a long thin parcel is cut across, never lengthwise (a piece of it is not almost as long as the parcel)", lengthwise == 0, f"{lengthwise} pieces")

    print("\n== compact farms")
    cent = defaultdict(list)
    for owner, lon, lat in q(f"SELECT f.owner_id, ST_X(ST_Centroid(a.geom)), ST_Y(ST_Centroid(a.geom)) FROM app.crop_area a JOIN app.field f USING (field_id) WHERE {EX}"):
        cent[owner].append((lon, lat))
    spread = {}
    for o, pts in cent.items():
        spread[o] = max((math.hypot((p[0] - r[0]) * math.cos(math.radians(p[1])) * 111.32, (p[1] - r[1]) * 110.57) for p in pts for r in pts), default=0.0)
    vals = sorted(spread.values())
    print(f"   the largest distance between the fields of a farm: median {statistics.median(vals):.1f} km, p90 {vals[int(.9 * len(vals))]:.1f}, max {vals[-1]:.1f}")
    report("fail", "no farm wider than 20 km", vals[-1] <= 20, f"max {vals[-1]:.1f} km")
    report("fail", "most farms within 6 km (at least 70 %)", pct(sum(v <= 6 for v in vals), n) >= 70, f"{pct(sum(v <= 6 for v in vals), n):.0f} %")
    report("warn", "farms with a second cluster 8 to 15 km are a minority (5 to 25 %)", 5 <= pct(sum(v > 8 for v in vals), n) <= 25, f"{pct(sum(v > 8 for v in vals), n):.0f} %")

    print("\n== colours on the demo day")
    rows = q(f"""SELECT f.owner_id, f.field_id, a.crop_area_id, a.farmer_crop_id, r.status, r.risk_class, r.conditions_met
        FROM app.crop_area a JOIN app.field f USING (field_id) JOIN curated.risk_assessment r ON r.crop_area_id = a.crop_area_id AND r.date = %s WHERE {EX}""", day)
    state_of = lambda st, cl: "grey" if st == "stage_unknown" else ("protected" if st == "protected" else (cl or "grey"))
    states = Counter(state_of(r[4], r[5]) for r in rows)
    wheat_states = Counter(state_of(r[4], r[5]) for r in rows if r[3] == "wheat")
    tot = sum(wheat_states.values())
    print("   wheat crop areas by state:", {k: f"{pct(v, tot):.0f} %" for k, v in wheat_states.most_common()}, "| all:", dict(states))
    report("fail", "every crop area has its assessment for the demo day", len(rows) == sum(areas_per.values()), f"{len(rows)} of {sum(areas_per.values())}")
    for name, lo, hi in (("protected", 12, 40), ("high", 12, 40), ("medium", 20, 50), ("low", 5, 30)):
        report("warn", f"wheat '{name}' between {lo} and {hi} %", lo <= pct(wheat_states[name], tot) <= hi, f"{pct(wheat_states[name], tot):.0f} %")
    by_farmer = defaultdict(set)
    count_by_farmer = Counter()
    for owner, _, _, _, st, cl, _ in rows:
        by_farmer[owner].add(state_of(st, cl))
        count_by_farmer[owner] += 1
    eligible = [o for o in by_farmer if count_by_farmer[o] >= 3]
    varied = sum(len(by_farmer[o]) >= 2 for o in eligible)
    report("fail", "a farm with 3 or more crop areas shows more than one colour on the demo day (at least 75 % of the farms)", pct(varied, len(eligible)) >= 75, f"{pct(varied, len(eligible)):.0f} % of {len(eligible)}")
    report("warn", "some farms show three or more colours", sum(len(by_farmer[o]) >= 3 for o in eligible) >= 0.2 * len(eligible), f"{sum(len(by_farmer[o]) >= 3 for o in eligible)} farms")

    print("\n== sprays")
    unconf = q(f"SELECT count(*) FROM app.crop_area a JOIN app.field f USING (field_id) WHERE {EX} AND a.sprays_confirmed IS NOT TRUE")[0][0]
    report("fail", "the spray question is answered on every crop area", unconf == 0, f"{unconf} not")
    sp = q(f"SELECT a.crop_area_id, f.owner_id, a.field_id, s.spray_date, s.protection_duration_days FROM app.spray s JOIN app.crop_area a USING (crop_area_id) JOIN app.field f USING (field_id) WHERE {EX} ORDER BY 1, 4")
    report("fail", "all sprays are between 15 April and the demo day", all(date(2024, 4, 15) <= r[3] <= day for r in sp), f"{min((r[3] for r in sp), default=None)} .. {max((r[3] for r in sp), default=None)}")
    report("fail", "a spray protects 14 or 21 days", all(r[4] in (14, 21) for r in sp), str(Counter(r[4] for r in sp)))
    per_area = defaultdict(list)
    for r in sp:
        per_area[r[0]].append(r[3])
    gaps = [(b - a_).days for ds in per_area.values() for a_, b in zip(ds, ds[1:])]
    report("fail", "two sprays of a crop area are 14 to 35 days apart (T1 to T2 are about three weeks)", all(14 <= g <= 35 for g in gaps), f"{len(gaps)} pairs, min {min(gaps, default=0)}, max {max(gaps, default=0)}")
    wheat_ids = {r[2] for r in rows if r[3] == "wheat"}
    unsprayed = len(wheat_ids - set(per_area))
    report("warn", "5 to 30 % of the wheat crop areas have no spray (some farms spray later or not at all)", 5 <= pct(unsprayed, len(wheat_ids)) <= 30, f"{pct(unsprayed, len(wheat_ids)):.0f} %")
    first = defaultdict(list)
    for r in sp:
        first[r[1]].append(r[3])
    wide = sum(1 for ds in first.values() if (max(ds) - min(ds)).days > 40)
    report("warn", "a farm sprays its fields within a few weeks (T1 and T2 included)", wide == 0, f"{wide} farms wider than 40 days")
    nonwheat_sprayed = [r for r in sp if r[0] not in wheat_ids]
    report("fail", "no spray on other crops", not nonwheat_sprayed)

    print("\n== names, logins")
    names = q(f"SELECT f.owner_id, f.name FROM app.field f WHERE {EX}")
    dup = [o for o, c in Counter((r[0], r[1]) for r in names).items() if c > 1]
    report("fail", "field names are unique within a farm", not dup, f"{len(dup)} duplicates")
    report("fail", "names are short and read as a place, not as an id", all(r[1] and len(r[1]) <= 40 and r[1] not in ("tmp",) and not re.search(r"farmer|-p\d|^f-|^Field \d+$", r[1]) for r in names),
           f"e.g. {', '.join(sorted({r[1] for r in names})[:4])}")
    users = {r[0]: (r[1], r[2]) for r in q("SELECT owner_id, password_hash, display_name FROM app.demo_user WHERE role = 'farmer' AND owner_id LIKE 'farmer-%%'")}
    report("fail", "a login for every farmer, with a display name", set(users) == set(farmers) and all(v[1] for v in users.values()), f"{len(users)} logins")
    ok_pw = sum(verify_password(f"{a.password_word}{o.split('-')[1]}", users[o][0]) for o in users if o in farmers)
    report("fail", f"the password of farmerNNN is '{a.password_word}NNN'", ok_pw == len(users), f"{ok_pw} of {len(users)}")
    report("fail", "the analyst login exists", bool(q("SELECT 1 FROM app.demo_user WHERE login = 'analyst'")))
    ids_ok = all(re.fullmatch(r"farmer-\d{3}-p\d", r[0]) for r in q(f"SELECT f.field_id FROM app.field f WHERE {EX}"))
    report("fail", "field ids look like farmer-014-p2 (the copies for visitors show p2, p2a)", ids_ok)
    thin = q(f"SELECT count(*) FROM curated.risk_assessment r JOIN app.crop_area a USING (crop_area_id) JOIN app.field f USING (field_id) WHERE {EX}")[0][0]
    report("fail", "the assessments of the whole season exist for every crop area", thin >= sum(areas_per.values()) * 85, f"{thin} rows")

    if a.html:
        feats = []
        for owner, fname, cid, crop, st, cl, cm, gj, ha in q(f"""SELECT f.owner_id, f.name, a.crop_area_id, a.farmer_crop_id, r.status, r.risk_class, r.conditions_met,
            ST_AsGeoJSON(a.geom, 6), ST_Area(a.geom::geography) / 10000 FROM app.crop_area a JOIN app.field f USING (field_id)
            JOIN curated.risk_assessment r ON r.crop_area_id = a.crop_area_id AND r.date = %s WHERE {EX}""", day):
            s = state_of(st, cl)
            feats.append({"type": "Feature", "geometry": json.loads(gj), "properties": {
                "farmer": owner, "field": fname, "crop": crop, "state": s, "colour": COLOURS[s], "ha": round(float(ha), 2),
                "sprays": ", ".join(f"{d:%d.%m} +{p} d" for d, p in [(r[3], r[4]) for r in sp if r[0] == cid]) or "none"}})
        page = HTML.replace("__DATA__", json.dumps({"type": "FeatureCollection", "features": feats})).replace("__DAY__", str(day)).replace(
            "__FARMERS__", json.dumps(sorted(farmers))).replace("__COLOURS__", json.dumps(COLOURS))
        a.html.parent.mkdir(parents=True, exist_ok=True)
        a.html.write_text(page, encoding="utf-8")
        print(f"\nmap written: {a.html}")
    print(f"\nRESULT: {'OK' if not RESULT['fail'] else 'FAILED'} ({RESULT['fail']} failures, {RESULT['warn']} warnings)")
    return 1 if RESULT["fail"] else 0


HTML = """<!doctype html><html lang="pl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Example farms</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.css">
<style>html,body{height:100%;margin:0;font-family:system-ui,sans-serif}#map{height:calc(100% - 46px)}
#bar{height:46px;display:flex;align-items:center;gap:12px;padding:0 12px;box-sizing:border-box;background:#f4f4f4;border-bottom:1px solid #ccc;flex-wrap:wrap}
.sw{display:inline-block;width:12px;height:12px;border-radius:2px;margin-right:4px;vertical-align:-1px}</style></head><body>
<div id="bar"><b>Example farms</b> on the demo day __DAY__ (data time)
<select id="farmer"><option value="">all farmers</option></select><span id="legend"></span></div><div id="map"></div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.js"></script>
<script>
const data=__DATA__, farmers=__FARMERS__, colours=__COLOURS__;
const labels={protected:"protected after a spray",high:"high",medium:"medium",low:"low",grey:"other crop"};
document.getElementById("legend").innerHTML=Object.keys(labels).map(k=>'<span><i class="sw" style="background:'+colours[k]+'"></i>'+labels[k]+'</span>').join(" &nbsp; ");
const sel=document.getElementById("farmer");farmers.forEach(f=>{const o=document.createElement("option");o.value=f;o.textContent=f;sel.appendChild(o)});
const map=L.map("map");L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png",{maxZoom:19,attribution:"&copy; OpenStreetMap"}).addTo(map);
let layer;function draw(){if(layer)layer.remove();const f=sel.value;
layer=L.geoJSON(data,{filter:x=>!f||x.properties.farmer===f,style:x=>({color:"#222",weight:1,fillColor:x.properties.colour,fillOpacity:.75}),
onEachFeature:(x,l)=>l.bindPopup("<b>"+x.properties.field+"</b><br>"+x.properties.farmer+"<br>"+x.properties.crop+", "+x.properties.ha+" ha<br>state: "+labels[x.properties.state]+"<br>sprays: "+x.properties.sprays)}).addTo(map);
map.fitBounds(layer.getBounds(),{padding:[20,20],maxZoom:f?16:9})}
sel.onchange=draw;draw();</script></body></html>
"""

if __name__ == "__main__":
    sys.exit(main())
