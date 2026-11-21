"""Local JSON API for the GUI in web/. Reads data/processed/ and serves it in small, screen-sized pieces.

Runs on this machine only (scripts/12_gui.py binds 127.0.0.1); no accounts, no deployment.

To add a feature: write a response model, add a route below (or a new module with its own APIRouter once this
file grows), and call it from web/src/api.ts. Keep responses to what one screen shows, not whole tables.
"""
from __future__ import annotations

import datetime as dt
from functools import lru_cache
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import overlay
from .config import PROCESSED, ROOT

WEB_DIST = ROOT / "web" / "dist"
MIN_MAP_VALID = 0.5             # greenness maps with less usable area than this are not offered
SOURCE_LABEL = {"naip": "USDA aerial survey", "neon_aop_camera": "NEON airborne camera"}


# ---------------------------------------------------------------- data access
@lru_cache(maxsize=32)
def _read(path: Path, mtime: float) -> pd.DataFrame:
    return pd.read_parquet(path)


def table(name: str) -> pd.DataFrame:
    """A processed table, re-read only when its file changed (so a pipeline re-run shows up without restart)."""
    f = PROCESSED / f"{name}.parquet"
    if not f.exists():
        raise HTTPException(503, f"{name}.parquet is missing: run the data pipeline first (see AGENT.md)")
    return _read(f, f.stat().st_mtime)


def plot_rows(name: str, plot_id: str, key: str = "plotID") -> pd.DataFrame:
    if plot_id not in set(table("plot_geometry")["plotID"]):
        raise HTTPException(404, f"unknown plot {plot_id}")
    df = table(name)
    return df[df[key] == plot_id]


# ---------------------------------------------------------------- response models
class Plot(BaseModel):
    plot_id: str
    site: str
    lat: float
    lon: float
    half_m: float                    # the plot is a square of 2 * half_m metres around (lat, lon)


class GreennessPoint(BaseModel):
    date: dt.date
    ndvi: float                      # satellite greenness, about 0 (bare soil) to 1 (dense green vegetation)


class EventSummary(BaseModel):
    event_id: str
    date: dt.date


class Event(EventSummary):
    plot_id: str
    site: str
    sampled: list[str]               # plain-language names of what was collected on this visit


class GreennessMap(BaseModel):
    map_id: str
    date: dt.date
    bounds: tuple[tuple[float, float], tuple[float, float]]    # ((south, west), (north, east))
    url: str


class GreennessValue(BaseModel):
    ndvi: float | None               # null: outside the map, or hidden by cloud on that day


class AerialPhoto(BaseModel):
    photo_id: str
    date: dt.date
    month_only: bool                 # true when only the flight month is known (date is then its first day)
    source: str
    bounds: tuple[tuple[float, float], tuple[float, float]]    # ((south, west), (north, east))
    url: str


# ---------------------------------------------------------------- routes
router = APIRouter(prefix="/api")


@router.get("/plots", response_model=list[Plot])
def plots():
    g = table("plot_geometry")
    return [Plot(plot_id=r.plotID, site=r.site, lat=r.lat, lon=r.lon, half_m=r.half_m) for r in g.itertuples()]


@router.get("/plots/{plot_id}/greenness", response_model=list[GreennessPoint])
def greenness(plot_id: str):
    """Cloud-free satellite observations of the plot, oldest first."""
    vi = plot_rows("plot_vi_timeseries", plot_id)
    vi = vi[vi["clear"] & vi["ndvi"].notna()].sort_values("date")
    return [GreennessPoint(date=d.date(), ndvi=round(float(v), 3)) for d, v in zip(vi["date"], vi["ndvi"])]


@router.get("/plots/{plot_id}/events", response_model=list[EventSummary])
def plot_events(plot_id: str):
    ev = plot_rows("events", plot_id).sort_values("date")
    return [EventSummary(event_id=r.event_id, date=r.date.date()) for r in ev.itertuples()]


@router.get("/events/{event_id}", response_model=Event)
def event(event_id: str):
    ev = table("events")
    hit = ev[ev["event_id"] == event_id]
    if hit.empty:
        raise HTTPException(404, f"unknown event {event_id}")
    r = hit.iloc[0]
    sampled = [label for flag, label in (("has_chem", "Soil chemistry"), ("has_metagenome", "Soil microbes (metagenome)"),
                                         ("has_its", "Soil fungi")) if bool(r[flag])]
    return Event(event_id=r.event_id, date=r.date.date(), plot_id=r.plotID, site=r.site, sampled=sampled)


