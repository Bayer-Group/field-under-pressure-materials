# -*- coding: utf-8 -*-
"""Spray window endpoints (docs/serve_read_contract.md, "Spray window"): is now a good window to consider a spray?

The rules live in backend/app/domain/spray_window.py and config/spray_window.toml; the reading in
backend/app/services/spray_window.py. A farmer sees only own crop areas, the analyst all of them (as in farm.py).
Times are the shown local time; the window is an assessment of the weather, never an instruction to spray.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.app.api.v1.endpoints.farm import _require_area, current_user
from backend.app.core.db import get_db
from backend.app.services import spray_window as service

router = APIRouter()


def _owner(user: dict) -> Optional[str]:
    return None if user.get("role") == "analyst" else user["owner_id"]


def _work_hours(work_from: Optional[int], work_to: Optional[int]) -> Optional[tuple[int, int]]:
    if work_from is None and work_to is None:
        return None
    lo, hi = work_from if work_from is not None else 0, work_to if work_to is not None else 24
    if lo >= hi:
        raise HTTPException(status_code=422, detail="work_from must be earlier than work_to")
    return lo, hi


def _window(w: dict) -> dict:
    return dict(w, start=service.iso(w["start"]), end=service.iso(w["end"]))


def _summary(result: dict) -> dict:
    """The properties of the map layer: no hour list, the best window only."""
    best = result["windows"][0] if result["windows"] else None
    return {
        "spray_window_status": result["status"],
        "signal": result["signal"],
        "signal_reason": result["signal_reason"],
        "weather_ok_now": result["weather_ok_now"],
        "next_window_start": service.iso(result["next_window_start"]),
        "next_window_end": service.iso(result["next_window_end"]),
        "windows_found": len(result["windows"]),
        "best_window_start": service.iso(best["start"]) if best else None,
        "best_window_end": service.iso(best["end"]) if best else None,
        "best_window_hours": best["hours"] if best else None,
        "best_window_margin_ms": best["wind_margin_ms"] if best else None,
        "best_window_confidence": best["confidence"] if best else None,
        "forecast_coverage": result["coverage"],
    }


_AT = Query(None, description="shown local time to assess (default now); the start of its hour is used")
_FROM = Query(None, ge=0, le=23, description="farmer's working hours: first hour (optional, never relaxes a limit)")
_TO = Query(None, ge=1, le=24, description="farmer's working hours: end hour, exclusive (optional)")


@router.get("/me/spray-window", summary="Spray window now for every crop area (GeoJSON layer)")
def my_spray_window(at: Optional[datetime] = _AT, work_from: Optional[int] = _FROM, work_to: Optional[int] = _TO,
                    user=Depends(current_user), con=Depends(get_db)):
    """FeatureCollection of the crop areas (a farmer: own, the analyst: all) with the spray window status at `at`:
    no_signal, no_forecast, window_now, window_later or no_window, the next and the best window."""
    now, rows = service.compute(con, _owner(user), at, _work_hours(work_from, work_to))
    features = []
    for area, result in rows:
        props = {k: area[k] for k in ("crop_area_id", "field_id", "field_name", "farmer_crop_id", "risk_class", "status")}
        props.update(_summary(result))
        features.append({"type": "Feature", "geometry": area["geometry"], "properties": props})
    return {"type": "FeatureCollection", "assessed_at": service.iso(now), "features": features,
            "model_version": service.rules().model_version, "notes": service.notes(service.rules())}


@router.get("/crop-areas/{crop_area_id}/spray-window", summary="Spray window of one crop area: signal, windows, hours")
def crop_area_spray_window(crop_area_id: str, at: Optional[datetime] = _AT, work_from: Optional[int] = _FROM,
                           work_to: Optional[int] = _TO, user=Depends(current_user), con=Depends(get_db)):
    """The signal (septoria assessment of the day), up to three ranked windows in the next 72 hours with a reason each, and
    the check of every hour (for a chart)."""
    _require_area(con, user, crop_area_id)
    now, rows = service.compute(con, _owner(user), at, _work_hours(work_from, work_to), crop_area_id)
    if not rows:
        raise HTTPException(status_code=404, detail="crop area not found")
    area, result = rows[0]
    hours = [dict(h, time=service.iso(h["time"])) for h in result["hours"]]
    return {
        "crop_area_id": crop_area_id,
        "assessed_at": service.iso(now),
        "status": result["status"],
        "signal": {"signal": result["signal"], "reason": result["signal_reason"], "risk_class": area["risk_class"],
                   "status": area["status"], "growth_stage_zone": area["growth_stage_zone"],
                   "protected_until": area["protected_until"], "h_hours": area["h_hours"]},
        "weather_ok_now": result["weather_ok_now"],
        "windows": [_window(w) for w in result["windows"]],
        "hours": hours,
        "forecast_coverage": result["coverage"],
        "grid_id": area["grid_id"],
        "model_version": result["model_version"],
        "notes": service.notes(service.rules()),
    }
