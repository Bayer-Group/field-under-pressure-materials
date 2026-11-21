#!/usr/bin/env python3
"""Smoke and load test of the public API with the scenario of a person from the audience.

    python scripts/load_test_api.py --base https://34-118-11-71.nip.io --users 1                 # smoke test
    python scripts/load_test_api.py --base https://34-118-11-71.nip.io --users 80 --ramp 60      # about a room

Each virtual user: starts a sandbox (copy of a ready farm or an empty one) -> reads the clock, crops, own crop areas -> risk per day and
changes of one crop area -> draws a new crop area (recomputed on the server) -> saves a spray in the past -> deletes the crop area.
Users start spread over --ramp seconds. Run it from the laptop against the public address (what a phone sees), and from the venue
network. All requests come from one address, as a room behind one NAT does. Uses data of the sandbox only (removed after the run and,
at the latest, by the server after SANDBOX_TTL_HOURS). Exit code 1 when the share of 5xx/connection errors is above --max-error-rate
or the p95 of any endpoint is above --max-p95 seconds.
"""
from __future__ import annotations

import argparse
import asyncio
import random
import statistics
import sys
import time
from datetime import date, timedelta

import httpx

CENTRES = [(20.5, 52.6), (21.1, 52.3), (21.5, 52.0), (20.9, 52.7), (21.8, 52.5), (20.3, 52.2), (21.3, 52.8)]


def square(x: float, y: float, h: float = 0.003) -> dict:
    return {"type": "Polygon", "coordinates": [[[x - h, y - h], [x + h, y - h], [x + h, y + h], [x - h, y + h], [x - h, y - h]]]}


class Recorder:
    def __init__(self):
        self.rows: list[tuple[str, int, float]] = []       # name, status (0 = connection error), seconds

    async def call(self, client: httpx.AsyncClient, name: str, method: str, url: str, **kw):
        t0 = time.perf_counter()
        try:
            r = await client.request(method, url, **kw)
            self.rows.append((name, r.status_code, time.perf_counter() - t0))
            return r
        except httpx.HTTPError:
            self.rows.append((name, 0, time.perf_counter() - t0))
            return None


async def visitor(i: int, base: str, rec: Recorder, start_after: float, write_share: float, cleanup: bool) -> None:
    await asyncio.sleep(start_after)
    api = base.rstrip("/") + "/api/v1"
    rnd = random.Random(i)
    async with httpx.AsyncClient(timeout=60) as c:
        r = await rec.call(c, "POST /sandbox", "POST", f"{api}/sandbox", json={"mode": rnd.choice(["mock", "empty"])})
        if r is None or r.status_code != 200:
            return
        h = {"Authorization": "Bearer " + r.json()["token"]}
        await rec.call(c, "GET /clock", "GET", f"{api}/clock")
        await rec.call(c, "GET /crops", "GET", f"{api}/crops")
        r = await rec.call(c, "GET /me/crop-areas", "GET", f"{api}/me/crop-areas", headers=h)
        feats = r.json()["features"] if r is not None and r.status_code == 200 else []
        if feats:
            cid = rnd.choice(feats)["properties"]["crop_area_id"]
            today = date.today()
            await rec.call(c, "GET /crop-areas/{id}/risk", "GET", f"{api}/crop-areas/{cid}/risk", headers=h,
                           params={"from": str(today - timedelta(days=20)), "to": str(today + timedelta(days=10))})
            await rec.call(c, "GET /crop-areas/{id}/changes", "GET", f"{api}/crop-areas/{cid}/changes", headers=h)
            await rec.call(c, "GET /crop-areas/{id}", "GET", f"{api}/crop-areas/{cid}", headers=h)
        if rnd.random() >= write_share:
            return
        x, y = rnd.choice(CENTRES)
        r = await rec.call(c, "POST /crop-areas", "POST", f"{api}/crop-areas", headers=h, json={
            "geometry": square(x + rnd.uniform(-0.05, 0.05), y + rnd.uniform(-0.05, 0.05)), "farmer_crop_id": "wheat",
            "sowing_date": str(date.today() - timedelta(days=rnd.randint(30, 60))), "name": f"Load test {i}"})
        if r is None or r.status_code != 201:
            return
        new = r.json()["properties"]["crop_area_id"]
        await rec.call(c, "POST /crop-areas/{id}/sprays", "POST", f"{api}/crop-areas/{new}/sprays", headers=h,
                       json={"spray_date": str(date.today() - timedelta(days=rnd.randint(1, 6))), "protection_duration_days": 10})
        if cleanup:
            await rec.call(c, "DELETE /crop-areas/{id}", "DELETE", f"{api}/crop-areas/{new}", headers=h)


def pct(values: list[float], p: float) -> float:
    s = sorted(values)
    return s[min(len(s) - 1, int(round(p * (len(s) - 1))))]


async def main_async(a) -> int:
    rec = Recorder()
    t0 = time.perf_counter()
    await asyncio.gather(*(visitor(i, a.base, rec, a.ramp * i / max(1, a.users), a.write_share, not a.keep) for i in range(a.users)))
    total = time.perf_counter() - t0
    names = list(dict.fromkeys(n for n, _, _ in rec.rows))
    print(f"{a.users} users, {len(rec.rows)} requests in {total:.1f} s ({len(rec.rows) / total:.1f} req/s)\n")
    print(f"{'endpoint':32} {'n':>5} {'2xx':>5} {'4xx':>5} {'429':>5} {'5xx/err':>8} {'p50 s':>7} {'p95 s':>7} {'max s':>7}")
    bad_total, worst = 0, 0.0
    for n in names:
        rows = [(s, d) for nm, s, d in rec.rows if nm == n]
        ds = [d for _, d in rows]
        ok = sum(200 <= s < 300 for s, _ in rows)
        e4 = sum(400 <= s < 500 and s != 429 for s, _ in rows)
        e429 = sum(s == 429 for s, _ in rows)
        e5 = sum(s == 0 or s >= 500 for s, _ in rows)
        bad_total += e5
        worst = max(worst, pct(ds, 0.95))
        print(f"{n:32} {len(rows):5d} {ok:5d} {e4:5d} {e429:5d} {e5:8d} {statistics.median(ds):7.2f} {pct(ds, 0.95):7.2f} {max(ds):7.2f}")
    rate = bad_total / max(1, len(rec.rows))
    print(f"\n5xx/connection errors: {bad_total} ({rate:.1%}); worst p95: {worst:.2f} s")
    if rate > a.max_error_rate or worst > a.max_p95:
        print("RESULT: FAIL")
        return 1
    print("RESULT: OK")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", required=True, help="e.g. https://34-118-11-71.nip.io (without /api/v1)")
    ap.add_argument("--users", type=int, default=1)
    ap.add_argument("--ramp", type=float, default=0.0, help="seconds over which the users start")
    ap.add_argument("--write-share", type=float, default=0.7, help="share of users who draw a crop area and save a spray")
    ap.add_argument("--keep", action="store_true", help="do not delete the crop areas drawn by the test")
    ap.add_argument("--max-error-rate", type=float, default=0.01)
    ap.add_argument("--max-p95", type=float, default=3.0, help="seconds")
    return asyncio.run(main_async(ap.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
