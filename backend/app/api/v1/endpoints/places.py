# -*- coding: utf-8 -*-
"""GET /places?q= : the search box of the map. Returns places (towns and villages of Mazowieckie) with the coordinates to fly to.

The answer is {"places": [{name, label, lon, lat, zoom, source}], "data_status": "live"}; `zoom` is the zoom from which the parcel
boundaries of GUGiK are visible, so flying there shows the parcels at once. No match is an empty list.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from backend.app.api.v1.endpoints.farm import current_user
from backend.app.core.db import get_db
from backend.app.core.limits import RateLimiter, enforce
from backend.app.services import places as place_service

router = APIRouter()

_limit = RateLimiter(120, 60)                   # searches per minute and owner (typing sends many requests)


@router.get("/places", summary="Search places (towns and villages) for the map search box")
def places(q: str = Query(..., min_length=2, max_length=80), user=Depends(current_user), con=Depends(get_db)):
    enforce(_limit, user["owner_id"])
    return {"places": place_service.search(con, q), "data_status": "live"}
