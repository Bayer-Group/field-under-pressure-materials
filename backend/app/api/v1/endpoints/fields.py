# -*- coding: utf-8 -*-
"""The field model of the farmer front end (FARMER_INPUT_CONTRACT.md, GEOMETRY_VALIDATION_CONTRACT.md) over our tables.

`GET /fields`, `GET /fields/{id}`, `PUT /fields/{id}` (atomic group save: one crop area may cover several parcels) and
`POST /fields/validate`. A field is linked to its parcels (app.field_parcel); a crop area keeps ONE geometry (the approved, repaired
and clipped one) and is read back as the same area with the same id. Ids chosen by the client are stored with the owner as a prefix
(`<owner>~<id>`) so that two visitors may both use `field-demo-1`; the prefix is removed again when reading. Dates are in the shown
time (the demo shift) and translated to the time of the data when saved. `past_sprays: []` is a confirmed "no sprays"; `null` or a
missing list is an unanswered question and cannot be saved.
"""
from __future__ import annotations

import datetime as _dt
import re
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.app.api.v1.endpoints.farm import current_user
from backend.app.api.v1.endpoints.farm_write import _require_writes, _recompute, _shift, _today
from backend.app.core.config import MAX_AREA_HA, MAX_AREAS_OTHER, MAX_AREAS_SANDBOX
from backend.app.core.db import get_db, get_db_rw
from backend.app.core.limits import RateLimiter, enforce
from backend.app.services import geometry_validation as gv
from backend.app.services.parcels import location_label

router = APIRouter()

_validate_limit = RateLimiter(120, 60)          # validations per minute and owner
_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
_PARCEL_ID = re.compile(r"^[A-Za-z0-9_.:/-]{1,80}$")


# ---------------------------------------------------------------- ids and models
def internal_id(owner: str, client_id: str) -> str:
    return f"{owner}~{client_id}"


def external_id(owner: str, stored: str) -> str:
    """The id the client chose: the owner prefix of this API (or of a sandbox copy) is removed."""
    for prefix in (f"{owner}~", f"{owner}-"):
        if stored.startswith(prefix):
            return stored[len(prefix):]
    return stored


def _check_id(value: str, what: str) -> None:
    if not _ID.match(value):
        raise HTTPException(status_code=422, detail=f"{what} must be 1 to 80 characters of letters, digits and _ . : -")


def _check_parcel_id(value: str) -> None:
    """Accept cadastral identifiers, including parcel numbers containing a slash."""
    if not _PARCEL_ID.fullmatch(value):
        raise HTTPException(status_code=422, detail="parcel_id must be 1 to 80 characters of letters, digits and _ . : / -")


class ValidateArea(BaseModel):
    crop_area_id: str
    geometry: dict


class ValidateIn(BaseModel):
    parcel_ids: list[str] = Field(min_length=1, max_length=20)
    crop_areas: list[ValidateArea] = Field(min_length=1, max_length=20)


class CropIn(BaseModel):
    farmer_crop_id: str
    map_crop_id: Optional[str] = None                     # computed by the server from the crop map; ignored when sent


class SprayIn(BaseModel):
    date: _dt.date
    protection_duration_days: int = Field(ge=1, le=60)


class CropAreaIn(BaseModel):
    crop_area_id: str
    geometry: dict
    crop: CropIn
    sowing_date: _dt.date
    past_sprays: Optional[list[SprayIn]] = None


class ParcelRef(BaseModel):
    parcel_id: str                                        # the other keys of a parcel are ignored: its geometry is ours


class FieldIn(BaseModel):
    field_id: Optional[str] = None
    name: Optional[str] = Field(None, max_length=60)
    parcel: Optional[ParcelRef] = None                    # one parcel (the earlier shape) ...
    parcel_ids: Optional[list[str]] = Field(None, max_length=20)   # ... or a group of parcels
    validation_id: Optional[str] = None
    confirmations: list[str] = []
    crop_areas: list[CropAreaIn] = Field(min_length=1, max_length=20)


