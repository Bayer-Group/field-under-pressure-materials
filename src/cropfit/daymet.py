"""Daymet single-pixel fetch and derived agro-climate features."""
from __future__ import annotations

import io
import math

import numpy as np
import pandas as pd

from . import http

API = "https://daymet.ornl.gov/single-pixel/api/data"


def snap_to_grid(lat: float, lon: float, km: float = 2.0) -> tuple[float, float]:
    """Snap a point to a regular km grid (for deduping field centroids)."""
    dlat = km / 111.32
    lat_s = round(lat / dlat) * dlat
    dlon = km / (111.32 * math.cos(math.radians(lat_s)))
    return round(lat_s, 4), round(round(lon / dlon) * dlon, 4)


def parse_daymet_csv(text: str) -> pd.DataFrame:
    lines = text.splitlines()
    start = next(i for i, l in enumerate(lines) if l.startswith("year,yday"))
    df = pd.read_csv(io.StringIO("\n".join(lines[start:])))
    df.columns = [c.split(" (")[0].strip() for c in df.columns]
    # Daymet uses a 365-day calendar: yday 1..365 map onto Jan 1.. Dec 30 (leap) / Dec 31 (non-leap)
    # Convention: leap years drop Dec 31, so date = Jan 1 + (yday-1) days always works.
    df["date"] = pd.to_datetime(df["year"].astype(str) + "-01-01") + pd.to_timedelta(df["yday"] - 1, unit="D")
    return df[["date", "year", "yday", "tmax", "tmin", "prcp"]]


def fetch_daymet(lat: float, lon: float, start_year: int, end_year: int) -> pd.DataFrame:
    """Daily tmax/tmin/prcp for the pixel at (lat, lon). Years not yet published are simply absent."""
    years = ",".join(str(y) for y in range(start_year, end_year + 1))
    key = f"{lat:.4f},{lon:.4f},{years}"

    def fetch():
        r = http.get(API, params=dict(lat=f"{lat:.4f}", lon=f"{lon:.4f}", vars="tmax,tmin,prcp",
                                      years=years))
        return r.text

    return parse_daymet_csv(http.cached("daymet", key, fetch, as_text=True))


def yearly_climate(df: pd.DataFrame) -> pd.DataFrame:
    """One row per year with the contract's per-year variables.
    Oct-Jun precip for year Y uses Oct-Dec of Y-1 (when present in df) plus Jan-Jun of Y."""
    d = df.copy()
    d["month"] = d["date"].dt.month
    tavg = (np.minimum(d["tmax"], 30) + np.maximum(d["tmin"], 10)) / 2 - 10
    d["gdd"] = np.maximum(0, tavg)
    rows = []
    for y, g in d.groupby("year"):
        gs = g[(g.month >= 5) & (g.month <= 9)]
        # frost-free: last spring (<1 Jul) and first fall (>=1 Jul) tmin <= 0
        fr = g[g["tmin"] <= 0]
        spring = fr[fr["date"] < pd.Timestamp(f"{y}-07-01")]
        fall = fr[fr["date"] >= pd.Timestamp(f"{y}-07-01")]
        last_spring = spring["yday"].max() if len(spring) else 0
        first_fall = fall["yday"].min() if len(fall) else g["yday"].max() + 1
        ja = g[g.month.isin([7, 8])]
        jun = g[g.month == 6]
        prev = d[(d.year == y - 1) & (d.month >= 10)]
        octjun = g[g.month <= 6]["prcp"].sum() + prev["prcp"].sum()
        rows.append(dict(
            year=int(y),
            gdd10_may_sep=gs["gdd"].sum(),
            frost_free_days=float(first_fall - last_spring - 1),
            prcp_apr_sep_mm=g[(g.month >= 4) & (g.month <= 9)]["prcp"].sum(),
            prcp_oct_jun_mm=octjun if len(prev) else np.nan,
            prcp_may_mm=g[g.month == 5]["prcp"].sum(),
            hot_days_jul_aug=int((ja["tmax"] >= 35).sum()),
            prcp_jul_aug_mm=ja["prcp"].sum(),
            june_heat_days=int((jun["tmax"] > 32).sum()),
        ))
    return pd.DataFrame(rows)


