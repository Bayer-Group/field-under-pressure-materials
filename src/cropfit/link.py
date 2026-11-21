"""Link every dataset to the sampling events: feature = aggregate(modality, plot footprint, time window
relative to the event). The spatial part is done when a dataset is fetched (all tables here are per plot);
this module applies the temporal operators and records what was actually used.

Output rows (long): event_id, modality, role, variable, window, value (number) or value_text (category),
obs_date (date of the observation used), lag_days (obs_date - event date; negative = before sampling),
n_obs, source. A feature that cannot be computed is simply absent: no zeros, no interpolation.

Windows: static | antecedent_<N>d | at_sample | nearest_flight | last_before | season | prior_t-<k> | anomaly.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import daymet

COLS = ["event_id", "modality", "role", "variable", "window", "value", "value_text", "obs_date", "lag_days",
        "n_obs", "source"]


def _rows(df: pd.DataFrame, variables, text, **const) -> pd.DataFrame:
    """Melt wide per-event columns into long rows; df has event_id and optional obs_date, lag_days, n_obs, source."""
    keep = [c for c in ("event_id", "obs_date", "lag_days", "n_obs", "source") if c in df.columns]
    parts = []
    for v in variables:
        if v in df.columns:
            p = df[keep].copy()
            p["variable"], p["value"] = v, pd.to_numeric(df[v], errors="coerce")
            parts.append(p[p["value"].notna()])
    for v in text:
        if v in df.columns:
            p = df[keep].copy()
            p["variable"], p["value_text"] = v, df[v].astype("string")
            parts.append(p[p["value_text"].notna()])
    if not parts:
        return pd.DataFrame(columns=COLS)
    out = pd.concat(parts, ignore_index=True)
    for k, v in const.items():
        if k not in out.columns:
            out[k] = v
    return out.reindex(columns=COLS)


def static(events: pd.DataFrame, table: pd.DataFrame, variables=(), text=(), key: str = "plotID", **const):
    """Time-invariant plot properties: the same value for every event of the plot."""
    j = events[["event_id", "plotID"]].merge(table, left_on="plotID", right_on=key, how="inner")
    return _rows(j, variables, text, window="static", **const)


def nearest(events: pd.DataFrame, obs: pd.DataFrame, variables=(), text=(), date: str = "date",
            max_lag_days: int = 10, direction: str = "nearest", window: str = "at_sample",
            source_col: str | None = None, **const):
    """The observation of the same plot closest in time to the event, within max_lag_days.
    direction: 'nearest' (either side) or 'backward' (only observations on or before the event date)."""
    o = obs.copy()
    o["obs_date"] = pd.to_datetime(o[date]).astype("datetime64[ns]")
    # full sort first, so that observations on the same day always come in the same order
    o = o.dropna(subset=["obs_date"]).sort_values(sorted(o.columns), kind="stable").sort_values("obs_date", kind="stable")
    e = events[["event_id", "plotID", "date"]].copy()
    e["date"] = pd.to_datetime(e["date"]).astype("datetime64[ns]")
    j = pd.merge_asof(e.sort_values("date"), o.drop(columns=[date] if date != "obs_date" else []),
                      left_on="date", right_on="obs_date", by="plotID", direction=direction,
                      tolerance=pd.Timedelta(days=max_lag_days))
    j = j[j["obs_date"].notna()].copy()
    j["lag_days"] = (j["obs_date"] - j["date"]).dt.days
    j["n_obs"] = 1
    if source_col and source_col in j:
        j["source"] = j[source_col]
    return _rows(j, variables, text, window=window, **const)


def annual(events: pd.DataFrame, table: pd.DataFrame, variables=(), text=(), year: str = "year",
           offsets=(0,), anomaly=(), key: str = "plotID", **const):
    """Per-year values: offset 0 is the year of the event ('season'), -k the k-th year before ('prior_t-k').
    anomaly: variables also given as the event-year value minus the plot's mean over all other years."""
    t = table.rename(columns={key: "plotID", year: "_year"})
    parts = []
    for off in offsets:
        e = events[["event_id", "plotID", "year"]].assign(_year=events["year"] + off)
        j = e.merge(t, on=["plotID", "_year"], how="inner")
        j["obs_date"] = pd.to_datetime(j["_year"].astype(int).astype(str) + "-07-01")
        parts.append(_rows(j, variables, text, window="season" if off == 0 else f"prior_t{off}", **const))
    for v in anomaly:
        if v not in t.columns:
            continue
        e = events[["event_id", "plotID", "year"]].merge(t[["plotID", "_year", v]], on="plotID")
        e[v] = pd.to_numeric(e[v], errors="coerce")
        cur = e[e["_year"] == e["year"]].set_index("event_id")[v]
        oth = e[e["_year"] != e["year"]].groupby("event_id")[v].agg(["mean", "count"])
        a = pd.DataFrame({"anom": cur - oth["mean"], "n_obs": oth["count"]}).dropna().reset_index()
        a = a[a["n_obs"] >= 3].rename(columns={"anom": v})
        parts.append(_rows(a, [v], (), window="anomaly", **const))
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=COLS)


