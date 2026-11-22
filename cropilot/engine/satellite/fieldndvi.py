"""
Per-field NDVI time series (mean of the clear pixels inside the polygon, one value per Sentinel-2
scene), cached in DATA_DIR/satellite/fields/ so the engine never needs the network at run time.

    python manage.py engine_fetch_ndvi [--season 2025] [--fields 1 2]     # fills the cache (network)
    series = load(field_id, season)   # DataFrame: date, ndvi, clear_share, pixels  (or None)
    anchors = phenology_anchors(series, crop, season)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

MIN_CLEAR_SHARE = 0.5  # a scene counts for a field when at least half its pixels are clear


def cache_dir() -> Path:
    try:
        from django.conf import settings
        base = Path(settings.BASE_DIR)
    except Exception:
        base = Path(__file__).resolve().parents[2]
    return (base / os.environ.get("DATA_DIR", "../field-under-pressure-data") / "satellite" / "fields").resolve()


def geometry_key(geometry) -> str:
    """Short hash of the polygon: the cache follows the shape, not just the database id (ids are reused)."""
    import hashlib
    import json

    return hashlib.sha1(json.dumps(geometry, sort_keys=True).encode()).hexdigest()[:10]


def path_for(field, season: int) -> Path:
    """Keyed by the polygon only: a scenario switch recreates fields with new ids, the same shapes keep their scenes."""
    return cache_dir() / f"field_{geometry_key(field.geometry)}_s{season}.parquet"


def _cached(field, season: int) -> Path | None:
    """The cache file of this polygon and season, also under the old id-based name (field<id>_<hash>_s<season>)."""
    p = path_for(field, season)
    if p.exists():
        return p
    old = sorted(cache_dir().glob(f"field*_{geometry_key(field.geometry)}_s{season}.parquet")) if cache_dir().exists() else []
    return old[0] if old else None


def fetch(field, season: int, end: date | None = None) -> pd.DataFrame | None:
    """Reads Sentinel-2 for the field's polygon over the season (Sep season-1 .. Nov season) and caches it."""
    import rasterio.features
    from pyproj import Transformer
    from shapely.geometry import mapping, shape
    from shapely.ops import transform as shp_transform

    from engine.satellite.earthsearch import read_ndvi_window

    geom = shape(field.geometry)
    start = date(season - 1, 9, 1)
    end = end or date(season, 11, 30)
    scenes = read_ndvi_window(geom.bounds, start.isoformat(), end.isoformat())
    if scenes is None:
        return None
    g = shp_transform(Transformer.from_crs("EPSG:4326", scenes.crs, always_xy=True).transform, geom)
    mask = rasterio.features.geometry_mask([mapping(g)], out_shape=scenes.ndvi.shape[1:], transform=scenes.transform, invert=True)
    rows = []
    for d, img in zip(scenes.dates, scenes.ndvi):
        v = img[mask]
        clear = np.isfinite(v)
        if mask.sum() == 0 or clear.mean() < MIN_CLEAR_SHARE:
            continue
        rows.append({"date": pd.Timestamp(d), "ndvi": float(np.nanmean(v)), "ndvi_p25": float(np.nanpercentile(v, 25)),
                     "ndvi_p75": float(np.nanpercentile(v, 75)), "clear_share": float(clear.mean()), "pixels": int(mask.sum())})
    df = pd.DataFrame(rows)
    p = path_for(field, season)
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(p, index=False)
    return df


def load(field, season: int) -> pd.DataFrame | None:
    """field: a Field (its polygon picks the cache file)."""
    p = _cached(field, season)
    if p is None:
        return None
    df = pd.read_parquet(p)
    return df.sort_values("date").reset_index(drop=True) if not df.empty else None


@dataclass
class Anchor:
    detected_on: date   # the first day this could be known (the scene that confirmed it)
    on: date            # the day the stage was reached
    bbch: float
    what: str