# ---------------------------------------------------------------- reading
def load_fields(con, owner: str, only: Optional[str] = None) -> list[dict]:
    where, args = " WHERE owner_id = %s", [owner]
    if only:
        where += " AND field_id = %s"
        args.append(only)
    fields = con.execute("SELECT field_id, name FROM app.field" + where + " ORDER BY field_id", args).fetchall()
    if not fields:
        return []
    ids = [f["field_id"] for f in fields]
    parcels: dict[str, list] = {}
    for r in con.execute(
            "SELECT fp.field_id, p.parcel_id, p.parcel_number, p.region, p.commune, p.county, p.voivodeship, "
            "ST_AsGeoJSON(p.geom, 7)::jsonb AS geometry "
            "FROM app.field_parcel fp JOIN app.parcel p USING (parcel_id) WHERE fp.field_id = ANY(%s) ORDER BY p.parcel_id",
            (ids,)).fetchall():
        parcels.setdefault(r["field_id"], []).append({
            "parcel_id": r["parcel_id"], "parcel_number": r["parcel_number"], "region": r["region"], "commune": r["commune"],
            "county": r["county"], "voivodeship": r["voivodeship"], "location": location_label(r["region"], r["commune"]),
            "geometry": r["geometry"]})
    areas = con.execute(
        "SELECT t.crop_area_id, t.field_id, ST_AsGeoJSON(t.geom, 7)::jsonb AS geometry, t.farmer_crop_id, c.sowing_date, "
        "a.sprays_confirmed, m.farmer_crop_id AS map_crop_id, ST_Area(t.geom::geography) / 10000 AS area_ha, "
        "t.date AS risk_date, t.risk_class, t.status, t.conditions_met, t.h_hours, t.growth_stage_zone, t.protected_until "
        "FROM serve.crop_area_today t JOIN serve.crop_area c ON c.crop_area_id = t.crop_area_id "
        "JOIN app.crop_area a ON a.crop_area_id = t.crop_area_id "
        "LEFT JOIN curated.field_context fc ON fc.crop_area_id = t.crop_area_id "
        "LEFT JOIN curated.crop_mapping m ON m.class_code = fc.map_crop_class_code "
        "WHERE t.field_id = ANY(%s) ORDER BY t.crop_area_id", (ids,)).fetchall()
    sprays: dict[str, list] = {}
    for r in con.execute("SELECT crop_area_id, spray_date + serve.shift_days() AS date, protection_duration_days FROM app.spray "
                         "WHERE crop_area_id = ANY(%s) ORDER BY spray_date", ([a["crop_area_id"] for a in areas],)).fetchall():
        sprays.setdefault(r["crop_area_id"], []).append({"date": r["date"], "protection_duration_days": r["protection_duration_days"]})
    by_field: dict[str, list] = {}
    for a in areas:
        by_field.setdefault(a["field_id"], []).append({
            "crop_area_id": external_id(owner, a["crop_area_id"]), "geometry": a["geometry"],
            "crop": {"farmer_crop_id": a["farmer_crop_id"], "map_crop_id": a["map_crop_id"]},
            "sowing_date": a["sowing_date"],
            "past_sprays": sprays.get(a["crop_area_id"], []) if a["sprays_confirmed"] else None,
            "area_ha": round(float(a["area_ha"]), 2),
            "risk": {"date": a["risk_date"], "risk_class": a["risk_class"], "status": a["status"],
                     "conditions_met": a["conditions_met"], "h_hours": a["h_hours"],
                     "growth_stage_zone": a["growth_stage_zone"], "protected_until": a["protected_until"]}})
    out = []
    for f in fields:
        ps = parcels.get(f["field_id"], [])
        out.append({"field_id": external_id(owner, f["field_id"]), "name": f["name"], "parcel": ps[0] if ps else None,
                    "parcel_ids": [p["parcel_id"] for p in ps], "parcels": ps, "crop_areas": by_field.get(f["field_id"], [])})
    return out


@router.get("/fields", summary="The farmer's fields (shape of FARMER_INPUT_CONTRACT.md, with parcels and today's risk)")
def list_fields(user=Depends(current_user), con=Depends(get_db)):
    return {"fields": load_fields(con, user["owner_id"]), "data_status": "mock"}


