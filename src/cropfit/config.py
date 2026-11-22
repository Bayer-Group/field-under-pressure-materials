"""Paths and region config shared by all modules."""
from __future__ import annotations

import math
import re
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
    """Site codes, defined once: the keys of `windows` in config/regions.yaml. In light mode only the sites
    of the light-mode plots."""
    out = list(regions()["windows"])
    lp = light_plots()
    return out if lp is None else [s for s in out if any(p.startswith(f"{s}_") for p in lp)]


# ---------------------------------------------------------------- light mode
# Light mode restricts every download (and the event registry built from it) to a few plots. It is ON BY
# DEFAULT, so a fresh clone never starts an hours-long full download by accident. State is in
# data/light_mode.txt:
#   - file missing (fresh clone)  -> on, with the default plots (`light_plots` in config/regions.yaml);
#   - file says "off"             -> off, all plots;
#   - file lists plots            -> on, with those plots (one per line, "STER_006" or "STER 006").
# A file with neither plots nor "off" also falls back to the default plots. Switch with scripts/00_light_mode.py.
LIGHT_FILE = DATA / "light_mode.txt"
_PLOT_RE = re.compile(r"^([A-Z]{4})[\s_-]*(\d{3})")


def normalise_plot(s: str) -> str | None:
    """'STER 006', 'ster_006', 'STER_006-M-21-20220607' -> 'STER_006'; None if it names no plot."""
    m = _PLOT_RE.match(str(s).strip().upper())
    return f"{m[1]}_{m[2]}" if m else None


def default_light_plots() -> list[str]:
    """The default light-mode plots (`light_plots` in config/regions.yaml)."""
    return sorted({p for p in map(normalise_plot, regions()["light_plots"]) if p})


def read_light_file(path: Path) -> list[str] | None:
    """Light-mode plots from a light_mode.txt (see the rules above), or None when it says "off"."""
    if not path.exists():
        return default_light_plots()
    words = [line.split("#")[0].strip() for line in path.read_text().splitlines()]
    words = [w for w in words if w]
    if any(w.lower() == "off" for w in words):
        return None
    plots = sorted({p for p in map(normalise_plot, words) if p})
    return plots or default_light_plots()


def light_plots() -> list[str] | None:
    """Plot IDs of light mode, or None when light mode is off. On by default (no data/light_mode.txt)."""
    return read_light_file(LIGHT_FILE)


def light_filter(df, cols=("plotID", "namedLocation", "sampleID", "dnaSampleID", "soilSampleID",
                           "geneticSampleID")):
    """Drop the rows of plots outside light mode (unchanged when light mode is off). The plot of a row is read
    from the first of `cols` that names one; rows that name no plot (site-level rows) are kept."""
    lp = light_plots()
    if lp is None or not hasattr(df, "columns") or not len(df):
        return df
    import pandas as pd
    plot = pd.Series(pd.NA, index=df.index, dtype=object)
    for c in cols:
        if c in df.columns:
            e = df[c].astype(str).str.upper().str.extract(_PLOT_RE.pattern)
            plot = plot.fillna(e[0] + "_" + e[1])
    return df[plot.isna() | plot.isin(lp)]


def window_bbox(site: str) -> tuple[float, float, float, float]:
    """(minlon, minlat, maxlon, maxlat) in WGS84 for a window (approximate square)."""
    w = regions()["windows"][site]
    dlat = w["half_km"] / 111.32
    dlon = w["half_km"] / (111.32 * math.cos(math.radians(w["center_lat"])))
    return (w["center_lon"] - dlon, w["center_lat"] - dlat, w["center_lon"] + dlon, w["center_lat"] + dlat)


def window_wkt(site: str) -> str:
    x0, y0, x1, y1 = window_bbox(site)
    return f"POLYGON(({x0} {y0}, {x1} {y0}, {x1} {y1}, {x0} {y1}, {x0} {y0}))"
