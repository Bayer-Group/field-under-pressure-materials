"""
Build the training set for the crop model: per-pixel half-month NDVI composites with crop-map labels.

    python engine/scripts/build_crop_samples.py DATA_DIR [--windows 30] [--seasons 2020 2021 2022 2023 2024]

- Picks random ~3x3 km windows inside the cropland extract (DATA_DIR/cropland/cropland_<year>.tif,
  made by clip_cropland.py) that are at least 40 % cropland.
- For each window and season (Sep year-1 .. Aug year) reads Sentinel-2 NDVI from Earth Search,
  builds the 24 half-month slots, reprojects the crop map of that year onto the Sentinel-2 grid and
  samples "pure" pixels (3x3 neighbourhood of one class), up to --per-class per class.
- Writes DATA_DIR/satellite/samples/w<window>_s<season>.parquet (resumable: existing files are skipped)
  and DATA_DIR/satellite/samples/windows.json.

Nothing about a farm or a field is used: the model is trained on pixels, fields only matter at inference.
"""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root, so `engine` imports without Django

import numpy as np
import pandas as pd
import rasterio
from affine import Affine
from rasterio.warp import Resampling, reproject, transform_bounds
from scipy.ndimage import maximum_filter, minimum_filter

from engine.satellite.earthsearch import read_ndvi_window
from engine.satellite.season import N_SLOTS, SLOT_NAMES, composite, season_bounds

WINDOW_DEG = (0.042, 0.027)  # ~3 x 3 km at 50.5° N (lon, lat)
CROP_CODES_OF_INTEREST = (1110, 1120, 1130, 1150, 1430)


def pick_windows(cropland_tif: Path, n: int, seed: int) -> list[dict]:
    rng = np.random.default_rng(seed)
    with rasterio.open(cropland_tif) as src:
        factor = 20
        low = src.read(1, out_shape=(src.height // factor, src.width // factor))
        t = src.transform * Affine.scale(src.width / low.shape[1], src.height / low.shape[0])
        b = src.bounds
    windows, tries = [], 0
    while len(windows) < n and tries < 20000:
        tries += 1
        lon = rng.uniform(b.left, b.right - WINDOW_DEG[0])
        lat = rng.uniform(b.bottom, b.top - WINDOW_DEG[1])
        c0, r0 = ~t * (lon, lat + WINDOW_DEG[1])
        c1, r1 = ~t * (lon + WINDOW_DEG[0], lat)
        sub = low[int(r0):int(r1), int(c0):int(c1)]
        if sub.size == 0 or (sub == 65535).any():
            continue
        crop_share = np.isin(sub, CROP_CODES_OF_INTEREST).mean()
        if crop_share < 0.4:
            continue
        bbox = (lon, lat, lon + WINDOW_DEG[0], lat + WINDOW_DEG[1])
        if any(abs(w["bbox"][0] - lon) < WINDOW_DEG[0] and abs(w["bbox"][1] - lat) < WINDOW_DEG[1] for w in windows):
            continue  # no overlapping windows
        windows.append({"id": len(windows), "bbox": [round(v, 5) for v in bbox], "crop_share": round(float(crop_share), 2)})
    return windows


def labels_on_grid(cropland_tif: Path, shape, transform: Affine, crs: str) -> np.ndarray:
    h, w = shape
    left, top = transform.c, transform.f
    bounds = transform_bounds(crs, "EPSG:4326", left, top + h * transform.e, left + w * transform.a, top)
    lab = np.zeros(shape, dtype="uint16")
    with rasterio.open(cropland_tif) as src:
        win = rasterio.windows.from_bounds(*bounds, transform=src.transform).round_offsets().round_lengths()
        win = rasterio.windows.Window(win.col_off - 2, win.row_off - 2, win.width + 4, win.height + 4)
        data = src.read(1, window=win, boundless=True, fill_value=65535)
        reproject(data, lab, src_transform=rasterio.windows.transform(win, src.transform), src_crs=src.crs,
                  dst_transform=transform, dst_crs=crs, resampling=Resampling.nearest)
    return lab


def build_one(data_dir: str, window: dict, season: int, per_class: int, seed: int) -> str:
    data_dir = Path(data_dir)
    out = data_dir / "satellite" / "samples" / f"w{window['id']:03d}_s{season}.parquet"
    if out.exists():
        return f"skip {out.name}"
    start, end = season_bounds(season)
    scenes = read_ndvi_window(tuple(window["bbox"]), start.isoformat(), end.isoformat())
    if scenes is None:
        return f"no scenes w{window['id']} s{season}"
    comp = composite(scenes.dates, scenes.ndvi, season)  # [24, h, w]
    lab = labels_on_grid(data_dir / "cropland" / f"cropland_{season}.tif", comp.shape[1:], scenes.transform, scenes.crs)
    pure = (maximum_filter(lab, 3) == minimum_filter(lab, 3)) & (lab != 65535)
    rng = np.random.default_rng(seed + window["id"] * 100 + season)
    rows, cols = [], []
    for code in np.unique(lab[pure]):
        r, c = np.nonzero(pure & (lab == code))
        k = min(per_class, len(r))
        idx = rng.choice(len(r), k, replace=False)
        rows.append(r[idx]); cols.append(c[idx])
    r = np.concatenate(rows); c = np.concatenate(cols)
    x, y = rasterio.transform.xy(scenes.transform, r, c)
    lon, lat = rasterio.warp.transform(scenes.crs, "EPSG:4326", x, y)
    df = pd.DataFrame({
        "window": window["id"], "season": season, "tile": scenes.tile, "row": r, "col": c,
        "lon": np.round(lon, 6), "lat": np.round(lat, 6), "crop_code": lab[r, c].astype("int32"),
        "n_scenes": len(scenes.dates),
    })
    vals = comp[:, r, c].T
    for i, name in enumerate(SLOT_NAMES):
        df[f"ndvi_{name}"] = vals[:, i]
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    return f"ok {out.name}: {len(df)} px, {len(scenes.dates)} scenes"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("data_dir", type=Path)
    p.add_argument("--windows", type=int, default=30)
    p.add_argument("--seasons", type=int, nargs="*", default=[2020, 2021, 2022, 2023, 2024])
    p.add_argument("--per-class", type=int, default=300)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--seed", type=int, default=42)
    a = p.parse_args()
    out_dir = a.data_dir / "satellite" / "samples"
    out_dir.mkdir(parents=True, exist_ok=True)
    wfile = out_dir / "windows.json"
    if wfile.exists():
        windows = json.loads(wfile.read_text())
    else:
        windows = pick_windows(a.data_dir / "cropland" / "cropland_2024.tif", a.windows, a.seed)
        wfile.write_text(json.dumps(windows, indent=1))
    print(f"{len(windows)} windows x {len(a.seasons)} seasons", flush=True)
    jobs = [(str(a.data_dir), w, s, a.per_class, a.seed) for w in windows for s in a.seasons]
    with ProcessPoolExecutor(a.workers) as ex:
        futs = [ex.submit(build_one, *j) for j in jobs]
        for i, f in enumerate(as_completed(futs), 1):
            try:
                print(f"[{i}/{len(jobs)}] {f.result()}", flush=True)
            except Exception as e:  # keep going; a rerun retries the missing ones
                print(f"[{i}/{len(jobs)}] FAIL {type(e).__name__}: {e}", flush=True)


if __name__ == "__main__":
    main()
