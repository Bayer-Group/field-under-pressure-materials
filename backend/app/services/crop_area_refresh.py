# -*- coding: utf-8 -*-
"""Refresh the curated results of one crop area: crop map, field context and septoria risk assessment.

Contract: docs/curated_layer_contract.md, sections 2.2, 2.3 and 3. Rules and thresholds: config/septoria.toml; the class logic is
backend/app/domain/septoria.py. Used by the API when a farmer saves a crop area or a spray and by scripts/refresh_crop_area.py.
For each crop area everything is deleted and rewritten inside the caller's transaction. Reads raw.cropland_cty, raw.soil_h3,
raw.grid_cell, curated.weather_*_features and app.*; writes curated.crop_area_crop_map, curated.field_context,
curated.risk_assessment and curated.risk_change. A field gets the weather of the grid cell nearest to its centroid (no interpolation).
"""
from __future__ import annotations

import json
import os
import tomllib
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from psycopg.rows import tuple_row

from backend.app.domain import septoria

ROOT = Path(__file__).resolve().parents[3]


def load_rules(path: str | os.PathLike | None = None) -> septoria.Rules:
    """Rules from config/septoria.toml (or the file in env SEPTORIA_CONFIG)."""
    p = Path(path or os.environ.get("SEPTORIA_CONFIG") or ROOT / "config" / "septoria.toml")
    with open(p, "rb") as fh:
        return septoria.Rules.from_config(tomllib.load(fh))


CROP_MAP_YEAR = 2024
DISEASE = "septoria"

# Mosaic of all tiles that touch the polygon: resampled (nearest neighbour) onto the pixel grid of the first tile, where tiles
# overlap the larger value wins (padding is 0), then clipped to the polygon (a pixel counts when its centre is inside).
CROP_MAP_SQL = """
WITH area AS (SELECT geom FROM app.crop_area WHERE crop_area_id = %(id)s),
tiles AS (
    SELECT t.rid, t.rast FROM raw.cropland_cty t, area a
    WHERE t.year = %(year)s AND ST_Intersects(t.rast::geometry, a.geom)
),
ref AS (SELECT rast FROM tiles ORDER BY rid LIMIT 1),
mosaic AS (
    SELECT ST_Union(
        ST_Resample(t.rast, ST_ScaleX(r.rast), ST_ScaleY(r.rast), ST_UpperLeftX(r.rast), ST_UpperLeftY(r.rast),
                    0, 0, 'NearestNeighbour'), 1, 'MAX') AS rast
    FROM tiles t, ref r
),
clipped AS (
    SELECT ST_Clip(ST_SetBandNoDataValue(m.rast, 1, 65534), 1, a.geom, 65534, true) AS rast FROM mosaic m, area a
    WHERE m.rast IS NOT NULL
)
SELECT (vc).value::int AS class_code, (vc).count::bigint AS pixel_count
FROM clipped, ST_ValueCount(clipped.rast, 1, true) AS vc
ORDER BY 1
"""

SOIL_SQL = """
WITH area AS (SELECT ST_Transform(geom, 2180) AS g FROM app.crop_area WHERE crop_area_id = %(id)s),
cells AS (
    SELECT s.*, ST_Area(ST_Intersection(ST_Transform(s.geom, 2180), a.g)) AS w
    FROM raw.soil_h3 s, area a
    WHERE s.geom && ST_Transform(a.g, 4326) AND ST_Intersects(ST_Transform(s.geom, 2180), a.g)
)
SELECT
    count(*)::int AS cell_count,
    COALESCE(sum(w) FILTER (WHERE ph IS NOT NULL) / NULLIF((SELECT ST_Area(g) FROM area), 0), 0)::real AS coverage,
    (sum(ph * w) FILTER (WHERE ph IS NOT NULL) / NULLIF(sum(w) FILTER (WHERE ph IS NOT NULL), 0))::real AS ph,
    (sum(clay * w) FILTER (WHERE clay IS NOT NULL) / NULLIF(sum(w) FILTER (WHERE clay IS NOT NULL), 0))::real AS clay,
    (sum(sand * w) FILTER (WHERE sand IS NOT NULL) / NULLIF(sum(w) FILTER (WHERE sand IS NOT NULL), 0))::real AS sand,
    (sum(silt * w) FILTER (WHERE silt IS NOT NULL) / NULLIF(sum(w) FILTER (WHERE silt IS NOT NULL), 0))::real AS silt,
    (sum(om * w) FILTER (WHERE om IS NOT NULL) / NULLIF(sum(w) FILTER (WHERE om IS NOT NULL), 0))::real AS om,
    (sum(cec * w) FILTER (WHERE cec IS NOT NULL) / NULLIF(sum(w) FILTER (WHERE cec IS NOT NULL), 0))::real AS cec,
    (sum(bulk_density * w) FILTER (WHERE bulk_density IS NOT NULL)
        / NULLIF(sum(w) FILTER (WHERE bulk_density IS NOT NULL), 0))::real AS bulk_density,
    (SELECT soil_texture FROM cells WHERE soil_texture IS NOT NULL GROUP BY soil_texture
        ORDER BY sum(w) DESC, soil_texture LIMIT 1) AS texture
FROM cells
"""