def phenology_anchors(series: pd.DataFrame | None, crop: int, season: int) -> list[Anchor]:
    """
    Growth-stage anchors from the field's NDVI curve; each is only usable from `detected_on` on.
    Wheat: spring NDVI peak ~ heading (BBCH 55); NDVI falling below 0.5 after it ~ yellow ripeness (BBCH 87).
    Maize: NDVI first above 0.35 after 20 April ~ 3-4 leaves (BBCH 13); summer NDVI peak ~ flowering (BBCH 65).
    """
    from engine.catalog import MAIZE, WHEAT

    if series is None or len(series) < 4:
        return []
    s = series.set_index("date")["ndvi"]
    out: list[Anchor] = []

    def peak_between(a: pd.Timestamp, b: pd.Timestamp, drop: float = 0.05):
        win = s[(s.index >= a) & (s.index <= b)]
        if win.empty:
            return None
        pk_day = win.idxmax()
        after = s[s.index > pk_day + pd.Timedelta(days=6)]
        conf = after[after <= win.max() - drop]
        if conf.empty:
            return None
        return pk_day, conf.index[0], float(win.max())

    if crop == WHEAT:
        # heading in Poland: mid-May to mid-June; an earlier or weaker peak is not a wheat heading
        pk = peak_between(pd.Timestamp(season, 5, 1), pd.Timestamp(season, 6, 30))
        if pk and pk[2] >= 0.7:
            out.append(Anchor(pk[1].date(), pk[0].date(), 55, f"szczyt NDVI {pk[2]:.2f} dnia {pk[0].strftime('%d.%m.%Y')} (kłoszenie)"))
            low = s[(s.index > pk[0]) & (s < 0.5)]
            if not low.empty:
                out.append(Anchor(low.index[0].date(), low.index[0].date(), 87, f"NDVI poniżej 0,5 dnia {low.index[0].strftime('%d.%m.%Y')} (dojrzałość woskowa)"))
    elif crop == MAIZE:
        # emergence = the rise after the spring minimum (bare soil after ploughing and sowing); a green
        # cover crop or weeds before ploughing must not count
        spring = s[(s.index >= pd.Timestamp(season, 4, 1)) & (s.index <= pd.Timestamp(season, 6, 20))]
        if not spring.empty:
            low_day, low = spring.idxmin(), float(spring.min())
            up = s[(s.index > low_day) & (s.index <= pd.Timestamp(season, 7, 15)) & (s >= max(0.35, low + 0.15))]
            if low < 0.3 and not up.empty:
                out.append(Anchor(up.index[0].date(), up.index[0].date(), 13,
                                  f"NDVI wzrosło z gołej gleby ({low:.2f} dnia {low_day.strftime('%d.%m.%Y')}) do {up.iloc[0]:.2f} dnia {up.index[0].strftime('%d.%m.%Y')} (młode rośliny)"))
        pk = peak_between(pd.Timestamp(season, 7, 1), pd.Timestamp(season, 9, 15))
        if pk and pk[2] >= 0.6:
            out.append(Anchor(pk[1].date(), pk[0].date(), 65, f"szczyt NDVI {pk[2]:.2f} dnia {pk[0].strftime('%d.%m.%Y')} (kwitnienie)"))
    return out


def crop_check(series: pd.DataFrame | None, crop: int, season: int, today: date) -> dict | None:
    """
    Does the field's NDVI curve so far look like the crop we think it is? Simple, explainable checks
    (the crop model in engine/cropmodel.py gives probabilities; this explains the obvious mismatches).
    """
    from engine.catalog import MAIZE, WHEAT

    if series is None or series.empty:
        return None
    s = series.set_index("date")["ndvi"]
    s = s[s.index <= pd.Timestamp(today)]
    if len(s) < 4:
        return None
    spring = s[(s.index >= pd.Timestamp(season, 3, 15)) & (s.index <= pd.Timestamp(season, 5, 15))]
    summer = s[(s.index >= pd.Timestamp(season, 7, 20)) & (s.index <= pd.Timestamp(season, 8, 31))]
    msgs, ok = [], True
    if crop == WHEAT and len(spring) >= 2:
        if spring.median() < 0.45:
            ok = False; msgs.append(f"wiosną goła gleba (mediana NDVI {spring.median():.2f} od połowy marca do połowy maja), a pszenica ozima jest wtedy zielona")
        if len(summer) >= 2 and summer.median() > 0.6:
            ok = False; msgs.append(f"zielono pod koniec lata (mediana NDVI {summer.median():.2f}), a pszenica jest już wtedy zebrana")
    if crop == MAIZE and len(spring) >= 2 and spring.median() > 0.7:
        ok = False; msgs.append(f"wiosną gęsta zieleń (mediana NDVI {spring.median():.2f}), a kukurydza jest wtedy dopiero siana")
    return {"consistent": ok, "issues": msgs, "scenes_used": int(len(s)),
            "text": "Krzywa z satelity pasuje do uprawy." if ok else "Krzywa z satelity nie pasuje do uprawy: " + "; ".join(msgs) + ". Potwierdź uprawę."}
