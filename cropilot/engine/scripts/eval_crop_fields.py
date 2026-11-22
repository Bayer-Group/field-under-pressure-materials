"""
Field-level evaluation of the crop model: for the held-out windows of the saved model, read the full
Sentinel-2 stack of the test season, cut fields out of the crop map (connected pixels of one class,
>= 1 ha, inner pixels), average the pixel probabilities per field and compare with the crop map.

    python engine/scripts/eval_crop_fields.py DATA_DIR
"""
import json
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy import ndimage

import engine.cropmodel as cm
from engine.satellite.earthsearch import read_ndvi_window
from engine.satellite.season import composite, season_bounds
from engine.scripts.build_crop_samples import labels_on_grid

D = Path(sys.argv[1])
meta = json.loads((D / "models" / "crop_model.json").read_text())
season = meta["report"]["test_season"]
held = meta["report"]["holdout_windows"]
wins = {w["id"]: w for w in json.loads((D / "satellite" / "samples" / "windows.json").read_text())}
booster = lgb.Booster(model_file=str(D / "models" / "crop_lgbm.txt"))
ww = cm.window_weather(D, [season]).set_index("window")
rows = []
for wid in held:
    w = wins[wid]
    s0, s1 = season_bounds(season)
    sc = read_ndvi_window(tuple(w["bbox"]), s0.isoformat(), s1.isoformat())
    comp = composite(sc.dates, sc.ndvi, season)
    lab = labels_on_grid(D / "cropland" / f"cropland_{season}.tif", comp.shape[1:], sc.transform, sc.crs)
    prev_lab = labels_on_grid(D / "cropland" / f"cropland_{season - 1}.tif", comp.shape[1:], sc.transform, sc.crs)
    gdd = ww.loc[wid, [f"gdd_{i}" for i in range(24)]].to_numpy("float32") if wid in ww.index else None
    for code in np.unique(lab):
        if code in (65535,):
            continue
        comps, n = ndimage.label(ndimage.binary_erosion(lab == code, iterations=1))
        for i in range(1, n + 1):
            m = comps == i
            if m.sum() < 100:  # < 1 ha
                continue
            X = comp[:, m].T
            prev_codes = prev_lab[m]
            prev_major = int(np.bincount(prev_codes[prev_codes != 65535]).argmax()) if (prev_codes != 65535).any() else None
            for k in (16, 18, 20, 24):
                xs = X.copy(); xs[:, k:] = np.nan
                pv = None if prev_major is None else np.full(len(xs), cm.PREV_CODES[cm.class_of(prev_major)], "float32")
                g = None if gdd is None else np.broadcast_to(gdd, (len(xs), 24))
                p = booster.predict(cm.features(xs, k, pv, g)).mean(axis=0)
                rows.append({"window": wid, "true": cm.class_of(code), "pred": cm.CLASSES[int(p.argmax())],
                             "conf": float(p.max()), "k": k, "ha": m.sum() / 100})
    print("window", wid, "done", flush=True)
df = pd.DataFrame(rows)
g3 = lambda s: s.where(s.isin(["wheat", "maize"]), "other")
for k, sub in df.groupby("k"):
    t, p = g3(sub.true), g3(sub.pred)
    wp = ((p == "wheat") & (t == "wheat")).sum() / max((p == "wheat").sum(), 1)
    mp = ((p == "maize") & (t == "maize")).sum() / max((p == "maize").sum(), 1)
    wr = ((p == "wheat") & (t == "wheat")).sum() / max((t == "wheat").sum(), 1)
    mr = ((p == "maize") & (t == "maize")).sum() / max((t == "maize").sum(), 1)
    wm = sub[t.isin(["wheat", "maize"]) & p.isin(["wheat", "maize"])]
    hi = sub[sub.conf >= 0.7]
    print(f"slots {k} ({sub.k.iloc[0]}): fields {len(sub)} | 7-class {(sub.true == sub.pred).mean():.2f} | 3-way {(t == p).mean():.2f} | "
          f"wheat P {wp:.2f} R {wr:.2f} | maize P {mp:.2f} R {mr:.2f} | wheat-vs-maize {(g3(wm.true) == g3(wm.pred)).mean():.2f} | "
          f"conf>=0.7: {len(hi)} fields, 3-way {(g3(hi.true) == g3(hi.pred)).mean():.2f}")
df.to_csv(D / "models" / "field_eval.csv", index=False)