CELL_SQL = """
SELECT g.grid_id FROM raw.grid_cell g, app.crop_area a
WHERE a.crop_area_id = %(id)s ORDER BY g.geom <-> ST_Centroid(a.geom) LIMIT 1
"""


def refresh_crop_map(cur, crop_area_id: str, year: int = CROP_MAP_YEAR) -> list[tuple[int, int]]:
    """Rewrite curated.crop_area_crop_map; returns [(class_code, pixel_count)]. A polygon outside the tiles gives no rows."""
    cur.execute("DELETE FROM curated.crop_area_crop_map WHERE crop_area_id = %s", (crop_area_id,))
    cur.execute(CROP_MAP_SQL, {"id": crop_area_id, "year": year})
    rows = [(r[0], r[1]) for r in cur.fetchall()]
    total = sum(n for _, n in rows)
    if not total:
        return []
    dominant = min(rows, key=lambda r: (-r[1], r[0]))[0]            # largest share; ties: lowest class_code
    for code, n in rows:
        cur.execute(
            "INSERT INTO curated.crop_area_crop_map (crop_area_id, year, class_code, pixel_count, total_pixels, share, is_map_crop) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)", (crop_area_id, year, code, n, total, n / total, code == dominant))
    return rows


def refresh_field_context(cur, crop_area_id: str, crop_map: list[tuple[int, int]], year: int = CROP_MAP_YEAR) -> None:
    cur.execute(SOIL_SQL, {"id": crop_area_id})
    n, cov, ph, clay, sand, silt, om, cec, bd, texture = cur.fetchone()
    map_class = min(crop_map, key=lambda r: (-r[1], r[0]))[0] if crop_map else None
    cur.execute("SELECT m.class_code FROM app.crop_area a JOIN curated.crop_mapping m USING (farmer_crop_id) "
                "WHERE a.crop_area_id = %s", (crop_area_id,))
    row = cur.fetchone()
    farmer_class = row[0] if row else None
    differs = None if map_class is None or farmer_class is None else map_class != farmer_class
    cur.execute("DELETE FROM curated.field_context WHERE crop_area_id = %s", (crop_area_id,))
    cur.execute(
        "INSERT INTO curated.field_context (crop_area_id, soil_ph, soil_clay, soil_sand, soil_silt, soil_om, soil_cec, "
        "soil_bulk_density, soil_texture, soil_cell_count, soil_coverage, crop_map_year, map_crop_class_code, "
        "farmer_class_code, crop_differs) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (crop_area_id, ph, clay, sand, silt, om, cec, bd, texture, n, min(cov, 1.0), year if crop_map else None,
         map_class, farmer_class, differs))


