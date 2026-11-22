"""
Calibrate the growth-stage curves (engine/phenology.py) on observed crop phenology.

Data: DWD annual phenology reporters (open data, Germany), stations in the eastern states (closest
climate to Opolskie), seasons 2024-2026; daily mean temperature for each station from
ERA5 (Open-Meteo archive API, no key). For each crop and observed phase the script computes the
degree days the engine's profile would have at that date, from the station's own sowing date when
reported, and compares them with the engine's table.

    python engine/scripts/calibrate_phenology_dwd.py DATA_DIR
        DATA_DIR/external/dwd/PH_*                 DWD files (downloaded by hand from opendata.dwd.de)
        DATA_DIR/external/dwd/era5/<lat>_<lon>.parquet   cached temperatures
        DATA_DIR/models/phenology_dwd.csv          per crop x phase: n, median date, median GDD, engine GDD
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

EAST = {"Sachsen", "Brandenburg", "Sachsen-Anhalt", "Thüringen"}
SEASONS = (2024, 2025, 2026)  # harvest years; DWD "Referenzjahr" is the calendar year of the observation
# DWD object id -> (engine crop code, file name part)
CROPS = {202: (1110, "Winterweizen"), 204: (1120, "Wintergerste"), 203: (1150, "Winterroggen"),
         205: (1430, "Winterraps"), 215: (1130, "Mais"), 253: (1320, "Zucker-Ruebe")}
# DWD phase id -> BBCH, per crop (phase definitions in PH_Beschreibung_Phasendefinition_...)
CEREAL = {12: 10, 15: 31, 18: 51, 19: 75, 21: 87, 22: 89}
PHASE_BBCH = {
    1110: CEREAL, 1120: CEREAL, 1150: {**CEREAL, 5: 61},
    1430: {12: 10, 14: 14, 67: 31, 17: 51, 5: 60, 22: 89},
    1130: {12: 9, 67: 31, 65: 53, 5: 63, 19: 75, 20: 85, 21: 87},
    1320: {12: 10, 13: 39},
}


def read_dwd(path: Path) -> pd.DataFrame:
    d = pd.read_csv(path, sep=";", skipinitialspace=True)
    d.columns = [c.strip() for c in d.columns]
    d = d[["Stations_id", "Referenzjahr", "Objekt_id", "Phase_id", "Eintrittsdatum"]]
    d["date"] = pd.to_datetime(d["Eintrittsdatum"].astype(str), format="%Y%m%d", errors="coerce")
    return d.dropna(subset=["date"])


def stations(path: Path) -> pd.DataFrame:
    s = pd.read_csv(path, sep=";", encoding="latin-1", skipinitialspace=True)
    s.columns = [c.strip() for c in s.columns]
    s = s.rename(columns={"geograph.Breite": "lat", "geograph.Laenge": "lon"})
    s["Bundesland"] = s["Bundesland"].astype(str).str.strip()
    s["Stations_id"] = pd.to_numeric(s["Stations_id"], errors="coerce")
    return s[s["Bundesland"].isin(EAST)][["Stations_id", "lat", "lon", "Bundesland"]]


def era5(lat: float, lon: float, cache: Path) -> pd.Series:
    """Daily mean 2 m temperature, 2023-07-01 .. 2026-10-31, on a 0.25° cell (cached)."""
    lat, lon = round(lat * 4) / 4, round(lon * 4) / 4
    f = cache / f"{lat:.2f}_{lon:.2f}.parquet"
    if f.exists():
        s = pd.read_parquet(f)["t"]
        s.index = pd.to_datetime(s.index)
        return s
    url = ("https://archive-api.open-meteo.com/v1/archive?latitude={:.2f}&longitude={:.2f}"
           "&start_date=2023-07-01&end_date=2026-10-31&daily=temperature_2m_mean&timezone=Europe%2FBerlin").format(lat, lon)
    for attempt in range(5):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                js = json.load(r)
            break
        except Exception:
            time.sleep(5 * (attempt + 1))
    else:
        raise RuntimeError(f"Open-Meteo failed for {lat},{lon}")
    s = pd.Series(js["daily"]["temperature_2m_mean"], index=pd.to_datetime(js["daily"]["time"]), name="t").astype(float)
    cache.mkdir(parents=True, exist_ok=True)
    s.to_frame().to_parquet(f)
    time.sleep(0.5)
    return s


def gdd_at(crop: int, temps: pd.Series, season: int, sowing: pd.Timestamp | None, day: pd.Timestamp) -> float:
    """Degree days the engine's profile counts at `day` (autumn since sowing / spring since 1 Jan / since sowing)."""
    from engine.phenology import PROFILES

    p = PROFILES[crop]
    m, d0 = p.sowing
    if p.winter:
        sow = sowing if sowing is not None else pd.Timestamp(season - 1, m, d0)
        jan1 = pd.Timestamp(season, 1, 1)
        if day < jan1:
            return float((temps[(temps.index >= sow) & (temps.index <= day)] - p.base).clip(lower=0).sum())
        base = p.spring_base if p.spring_base is not None else p.base
        return float((temps[(temps.index >= jan1) & (temps.index <= day)] - base).clip(lower=0).sum())
    sow = sowing if sowing is not None else pd.Timestamp(season, m, d0)
    return float((temps[(temps.index >= sow) & (temps.index <= day)] - p.base).clip(lower=0).sum())


