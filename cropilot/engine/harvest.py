"""
Harvest and storage outlook (not a Risk row: there is no threat category for it).

- Cereals (wheat, barley, other cereals): harvest when fully ripe (BBCH >= 89, grain < 15 % moisture). After that, 2-3 days of rain can
  start sprouting in the ear, which disqualifies the grain for bread.
  Safe storage moisture < 15 %.
- Maize: safe storage time of grain by moisture and temperature table below);
  storage moisture < 14.5 %, dry to 16 % and cool to lose 2-3 % more.

    harvest_outlook(crop, stage_bbch, weather_last_days, forecast)  -> dict for the field summary
    safe_storage_days(moisture_pct, grain_temp_c)                   -> days (maize)
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from engine.catalog import CEREALS, MAIZE

# Safe storage table: rows grain temperature (°C), columns grain moisture (%), values safe storage days
_T37_TEMPS = [-1.1, 1.7, 4.4, 7.2, 10.0, 12.8, 15.6, 18.3, 21.1, 23.9, 26.7]
_T37_MOIST = [18, 20, 22, 24, 26, 28, 30]
_T37 = np.array([
    [648, 321, 190, 127, 94, 74, 61], [432, 214, 126, 85, 62, 49, 40], [288, 142, 84, 56, 41, 32, 27],
    [192, 95, 56, 37, 27, 21, 18], [128, 63, 37, 25, 18, 14, 12], [85, 42, 25, 16, 12, 9, 8],
    [56, 28, 17, 11, 8, 7, 5], [42, 21, 13, 8, 6, 5, 4], [31, 16, 9, 6, 5, 4, 3],
    [23, 12, 7, 5, 4, 3, 2], [17, 9, 5, 4, 3, 2, 2]], dtype=float)


def safe_storage_days(moisture_pct: float, grain_temp_c: float) -> float:
    """Maize grain: days of safe storage, interpolated on log(days); outside the table it is clamped."""
    t = float(np.clip(grain_temp_c, _T37_TEMPS[0], _T37_TEMPS[-1]))
    m = float(np.clip(moisture_pct, _T37_MOIST[0], _T37_MOIST[-1]))
    logd = np.log(_T37)
    by_temp = np.array([np.interp(t, _T37_TEMPS, logd[:, j]) for j in range(len(_T37_MOIST))])
    return float(np.exp(np.interp(m, _T37_MOIST, by_temp)))


def _pl(iso: str) -> str:
    return f"{iso[8:10]}.{iso[5:7]}.{iso[:4]}"


def harvest_outlook(crop: int, bbch: float, recent: pd.DataFrame, forecast: pd.DataFrame | None,
                    grain_moisture_pct: float | None = None) -> dict | None:
    """
    recent: daily observed weather up to today (index dates; columns precip, avg_temperature, avg_relative_humidity).
    forecast: daily forecast (index dates; max/min temperature, total_precipitation, avg_relative_humidity) or None.
    """
    if (crop not in CEREALS and crop != MAIZE) or bbch < 83:
        return None
    out: dict = {"stage_bbch": int(round(bbch))}
    rain = recent["precip"].fillna(0) if "precip" in recent else pd.Series(dtype=float)
    wet = (rain >= 1.0).astype(int)
    run = 0
    for v in wet.iloc[::-1]:  # consecutive rainy days up to today
        if not v:
            break
        run += 1
    dry_days = []
    if forecast is not None and not forecast.empty:
        for d, row in forecast.sort_index().iterrows():
            p, rh = row.get("total_precipitation"), row.get("avg_relative_humidity")
            if (p is None or pd.isna(p) or p < 1) and (rh is None or pd.isna(rh) or rh < 80):
                dry_days.append(pd.Timestamp(d).date().isoformat())
    out["dry_days_ahead"] = dry_days
    out["rain_days_in_a_row"] = run
    if crop in CEREALS:
        ripe = bbch >= 89
        out["ready"] = ripe
        sprouting = "high" if ripe and run >= 2 else ("medium" if ripe and run == 1 else "low")
        out["sprouting_risk"] = sprouting
        out["text"] = (("Dojrzałość pełna: zbieraj w najbliższy suchy dzień" + (f" ({_pl(dry_days[0])})" if dry_days else "")
                        + (". Pada już 2 dni lub dłużej z rzędu: porastanie ziarna w kłosie może zdyskwalifikować ziarno (konsumpcyjne, browarne, siewne)." if sprouting == "high" else "."))
                       if ripe else "Dojrzewanie: zaplanuj zbiór; wilgotność ziarna powinna spaść poniżej 15 %.")
    else:
        out["ready"] = bbch >= 87
        temp = float(recent["avg_temperature"].tail(7).mean()) if "avg_temperature" in recent and len(recent) else 10.0
        moist = grain_moisture_pct if grain_moisture_pct is not None else 26.0
        days = safe_storage_days(moist, temp)
        out["storage"] = {"grain_moisture_pct": moist, "moisture_source": "rolnik" if grain_moisture_pct is not None else "typowa przy zbiorze (założenie)",
                          "grain_temp_c": round(temp, 1), "safe_days_undried": round(days),
                          "target_moisture_pct": 14.5}
        out["text"] = (f"Ziarno o wilgotności ok. {moist:.0f} % i temperaturze ok. {temp:.0f} °C przechowa się bez suszenia ok. {days:.0f} dni; "
                       "wysusz je do 16 % i schłodź (przy schładzaniu traci jeszcze 2-3 %), przechowuj poniżej 14,5 %."
                       + (f" Najbliższy suchy dzień: {_pl(dry_days[0])}." if dry_days else ""))
    return out
