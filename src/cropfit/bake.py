"""Bake the GUI API into a static data dump (see scripts/19_bake_static.py).

The crawl walks every GET route the frontend (web/src/api.ts) uses, in-process through a TestClient, and writes each
JSON body as `<out>/data/<key>.js` (a one-line script that registers the body in `window.__BAKED__[path]`). Overlay
PNGs go to `<out>/img/`, and the click-to-read NDVI lookup becomes a small per-map grid (`.../grid`) plus one shared
decode table (`/ndvi-decode`).
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote

import numpy as np

AERIAL_PREFIX, NDVI_PREFIX = "/api/aerial/", "/api/greenness-maps/"
GRID_STEP = 2                       # the click grid keeps every 2nd pixel of the warped chip


def enc(s: str) -> str:
    """Same escaping as JS encodeURIComponent."""
    return quote(str(s), safe="-_.!~*'()")


def path_to_key(path: str) -> str:
    """API path (no /api prefix, with query) -> file name stem."""
    return path.replace("/", "__").replace("?", "~").replace("=", "-").replace("&", "+")


def _rewrite_str(s: str) -> str:
    if s.endswith(".png"):
        for prefix, folder in ((AERIAL_PREFIX, "img/aerial/"), (NDVI_PREFIX, "img/ndvi/")):
            if s.startswith(prefix):
                name = s[len(prefix):-4]
                if "/" in name or not name:
                    raise ValueError(f"image id with a slash or empty: {s!r}")
                return f"{folder}{name}.png"
    return s


def rewrite_urls(obj):
    """Copy of a JSON value with /api/aerial/<id>.png and /api/greenness-maps/<id>.png rewritten to img/ paths."""
    if isinstance(obj, str):
        return _rewrite_str(obj)
    if isinstance(obj, list):
        return [rewrite_urls(v) for v in obj]
    if isinstance(obj, dict):
        return {k: rewrite_urls(v) for k, v in obj.items()}
    return obj


def js_payload(path: str, body) -> str:
    return ("window.__BAKED__=window.__BAKED__||{};window.__BAKED__[" + json.dumps(path, ensure_ascii=False) + "]="
            + json.dumps(body, ensure_ascii=False, separators=(",", ":")) + ";")


def _git_sha() -> str | None:
    try:
        root = Path(__file__).resolve().parents[2]
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True,
                              timeout=10).stdout.strip() or None
    except Exception:
        return None


def ndvi_decode_table() -> list[float | None]:
    """Value of every stored NDVI code, as the PNG colours it (codes above 201 clip); null for nodata."""
    from . import ndvimap
    v = ndvimap.decode(np.arange(256).clip(0, 201))
    return [None if (i == 0 or not np.isfinite(x)) else round(float(x), 3) for i, x in enumerate(v)]


def ndvi_grid(chip: Path) -> dict:
    from . import overlay
    s, w, n, e = overlay.bounds_latlon(chip)
    codes = np.ascontiguousarray(overlay._warp(chip, [1], smooth=False)[0][::GRID_STEP, ::GRID_STEP])
    h, wd = codes.shape
    return {"s": s, "w": w, "n": n, "e": e, "width": int(wd), "height": int(h),
            "codes": base64.b64encode(codes.tobytes()).decode("ascii")}


def bake(client, out_dir: Path, workers: int = 8, log=print) -> dict:
    """Crawl the API behind `client` and write the static dump into out_dir/data and out_dir/img."""
    from . import api
    from .config import light_plots

    out_dir = Path(out_dir)
    data_dir, img_dir = out_dir / "data", out_dir / "img"
    for d in (data_dir, img_dir):
        shutil.rmtree(d, ignore_errors=True)
    (img_dir / "aerial").mkdir(parents=True)
    (img_dir / "ndvi").mkdir(parents=True)
    data_dir.mkdir(parents=True)

    skipped: list[list] = []
    counts: dict[str, int] = {}
    written: set[str] = set()

    def write(path: str, body, kind: str):
        key = path_to_key(path)
        (data_dir / f"{key}.js").write_text(js_payload(path, body), encoding="utf-8")
        written.add(path)
        counts[kind] = counts.get(kind, 0) + 1

    def fetch(path: str, kind: str):
        """GET /api<path>; write it and return the parsed (unrewritten) body, or None when skipped."""
        r = client.get("/api" + path)
        if r.status_code != 200:
            skipped.append([path, r.status_code])
            return None
        body = r.json()
        write(path, rewrite_urls(body), kind)
        return body

    def pmap(fn, items):
        with ThreadPoolExecutor(workers) as ex:
            return list(ex.map(fn, items))

    plots = fetch("/plots", "plots") or []
    plot_ids = [p["plot_id"] for p in plots]
    log(f"plots: {plot_ids}")

    def per_plot(pid):
        e = enc(pid)
        res = {}
        for name, kind in (("greenness", "greenness"), ("events", "events"), ("aerial", "aerial"),
                           ("greenness-maps", "greenness_maps"), ("microbiome", "microbiome"),
                           ("functions", "functions"), ("crop-risk", "crop_risk_units")):
            res[name] = fetch(f"/plots/{e}/{name}", kind)
        return pid, res

    per = dict(pmap(per_plot, plot_ids))
    log("per-plot lists done")

    # ---- events
    ev_ids = [x["event_id"] for pid in plot_ids for x in per[pid]["events"] or []]
    pmap(lambda i: fetch(f"/events/{enc(i)}", "event"), ev_ids)

    # ---- images + ndvi grids
    photo_ids = sorted({x["photo_id"] for pid in plot_ids for x in per[pid]["aerial"] or []})
    map_ids = sorted({x["map_id"] for pid in plot_ids for x in per[pid]["greenness-maps"] or []})
    for i in photo_ids + map_ids:
        if "/" in i:
            raise ValueError(f"image id contains '/': {i!r}")

    def image(args):
        prefix, folder, i = args
        r = client.get(f"{prefix}{i}.png")
        if r.status_code != 200:
            skipped.append([f"{prefix[4:]}{i}.png", r.status_code])
            return
        (img_dir / folder / f"{i}.png").write_bytes(r.content)
        counts["img_" + folder] = counts.get("img_" + folder, 0) + 1

    pmap(image, [(AERIAL_PREFIX, "aerial", i) for i in photo_ids] + [(NDVI_PREFIX, "ndvi", i) for i in map_ids])
    log(f"images: {len(photo_ids)} aerial, {len(map_ids)} ndvi")

    def grid(i):
        try:
            write(f"/greenness-maps/{enc(i)}/grid", ndvi_grid(api._ndvi_chip(i)), "ndvi_grid")
        except Exception as exc:
            skipped.append([f"/greenness-maps/{enc(i)}/grid", repr(exc)])

    pmap(grid, map_ids)
    write("/ndvi-decode", {"values": ndvi_decode_table()}, "ndvi_decode")

    # ---- microbiome + functions
    sids = sorted({x["sample_id"] for pid in plot_ids for x in per[pid]["microbiome"] or []})
    fsids = sorted({x["sample_id"] for pid in plot_ids for x in per[pid]["functions"] or []})
    jobs = [(f"/microbiome/{enc(s)}?rank={r}", "composition") for s in sids for r in ("phylum", "class", "genus")]
    jobs += [(f"/microbiome/{enc(s)}/roles", "roles") for s in sids]
    jobs += [(f"/functions/{enc(s)}", "function_profile") for s in fsids]
    pmap(lambda j: fetch(*j), jobs)
    log(f"microbiome samples: {len(sids)}, function samples: {len(fsids)}")

    # ---- crop risk
    def risk_unit(args):
        pid, u = args
        base = f"/plots/{enc(pid)}/crop-risk/{enc(u)}"
        body = fetch(base, "crop_risk")
        crops = [c["crop"] for c in (body or {}).get("crops", [])]
        for c in crops:
            fetch(f"{base}/{enc(c)}", "crop_contributions")
            fetch(f"{base}/{enc(c)}/tests", "crop_tests")
            fetch(f"{base}/{enc(c)}/products", "crop_products")

    pmap(risk_unit, [(pid, u["unit"]) for pid in plot_ids for u in per[pid]["crop-risk"] or []])
    log("crop risk done")

    manifest = {"baked_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "git_sha": _git_sha(),
                "light_plots": light_plots(), "counts": counts, "skipped": sorted(skipped, key=str)}
    (data_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    return manifest