def engine_gdd(crop: int, bbch: float, autumn: bool) -> float:
    from engine.phenology import PROFILES

    p = PROFILES[crop]
    table = p.autumn if (p.winter and autumn) else p.table
    g, b = zip(*table)
    return float(np.interp(bbch, b, g))


def main(data_dir: str) -> None:
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root))
    import os

    import django

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "fieldpressure.settings")
    django.setup()
    D = Path(data_dir) / "external" / "dwd"
    st = stations(D / "PH_Beschreibung_Phaenologie_Stationen_Jahresmelder.txt")
    rows = []
    for obj, (crop, name) in CROPS.items():
        obs = read_dwd(D / f"PH_Jahresmelder_Landwirtschaft_Kulturpflanze_{name}_akt.txt")
        obs = obs.merge(st, on="Stations_id")
        winter = crop in (1110, 1120, 1150, 1430)
        # season (harvest year) of each observation: autumn observations of winter crops belong to the next year
        autumn_obs = winter & (obs["date"].dt.month >= 7) & (obs["Phase_id"].isin([10, 12, 14]))
        obs["season"] = obs["Referenzjahr"] + autumn_obs.astype(int)
        for (sid, season), g in obs.groupby(["Stations_id", "season"]):
            if season not in SEASONS:
                continue
            temps = era5(g["lat"].iloc[0], g["lon"].iloc[0], D / "era5")
            sow_rows = g[g["Phase_id"] == 10]
            sowing = sow_rows["date"].min() if not sow_rows.empty else None
            for _, r in g.iterrows():
                if r["date"] > temps.index.max():
                    continue
                autumn = bool(winter and r["date"] < pd.Timestamp(season, 1, 1))
                if r["Phase_id"] == 10:
                    rows.append({"crop": crop, "phase": 10, "bbch": 0, "date": r["date"], "gdd": 0.0, "autumn": autumn,
                                 "station": sid, "season": season, "own_sowing": True})
                    continue
                bbch = PHASE_BBCH[crop].get(int(r["Phase_id"]))
                if bbch is None:
                    continue
                if not autumn and winter and r["date"].month >= 8 and bbch < 80:
                    continue  # implausible
                rows.append({"crop": crop, "phase": int(r["Phase_id"]), "bbch": bbch, "date": r["date"],
                             "gdd": gdd_at(crop, temps, int(season), sowing, r["date"]), "autumn": autumn,
                             "station": sid, "season": season, "own_sowing": sowing is not None})
    df = pd.DataFrame(rows)
    out = []
    for (crop, phase, bbch, autumn), g in df.groupby(["crop", "phase", "bbch", "autumn"]):
        doy = g["date"].dt.day_of_year
        out.append({"crop": crop, "phase": phase, "bbch": bbch, "autumn": autumn, "n": len(g),
                    "median_date": (pd.Timestamp(2001, 1, 1) + pd.Timedelta(days=int(doy.median()) - 1)).strftime("%d %b"),
                    "gdd_median": round(g["gdd"].median()), "gdd_p25": round(g["gdd"].quantile(0.25)),
                    "gdd_p75": round(g["gdd"].quantile(0.75)),
                    "engine_gdd": None if phase == 10 else round(engine_gdd(crop, bbch, autumn))})
    res = pd.DataFrame(out).sort_values(["crop", "autumn", "bbch"], ascending=[True, False, True])
    (Path(data_dir) / "models").mkdir(exist_ok=True)
    res.to_csv(Path(data_dir) / "models" / "phenology_dwd.csv", index=False)
    df.to_parquet(Path(data_dir) / "models" / "phenology_dwd_obs.parquet", index=False)
    pd.set_option("display.width", 200)
    print(res.to_string(index=False))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "../field-under-pressure-data")
