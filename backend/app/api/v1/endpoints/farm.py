# -*- coding: utf-8 -*-
"""Read endpoints of docs/serve_read_contract.md: a thin SELECT over the views of schema serve.

Dates in the answers are already shifted for the demo by the views; the API never converts them. A farmer sees only own crop areas
(the owner comes from the signed token); the analyst role sees all and the grid layer.
"""
from __future__ import annotations

import json
import threading
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from pydantic import BaseModel

from backend.app.core.cache import TtlCache
from backend.app.core.config import AUTH_SECRET, TOKEN_TTL_SECONDS
from backend.app.core.db import get_db
from backend.app.core.limits import RateLimiter, enforce
from backend.app.core.security import hash_password, make_token, read_token, verify_password
from backend.app.domain import septoria
from backend.app.services import risk_surface
from backend.app.services.crop_area_refresh import load_rules

router = APIRouter()

# Verified when the login does not exist, so the answer takes as long as for a wrong password.
_DUMMY_HASH = hash_password("not-a-real-password")


class LoginIn(BaseModel):
    login: str
    password: str


def current_user(authorization: Optional[str] = Header(None)) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    claims = read_token(authorization[7:].strip(), AUTH_SECRET)
    if claims is None:
        raise HTTPException(status_code=401, detail="invalid or expired token")
    return claims


def _own(user: dict) -> tuple[str, tuple]:
    """SQL condition limiting the rows to the farmer's own crop areas (none for the analyst)."""
    if user.get("role") == "analyst":
        return "", ()
    return " AND owner_id = %s", (user["owner_id"],)


def _require_area(con, user: dict, crop_area_id: str) -> None:
    cond, args = _own(user)
    if not con.execute("SELECT 1 FROM serve.crop_area WHERE crop_area_id = %s" + cond, (crop_area_id, *args)).fetchone():
        raise HTTPException(status_code=404, detail="crop area not found")      # also for somebody else's area


def _collection(rows) -> dict:
    return {"type": "FeatureCollection", "features": [r["f"] for r in rows]}


_RULES: Optional[septoria.Rules] = None
# The answers of the grid layer and of the surface are the same for every user and change rarely: kept for a minute as bytes, so a hit
# costs a millisecond (measured: 400 surface requests of 100 visitors, every one asking the database and serialising, raised the p95
# of the room from 0.4 s to 7.5 s). The data of the demo clock and a recomputation reach the readers within a minute.
_RESPONSES = TtlCache(60, 64)
_SMOOTH_SLOT = threading.BoundedSemaphore(1)      # the Gaussian method costs seconds of CPU: one at a time per process
_surface_limit = RateLimiter(30, 60)                # grid and surface requests per minute and user, per worker process (3 workers: 90 a minute)


def _rules() -> septoria.Rules:
    global _RULES
    if _RULES is None:
        _RULES = load_rules()
    return _RULES


def _add_index(p: dict, h_key: str = "h_hours", low_key: Optional[str] = None, high_key: Optional[str] = None) -> dict:
    """Add risk_index (0-1, aligned with the classes, see septoria.risk_index) where a class applies; NULL otherwise.
    With low_key/high_key also index_low/index_high, the range when missing hours are counted dry / wet."""
    has_class = p.get("risk_class") is not None
    p["risk_index"] = septoria.risk_index(p.get(h_key), _rules()) if has_class else None
    if low_key and high_key:
        p["index_low"] = septoria.risk_index(p.get(low_key), _rules()) if has_class else None
        p["index_high"] = septoria.risk_index(p.get(high_key), _rules()) if has_class else None
    return p


@router.post("/login", summary="Log in (demo)")
def login(body: LoginIn, con=Depends(get_db)):
    row = con.execute("SELECT login, password_hash, owner_id, role, display_name FROM app.demo_user WHERE login = %s",
                      (body.login,)).fetchone()
    ok = verify_password(body.password, row["password_hash"] if row else _DUMMY_HASH)
    if not (row and ok):
        raise HTTPException(status_code=401, detail="wrong login or password")
    token = make_token({"sub": row["login"], "owner_id": row["owner_id"], "role": row["role"]}, AUTH_SECRET, TOKEN_TTL_SECONDS)
    return {"token": token, "owner_id": row["owner_id"], "role": row["role"], "display_name": row["display_name"],
            "expires_in": TOKEN_TTL_SECONDS}


@router.get("/clock", summary="The shown 'today'")
def clock(con=Depends(get_db)):
    row = con.execute("SELECT today, mode FROM serve.clock").fetchone()
    if not row:
        raise HTTPException(status_code=503, detail="demo time is not configured")
    return row


