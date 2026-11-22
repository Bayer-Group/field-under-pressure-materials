"""Bake the GUI API into a static data dump (data/*.js + img/*.png) for hosting without a backend.

Run from the repo root: .venv/bin/python scripts/19_bake_static.py [--out static_version]
Only <out>/data and <out>/img are deleted and rebuilt; other files in <out> (the frontend build) are left alone.
Contract: see src/cropfit/bake.py.
"""
import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fastapi.testclient import TestClient  # noqa: E402

from cropfit import api, bake  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=ROOT / "static_version")
    out = ap.parse_args().out
    t = time.time()
    m = bake.bake(TestClient(api.app), out)
    print(f"baked into {out} in {time.time() - t:.0f}s: {m['counts']}; skipped {len(m['skipped'])}")
    for s in m["skipped"][:30]:
        print("  skipped", s)


if __name__ == "__main__":
    main()