def refresh_risk(cur, crop_area_id: str, d0: date, d1: date, rules: septoria.Rules, reason: str = "recompute") -> int:
    """Rewrite curated.risk_assessment of the crop area for the local days d0..d1; returns the number of rows.
    Changes of class, status or conditions_met are logged in curated.risk_change with the given reason
    (created, recompute, spray, sowing, weather, rules)."""
    cur.execute(CELL_SQL, {"id": crop_area_id})
    row = cur.fetchone()
    if not row:
        return 0
    grid_id = row[0]
    cur.execute("SELECT farmer_crop_id, bbch_override FROM app.crop_area WHERE crop_area_id = %s", (crop_area_id,))
    crop, bbch = cur.fetchone()
    winter_crop = crop == "wheat"                                  # spring wheat has no separate crop id: stage_unknown later
    cur.execute("SELECT spray_date, protection_duration_days FROM app.spray WHERE crop_area_id = %s", (crop_area_id,))
    sprays = cur.fetchall()
    cur.execute("SELECT utc_time, date, is_wet FROM curated.weather_hourly_features WHERE grid_id = %s "
                "AND date BETWEEN %s AND %s ORDER BY utc_time", (grid_id, d0 - timedelta(days=4), d1))
    hours: dict[datetime, bool | None] = {}
    last_hour: dict[date, datetime] = {}                           # the last hour of each local day (rows are ordered)
    for utc_time, local_date, is_wet in cur.fetchall():
        hours[utc_time] = is_wet
        if d0 <= local_date <= d1:
            last_hour[local_date] = utc_time
    cur.execute("SELECT date, gdd_since_resumption FROM curated.weather_daily_features WHERE grid_id = %s "
                "AND date BETWEEN %s AND %s", (grid_id, d0, d1))
    gdd = {r[0]: r[1] for r in cur.fetchall()}

    cur.execute("SELECT date, risk_class, status, conditions_met FROM curated.risk_assessment WHERE crop_area_id = %s "
                "AND disease = %s AND date BETWEEN %s AND %s", (crop_area_id, DISEASE, d0, d1))
    previous = {r[0]: tuple(r[1:]) for r in cur.fetchall()}
    cur.execute("DELETE FROM curated.risk_assessment WHERE crop_area_id = %s AND disease = %s AND date BETWEEN %s AND %s",
                (crop_area_id, DISEASE, d0, d1))
    risk_rows, change_rows = [], []                                # written in one batch (pipeline) after the loop
    day = d0
    while day <= d1:
        end = last_hour.get(day)
        if end is None:                                            # no weather for this day at all
            day += timedelta(days=1)
            continue
        flags = [hours.get(end - timedelta(hours=i)) for i in range(rules.window_hours - 1, -1, -1)]
        active = [(s, p) for s, p in sprays if s <= day]
        spray_date, prot = max(active, key=lambda sp_: sp_[0] + timedelta(days=sp_[1])) if active else (None, None)
        r = septoria.assess(day, flags, gdd=gdd.get(day), bbch_override=bbch, winter_crop=winter_crop,
                            spray_date=spray_date, protection_days=prot, rules=rules)
        risk_rows.append((crop_area_id, DISEASE, day, grid_id, r["h_hours"], r["h_low"], r["h_high"], r["risk_class"], r["status"],
                          r["threshold_medium"], r["threshold_high"], r["coverage"], r["protected_until"], r["growth_stage_zone"],
                          r["growth_stage_source"], r["gdd_since_resumption"], r["conditions_met"], json.dumps(r["reasons"]),
                          datetime.now(timezone.utc), r["model_version"], r["input_hash"]))
        old, new = previous.get(day), (r["risk_class"], r["status"], r["conditions_met"])
        if old != new:                                             # log only real changes (and the first calculation)
            o = old or (None, None, None)
            change_rows.append((crop_area_id, DISEASE, day, "created" if old is None else reason, o[0], new[0], o[1], new[1],
                                o[2], new[2], r["input_hash"]))
        day += timedelta(days=1)
    if risk_rows:
        cur.executemany(
            "INSERT INTO curated.risk_assessment (crop_area_id, disease, date, grid_id, h_hours, h_low, h_high, risk_class, "
            "status, threshold_medium, threshold_high, coverage, protected_until, growth_stage_zone, growth_stage_source, "
            "gdd_since_resumption, conditions_met, reasons, computed_at, model_version, input_hash) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", risk_rows)
    if change_rows:
        cur.executemany(
            "INSERT INTO curated.risk_change (crop_area_id, disease, date, reason, old_class, new_class, old_status, "
            "new_status, old_conditions_met, new_conditions_met, new_input_hash) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            change_rows)
    return len(risk_rows)


def refresh(con, crop_area_id: str, d0: date, d1: date, rules: septoria.Rules, reason: str = "recompute",
            what: str = "all") -> dict:
    """Refresh one crop area inside the caller's transaction. what="all": crop map, field context and risk assessment (a new or
    changed geometry or crop); what="risk": only the risk assessment (a spray changes nothing in the crop map or the soil)."""
    if what not in ("all", "risk"):
        raise ValueError("what must be 'all' or 'risk'")
    with con.cursor(row_factory=tuple_row) as cur:           # tuple rows whatever the connection's row factory is
        crop_map = []
        if what == "all":
            crop_map = refresh_crop_map(cur, crop_area_id)
            refresh_field_context(cur, crop_area_id, crop_map)
        days = refresh_risk(cur, crop_area_id, d0, d1, rules, reason)
    return {"crop_area_id": crop_area_id, "map_classes": len(crop_map), "risk_days": days}