@router.get("/me/crop-areas", summary="Crop areas with today's class (GeoJSON)")
def my_crop_areas(limit: int = Query(5000, ge=1, le=50000), user=Depends(current_user), con=Depends(get_db)):
    cond, args = _own(user)
    rows = con.execute(
        "SELECT jsonb_build_object('type', 'Feature', 'geometry', ST_AsGeoJSON(geom, 6)::jsonb, "
        "'properties', to_jsonb(t) - 'geom') AS f FROM serve.crop_area_today t WHERE true" + cond +
        " ORDER BY crop_area_id LIMIT %s", (*args, limit)).fetchall()
    collection = _collection(rows)
    for feature in collection["features"]:
        _add_index(feature["properties"])
    return collection


@router.get("/crop-areas/{crop_area_id}", summary="One crop area with soil and crop-map context (GeoJSON Feature)")
def crop_area(crop_area_id: str, user=Depends(current_user), con=Depends(get_db)):
    cond, args = _own(user)
    row = con.execute(
        "SELECT jsonb_build_object('type', 'Feature', 'geometry', ST_AsGeoJSON(geom, 6)::jsonb, "
        "'properties', to_jsonb(c) - 'geom') AS f FROM serve.crop_area c WHERE crop_area_id = %s" + cond,
        (crop_area_id, *args)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="crop area not found")
    return row["f"]


@router.get("/crop-areas/{crop_area_id}/risk", summary="Assessment per day (the date slider)")
def crop_area_risk(crop_area_id: str, date_from: Optional[date] = Query(None, alias="from"),
                   date_to: Optional[date] = Query(None, alias="to"), user=Depends(current_user), con=Depends(get_db)):
    _require_area(con, user, crop_area_id)
    rows = con.execute(
        "SELECT date, risk_class, status, conditions_met, h_hours, h_low, h_high, coverage, protected_until, "
        "growth_stage_zone, growth_stage_source, gdd_since_resumption, reasons, model_version FROM serve.risk_daily "
        "WHERE crop_area_id = %s AND disease = 'septoria' AND (%s::date IS NULL OR date >= %s) "
        "AND (%s::date IS NULL OR date <= %s) ORDER BY date",
        (crop_area_id, date_from, date_from, date_to, date_to)).fetchall()
    return [_add_index(dict(r), "h_hours", "h_low", "h_high") for r in rows]


@router.get("/crop-areas/{crop_area_id}/changes", summary="Changes of the class, status or conditions_met")
def crop_area_changes(crop_area_id: str, user=Depends(current_user), con=Depends(get_db)):
    _require_area(con, user, crop_area_id)
    return con.execute(
        "SELECT date, computed_at, reason, old_class, new_class, old_status, new_status, old_conditions_met, "
        "new_conditions_met FROM serve.risk_change_log WHERE crop_area_id = %s AND old_status IS NOT NULL "   # not the first calculation
        "ORDER BY computed_at DESC, change_id DESC LIMIT 200", (crop_area_id,)).fetchall()


@router.get("/grid/risk", summary="Grid cells of the voivodeship for one day (any signed-in user, GeoJSON)")
def grid_risk(day: Optional[date] = Query(None, alias="date"), user=Depends(current_user), con=Depends(get_db)):
    """Weather and risk per grid cell: public data, nothing of a farmer, so every signed-in user may read it."""
    enforce(_surface_limit, user["owner_id"])
    def build():
        rows = con.execute(
            "SELECT jsonb_build_object('type', 'Feature', 'geometry', ST_AsGeoJSON(geom, 6)::jsonb, "
            "'properties', to_jsonb(g) - 'geom' - 'data_date') AS f FROM serve.grid_risk_daily g "
            "WHERE data_date = COALESCE(%s::date, current_date) - serve.shift_days() ORDER BY grid_id", (day,)).fetchall()
        collection = _collection(rows)
        for feature in collection["features"]:
            _add_index(feature["properties"], "h_low", "h_low", "h_high")
        return json.dumps(collection, separators=(",", ":"), default=str).encode() if rows else None

    body = _RESPONSES.get_or_build(("grid", day, date.today()), build)
    if body is None:                                              # nothing for this day: an empty collection, as before
        body = json.dumps(_collection([]), separators=(",", ":")).encode()
    return Response(body, media_type="application/json")


