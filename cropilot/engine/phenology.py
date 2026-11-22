"""
Growth stage (BBCH) per day from growing degree days (GDD).

No sowing dates exist in the data, so the model uses typical regional dates (team assumption) and
reports a stage_confidence below 1. Each estimate says how it was made, for the explanation.

- Winter wheat: sown ~1 October. Autumn development from GDD base 0 °C since sowing (to BBCH 25,
  tillering, by winter). From 1 January the spring development follows GDD base 0 °C since 1 January.
- Maize: sown ~25 April. GDD base 6 °C since sowing.
- Winter barley and other winter cereals: like wheat, sown a little earlier, heading and harvest earlier.
- Winter rapeseed: sown ~25 August (before the season starts on 1 September). Autumn and spring
  development from GDD base 5 °C (since sowing / since 1 January).
- Sugar beet: sown ~5 April, GDD base 3 °C since sowing. Potato: planted ~20 April, GDD base 6 °C.

The GDD -> BBCH tables are calibrated to typical dates in Opolskie (heading end of May, wheat
harvest mid-July; maize tasseling mid/late July, maturity end of September).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from engine.catalog import BARLEY, MAIZE, OTHER_CEREALS, POTATO, RAPESEED, SUGAR_BEET, WHEAT

STAGE_NAMES = [
    (-1, "przed siewem"), (0, "siew, kiełkowanie"), (9, "wschody"), (10, "rozwój liści"), (20, "krzewienie"),
    (30, "strzelanie w źdźbło"), (51, "kłoszenie"), (61, "kwitnienie"), (71, "rozwój ziarniaków"),
    (83, "dojrzewanie"), (89, "dojrzałość pełna"), (92, "zbiór / przejrzałość"),
]

# (GDD, BBCH) breakpoints, linear in between.
# Calibrated on observed phenology (engine/scripts/calibrate_phenology_dwd.py): DWD annual reporters in
# eastern Germany (Saxony, Brandenburg, Saxony-Anhalt, Thuringia; ~250 station-seasons per phase,
# seasons 2024-2026) with ERA5 temperatures. Wheat heading (BBCH 51) at a median 957 GDD agrees with the
# earlier Sentinel-2 calibration near Krapkowice (NDVI peak ~ heading at 1060 GDD).
WHEAT_AUTUMN = [(0, 0), (145, 10), (270, 13), (440, 21), (620, 25)]  # base 0, since sowing (emergence: DWD 144)
WHEAT_SPRING = [(0, 25), (400, 30), (485, 31), (560, 32), (700, 37), (820, 39), (900, 49), (957, 51), (1010, 55),
                (1080, 59), (1130, 61), (1250, 69), (1440, 75), (1650, 83), (1785, 87), (1950, 89), (2150, 92)]  # base 0, since 1 Jan
MAIZE_TABLE = [(0, 0), (90, 9), (120, 10), (210, 13), (300, 16), (350, 30), (370, 31), (780, 51), (812, 53), (860, 59),
               (909, 63), (1000, 69), (1199, 75), (1374, 85), (1499, 87), (1650, 89)]  # base 6, since sowing

def _scaled(table, k):
    """The same stage curve reached with k x the degree days (k < 1 = an earlier crop)."""
    return [(g * k if b > 25 else g, b) for g, b in table]


# Other crops, same DWD calibration (rye stands for "other cereals"; triticale and oats are a little later).
BARLEY_SPRING = [(0, 25), (330, 30), (400, 31), (560, 37), (650, 49), (709, 51), (760, 55), (800, 59), (840, 61),
                 (930, 69), (1100, 75), (1270, 83), (1377, 87), (1500, 89), (1650, 92)]  # winter barley, base 0
OTHER_CEREALS_SPRING = [(0, 25), (360, 30), (430, 31), (620, 37), (780, 49), (830, 51), (880, 55), (950, 59), (1000, 61),
                        (1120, 69), (1380, 75), (1600, 83), (1750, 87), (1900, 89), (2100, 92)]  # rye / triticale, base 0
RAPESEED_AUTUMN = [(0, 0), (100, 9), (160, 10), (260, 12), (380, 14), (480, 16), (580, 18), (700, 19)]   # base 5, since sowing
RAPESEED_SPRING = [(0, 19), (40, 30), (65, 31), (82, 51), (120, 57), (160, 60), (230, 65), (330, 69), (520, 75),
                   (720, 79), (860, 83), (990, 89), (1100, 92)]  # base 5, since 1 Jan: flowering mid April, harvest early July
SUGAR_BEET_TABLE = [(0, 0), (155, 10), (230, 12), (320, 14), (450, 19), (520, 31), (590, 39), (1300, 45), (2000, 49)]  # base 3
POTATO_TABLE = [(0, 0), (130, 9), (200, 15), (300, 21), (450, 35), (550, 51), (650, 61), (750, 65), (850, 69),
                (1000, 75), (1300, 91), (1500, 97)]  # base 6, since planting


@dataclass(frozen=True)
class Profile:
    winter: bool              # sown in autumn of the previous year
    sowing: tuple             # (month, day), team assumption
    base: float               # GDD base temperature (°C)
    table: list               # spring crops: since sowing; winter crops: spring curve since 1 January
    autumn: list | None = None
    spring_base: float | None = None  # winter crops: base of the spring curve (default: base)
    season_end: tuple = (8, 31)       # last day of the crop's season (harvest), (month, day) of the season year


PROFILES = {
    WHEAT: Profile(True, (10, 1), 0.0, WHEAT_SPRING, WHEAT_AUTUMN),
    BARLEY: Profile(True, (9, 20), 0.0, BARLEY_SPRING, WHEAT_AUTUMN),
    OTHER_CEREALS: Profile(True, (9, 25), 0.0, OTHER_CEREALS_SPRING, WHEAT_AUTUMN),
    RAPESEED: Profile(True, (8, 25), 5.0, RAPESEED_SPRING, RAPESEED_AUTUMN),
    MAIZE: Profile(False, (4, 25), 6.0, MAIZE_TABLE, season_end=(12, 31)),
    SUGAR_BEET: Profile(False, (4, 5), 3.0, SUGAR_BEET_TABLE, season_end=(11, 30)),
    POTATO: Profile(False, (4, 20), 6.0, POTATO_TABLE, season_end=(10, 31)),
}
DEFAULT_SOWING = {c: p.sowing for c, p in PROFILES.items()}  # (month, day), team assumption
GDD_BASE = {c: p.base for c, p in PROFILES.items()}


def season_end(crop: int, season: int) -> date:
    """Last day a crop of `season` is in the field (spring crops harvested after 31 August stay open)."""
    m, d = PROFILES[crop].season_end if crop in PROFILES else (8, 31)
    return date(season, m, d)


def crop_season(crop: int, day: date) -> int:
    """The season a day belongs to for this crop (a beet field in October still belongs to that year)."""
    s = day.year + 1 if day.month >= 9 else day.year
    if crop in PROFILES and not PROFILES[crop].winter and day.month >= 9 and day <= season_end(crop, day.year):
        return day.year
    return s
STAGE_CONFIDENCE_GDD = 0.6


@dataclass
class StageEstimate:
    bbch: float
    name: str
    method: str
    sowing: date
    gdd: float
    confidence: float

    def as_dict(self) -> dict:
        return {"bbch": int(round(self.bbch)), "name": self.name, "method": self.method,
                "sowing_assumed": self.sowing.isoformat(), "gdd": round(self.gdd), "confidence": self.confidence}


MAIZE_STAGE_NAMES = [
    (-1, "przed siewem"), (0, "siew, kiełkowanie"), (9, "wschody"), (10, "rozwój liści"),
    (30, "wzrost łodygi"), (51, "wiechowanie"), (63, "kwitnienie (znamiona)"), (71, "nalewanie ziarna"),
    (83, "dojrzewanie"), (87, "dojrzałość fizjologiczna"), (89, "dojrzałość pełna"),
]


RAPESEED_STAGE_NAMES = [
    (-1, "przed siewem"), (0, "siew, kiełkowanie"), (9, "wschody"), (10, "rozwój liści (rozeta)"),
    (30, "wzrost pędu"), (50, "pąkowanie"), (60, "kwitnienie"), (70, "rozwój łuszczyn"), (80, "dojrzewanie"),
    (89, "dojrzałość pełna"), (92, "zbiór / przejrzałość"),
]
SUGAR_BEET_STAGE_NAMES = [
    (-1, "przed siewem"), (0, "siew, kiełkowanie"), (10, "wschody, liścienie"), (11, "rozwój liści"),
    (31, "zakrywanie międzyrzędzi"), (39, "zakryte międzyrzędzia"), (40, "wzrost korzenia"), (49, "korzeń gotowy do zbioru"),
]
POTATO_STAGE_NAMES = [
    (-1, "przed sadzeniem"), (0, "sadzenie, kiełkowanie"), (9, "wschody"), (10, "rozwój liści"),
    (21, "pędy boczne"), (31, "zwieranie rzędów"), (40, "zawiązywanie bulw"), (51, "pąkowanie"), (60, "kwitnienie"),
    (70, "jagody, przyrost bulw"), (91, "zasychanie naci"), (97, "zaschnięta nać"),
]
CROP_STAGE_NAMES = {MAIZE: MAIZE_STAGE_NAMES, RAPESEED: RAPESEED_STAGE_NAMES, SUGAR_BEET: SUGAR_BEET_STAGE_NAMES,
                    POTATO: POTATO_STAGE_NAMES}


def stage_name(bbch: float, crop: int | None = None) -> str:
    names = CROP_STAGE_NAMES.get(crop, STAGE_NAMES)
    name = names[0][1]  # bbch < 0: not sown yet
    for b, n in names:
        if bbch >= b:
            name = n
    return name


def _interp(table, x):
    xs, ys = zip(*table)
    return np.interp(x, xs, ys)


def bbch_series(crop: int, daily_temp: pd.Series, season: int, sowing: date | None = None) -> pd.DataFrame:
    """
    daily_temp: avg temperature (°C) indexed by date, covering the season (gaps are filled).
    Returns a frame indexed by date with columns bbch, gdd, sowing (trailing sums only: no look-ahead).
    """
    t = daily_temp.sort_index().astype(float)
    t = t.reindex(pd.date_range(t.index.min(), t.index.max(), freq="D")).interpolate(limit_direction="both")
    prof = PROFILES.get(crop, PROFILES[MAIZE])
    base = prof.base
    month, day = prof.sowing
    out = pd.DataFrame(index=t.index)
    given = sowing is not None
    if prof.winter:
        sowing = pd.Timestamp(sowing) if given else pd.Timestamp(season - 1, month, day)
        gdd_day = (t - base).clip(lower=0)
        spring_day = (t - (prof.spring_base if prof.spring_base is not None else base)).clip(lower=0)
        autumn = gdd_day.where((t.index >= sowing) & (t.index < pd.Timestamp(season, 1, 1)), 0).cumsum()
        spring = spring_day.where(t.index >= pd.Timestamp(season, 1, 1), 0).cumsum()
        bbch_aut = _interp(prof.autumn, autumn.values)
        bbch_spr = _interp(prof.table, spring.values)
        in_spring = t.index >= pd.Timestamp(season, 1, 1)
        out["bbch"] = np.where(in_spring, np.maximum(bbch_spr, bbch_aut), bbch_aut)
        out.loc[t.index < sowing, "bbch"] = -1
        out["gdd"] = np.where(in_spring, spring.values, autumn.values)
    else:
        sowing = pd.Timestamp(sowing) if given else pd.Timestamp(season, month, day)
        gdd = (t - base).clip(lower=0).where(t.index >= sowing, 0).cumsum()
        out["bbch"] = _interp(prof.table, gdd.values)
        out.loc[t.index < sowing, "bbch"] = -1
        out["gdd"] = gdd.values
    out["sowing"] = sowing.date()
    out["method"] = "suma temperatur, data siewu od rolnika" if given else "suma temperatur, typowa data siewu"
    out["confidence"] = 0.85 if given else STAGE_CONFIDENCE_GDD
    return out


def estimate(crop: int, stages: pd.DataFrame, day: date) -> StageEstimate:
    row = stages.loc[pd.Timestamp(day)]
    return StageEstimate(bbch=float(row.bbch), name=stage_name(row.bbch, crop), method="suma temperatur, typowa data siewu",
                         sowing=row.sowing, gdd=float(row.gdd), confidence=STAGE_CONFIDENCE_GDD)


def degree_days_base10(daily_temp: pd.Series, year: int) -> pd.Series:
    """Degree days base 10 °C since 1 January of `year` (for pest activity). Trailing sum."""
    t = daily_temp.sort_index().astype(float)
    t = t.reindex(pd.date_range(t.index.min(), t.index.max(), freq="D")).interpolate(limit_direction="both")
    return (t - 10).clip(lower=0).where(t.index >= pd.Timestamp(year, 1, 1), 0).cumsum()


STAGE_CONFIDENCE_SATELLITE = 0.8


def calibrate(stages: pd.DataFrame, crop: int, anchors) -> pd.DataFrame:
    """
    Shift the degree-day stage curve so it passes through satellite anchors (engine.satellite.fieldndvi).
    An anchor is applied only from the day it could be known (`detected_on`), so earlier days keep the
    uncalibrated estimate: no look-ahead.
    """
    if not anchors or crop not in (WHEAT, MAIZE):  # satellite anchors exist for wheat and maize only
        return stages
    table = WHEAT_SPRING if crop == WHEAT else MAIZE_TABLE
    gdds, bbchs = zip(*table)
    out = stages.copy()
    for a in sorted(anchors, key=lambda x: x.detected_on):
        on = pd.Timestamp(a.on)
        if on not in out.index:
            continue
        if crop == WHEAT and on.month >= 9:  # an autumn scene: the spring curve below starts on 1 January
            continue
        need = float(np.interp(a.bbch, bbchs, gdds))
        delta = float(stages.loc[on, "gdd"]) - need
        use = out.index >= pd.Timestamp(a.detected_on)
        if crop == WHEAT:
            use &= out.index >= pd.Timestamp(on.year, 1, 1)
        shifted = np.interp(stages.loc[use, "gdd"].to_numpy() - delta, gdds, bbchs)
        out.loc[use, "bbch"] = np.maximum(shifted, 0)
        out.loc[use, "method"] = f"suma temperatur skalibrowana zdjęciami satelitarnymi: {a.what}"
        out.loc[use, "confidence"] = STAGE_CONFIDENCE_SATELLITE
    return out
