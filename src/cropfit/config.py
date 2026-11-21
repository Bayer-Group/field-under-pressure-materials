"""Paths and region config shared by all modules."""
from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
RESOURCES = ROOT / "resources"
RULES = ROOT / "rules"
DATA = ROOT / "data"
RAW = DATA / "raw"
PROCESSED = DATA / "processed"
CACHE = DATA / "cache"
OUTPUTS = ROOT / "outputs"
FIGURES = OUTPUTS / "figures"

for _p in (RAW, PROCESSED, CACHE, FIGURES):
    _p.mkdir(parents=True, exist_ok=True)


@lru_cache
def regions() -> dict:
    return yaml.safe_load((ROOT / "config" / "regions.yaml").read_text())


def sites() -> list[str]:
    """Site codes, defined once: the keys of `windows` in config/regions.yaml."""
    return list(regions()["windows"])


def window_bbox(site: str) -> tuple[float, float, float, float]:
    """(minlon, minlat, maxlon, maxlat) in WGS84 for a window (approximate square)."""
    w = regions()["windows"][site]
    dlat = w["half_km"] / 111.32
    dlon = w["half_km"] / (111.32 * math.cos(math.radians(w["center_lat"])))
    return (w["center_lon"] - dlon, w["center_lat"] - dlat, w["center_lon"] + dlon, w["center_lat"] + dlat)


def window_wkt(site: str) -> str:
    x0, y0, x1, y1 = window_bbox(site)
    return f"POLYGON(({x0} {y0}, {x1} {y0}, {x1} {y1}, {x0} {y1}, {x0} {y0}))"
