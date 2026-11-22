"""
Crop model: which crop is growing, from the Sentinel-2 NDVI curve known so far.

Input per pixel: the 24 half-month NDVI slots of the season (engine.satellite.season), slots after
"today" set to NaN, plus how many slots are known. One LightGBM model serves every day of the season
(it is trained on curves cut at random dates). A field's crop = the mean of its pixels' probabilities.

    python -m engine.cropmodel train DATA_DIR      # trains on DATA_DIR/satellite/samples, writes DATA_DIR/models/
    from engine.cropmodel import predict_pixels     # {"crop": 1110, "confidence": 0.93, "probabilities": {...}}

Labels come from the CLMS crop maps 2020-2024; the model never sees a farm or a field when training.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from engine.satellite.season import N_SLOTS, SLOT_NAMES, known_slots, slot_end

# Model classes: crop-map codes grouped. Wheat and maize are what the engine scores; the rest exist so
# the model can say "this is not wheat / maize".
CLASSES = ["wheat", "maize", "barley", "rapeseed", "other_cereal", "other_crop", "no_crop"]
CLASS_CODE = {"wheat": 1110, "maize": 1130, "barley": 1120, "rapeseed": 1430, "other_cereal": 1150,
              "other_crop": 3100, "no_crop": 0}
CUTOFFS_TRAIN = list(range(4, N_SLOTS + 1))  # known slots: from mid-October to the full season
MODEL_VERSION = "0.1.0"
SLOT_COLS = [f"ndvi_{s}" for s in SLOT_NAMES]


def class_of(code: int) -> str:
    return {1110: "wheat", 1130: "maize", 1120: "barley", 1430: "rapeseed", 1150: "other_cereal", 0: "no_crop"}.get(
        int(code), "other_crop")


GDD_TARGETS = [300, 600, 900, 1200, 1500, 1800, 2100]  # degree days (base 0) since 1 January
PREV_CODES = {c: i for i, c in enumerate(CLASSES)}


def ndvi_at_gdd(slots: np.ndarray, slot_gdd: np.ndarray) -> np.ndarray:
    """
    NDVI read at fixed degree-day points instead of calendar dates, so an early (warm) year and a late
    one line up. slot_gdd: [n, 24] degree days since 1 January at each slot's end (0 before January).
    Linear interpolation between the two slots around each target; NaN if either is unknown.
    """
    x = np.asarray(slots, dtype="float32")
    g = np.asarray(slot_gdd, dtype="float32")
    out = np.full((x.shape[0], len(GDD_TARGETS)), np.nan, dtype="float32")
    rows = np.arange(x.shape[0])
    for j, T in enumerate(GDD_TARGETS):
        above = g >= T
        has = above.any(axis=1)
        hi = np.where(has, above.argmax(axis=1), 0)
        lo = np.clip(hi - 1, 0, None)
        g0, g1 = g[rows, lo], g[rows, hi]
        v0, v1 = x[rows, lo], x[rows, hi]
        w = np.where(g1 > g0, (T - g0) / np.maximum(g1 - g0, 1e-6), 1.0)
        val = v0 + w * (v1 - v0)
        out[:, j] = np.where(has & (hi > 0), val, np.nan)
    return out


def features(slots: np.ndarray, n_known: np.ndarray | int, prev: np.ndarray | None = None,
             slot_gdd: np.ndarray | None = None) -> np.ndarray:
    """
    slots: [n, 24] NDVI with unknown slots NaN; prev: [n] last season's crop class index (PREV_CODES) or NaN;
    slot_gdd: [n, 24] degree days at slot ends. Returns [n, len(FEATURE_NAMES)].
    """
    x = np.asarray(slots, dtype="float32")
    n = x.shape[0]
    k = np.broadcast_to(np.asarray(n_known, dtype="float32"), (n,))
    with np.errstate(all="ignore"):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            autumn = np.nanmean(x[:, 2:8], axis=1)    # Oct - Dec: winter crops emerge
            spring = np.nanmean(x[:, 13:18], axis=1)  # Mar b - May b
            summer = np.nanmean(x[:, 20:24], axis=1)  # Jul - Aug
            peak = np.nanmax(x, axis=1)
            peak_slot = np.where(np.isfinite(x).any(axis=1), np.nanargmax(np.nan_to_num(x, nan=-9), axis=1), np.nan)
    p = np.full(n, np.nan, dtype="float32") if prev is None else np.asarray(prev, dtype="float32")
    gd = np.full((n, len(GDD_TARGETS)), np.nan, dtype="float32") if slot_gdd is None else ndvi_at_gdd(x, slot_gdd)
    return np.column_stack([x, k, autumn, spring, summer, peak, peak_slot, p, gd]).astype("float32")


FEATURE_NAMES = SLOT_COLS + ["n_known_slots", "autumn_mean", "spring_mean", "summer_mean", "peak", "peak_slot",
                             "prev_crop"] + [f"ndvi_at_gdd_{t}" for t in GDD_TARGETS]


GDD_COLS = [f"gdd_{i}" for i in range(N_SLOTS)]


def _ctx(df: pd.DataFrame, use_prev: bool, use_gdd: bool):
    prev = df["prev_crop"].to_numpy("float32") if use_prev and "prev_crop" in df else None
    gdd = df[GDD_COLS].to_numpy("float32") if use_gdd and GDD_COLS[0] in df else None
    return prev, gdd


def _augment(df: pd.DataFrame, rng: np.random.Generator, copies: int, use_prev=True, use_gdd=True) -> tuple[np.ndarray, np.ndarray]:
    slots = df[SLOT_COLS].to_numpy(dtype="float32")
    prev, gdd = _ctx(df, use_prev, use_gdd)
    y = df["label"].map({c: i for i, c in enumerate(CLASSES)}).to_numpy()
    X, Y = [], []
    for _ in range(copies):
        k = rng.choice(CUTOFFS_TRAIN, size=len(df))
        masked = slots.copy()
        masked[np.arange(N_SLOTS)[None, :] >= k[:, None]] = np.nan
        X.append(features(masked, k, prev, gdd)); Y.append(y)
    return np.vstack(X), np.concatenate(Y)


def _fold(s: str) -> str:
    import unicodedata
    return unicodedata.normalize("NFKD", s.replace("ł", "l").replace("Ł", "L")).encode("ascii", "ignore").decode().lower()


def window_weather(data_dir: Path, seasons) -> pd.DataFrame:
    """Per window and season: degree days (base 0, since 1 Jan of the season year) at each slot end."""
    import io
    import json
    import zipfile

    from engine.satellite.season import slot_end

    grids = pd.read_parquet(data_dir / "weather" / "weather_grids.parquet", columns=["grid_id", "lat", "lon", "l1_name"])
    grids[["lat", "lon"]] = grids[["lat", "lon"]].astype(float)
    wins = json.loads((data_dir / "satellite" / "samples" / "windows.json").read_text())
    rows = []
    for w in wins:
        lon = (w["bbox"][0] + w["bbox"][2]) / 2; lat = (w["bbox"][1] + w["bbox"][3]) / 2
        dd = (grids.lat - lat) ** 2 + ((grids.lon - lon) * np.cos(np.radians(lat))) ** 2
        g = grids.loc[dd.idxmin()]
        rows.append({"window": w["id"], "grid_id": g.grid_id, "region": g.l1_name})
    wg = pd.DataFrame(rows)
    out = []
    for season in seasons:
        temps = []
        zdir = data_dir / "raw" / "weather_data" / "daily" / str(season)
        files = {p.stem.split(f"weather_daily_{season}_")[-1]: p for p in zdir.glob("*.zip")}
        for region, grp in wg.groupby("region"):
            name = _fold(region)
            match = max((k for k in files if name.endswith(k.lower())), key=len, default=None)
            if match is None:
                continue
            with zipfile.ZipFile(files[match]) as z:
                pq = [n for n in z.namelist() if n.endswith(".parquet") and "__MACOSX" not in n][0]
                df = pd.read_parquet(io.BytesIO(z.read(pq)), columns=["grid_id", "date", "avg_temperature"],
                                     filters=[("grid_id", "in", list(grp.grid_id.unique()))])
            temps.append(df)
        if not temps:
            continue
        t = pd.concat(temps)
        t["date"] = pd.to_datetime(t["date"])
        ends = [pd.Timestamp(slot_end(season, s)) for s in range(N_SLOTS)]
        for gid, gt in t.groupby("grid_id"):
            gdd = gt.set_index("date")["avg_temperature"].sort_index().clip(lower=0).cumsum()
            vals = [float(gdd[gdd.index <= e].iloc[-1]) if e.year == season and (gdd.index <= e).any() else 0.0 for e in ends]
            for wid in wg[wg.grid_id == gid].window:
                out.append({"window": wid, "season": season, **{f"gdd_{i}": v for i, v in enumerate(vals)}})
    return pd.DataFrame(out)


def previous_crop(data_dir: Path, df: pd.DataFrame) -> np.ndarray:
    """Last season's crop class index at each sample's location (NaN where that map is missing or bad)."""
    import rasterio

    prev = np.full(len(df), np.nan, dtype="float32")
    for season, idx in df.groupby("season").groups.items():
        year = int(season) - 1
        tif = data_dir / "cropland" / f"cropland_{year}.tif"
        if year in BAD_LABEL_SEASONS or not tif.exists():
            continue
        sub_df = df.loc[idx]
        with rasterio.open(tif) as src:
            codes = np.array([v[0] for v in src.sample(zip(sub_df.lon, sub_df.lat))])
        prev[df.index.get_indexer(idx)] = [PREV_CODES[class_of(c)] if c != 65535 else np.nan for c in codes]
    return prev


def load_samples(data_dir: Path) -> pd.DataFrame:
    files = sorted((data_dir / "satellite" / "samples").glob("*.parquet"))
    df = pd.concat((pd.read_parquet(f) for f in files), ignore_index=True)
    df["label"] = df["crop_code"].map(class_of)
    return df


# The organisers' 2021 crop map is pixel-identical to 2022 (checked 21 Nov 2026): its labels do not match
# the 2021 imagery, so season 2021 is left out of training and testing.
BAD_LABEL_SEASONS = {2021}


def train(data_dir: Path, test_season: int = 2024, holdout_windows: int = 6, copies: int = 4,
          exclude_seasons: set[int] = BAD_LABEL_SEASONS, use_prev: bool = True, use_gdd: bool = True,
          save: bool = True) -> dict:
    import lightgbm as lgb
    from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score

    df = load_samples(data_dir)
    df = df[~df.season.isin(exclude_seasons)].reset_index(drop=True)
    if use_prev:
        df["prev_crop"] = previous_crop(data_dir, df)
    if use_gdd:
        ww = window_weather(data_dir, sorted(df.season.unique()))
        df = df.merge(ww, on=["window", "season"], how="left")
    windows = sorted(df["window"].unique())
    rng = np.random.default_rng(0)
    held = set(rng.choice(windows, size=holdout_windows, replace=False).tolist())
    train_df = df[(df.season != test_season) & ~df.window.isin(held)]
    test_df = df[(df.season == test_season) & df.window.isin(held)]
    # balance classes a little: at most 25k pixels per class in training
    train_df = pd.concat(g.sample(min(len(g), 25000), random_state=0) for _, g in train_df.groupby("label"))
    Xtr, ytr = _augment(train_df, rng, copies, use_prev, use_gdd)
    params = dict(objective="multiclass", num_class=len(CLASSES), learning_rate=0.08, num_leaves=63,
                  min_data_in_leaf=100, feature_fraction=0.9, bagging_fraction=0.8, bagging_freq=1, verbose=-1, seed=0)
    booster = lgb.train(params, lgb.Dataset(Xtr, ytr, feature_name=FEATURE_NAMES, categorical_feature=["prev_crop"]),
                        num_boost_round=300)

    report = {"train_pixels": len(train_df), "test_pixels": len(test_df), "test_season": test_season,
              "excluded_seasons": sorted(exclude_seasons),
              "holdout_windows": sorted(int(w) for w in held), "by_cutoff": {}}
    ytest = test_df["label"].map({c: i for i, c in enumerate(CLASSES)}).to_numpy()
    slots = test_df[SLOT_COLS].to_numpy(dtype="float32")
    tprev, tgdd = _ctx(test_df, use_prev, use_gdd)
    grp = lambda a: np.where(a == 0, 0, np.where(a == 1, 1, 2))  # wheat / maize / other
    for k in (6, 8, 14, 16, 17, 18, 20, 22, 24):
        masked = slots.copy(); masked[:, k:] = np.nan
        p = booster.predict(features(masked, k, tprev, tgdd))
        pred = p.argmax(1)
        when = slot_end(test_season, k - 1).isoformat()
        per = {c: round(float(f1_score(ytest == i, pred == i)), 3) for i, c in enumerate(CLASSES)}
        yt3, yp3 = grp(ytest), grp(pred)
        prec = lambda c: float(((yp3 == c) & (yt3 == c)).sum() / max((yp3 == c).sum(), 1))
        report["by_cutoff"][when] = {"known_slots": k, "accuracy": round(float(accuracy_score(ytest, pred)), 3), "f1": per,
                                     "three_way_accuracy": round(float((yt3 == yp3).mean()), 3),
                                     "wheat_precision": round(prec(0), 3), "maize_precision": round(prec(1), 3)}
        if k in (18, 24):
            report["by_cutoff"][when]["confusion"] = confusion_matrix(ytest, pred, labels=range(len(CLASSES))).tolist()
    report["features"] = {"prev_crop": use_prev, "ndvi_at_gdd": use_gdd}
    if not save:
        return report
    out = data_dir / "models"
    out.mkdir(parents=True, exist_ok=True)
    booster.save_model(str(out / "crop_lgbm.txt"))
    (out / "crop_model.json").write_text(json.dumps({"version": MODEL_VERSION, "classes": CLASSES, "features": FEATURE_NAMES,
                                                     "report": report}, indent=1))
    return report


@lru_cache(maxsize=1)
def _booster(path: str):
    import lightgbm as lgb
    return lgb.Booster(model_file=path)


def model_path() -> Path:
    try:
        from django.conf import settings
        base = Path(settings.BASE_DIR)
    except Exception:
        base = Path(__file__).resolve().parents[1]
    return (base / os.environ.get("DATA_DIR", "../field-under-pressure-data") / "models" / "crop_lgbm.txt").resolve()


def predict_pixels(slots: np.ndarray, season: int, today: date, path: Path | None = None,
                   prev_code: int | None = None, slot_gdd: np.ndarray | None = None) -> dict:
    """
    slots: [pixels, 24] NDVI composites of one field (from engine.satellite.season.composite).
    Only slots complete by `today` are used. Returns the field's crop and the class probabilities.
    """
    path = path or model_path()
    if not path.exists():
        raise FileNotFoundError(f"crop model not trained: {path}")
    known = known_slots(season, today)
    x = np.array(slots, dtype="float32", copy=True)
    if x.ndim == 1:
        x = x[None, :]
    x[:, ~known] = np.nan
    x = x[np.isfinite(x).any(axis=1)]
    if len(x) == 0:
        return {"crop": None, "confidence": 0.0, "probabilities": {}, "pixels": 0, "known_slots": int(known.sum())}
    prev = None if prev_code is None else np.full(len(x), PREV_CODES[class_of(prev_code)], dtype="float32")
    gdd = None if slot_gdd is None else np.broadcast_to(np.asarray(slot_gdd, dtype="float32"), (len(x), N_SLOTS))
    p = _booster(str(path)).predict(features(x, int(known.sum()), prev, gdd)).mean(axis=0)
    best = int(p.argmax())
    return {"crop": CLASS_CODE[CLASSES[best]], "label": CLASSES[best], "confidence": round(float(p[best]), 3),
            "probabilities": {c: round(float(v), 3) for c, v in zip(CLASSES, p)}, "pixels": int(len(x)),
            "known_slots": int(known.sum()), "as_of": today.isoformat(), "model_version": MODEL_VERSION}


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "train":
        rep = train(Path(sys.argv[2]))
        for when, r in rep["by_cutoff"].items():
            print(f"as of {when} ({r['known_slots']:2d} slots): acc {r['accuracy']:.3f}  " +
                  " ".join(f"{c}={v:.2f}" for c, v in r["f1"].items()))
        print("classes:", CLASSES)
        for when, r in rep["by_cutoff"].items():
            if "confusion" in r:
                print(f"confusion as of {when} (rows = true):")
                for c, row in zip(CLASSES, r["confusion"]):
                    print(f"  {c:13s}", row)
    else:
        print(__doc__)


def slot_gdd_from_temps(daily_temp: pd.Series, season: int) -> np.ndarray:
    """Degree days (base 0) since 1 January of `season` at each slot end; 0 for slots before January."""
    t = daily_temp.sort_index().astype(float)
    t.index = pd.to_datetime(t.index)
    gdd = t[t.index >= pd.Timestamp(season, 1, 1)].clip(lower=0).cumsum()
    out = np.zeros(N_SLOTS, dtype="float32")
    for s in range(N_SLOTS):
        e = pd.Timestamp(slot_end(season, s))
        if e.year == season and (gdd.index <= e).any():
            out[s] = float(gdd[gdd.index <= e].iloc[-1])
    return out


def predict_field(field, season: int, today: date) -> dict | None:
    """The crop model on a field's cached NDVI series (engine/satellite/fieldndvi.py), as of `today`."""
    from engine import features as F
    from engine.satellite import fieldndvi
    from engine.satellite.season import composite, season_bounds

    if not model_path().exists():
        return None
    series = fieldndvi.load(field, season)
    if series is None:
        return None
    series = series[series.date <= pd.Timestamp(today)]
    if series.empty:
        return None
    slots = composite(series.date.dt.date.tolist(), series.ndvi.to_numpy()[:, None], season)[:, 0]
    prev = field.crop_years.filter(year=season - 1).order_by("-share").values_list("crop_class_id", flat=True).first()
    prev = None if prev is None or season - 1 in BAD_LABEL_SEASONS else prev
    daily = F.load_daily(field.weather_grid_id, season_bounds(season)[0], today)
    gdd = slot_gdd_from_temps(daily["avg_temperature"], season) if not daily.empty else None
    out = predict_pixels(slots[None, :], season, today, prev_code=prev, slot_gdd=gdd)
    out["previous_crop"] = prev
    out["evaluation"] = "2024, 534 fields never seen in training: wheat/maize/other right 74 % by end of May, 77 % by end of August; wheat vs maize 99-100 % from end of May"
    return out