@router.get("/grid/risk/surface", summary="Risk surface (heatmap) of the voivodeship for one day (any signed-in user)")
def grid_risk_surface(day: Optional[date] = Query(None, alias="date"),
                      format: str = Query("json", pattern="^(json|png|asc)$"),
                      method: str = Query("interpolate", pattern="^(interpolate|smooth)$",
                                          description="interpolate: bilinear, exact at the cell centres; smooth: Gaussian"),
                      value: str = Query("index", pattern="^(index|hours)$", description="what json and asc carry; png is always the index"),
                      resolution: float = Query(0.02, ge=0.01, le=0.1, description="pixel size in degrees"),
                      sigma_km: float = Query(5.0, ge=1.0, le=10.0, description="smoothing radius, method=smooth only"),
                      user=Depends(current_user), con=Depends(get_db)):
    """The hours of continuous leaf wetness (h_low) of the cells as a continuous surface (services/risk_surface.py); the risk
    index is applied to each pixel afterwards. json: the grid (EPSG:4326, row 0 north, null outside the data). png: RGBA image on
    the fixed ramp, bounds in the X-Bounds header (west,south,east,north). asc: ESRI ASCII Grid (QGIS reads it directly)."""
    if method == "smooth" and user.get("role") != "analyst":      # the slow method is for the analyst; interpolate is better anyway
        raise HTTPException(status_code=403, detail="method=smooth is for the analyst role (method=interpolate is the default)")
    enforce(_surface_limit, user["owner_id"])
    if method == "smooth" and (resolution < 0.02 or sigma_km > 10.0):
        raise HTTPException(status_code=422, detail="method=smooth needs resolution >= 0.02 (it takes seconds per request)")
    rkey = ("surface", day, date.today(), format, method, value, resolution, sigma_km if method == "smooth" else None)

    def build_response():
        rows = con.execute(
            "SELECT ST_X(ST_Centroid(geom)) AS lon, ST_Y(ST_Centroid(geom)) AS lat, h_low, date FROM serve.grid_risk_daily "
            "WHERE data_date = COALESCE(%s::date, current_date) - serve.shift_days()", (day,)).fetchall()
        if not rows:
            raise HTTPException(status_code=404, detail="no grid data for this date")
        rules = _rules()
        points = [(r["lon"], r["lat"], r["h_low"]) for r in rows]
        key = (method, resolution, sigma_km if method == "smooth" else None, risk_surface.fingerprint(points))

        def build():
            if method != "smooth":
                return risk_surface.build(points, method=method, resolution_deg=resolution, sigma_km=sigma_km)
            if not _SMOOTH_SLOT.acquire(blocking=False):             # never queue behind a heavy computation (it would hold a connection)
                raise HTTPException(status_code=503, detail="another smoothing is running, try again in a moment (method=interpolate is instant)")
            try:
                return risk_surface.build(points, method=method, resolution_deg=resolution, sigma_km=sigma_km)
            finally:
                _SMOOTH_SLOT.release()

        grid = risk_surface.cached(key, build)
        if grid is None:
            raise HTTPException(status_code=404, detail="no grid data for this date")
        index_values = risk_surface.to_index(grid["values"], lambda h: septoria.risk_index(h, rules))
        date_text = rows[0]["date"].isoformat()
        if format == "png":
            body, media_type = risk_surface.to_png(index_values), "image/png"
            headers = {"X-Bounds": ",".join(str(v) for v in grid["bounds"]), "X-Date": date_text, "X-Method": grid["method"],
                       "Access-Control-Expose-Headers": "X-Bounds, X-Date, X-Method"}
        else:
            carried = index_values if value == "index" else grid["values"]
            if format == "asc":
                body, media_type = risk_surface.to_asc(carried, grid["bounds"], grid["resolution_deg"]).encode(), "text/plain"
                headers = {"X-Date": date_text, "X-Value": value, "Access-Control-Expose-Headers": "X-Date, X-Value"}
            else:
                out = {k: v for k, v in grid.items() if k != "values"}
                out.update({"date": date_text, "model_version": rules.model_version, "value": value, "values": carried,
                            "class_thresholds": {"hours": {"medium": rules.threshold_medium, "high": rules.threshold_high},
                                                 "index": {"medium": 0.5, "high": 1.0}},
                            "index_scale": {"low": [0.0, 0.5], "medium": [0.5, 1.0], "high": [1.0, 1.0]},
                            "class_note": "The classes belong to the cells (GET /grid/risk). A pixel is a continuous estimate between cell "
                                          "centres: colour it by value, and read the thresholds in class_thresholds as landmarks, not as a "
                                          "new assessment."})
                body, media_type, headers = json.dumps(out, separators=(",", ":")).encode(), "application/json", {}
        return body, media_type, headers

    body, media_type, headers = _RESPONSES.get_or_build(rkey, build_response)
    return Response(body, media_type=media_type, headers=headers)