def summarise_yearly(yc: pd.DataFrame) -> dict:
    p25 = yc["prcp_jul_aug_mm"].quantile(0.25)
    return dict(
        gdd10_may_sep=float(yc["gdd10_may_sep"].median()),
        frost_free_days=float(yc["frost_free_days"].median()),
        prcp_apr_sep_mm=float(yc["prcp_apr_sep_mm"].median()),
        prcp_oct_jun_mm=float(yc["prcp_oct_jun_mm"].median()),
        prcp_may_mm=float(yc["prcp_may_mm"].median()),
        hot_days_jul_aug=float(yc["hot_days_jul_aug"].median()),
        p_wet_may=float((yc["prcp_may_mm"] > 100).mean()),
        p_hot_dry_jul_aug=float(((yc["hot_days_jul_aug"] >= 15) & (yc["prcp_jul_aug_mm"] < p25)).mean()),
        p_june_heat=float((yc["june_heat_days"] >= 5).mean()),
    )


def climate_features(lat: float, lon: float, start_year: int = 2008, end_year: int = 2025) -> dict:
    """Contract climate columns (without water-supply). Adds climate_years_used 'YYYY-YYYY'.
    Only complete years actually returned by Daymet are used."""
    df = fetch_daymet(lat, lon, start_year - 1, end_year)  # y-1 for Oct-Jun precip
    yc = yearly_climate(df)
    yc = yc[(yc.year >= start_year) & (yc.year <= end_year) & (df.groupby("year")["yday"].max()
            .reindex(yc.year).values >= 365)]
    out = summarise_yearly(yc)
    out["climate_years_used"] = f"{int(yc.year.min())}-{int(yc.year.max())}"
    return out


def event_windows(df: pd.DataFrame, date, windows=(7, 30, 90)) -> dict:
    """Weather the soil experienced before a sampling date, from the daily frame of fetch_daymet().

    Each window covers the N days ending the day before `date`. A window is NaN unless at least N-1 days are
    present (Daymet drops 31 Dec in leap years). Keys: prcp_<N>d_mm, tmean_<N>d_c, plus tmax_max_7d_c,
    frost_days_30d, days_since_rain5 (days since the last day with >= 5 mm, looking back up to 90 days; NaN if
    none), gdd10_ytd (growing degree days base 10 from 1 Jan to the day before), weather_last_day."""
    date = pd.Timestamp(date).normalize()
    d = df[(df["date"] < date) & (df["date"] >= date - pd.Timedelta(days=366))]
    out: dict = {}

    def win(n):
        w = d[d["date"] >= date - pd.Timedelta(days=n)]
        return w if len(w) >= n - 1 else None

    for n in windows:
        w = win(n)
        out[f"prcp_{n}d_mm"] = float(w["prcp"].sum()) if w is not None else np.nan
        out[f"tmean_{n}d_c"] = float(((w["tmax"] + w["tmin"]) / 2).mean()) if w is not None else np.nan
    w7, w30, w90 = win(7), win(30), win(90)
    out["tmax_max_7d_c"] = float(w7["tmax"].max()) if w7 is not None else np.nan
    out["frost_days_30d"] = float((w30["tmin"] <= 0).sum()) if w30 is not None else np.nan
    if w90 is not None:
        wet = w90[w90["prcp"] >= 5]
        out["days_since_rain5"] = float((date - wet["date"].max()).days) if len(wet) else np.nan
    else:
        out["days_since_rain5"] = np.nan
    ytd = d[d["date"] >= pd.Timestamp(year=date.year, month=1, day=1)]
    if len(ytd) >= date.day_of_year - 2:
        gdd = np.maximum(0, (np.minimum(ytd["tmax"], 30) + np.maximum(ytd["tmin"], 10)) / 2 - 10)
        out["gdd10_ytd"] = float(gdd.sum())
    else:
        out["gdd10_ytd"] = np.nan
    out["weather_last_day"] = d["date"].max() if len(d) else pd.NaT
    return out
