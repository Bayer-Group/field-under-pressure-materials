#!/usr/bin/env python3
"""Check the septoria thresholds on historical weather: how often is each class reached? (thresholds note, section 4)

For every grid cell and every local day from 1 April to 30 June, H = the longest run of consecutive wet hours in the 72 hours
ending at the last hour of that day (wet hour: relative humidity >= RH threshold or precipitation > 0.2 mm), then the share of
cell-days in each class (low < 10 h, medium 10-19 h, high >= 20 h). Also reported: the open variants of the note, the TOTAL
number of wet hours instead of the longest run, and higher RH thresholds. If "high" holds for most of the season the alert
says nothing and the thresholds need a calibration.

    python scripts/septoria_threshold_check.py --raw <folder> --years 2024 [--out data/calib/threshold_check]

<folder> has the layout of the raw data:
    weather_hourly/year=YYYY/voivodeship=mazowieckie/*.parquet     (grid_id, utc_time, local_time, date, relative_humidity)
    imerg_hourly/hourly/YYYY/precip_hourly_YYYY_Mazowieckie.parquet  (grid_id, utc_time, precipitation)
Reads the files only; never touches the database. Weather comes from a 4 km grid, not from a measurement in the canopy.
"""
from __future__ import annotations

import argparse
import csv
import sys
import tomllib
from datetime import date
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
WINDOW = 72


def load_cfg(path: Path) -> dict:
    with open(path, "rb") as fh:
        return tomllib.load(fh)["septoria"]


def read_season(raw: Path, year: int, voiv: str, first: date, last: date):
    """(cells, hours_utc_ns, local_hour, local_date, rh[cell, hour], precip[cell, hour]) for [first, last] local dates."""
    files = sorted((raw / "weather_hourly" / f"year={year}" / f"voivodeship={voiv}").glob("*.parquet"))
    if not files:
        raise FileNotFoundError(f"no hourly weather for {year}/{voiv} under {raw}")
    parts = []
    for f in files:
        t = pq.read_table(f, columns=["grid_id", "utc_time", "local_time", "date", "relative_humidity"])
        keep = pc.and_(pc.greater_equal(t["date"], pa.scalar(first)), pc.less_equal(t["date"], pa.scalar(last)))
        parts.append(t.filter(keep))
    w = pa.concat_tables(parts)
    ip = sorted((raw / "imerg_hourly" / "hourly" / str(year)).glob("*azowiec*.parquet"))
    if not ip:
        raise FileNotFoundError(f"no IMERG hourly file for {year}")
    p = pq.read_table(ip[0], columns=["grid_id", "utc_time", "precipitation"])
    cells = np.array(sorted(set(w["grid_id"].to_pylist())))
    utc = w["utc_time"].cast(pa.int64()).to_numpy()
    hours = np.unique(utc)
    ci = np.searchsorted(cells, np.array(w["grid_id"].to_pylist()))
    ti = np.searchsorted(hours, utc)
    rh = np.full((len(cells), len(hours)), np.nan, dtype=np.float32)
    rh[ci, ti] = w["relative_humidity"].to_numpy(zero_copy_only=False).astype(np.float32)
    pr = np.zeros((len(cells), len(hours)), dtype=np.float32)
    pci = np.searchsorted(cells, np.array(p["grid_id"].to_pylist()))
    ok = (pci < len(cells)) & (cells[np.minimum(pci, len(cells) - 1)] == np.array(p["grid_id"].to_pylist()))
    pti = np.searchsorted(hours, p["utc_time"].cast(pa.int64()).to_numpy())
    ok &= (pti < len(hours)) & (hours[np.minimum(pti, len(hours) - 1)] == p["utc_time"].cast(pa.int64()).to_numpy())
    pr[pci[ok], pti[ok]] = p["precipitation"].to_numpy(zero_copy_only=False).astype(np.float32)[ok]
    # local clock (the same for every cell) from the first cell
    first_cell = w["grid_id"].to_pylist()[0]
    sel = pc.equal(w["grid_id"], pa.scalar(first_cell))
    lt = w.filter(sel)
    order = np.argsort(lt["utc_time"].cast(pa.int64()).to_numpy())
    local_hour = np.array(pc.hour(lt["local_time"]).to_numpy())[order]
    local_date = np.array(lt["date"].to_pylist(), dtype="datetime64[D]")[order]
    return cells, hours, local_hour, local_date, rh, pr


