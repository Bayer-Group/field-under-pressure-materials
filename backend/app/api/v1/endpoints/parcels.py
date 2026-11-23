# -*- coding: utf-8 -*-
"""GET /parcels of FARMER_INPUT_CONTRACT.md: cadastral parcels from GUGiK ULDK (with a cache in app.parcel).

`?lon=&lat=` is the parcel under a click, `?number=` an identifier or a number. The answer has the shape of the farmer contract:
{"parcels": [{parcel_id, parcel_number, geometry}], "data_status": "live"}. No match is a successful answer with an empty list; an
unavailable service is 502, not an empty list.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.app.api.v1.endpoints.farm import current_user
from backend.app.core.db import get_db_rw
from backend.app.core.limits import RateLimiter, enforce
from backend.app.ingestion.uldk_connector import UldkError
from backend.app.services import parcels as parcel_service

router = APIRouter()

_limit = RateLimiter(60, 60)                    # lookups per minute and owner (the service of GUGiK is shared by everybody)


@router.get("/parcels", summary="Parcels by number or by a clicked position (GUGiK ULDK)")
def parcels(number: Optional[str] = Query(None, min_length=3, max_length=80), lon: Optional[float] = Query(None),
            lat: Optional[float] = Query(None), user=Depends(current_user), con=Depends(get_db_rw)):
    enforce(_limit, user["owner_id"])
    by_xy = lon is not None or lat is not None
    if (number is None) == (not by_xy):
        raise HTTPException(status_code=422, detail="give either number or both lon and lat")
    try:
        if by_xy:
            if lon is None or lat is None:
                raise HTTPException(status_code=422, detail="give both lon and lat")
            if not (14.0 <= lon <= 24.5 and 48.9 <= lat <= 55.0):
                raise HTTPException(status_code=422, detail="the position is outside Poland")
            found = parcel_service.find_by_xy(con, lon, lat)
        else:
            found = parcel_service.find_by_number(con, number.strip())
    except UldkError:
        raise HTTPException(status_code=502, detail="the parcel service (GUGiK ULDK) is not available, try again later")
    con.commit()
    return {"parcels": found, "data_status": "live"}
