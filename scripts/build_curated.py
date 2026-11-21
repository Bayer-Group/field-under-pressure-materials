#!/usr/bin/env python3
"""Build the curated weather features from the raw layer (docs/curated_layer_contract.md, sections 1, 1.1, 1.2).

    export LOAD_DB_DSN="postgresql://user:password@localhost:5433/dbname"      # the same variable as the loader
    python scripts/build_curated.py weather                                   # everything loaded in raw
    python scripts/build_curated.py weather --from 2024-04-01 --to 2024-06-30 # hourly features for a range

Reads raw tables only. Writes curated.weather_hourly_features, weather_daily_features and vegetation_resumption.
Rules and thresholds come from config/septoria.toml. Repeatable: each run deletes and rewrites its range (hourly
features) or its year (daily features and resumption), in one transaction.
"""
from __future__ import annotations

import argparse
import os
import sys
import tomllib
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app.domain import septoria  # noqa: E402

HOURLY = """
INSERT INTO curated.weather_hourly_features
    (grid_id, utc_time, date, local_time, relative_humidity, precipitation, temperature, is_wet, wind_speed_2m_flag)
SELECT grid_id, utc_time, date, local_time, relative_humidity, precipitation, temperature,
       CASE
         WHEN relative_humidity >= %(rh_min)s OR precipitation > %(p_min)s THEN true
         WHEN relative_humidity IS NULL OR precipitation IS NULL THEN NULL   -- unknown, not dry
         ELSE false
       END,
       COALESCE(wind_speed_2m < 0, false)
FROM raw.weather_hourly
WHERE date BETWEEN %(d0)s AND %(d1)s
"""

DAILY = """
INSERT INTO curated.weather_daily_features
    (grid_id, date, t_mean, gdd3, wet_hours, valid_hours, expected_hours, coverage)
SELECT d.grid_id, d.date, d.avg_temperature, GREATEST(d.avg_temperature - %(gdd_base)s, 0),
       h.wet_hours, h.valid_hours, e.expected,
       CASE WHEN h.valid_hours IS NULL THEN NULL ELSE h.valid_hours::real / e.expected END
FROM raw.weather_daily d
LEFT JOIN (SELECT grid_id, date, count(*) FILTER (WHERE is_wet) AS wet_hours, count(is_wet) AS valid_hours
           FROM curated.weather_hourly_features GROUP BY grid_id, date) h USING (grid_id, date)
CROSS JOIN LATERAL (SELECT round(extract(epoch FROM ((d.date + 1)::timestamp AT TIME ZONE 'Europe/Warsaw'
                                                    - d.date::timestamp AT TIME ZONE 'Europe/Warsaw')) / 3600)::int AS expected) e
WHERE d.date >= %(y0)s AND d.date < %(y1)s
"""

# first day after the cut-off from which t_mean >= tmin holds for k consecutive days (k is an int from the config)
RESUMPTION = """
INSERT INTO curated.vegetation_resumption (grid_id, year, resumption_date)
SELECT c.grid_id, %(year)s, r.resumption_date
FROM (SELECT DISTINCT grid_id FROM curated.weather_daily_features WHERE date >= %(y0)s AND date < %(y1)s) c
LEFT JOIN (
    SELECT grid_id, min(date) AS resumption_date
    FROM (SELECT grid_id, date,
                 count(*) FILTER (WHERE t_mean >= %(tmin)s)
                     OVER (PARTITION BY grid_id ORDER BY date ROWS BETWEEN CURRENT ROW AND {k1} FOLLOWING) AS warm_days,
                 count(*) OVER (PARTITION BY grid_id ORDER BY date ROWS BETWEEN CURRENT ROW AND {k1} FOLLOWING) AS window_days
          FROM curated.weather_daily_features
          WHERE date > %(after)s AND date < %(y1)s) w
    WHERE warm_days = %(k)s AND window_days = %(k)s
    GROUP BY grid_id) r USING (grid_id)
"""

GDD_SINCE = """
UPDATE curated.weather_daily_features f SET gdd_since_resumption = c.cum
FROM (SELECT f2.grid_id, f2.date,
             CASE WHEN r.resumption_date IS NOT NULL AND f2.date >= r.resumption_date
                  THEN sum(f2.gdd3) FILTER (WHERE f2.date >= r.resumption_date)
                           OVER (PARTITION BY f2.grid_id ORDER BY f2.date) END AS cum
      FROM curated.weather_daily_features f2
      JOIN curated.vegetation_resumption r ON r.grid_id = f2.grid_id AND r.year = %(year)s
      WHERE f2.date >= %(y0)s AND f2.date < %(y1)s) c
WHERE f.grid_id = c.grid_id AND f.date = c.date
"""


def load_config(path: Path) -> dict:
    with open(path, "rb") as fh:
        return tomllib.load(fh)["septoria"]