def longest_run_and_total(wet: np.ndarray, ends: np.ndarray):
    """wet[cell, hour] bool; for each end index: longest run and total of wet hours in the 72 h ending there."""
    idx = np.arange(WINDOW)
    longest = np.empty((wet.shape[0], len(ends)), dtype=np.int16)
    total = np.empty_like(longest)
    for j, e in enumerate(ends):
        w = wet[:, e - WINDOW + 1:e + 1]
        last_dry = np.maximum.accumulate(np.where(~w, idx, -1), axis=1)
        longest[:, j] = np.where(w, idx - last_dry, 0).max(axis=1)
        total[:, j] = w.sum(axis=1)
    return longest, total


def shares(values: np.ndarray, medium: int, high: int) -> tuple[float, float, float]:
    n = values.size
    return ((values < medium).sum() / n, ((values >= medium) & (values < high)).sum() / n, (values >= high).sum() / n)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", type=Path, required=True)
    ap.add_argument("--years", required=True, help="comma list, e.g. 2020,2021,2024")
    ap.add_argument("--voiv", default="mazowieckie")
    ap.add_argument("--rh", default="85,90,95", help="RH thresholds to compare (the contract uses 85)")
    ap.add_argument("--config", type=Path, default=ROOT / "config" / "septoria.toml")
    ap.add_argument("--out", type=Path, help="write <out>.csv and <out>.md")
    a = ap.parse_args(argv)
    cfg = load_cfg(a.config)
    med, high, p_min = cfg["thresholds"]["medium"], cfg["thresholds"]["high"], cfg["wet_hour"]["precipitation_min_mm"]
    rows = []
    for year in [int(y) for y in a.years.split(",")]:
        first, last = date(year, 3, 28), date(year, 6, 30)           # 72 h of lead-in before 1 April
        cells, hours, lh, ld, rh, pr = read_season(a.raw, year, a.voiv, first, last)
        ends = np.flatnonzero((lh == 23) & (ld >= np.datetime64(date(year, 4, 1))) & (ld <= np.datetime64(date(year, 6, 30))))
        ends = ends[ends >= WINDOW - 1]
        months = np.array([int(str(d)[5:7]) for d in ld[ends]])
        for rh_min in [float(x) for x in a.rh.split(",")]:
            wet = (rh >= rh_min) | (pr > p_min)
            longest, total = longest_run_and_total(wet, ends)
            for label, vals in (("longest run (contract)", longest), ("total wet hours", total)):
                lo, me, hi = shares(vals, med, high)
                rows.append({"year": year, "rh_min": rh_min, "measure": label, "scope": "Apr-Jun", "low": lo, "medium": me, "high": hi,
                             "high_days_per_cell": hi * len(ends)})
                if label.startswith("longest") and rh_min == 85.0:
                    for m, name in ((4, "Apr"), (5, "May"), (6, "Jun")):
                        l2, m2, h2 = shares(vals[:, months == m], med, high)
                        rows.append({"year": year, "rh_min": rh_min, "measure": label, "scope": name, "low": l2, "medium": m2,
                                     "high": h2, "high_days_per_cell": h2 * int((months == m).sum())})
        print(f"{year}: {len(cells):,} cells, {len(ends)} days", file=sys.stderr)
    md = ["| year | RH ≥ | measure | scope | low | medium | high | high days / cell |", "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in rows:
        md.append(f"| {r['year']} | {r['rh_min']:.0f} % | {r['measure']} | {r['scope']} | {r['low']:.0%} | {r['medium']:.0%} | "
                  f"{r['high']:.0%} | {r['high_days_per_cell']:.1f} |")
    print("\n".join(md))
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        with open(a.out.with_suffix(".csv"), "w", newline="") as fh:
            wr = csv.DictWriter(fh, fieldnames=list(rows[0]))
            wr.writeheader()
            wr.writerows(rows)
        a.out.with_suffix(".md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