def weather(events: pd.DataFrame, daily: pd.DataFrame, key: str = "unit_id", windows=(7, 30, 90), **const):
    """Antecedent weather from the daily series of each plot (daymet.event_windows)."""
    by_plot = {k: g.sort_values("date") for k, g in daily.groupby(key)}
    rows = []
    for e in events.itertuples():
        d = by_plot.get(e.plotID)
        if d is None:
            continue
        w = daymet.event_windows(d, e.date, windows)
        last = w.pop("weather_last_day")
        if pd.isna(last) or (pd.Timestamp(e.date) - last).days > 2:      # series ends before the event
            continue
        for k, v in w.items():
            if pd.isna(v):
                continue
            n = next((n for n in windows if f"_{n}d" in k), None)
            var = k.replace(f"_{n}d", "") if n else k
            win = f"antecedent_{n}d" if n else ("antecedent_90d" if k == "days_since_rain5" else "year_to_date")
            rows.append(dict(event_id=e.event_id, variable=var, window=win, value=float(v), obs_date=last,
                             lag_days=(last - pd.Timestamp(e.date)).days, n_obs=n))
    out = pd.DataFrame(rows)
    for k, v in const.items():
        out[k] = v
    return out.reindex(columns=COLS)


def last_before(events: pd.DataFrame, ev_log: pd.DataFrame, type_col: str, date: str = "date",
                key: str = "plotID", max_days: int = 365, text_col: str | None = None, **const):
    """Dated management events: for each type, days since the last one on or before the sampling date
    (variable = days_since_<type>, window 'last_before'), looking back at most max_days. With text_col, what
    that event involved (product, species) is added as last_<type>_what."""
    log = ev_log.rename(columns={key: "_k"}).copy()
    log["obs_date"] = pd.to_datetime(log[date]).astype("datetime64[ns]")
    log = log.dropna(subset=["obs_date", type_col]).sort_values("obs_date")
    e = events[["event_id", "plotID", "site", "date"]].copy()
    e["_k"] = e[key] if key in e else e["plotID"]
    e["date"] = pd.to_datetime(e["date"]).astype("datetime64[ns]")
    parts = []
    for typ, g in log.groupby(type_col):
        j = pd.merge_asof(e.sort_values("date"), g[["_k", "obs_date"] + ([text_col] if text_col else [])],
                          left_on="date", right_on="obs_date",
                          by="_k", direction="backward", tolerance=pd.Timedelta(days=max_days))
        j = j[j["obs_date"].notna()].copy()
        j["lag_days"] = (j["obs_date"] - j["date"]).dt.days
        name = "days_since_" + str(typ).strip().lower().replace(" ", "_")
        j[name] = -j["lag_days"]
        j["n_obs"] = 1
        what = []
        if text_col:
            what = [f"last_{name[11:]}_what"]
            j[what[0]] = j[text_col]
        parts.append(_rows(j, [name], what, window="last_before", **const))
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=COLS)


def wide(features: pd.DataFrame) -> pd.DataFrame:
    """One row per event; columns <modality>__<variable>__<window>, plus __lag for at_sample / nearest_flight
    features so the distance in time stays visible next to the value."""
    f = features.copy()
    f["col"] = f["modality"] + "__" + f["variable"] + "__" + f["window"]
    num = f[f["value"].notna()].pivot_table(index="event_id", columns="col", values="value", aggfunc="first")
    txt = f[f["value_text"].notna()].pivot_table(index="event_id", columns="col", values="value_text", aggfunc="first")
    lag = f[f["window"].isin(["at_sample", "nearest_flight", "nearest_survey"])].assign(
        col=lambda d: d["modality"] + "__lag_days__" + d["window"]).pivot_table(
        index="event_id", columns="col", values="lag_days", aggfunc="first")
    out = pd.concat([num, txt, lag], axis=1)
    return out.reindex(sorted(out.columns), axis=1).reset_index()