@router.get("/fields/{field_id}", summary="One field with its crop areas")
def get_field(field_id: str, user=Depends(current_user), con=Depends(get_db)):
    _check_id(field_id, "field_id")
    for candidate in (internal_id(user["owner_id"], field_id), field_id):    # a field made through this API, or a generated one
        found = load_fields(con, user["owner_id"], candidate)
        if found:
            return found[0]
    raise HTTPException(status_code=404, detail="field not found")


# ---------------------------------------------------------------- validation
@router.post("/fields/validate", summary="Validate drawn crop areas against the selected parcels")
def validate_geometry(body: ValidateIn, user=Depends(current_user), con=Depends(get_db_rw)):
    enforce(_validate_limit, user["owner_id"])
    ids = [a.crop_area_id for a in body.crop_areas]
    for i in ids:
        _check_id(i, "crop_area_id")
    for parcel_id in body.parcel_ids:
        _check_parcel_id(parcel_id)
    if len(set(ids)) != len(ids):
        raise HTTPException(status_code=422, detail="crop_area_id values must be unique")
    response, _ = gv.validate(con, list(dict.fromkeys(body.parcel_ids)),
                              [{"crop_area_id": a.crop_area_id, "geometry": a.geometry} for a in body.crop_areas])
    con.commit()                                              # the parcels fetched from GUGiK are cached
    return response