def _aerial(plot_id: str | None = None) -> pd.DataFrame:
    """Aerial rows whose chip file exists, with photo_id = chip file name without extension."""
    a = table("plot_aerial") if plot_id is None else plot_rows("plot_aerial", plot_id)
    a = a[a["chip"].notna()].copy()
    a["photo_id"] = a["chip"].map(lambda c: Path(c).stem)
    return a[a["chip"].map(lambda c: (ROOT / c).exists())]


@router.get("/plots/{plot_id}/aerial", response_model=list[AerialPhoto])
def aerial(plot_id: str):
    """Aerial photos of the plot, oldest first, each ready to be laid on a web map."""
    out = []
    for r in _aerial(plot_id).sort_values("date").itertuples():
        s, w, n, e = overlay.bounds_latlon(ROOT / r.chip)
        out.append(AerialPhoto(photo_id=r.photo_id, date=r.date.date(), month_only=r.date_precision == "month",
                               source=SOURCE_LABEL.get(r.source, r.source), bounds=((s, w), (n, e)),
                               url=f"/api/aerial/{r.photo_id}.png"))
    return out


@router.get("/aerial/{photo_id}.png")
def aerial_image(photo_id: str):
    a = _aerial()
    hit = a[a["photo_id"] == photo_id]          # looked up in the table: the request never names a file path
    if hit.empty:
        raise HTTPException(404, f"unknown photo {photo_id}")
    return FileResponse(overlay.overlay_png(ROOT / hit.iloc[0]["chip"]), media_type="image/png")


def _ndvi_maps() -> pd.DataFrame | None:
    """The greenness map table, or None when scripts/13_fetch_ndvi_maps.py has not been run (maps are optional)."""
    return table("plot_ndvi_maps") if (PROCESSED / "plot_ndvi_maps.parquet").exists() else None


def _ndvi_chip(map_id: str) -> Path:
    m = _ndvi_maps()
    hit = m[m["chip"].str.endswith(f"/{map_id}.tif")] if m is not None else []    # table lookup, never a path
    if len(hit) == 0 or not (ROOT / hit.iloc[0]["chip"]).exists():
        raise HTTPException(404, f"unknown greenness map {map_id}")
    return ROOT / hit.iloc[0]["chip"]


@router.get("/plots/{plot_id}/greenness-maps", response_model=list[GreennessMap])
def greenness_maps(plot_id: str):
    """Satellite greenness images of the plot's surroundings, oldest first; mostly cloud-covered ones left out."""
    if _ndvi_maps() is None:
        return []
    out = []
    m = plot_rows("plot_ndvi_maps", plot_id)
    for r in m[m["valid_frac"] >= MIN_MAP_VALID].sort_values("date").itertuples():
        chip = ROOT / r.chip
        if chip.exists():
            s, w, n, e = overlay.bounds_latlon(chip)
            out.append(GreennessMap(map_id=chip.stem, date=r.date.date(), bounds=((s, w), (n, e)),
                                    url=f"/api/greenness-maps/{chip.stem}.png"))
    return out


@router.get("/greenness-maps/{map_id}.png")
def greenness_map_image(map_id: str):
    return FileResponse(overlay.ndvi_png(_ndvi_chip(map_id)), media_type="image/png")


@router.get("/greenness-maps/{map_id}/value", response_model=GreennessValue)
def greenness_map_value(map_id: str, lat: float, lon: float):
    """Greenness at one spot of a map."""
    v = overlay.ndvi_at(_ndvi_chip(map_id), lat, lon)
    return GreennessValue(ndvi=None if v is None else round(v, 2))


def create_app() -> FastAPI:
    from . import api_microbiome, api_risk      # imported here: they use table() and plot_rows() from this module
    app = FastAPI(title="cropfit GUI API")
    app.include_router(router)
    app.include_router(api_microbiome.router)
    app.include_router(api_risk.router)
    if WEB_DIST.exists():                       # built frontend (npm run build in web/); absent in dev mode
        app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
    return app


app = create_app()
