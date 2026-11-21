"""E1 helpers: Open-Meteo climate baseline for LUCAS points."""
from __future__ import annotations
import time
import numpy as np
import pandas as pd
from .http import session, cached

API = "https://archive-api.open-meteo.com/v1/archive"


def _batch(lats, lons):
    q = (f"{API}?latitude={','.join(f'{x:.3f}' for x in lats)}&longitude={','.join(f'{x:.3f}' for x in lons)}"
         "&start_date=2010-01-01&end_date=2018-12-31&daily=temperature_2m_mean,precipitation_sum&timezone=UTC")
    def fetch():
        for _ in range(12):
            time.sleep(2.0)
            r = session.get(q, timeout=120)
            if r.status_code == 429:
                time.sleep(65)  # minutely limit: back off a full minute
                continue
            r.raise_for_status()
            return r.json()
        raise RuntimeError("Open-Meteo rate limit persisted")
    js = cached("openmeteo_e1", q, fetch)
    return js if isinstance(js, list) else [js]


def climate(df: pd.DataFrame, bs: int = 8) -> pd.DataFrame:
    """Mean annual T (C) and mean annual precip (mm), 2010-2018, per row (coords rounded to 0.001 deg)."""
    out = []
    for i in range(0, len(df), bs):
        sub = df.iloc[i:i + bs]
        res = _batch(sub.latitude.values, sub.longitude.values)
        for r in res:
            d = r["daily"]
            t = np.array(d["temperature_2m_mean"], float)
            p = np.array(d["precipitation_sum"], float)
            out.append((np.nanmean(t), np.nansum(p) / 9.0))
    return pd.DataFrame(out, columns=["mat", "map"], index=df.index)


# ---------------- modelling ----------------
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.metrics import roc_auc_score
from sklearn.utils.class_weight import compute_sample_weight

REGION = {  # countries with n<10 merged into regional groups
    "Portugal": "Iberia-S", "Cyprus": "Balkan-E.Med", "Greece": "Balkan-E.Med",
    "Denmark": "Nordic", "Sweden": "Nordic", "Finland": "Nordic",
    "Latvia": "Baltic", "Lithuania": "Baltic", "Estonia": "Baltic",
    "Netherlands": "Benelux/UK", "Belgium": "Benelux/UK", "UK": "Benelux/UK",
    "Austria": "Central", "Slovakia": "Central", "Hungary": "Central", "Slovenia": "Central",
}


def clr(X: np.ndarray) -> np.ndarray:
    """X: relative abundance in % (n x g). Adds 'other' remainder, pseudocount = half min non-zero."""
    other = np.maximum(100 - X.sum(1, keepdims=True), 1e-3)
    A = np.hstack([X, other])
    pc = 0.5 * A[A > 0].min()
    L = np.log(A + pc)
    return L - L.mean(1, keepdims=True)


def make_model(kind: str):
    if kind == "logit":
        return make_pipeline(StandardScaler(), LogisticRegression(C=1.0, class_weight="balanced", max_iter=2000))
    return HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=150, random_state=0)


def fit_predict(kind, Xtr, ytr, Xte):
    m = make_model(kind)
    if kind == "logit":
        m.fit(Xtr, ytr)
    else:
        m.fit(Xtr, ytr, sample_weight=compute_sample_weight("balanced", ytr))
    return m.predict_proba(Xte)[:, 1]


def group_folds(groups, k, rng):
    ug = np.unique(groups)
    rng.shuffle(ug)
    # greedy balancing on size with shuffled order -> shuffled assignment
    sizes = {g: (groups == g).sum() for g in ug}
    load = np.zeros(k); asg = {}
    for g in ug:
        f = int(np.argmin(load + rng.random(k) * 1e-6)); asg[g] = f; load[f] += sizes[g]
    return np.array([asg[g] for g in groups])


def oof(kind, X, y, groups, k, seed):
    """One CV repeat: out-of-fold predictions."""
    fold = group_folds(groups, k, np.random.default_rng(seed))
    p = np.full(len(y), np.nan)
    for f in range(k):
        te = fold == f; tr = ~te
        if len(np.unique(y[tr])) < 2 or te.sum() == 0:
            continue
        p[te] = fit_predict(kind, X[tr], y[tr], X[te])
    return p


def climate_power(df: pd.DataFrame) -> pd.DataFrame:
    """Fallback when Open-Meteo hourly limit blocks the archive pull: NASA POWER (MERRA-2) 2001-2025
    annual climatology, one request per point. mat in C, map in mm/yr."""
    out = []
    for lat, lon in zip(df.latitude, df.longitude):
        url = ("https://power.larc.nasa.gov/api/temporal/climatology/point?parameters=T2M,PRECTOTCORR"
               f"&community=AG&longitude={lon:.2f}&latitude={lat:.2f}&format=JSON")
        def fetch():
            time.sleep(0.25)
            for _ in range(6):
                r = session.get(url, timeout=60)
                if r.status_code == 429:
                    time.sleep(10); continue
                r.raise_for_status(); return r.json()
            raise RuntimeError("POWER rate limit")
        p = cached("power_e1", url, fetch)["properties"]["parameter"]
        out.append((p["T2M"]["ANN"], p["PRECTOTCORR"]["ANN"] * 365.25))
    return pd.DataFrame(out, columns=["mat", "map"], index=df.index)