# ---------------------------------------------------------------- group save
@router.put("/fields/{field_id}", summary="Save a field with its crop areas, atomically (one crop area may cover several parcels)")
def put_field(field_id: str, body: FieldIn, user=Depends(current_user), con=Depends(get_db_rw)):
    _require_writes(user)
    owner = user["owner_id"]
    _check_id(field_id, "field_id")
    if body.field_id and body.field_id != field_id:
        raise HTTPException(status_code=422, detail="field_id in the body differs from the path")
    parcel_ids = list(dict.fromkeys(body.parcel_ids or ([body.parcel.parcel_id] if body.parcel else [])))
    if not parcel_ids:
        raise HTTPException(status_code=422, detail="give parcel_ids (or a parcel)")
    for p in parcel_ids:
        _check_parcel_id(p)
    ids = [a.crop_area_id for a in body.crop_areas]
    for i in ids:
        _check_id(i, "crop_area_id")
    if len(set(ids)) != len(ids):
        raise HTTPException(status_code=422, detail="crop_area_id values must be unique")
    for a in body.crop_areas:
        if a.past_sprays is None:
            raise HTTPException(status_code=422, detail=f"the spray question of {a.crop_area_id} is unanswered: send past_sprays "
                                "([] confirms that there were no sprays)")
        if not con.execute("SELECT 1 FROM curated.crop_mapping WHERE farmer_crop_id = %s", (a.crop.farmer_crop_id,)).fetchone():
            raise HTTPException(status_code=422, detail=f"unknown crop {a.crop.farmer_crop_id} (see GET /crops)")
    shift, today = _shift(con), _today(con)
    for a in body.crop_areas:
        if a.sowing_date > today or any(s.date > today for s in a.past_sprays):
            raise HTTPException(status_code=422, detail="dates cannot be in the future (send dates in the time shown by GET /clock)")

    # the server's own validation of exactly this selection and geometry
    areas = [{"crop_area_id": a.crop_area_id, "geometry": a.geometry} for a in body.crop_areas]
    resp, internals = gv.validate(con, parcel_ids, areas)
    con.commit()                                              # the parcels fetched from GUGiK are cached
    if resp["errors"]:
        raise HTTPException(status_code=422, detail={"message": "the geometry cannot be saved", "errors": resp["errors"]})
    if resp["overlaps"]:
        raise HTTPException(status_code=422, detail={"message": "crop areas overlap; confirmation does not allow an overlap",
                                                     "overlaps": [o["overlap_id"] for o in resp["overlaps"]]})
    stale = gv.check_validation_id(body.validation_id, parcel_ids, areas, internals["needed"])
    if stale:
        raise HTTPException(status_code=409 if body.validation_id else 422, detail=stale)
    missing = [c for c in internals["needed"] if c not in set(body.confirmations)]
    if missing:
        raise HTTPException(status_code=422, detail={"message": "confirmations are missing", "missing": missing})

    limit = MAX_AREAS_SANDBOX if user.get("sandbox") else MAX_AREAS_OTHER
    fid = internal_id(owner, field_id)
    others = con.execute("SELECT count(*) AS n FROM app.crop_area a JOIN app.field f USING (field_id) "
                         "WHERE f.owner_id = %s AND f.field_id <> %s", (owner, fid)).fetchone()["n"]
    if others + len(body.crop_areas) > limit:
        raise HTTPException(status_code=422, detail=f"at most {limit} crop areas")
    for a in body.crop_areas:                                # size and the area of the weather data, of the geometry that will be stored
        g = con.execute("SELECT ST_Area(ST_GeomFromEWKB(decode(%(h)s, 'hex'))::geography) / 10000 AS ha, EXISTS (SELECT 1 FROM raw.grid_cell c "
                        "JOIN curated.vegetation_resumption v ON v.grid_id = c.grid_id WHERE c.geom && ST_Expand(ST_Centroid("
                        "ST_GeomFromEWKB(decode(%(h)s, 'hex'))), 0.05)) AS in_area",
                        {"h": internals["proposed"][a.crop_area_id]}).fetchone()
        if g["ha"] > MAX_AREA_HA:
            raise HTTPException(status_code=422, detail=f"{a.crop_area_id}: {g['ha']:.0f} ha; at most {MAX_AREA_HA:.0f} ha")
        if not g["in_area"]:
            raise HTTPException(status_code=422, detail=f"{a.crop_area_id}: outside the demo area (Mazowieckie)")

    # ---- the atomic part: nothing is visible until the commit below
    if con.execute("SELECT 1 FROM app.field WHERE field_id = %s AND owner_id = %s", (fid, owner)).fetchone():
        con.execute("UPDATE app.field SET name = COALESCE(%s, name), updated_at = now() WHERE field_id = %s", (body.name, fid))
    else:
        con.execute("INSERT INTO app.field (field_id, name, owner_id, data_status) VALUES (%s, %s, %s, 'mock')",
                    (fid, body.name or "My field", owner))
    con.execute("DELETE FROM app.field_parcel WHERE field_id = %s", (fid,))
    for p in parcel_ids:
        con.execute("INSERT INTO app.field_parcel (field_id, parcel_id) VALUES (%s, %s)", (fid, p))
    keep = [internal_id(owner, i) for i in ids]
    con.execute("DELETE FROM app.crop_area WHERE field_id = %s AND NOT (crop_area_id = ANY(%s))", (fid, keep))
    for a in body.crop_areas:
        cid = internal_id(owner, a.crop_area_id)
        con.execute(
            "INSERT INTO app.crop_area (crop_area_id, field_id, geom, farmer_crop_id, sowing_date, sprays_confirmed) "
            "VALUES (%s, %s, ST_GeomFromEWKB(decode(%s, 'hex')), %s, %s, true) "
            "ON CONFLICT (crop_area_id) DO UPDATE SET geom = EXCLUDED.geom, farmer_crop_id = EXCLUDED.farmer_crop_id, "
            "sowing_date = EXCLUDED.sowing_date, sprays_confirmed = true",
            (cid, fid, internals["proposed"][a.crop_area_id], a.crop.farmer_crop_id, a.sowing_date - timedelta(days=shift)))
        con.execute("DELETE FROM app.spray WHERE crop_area_id = %s", (cid,))
        for s in a.past_sprays:
            con.execute("INSERT INTO app.spray (crop_area_id, spray_date, protection_duration_days) VALUES (%s, %s, %s)",
                        (cid, s.date - timedelta(days=shift), s.protection_duration_days))
        _recompute(con, cid, "save")
    con.commit()
    return load_fields(con, owner, fid)[0]