def build_weather(con, cfg: dict, d0: date | None, d1: date | None, log=print) -> None:
    cur = con.cursor()
    wet, gs = cfg["wet_hour"], cfg["growth_stage"]
    cur.execute("SELECT min(date), max(date) FROM raw.weather_hourly")
    h0, h1 = cur.fetchone()
    d0, d1 = d0 or h0, d1 or h1
    if h0 is not None and d0 is not None:
        cur.execute("DELETE FROM curated.weather_hourly_features WHERE date BETWEEN %s AND %s", (d0, d1))
        cur.execute(HOURLY, {"rh_min": wet["rh_min"], "p_min": wet["precipitation_min_mm"], "d0": d0, "d1": d1})
        log(f"hourly features {d0} .. {d1}: {cur.rowcount:,} rows")
    cur.execute("SELECT min(date), max(date) FROM raw.weather_daily")
    w0, w1 = cur.fetchone()
    if w0 is None:
        log("no daily weather in raw: daily features skipped")
        return
    k = int(gs["resumption_consecutive_days"])
    for year in range(w0.year, w1.year + 1):
        p = {"year": year, "y0": date(year, 1, 1), "y1": date(year + 1, 1, 1), "gdd_base": gs["gdd_base"],
             "tmin": gs["resumption_t_mean_min"], "k": k,
             "after": date(year, *map(int, gs["resumption_after"].split("-")))}
        cur.execute("DELETE FROM curated.weather_daily_features WHERE date >= %(y0)s AND date < %(y1)s", p)
        cur.execute(DAILY, p)
        n_daily = cur.rowcount
        cur.execute("DELETE FROM curated.vegetation_resumption WHERE year = %(year)s", p)
        cur.execute(RESUMPTION.format(k1=k - 1), p)
        n_res = cur.rowcount
        cur.execute(GDD_SINCE, p)
        log(f"{year}: daily features {n_daily:,} rows, resumption {n_res:,} cells, gdd updated {cur.rowcount:,} rows")


def build_cells(con, rules, d0: date | None, d1: date | None, log=print) -> None:
    """curated.septoria_cell_day: H and the class per grid cell and local day (the window of the last hour of the day), with
    the same functions as the per-field assessment. Days with coverage below min_coverage are not written."""
    from itertools import groupby
    from datetime import timedelta
    n, step = rules.window_hours, timedelta(hours=1)
    cur = con.cursor()
    cur.execute("SELECT min(date), max(date) FROM curated.weather_hourly_features")
    h0, h1 = cur.fetchone()
    d0, d1 = d0 or h0, d1 or h1
    if h0 is None:
        log("no hourly features: run `weather` first")
        return
    cur.execute("DELETE FROM curated.septoria_cell_day WHERE date BETWEEN %s AND %s", (d0, d1))
    out = []                                                       # ~220k small rows: kept, then written with one COPY
    with con.cursor(name="cell_stream") as src:                    # server-side cursor: the hourly rows are streamed
        src.itersize = 20000
        src.execute("SELECT grid_id, utc_time, date, is_wet FROM curated.weather_hourly_features "
                    "WHERE date BETWEEN %s AND %s ORDER BY grid_id, utc_time", (d0 - timedelta(days=4), d1))
        for grid_id, rows in groupby(src, key=lambda r: r[0]):
            wet, last = {}, {}
            for _, t, d, w in rows:
                wet[t] = w
                last[d] = t                                        # rows are ordered: the last hour of each local day
            for day, end in last.items():
                if not d0 <= day <= d1:
                    continue
                flags = [wet.get(end - step * i) for i in range(n - 1, -1, -1)]
                cov = sum(f is not None for f in flags) / n
                if cov < rules.min_coverage:
                    continue
                lo, hi = septoria.longest_run(flags, False), septoria.longest_run(flags, True)
                c_lo, c_hi = septoria.classify(lo, rules), septoria.classify(hi, rules)
                out.append((grid_id, day, lo, hi, cov, c_lo, c_lo != c_hi, rules.model_version))
    with cur.copy("COPY curated.septoria_cell_day (grid_id, date, h_low, h_high, coverage, risk_class, uncertain, "
                  "model_version) FROM STDIN") as cp:
        for row in out:
            cp.write_row(row)
    log(f"septoria per cell and day {d0} .. {d1}: {len(out):,} rows")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("cells", help="septoria H and class per grid cell and day (after `weather`)")
    c.add_argument("--from", dest="d0", type=date.fromisoformat)
    c.add_argument("--to", dest="d1", type=date.fromisoformat)
    w = sub.add_parser("weather", help="hourly and daily weather features and the vegetation resumption")
    w.add_argument("--from", dest="d0", type=date.fromisoformat, help="first local date of the hourly features")
    w.add_argument("--to", dest="d1", type=date.fromisoformat, help="last local date of the hourly features")
    ap.add_argument("--config", default=str(ROOT / "config" / "septoria.toml"))
    ap.add_argument("--dsn", help="connection string (default: env LOAD_DB_DSN)")
    a = ap.parse_args(argv)
    dsn = a.dsn or os.environ.get("LOAD_DB_DSN")
    if not dsn:
        sys.exit("no connection string: set env LOAD_DB_DSN or pass --dsn")
    import psycopg
    cfg = load_config(Path(a.config))
    with psycopg.connect(dsn) as con:          # one transaction: commits at the end, rolls back on an error
        con.execute("SET TIME ZONE 'UTC'")
        if a.cmd == "weather":
            build_weather(con, cfg, a.d0, a.d1)
        else:
            with open(a.config, "rb") as fh:
                build_cells(con, septoria.Rules.from_config(tomllib.load(fh)), a.d0, a.d1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
