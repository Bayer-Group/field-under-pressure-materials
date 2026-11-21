# -*- coding: utf-8 -*-
"""Spray window of crop areas from the database (rules: backend/app/domain/spray_window.py, config/spray_window.toml).

Reads only views of schema serve: serve.crop_area and serve.risk_daily (the septoria signal of the day) and
serve.spray_weather_hourly (the hourly weather in m/s and in shown time). Nothing is stored: the window is computed on request.
A crop area gets the weather of the grid cell of its assessment, or else of the cell nearest to its centroid (as in
services/crop_area_refresh.py). Times are the shown local time (Europe/Warsaw); the demo shift is already in the views.
"""
from __future__ import annotations

import os
import tomllib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from backend.app.domain import spray_window as sw

ROOT = Path(__file__).resolve().parents[3]
TZ = ZoneInfo("Europe/Warsaw")

_RULES: Optional[sw.Rules] = None


def load_rules(path: str | os.PathLike | None = None) -> sw.Rules:
    """Rules from config/spray_window.toml (or the file in env SPRAY_WINDOW_CONFIG)."""
    p = Path(path or os.environ.get("SPRAY_WINDOW_CONFIG") or ROOT / "config" / "spray_window.toml")
    with open(p, "rb") as fh:
        return sw.Rules.from_config(tomllib.load(fh))


def rules() -> sw.Rules:
    global _RULES
    if _RULES is None:
        _RULES = load_rules()
    return _RULES


def now_shown(at: Optional[datetime] = None) -> datetime:
    """The start of the current hour in shown local time (naive), or of the hour of `at`."""
    t = at or datetime.now(TZ)
    if t.tzinfo is not None:
        t = t.astimezone(TZ).replace(tzinfo=None)
    return t.replace(minute=0, second=0, microsecond=0)


# Crop areas with the septoria assessment of the day and the grid cell of their weather (owner NULL = all, for the analyst).
AREAS_SQL = """
SELECT a.crop_area_id, a.field_id, a.owner_id, a.field_name, a.farmer_crop_id,
       ST_AsGeoJSON(a.geom, 6)::jsonb AS geometry,
       r.risk_class, r.status, r.conditions_met, r.growth_stage_zone, r.protected_until, r.h_hours,
       COALESCE(r.grid_id, (SELECT g.grid_id FROM raw.grid_cell g ORDER BY g.geom <-> ST_Centroid(a.geom) LIMIT 1)) AS grid_id
FROM serve.crop_area a
LEFT JOIN serve.risk_daily r ON r.crop_area_id = a.crop_area_id AND r.disease = 'septoria' AND r.date = %(day)s
WHERE (%(owner)s::text IS NULL OR a.owner_id = %(owner)s) AND (%(area)s::text IS NULL OR a.crop_area_id = %(area)s)
ORDER BY a.crop_area_id
"""

HOURS_SQL = """
SELECT grid_id, local_time, wind_speed_ms, wind_gust_ms, temperature, precipitation
FROM serve.spray_weather_hourly
WHERE grid_id = ANY(%(cells)s) AND local_time >= %(t0)s AND local_time < %(t1)s
ORDER BY grid_id, local_time
"""


def _hours(con, cells: list[str], now: datetime, r: sw.Rules) -> dict[str, list[sw.Hour]]:
    """The next horizon_hours of every cell, one Hour per expected hour (a missing hour has None values)."""
    rows = con.execute(HOURS_SQL, {"cells": cells, "t0": now, "t1": now + timedelta(hours=r.horizon_hours)}).fetchall()
    seen: dict[str, dict[datetime, dict]] = {c: {} for c in cells}
    for row in rows:
        seen[row["grid_id"]][row["local_time"]] = row
    out = {}
    for cell, by_time in seen.items():
        hours = []
        for i in range(r.horizon_hours):
            t = now + timedelta(hours=i)
            row = by_time.get(t)
            if row is None:
                hours.append(sw.Hour(t, None, None, None, None))
            else:
                hours.append(sw.Hour(t, row["wind_speed_ms"], row["wind_gust_ms"], row["temperature"], row["precipitation"]))
        out[cell] = hours
    return out


def compute(con, owner_id: Optional[str], at: Optional[datetime] = None, work_hours: Optional[tuple[int, int]] = None,
            crop_area_id: Optional[str] = None) -> tuple[datetime, list[tuple[dict, dict]]]:
    """[(crop area row, assessment of domain.spray_window.assess)]: the crop areas of owner_id (None = all, the analyst),
    or only crop_area_id."""
    r = rules()
    now = now_shown(at)
    params = {"day": now.date(), "owner": owner_id, "area": crop_area_id}
    areas = con.execute(AREAS_SQL, params).fetchall()
    cells = sorted({a["grid_id"] for a in areas if a["grid_id"]})
    hours = _hours(con, cells, now, r) if cells else {}
    out = []
    for a in areas:
        result = sw.assess(a, hours.get(a["grid_id"], []), now, r, work_hours)
        out.append((a, result))
    return now, out


def iso(t: Optional[datetime]) -> Optional[str]:
    """Shown local time as ISO 8601 with the offset of Europe/Warsaw."""
    return None if t is None else t.replace(tzinfo=TZ).isoformat()


def notes(r: sw.Rules) -> dict:
    """What every answer carries (note 1 and 5.1): the disclaimer, the wind height, the replay label and the limits used."""
    return {
        "disclaimer": r.texts.get("disclaimer"),
        "wind_height": r.texts.get("wind_height"),
        "source": r.source_label,
        "source_note": r.texts.get("replay") if r.source_label == "replay" else None,
        "limits": {
            "wind_max_ms": r.wind_max_ms, "gust_max_ms": r.gust_max_ms,
            "temperature_min_c": r.temperature_min_c, "temperature_max_c": r.temperature_max_c,
            "precipitation_max_mm": r.precipitation_max_mm, "min_window_hours": r.min_window_hours,
            "horizon_hours": r.horizon_hours, "indicative_after_hours": r.indicative_after_hours,
        },
        "origin": r.origin,
    }
