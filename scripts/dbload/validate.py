"""Post-load checks in plain SQL (COUNT / GROUP BY / LEFT JOIN / SUM). Tables may hold rows the loader
did not write, so absolute counts are informational; integrity problems are FAIL."""
from __future__ import annotations

from .backends.base import Backend
from .config import Settings

GRID_CELLS_FULL = 21_196          # weather_grids.parquet


def run_validation(b: Backend, s: Settings, ds_report: dict) -> list[dict]:
    out: list[dict] = []

    def add(check: str, status: str, detail: str) -> None:
        out.append({"check": check, "status": status, "detail": detail})

    def scalar(sql: str):
        return b.query(sql)[0][0]

    tq = b.tq
    have = {t: b.table_exists(t) for t in ("grid_cell", "weather_hourly", "field", "field_crop_share", "crop_class", "ingest_log")}

    for t in ("grid_cell", "weather_hourly", "field", "field_crop_share"):
        if have[t]:
            add(f"{t}: rows", "INFO", f"{b.count(t):,} in {b.phys(t)}")
    if have["grid_cell"] and not (s.limit_files or s.voiv):
        n = b.count("grid_cell")
        add("grid_cell: full grid", "OK" if n == GRID_CELLS_FULL else "WARN", f"{n:,} cells (source has {GRID_CELLS_FULL:,})")

    def orphans(child, col, parent, pcol, label):
        if not (have.get(child) and have.get(parent)):
            return
        n = scalar(f"SELECT COUNT(*) FROM (SELECT DISTINCT {b.qi(col)} AS k FROM {tq(child)}) c "
                   f"LEFT JOIN {tq(parent)} p ON p.{b.qi(pcol)} = c.k WHERE p.{b.qi(pcol)} IS NULL AND c.k IS NOT NULL")
        add(label, "OK" if n == 0 else "FAIL", f"{n:,} orphan key(s)")

    orphans("weather_hourly", "grid_id", "grid_cell", "grid_id", "weather_hourly.grid_id in grid_cell")
    orphans("field_crop_share", "field_id", "field", "field_id", "field_crop_share.field_id in field")
    orphans("field_crop_share", "class_code", "crop_class", "code", "field_crop_share.class_code in crop_class")

    if have["field_crop_share"]:
        bad = scalar(f"SELECT COUNT(*) FROM (SELECT field_id, year, SUM(share) AS s FROM {tq('field_crop_share')} "
                     "GROUP BY field_id, year) x WHERE s > 1.0001")
        add("field_crop_share: shares per field/year <= 1", "OK" if bad == 0 else "FAIL", f"{bad:,} field-year(s) above 1")
    if have["weather_hourly"] and ds_report.get("weather_hourly", {}).get("loaded"):
        nulls = scalar(f"SELECT COUNT(*) FROM {tq('weather_hourly')} WHERE precipitation IS NULL")
        add("weather_hourly: precipitation NULL rows", "INFO", f"{nulls:,} (no IMERG match)")
    if have["ingest_log"]:
        for ds in ("grid_cell", "weather_hourly", "field", "field_crop_share"):
            if have[ds]:
                logged = scalar(f"SELECT COALESCE(SUM(row_count), 0) FROM {tq('ingest_log')} WHERE dataset = '{ds}'")
                add(f"{ds}: ingest_log rows", "INFO", f"{int(logged):,} logged vs {b.count(ds):,} in table")

    for name, r in ds_report.items():
        if r.get("status") == "failed":
            add(f"{name}: load", "FAIL", r.get("message", "failed"))
    return out
