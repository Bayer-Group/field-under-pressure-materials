# -*- coding: utf-8 -*-
"""Write side of docs/serve_read_contract.md and the demo sandbox for the audience.

A visitor gets a sandbox with one request (no password): either a copy of a ready farm or an empty one, and a token for
SANDBOX_TTL_HOURS. Everything a visitor saves belongs to that sandbox owner (owner_id starts with "sbx-"; the data stays data_status = 'mock') and is
deleted after the same time. Dates arrive in the
shown time and are translated back to the time of the data (serve.shift_days()). Limits protect the small VM; DEMO_READONLY turns
all writes off.
"""
from __future__ import annotations

import json
import secrets
import threading
from datetime import date, timedelta
from typing import Literal, Optional

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from psycopg import sql
from pydantic import BaseModel, Field

from backend.app.api.v1.endpoints.farm import _require_area, current_user
from backend.app.core.config import (ALLOW_EXAMPLE_FARM_WRITES, AUTH_SECRET, DEMO_READONLY, MAX_AREA_HA, MAX_AREAS_OTHER, MAX_AREAS_SANDBOX,
                                     MAX_PARALLEL_REFRESH, SANDBOX_MAX_OWNERS, SANDBOX_RATE_PER_MIN, SANDBOX_TTL_HOURS)
from backend.app.core.db import get_db, get_db_rw
from backend.app.core.limits import RateLimiter, client_ip, enforce
from backend.app.core.security import make_token
from backend.app.services.crop_area_refresh import load_rules, refresh

router = APIRouter()

_sandbox_limit = RateLimiter(SANDBOX_RATE_PER_MIN, 60)   # sandboxes per minute and address (a room behind one NAT shares it)
_write_limit = RateLimiter(60, 60)              # writes per minute and owner
_slots = threading.BoundedSemaphore(MAX_PARALLEL_REFRESH)
_rules = None
_COLUMNS: dict[tuple[str, str], list[str]] = {}


def rules():
    global _rules
    if _rules is None:
        _rules = load_rules()
    return _rules


class SandboxIn(BaseModel):
    mode: Literal["mock", "empty"] = "mock"


class AreaIn(BaseModel):
    geometry: dict                                         # GeoJSON Polygon or MultiPolygon, EPSG:4326
    farmer_crop_id: str
    sowing_date: date                                      # in the shown time
    name: Optional[str] = Field(None, max_length=60)
    bbch_override: Optional[Literal[31, 37, 39, 51, 59]] = None


class SprayIn(BaseModel):
    spray_date: date                                       # in the shown time, may be in the past
    protection_duration_days: int = Field(10, ge=1, le=60)


def _require_writes(user: dict) -> None:
    if DEMO_READONLY:
        raise HTTPException(status_code=503, detail="the demo is read-only now")
    if user.get("role") != "farmer":
        raise HTTPException(status_code=403, detail="only a farmer can save crop areas")
    if not (user.get("account") or user.get("sandbox")) and not ALLOW_EXAMPLE_FARM_WRITES:
        raise HTTPException(status_code=403, detail="an example farm is read-only: log in with your account (POST /login) or start a "
                                                    "sandbox (POST /sandbox) and edit your own copy")
    enforce(_write_limit, user["owner_id"])


def pick_template(owners: list[str], n: int) -> str:
    """The example farm for the n-th sandbox (n counts from 1): they are handed out one after another and start again after the last."""
    return sorted(owners)[(n - 1) % len(owners)]


def _shift(con) -> int:
    return con.execute("SELECT serve.shift_days() AS s").fetchone()["s"]


def _today(con) -> date:
    return con.execute("SELECT current_date AS d").fetchone()["d"]


def _data_range(con) -> tuple[date, date]:
    r = con.execute("SELECT min(date) AS d0, max(date) AS d1 FROM curated.weather_hourly_features").fetchone()
    if r["d0"] is None:
        raise HTTPException(status_code=503, detail="no weather in the database")
    return r["d0"], r["d1"]


def _feature(con, crop_area_id: str) -> dict:
    return con.execute(
        "SELECT jsonb_build_object('type', 'Feature', 'geometry', ST_AsGeoJSON(geom, 6)::jsonb, "
        "'properties', to_jsonb(t) - 'geom') AS f FROM serve.crop_area_today t WHERE crop_area_id = %s",
        (crop_area_id,)).fetchone()["f"]


def _recompute(con, crop_area_id: str, reason: str, what: str = "all") -> None:
    d0, d1 = _data_range(con)
    if not _slots.acquire(timeout=10):
        raise HTTPException(status_code=503, detail="busy, try again in a moment")
    try:
        refresh(con, crop_area_id, d0, d1, rules(), reason, what)
    finally:
        _slots.release()


def _clone(con, schema: str, table: str, where: str, params: dict, replace: dict[str, str]) -> None:
    """INSERT .. SELECT of the rows matching `where`, with some columns replaced by SQL expressions; generated keys are skipped."""
    cols = _COLUMNS.get((schema, table))
    if cols is None:                                      # the catalog view is slow: read it once per process
        cols = _COLUMNS[(schema, table)] = [r["column_name"] for r in con.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema = %s AND table_name = %s "
            "AND (column_default IS NULL OR column_default NOT LIKE 'nextval%%') ORDER BY ordinal_position",
            (schema, table)).fetchall()]
    ident = sql.Identifier(schema, table)
    con.execute(
        sql.SQL("INSERT INTO {t} ({c}) SELECT {e} FROM {t} WHERE ").format(
            t=ident, c=sql.SQL(", ").join(map(sql.Identifier, cols)),
            e=sql.SQL(", ").join(sql.SQL(replace[c]) if c in replace else sql.Identifier(c) for c in cols)) + sql.SQL(where),
        params)


@router.get("/crops", summary="Crops a farmer can choose (shape of FARMER_INPUT_CONTRACT.md)")
def crops(con=Depends(get_db)):
    rows = con.execute("SELECT farmer_crop_id, label FROM curated.crop_mapping ORDER BY farmer_crop_id").fetchall()
    return {"crops": [{"id": r["farmer_crop_id"], "label": r["label"]} for r in rows], "data_status": "mock"}


@router.post("/sandbox", summary="Start a sandbox for a visitor (no password)")
def sandbox(body: SandboxIn, request: Request, con=Depends(get_db_rw)):
    enforce(_sandbox_limit, client_ip(request))
    ttl = SANDBOX_TTL_HOURS * 3600
    if DEMO_READONLY:                                    # read-only fallback: look at a shared farm, nothing is saved
        owner = con.execute("SELECT owner_id FROM app.field WHERE data_status = 'mock' AND owner_id LIKE 'farmer-%' "
                            "GROUP BY owner_id ORDER BY count(*) DESC, owner_id LIMIT 1").fetchone()
        if not owner:
            raise HTTPException(status_code=503, detail="no demo data")
        token = make_token({"sub": "viewer", "owner_id": owner["owner_id"], "role": "viewer", "sandbox": True}, AUTH_SECRET, ttl)
        return {"token": token, "owner_id": owner["owner_id"], "role": "viewer", "mode": "readonly", "expires_in": ttl,
                "display_name": "Viewer", "crop_areas": None}
    con.execute("DELETE FROM app.field WHERE owner_id LIKE 'sbx-%%' AND created_at < now() - make_interval(secs => %s)", (ttl,))
    owners = con.execute("SELECT count(DISTINCT owner_id) AS n FROM app.field WHERE owner_id LIKE 'sbx-%'").fetchone()["n"]
    if owners >= SANDBOX_MAX_OWNERS:                      # make room: drop the oldest sandbox rather than refuse a new visitor
        con.execute("DELETE FROM app.field WHERE owner_id = (SELECT owner_id FROM app.field WHERE owner_id LIKE 'sbx-%' "
                    "GROUP BY owner_id ORDER BY min(created_at) LIMIT 1)")
    sid = "sbx-" + secrets.token_hex(4)
    n_areas = 0
    template = display = None
    if body.mode == "mock":
        owners = [r["owner_id"] for r in con.execute(
            "SELECT owner_id FROM app.field WHERE data_status = 'mock' AND owner_id LIKE 'farmer-%' "   # example farmers only, not accounts
            "GROUP BY owner_id HAVING count(*) >= 2 ORDER BY owner_id").fetchall()]
        if owners:
            try:
                with con.transaction():
                    n = con.execute("UPDATE app.sandbox_counter SET n = n + 1 WHERE id = 1 RETURNING n").fetchone()["n"]
            except psycopg.errors.UndefinedTable:                 # the migration 009 is not applied: a random example farm
                n = secrets.randbelow(len(owners)) + 1
            template = pick_template(owners, n)
            ids = [r["crop_area_id"] for r in con.execute(
                "SELECT a.crop_area_id FROM app.crop_area a JOIN app.field f USING (field_id) WHERE f.owner_id = %s "
                "ORDER BY a.crop_area_id LIMIT 12", (template,)).fetchall()]
            p = {"sid": sid, "ids": ids, "tpl": template}
            tail = "CASE WHEN {c} LIKE %(tpl)s || '-%%' THEN substr({c}, length(%(tpl)s) + 2) ELSE {c} END"    # p1, p1a: no owner prefix
            ca = "%(sid)s || '~' || " + tail.format(c="crop_area_id")          # the id format of PUT /fields (owner~id): edited in place
            fld = "%(sid)s || '~' || " + tail.format(c="field_id")
            _clone(con, "app", "field", "field_id IN (SELECT field_id FROM app.crop_area WHERE crop_area_id = ANY(%(ids)s))", p,
                   {"field_id": fld, "owner_id": "%(sid)s", "created_at": "now()", "updated_at": "now()"})
            _clone(con, "app", "field_parcel", "field_id IN (SELECT field_id FROM app.crop_area WHERE crop_area_id = ANY(%(ids)s))", p,
                   {"field_id": fld})                       # the cadastral parcels of the copied fields (parcel_ids of GET /fields)
            _clone(con, "app", "crop_area", "crop_area_id = ANY(%(ids)s)", p, {"crop_area_id": ca, "field_id": fld})
            _clone(con, "app", "spray", "crop_area_id = ANY(%(ids)s)", p, {"crop_area_id": ca})
            for table in ("crop_area_crop_map", "field_context", "risk_assessment"):
                _clone(con, "curated", table, "crop_area_id = ANY(%(ids)s)", p, {"crop_area_id": ca})
            n_areas = len(ids)
            row = con.execute("SELECT display_name FROM app.demo_user WHERE owner_id = %s AND role = 'farmer' LIMIT 1", (template,)).fetchone()
            display = row["display_name"] if row else None
    con.commit()
    token = make_token({"sub": sid, "owner_id": sid, "role": "farmer", "sandbox": True}, AUTH_SECRET, ttl)
    return {"token": token, "owner_id": sid, "role": "farmer", "mode": body.mode, "expires_in": ttl,
            "display_name": display or "Visitor", "crop_areas": n_areas, "template": template}


@router.delete("/sandbox", status_code=204, summary="Delete everything in my sandbox (start over)")
def end_sandbox(user=Depends(current_user), con=Depends(get_db_rw)):
    if not user.get("sandbox") or user.get("role") != "farmer":
        raise HTTPException(status_code=403, detail="only a sandbox visitor can do this")
    con.execute("DELETE FROM app.field WHERE owner_id = %s AND owner_id LIKE 'sbx-%%'", (user["owner_id"],))
    con.commit()
    return Response(status_code=204)


@router.post("/crop-areas", status_code=201, summary="Save a crop area (recomputes it)")
def create_crop_area(body: AreaIn, user=Depends(current_user), con=Depends(get_db_rw)):
    _require_writes(user)
    owner = user["owner_id"]
    limit = MAX_AREAS_SANDBOX if user.get("sandbox") else MAX_AREAS_OTHER
    n = con.execute("SELECT count(*) AS n FROM app.field WHERE owner_id = %s", (owner,)).fetchone()["n"]
    if n >= limit:
        raise HTTPException(status_code=422, detail=f"at most {limit} crop areas")
    if not con.execute("SELECT 1 FROM curated.crop_mapping WHERE farmer_crop_id = %s", (body.farmer_crop_id,)).fetchone():
        raise HTTPException(status_code=422, detail="unknown crop (see GET /crops)")
    shift, today = _shift(con), _today(con)
    if body.sowing_date > today:
        raise HTTPException(status_code=422, detail="the sowing date cannot be in the future")
    try:
        g = con.execute(
            "WITH g AS (SELECT ST_SetSRID(ST_GeomFromGeoJSON(%(gj)s), 4326) AS geom) "
            "SELECT ST_IsValid(geom) AS valid, GeometryType(geom) AS gtype, ST_NPoints(geom) AS pts, "
            "ST_Area(geom::geography) / 10000 AS ha, EXISTS (SELECT 1 FROM raw.grid_cell c JOIN curated.vegetation_resumption v "
            "ON v.grid_id = c.grid_id WHERE c.geom && ST_Expand(ST_Centroid(g.geom), 0.05)) AS in_area FROM g",
            {"gj": json.dumps(body.geometry)}).fetchone()
    except (psycopg.errors.DataError, psycopg.errors.InternalError, psycopg.errors.InvalidParameterValue):
        raise HTTPException(status_code=422, detail="invalid GeoJSON geometry")
    if g["gtype"] not in ("POLYGON", "MULTIPOLYGON") or not g["valid"] or g["pts"] > 500:
        raise HTTPException(status_code=422, detail="the geometry must be a valid polygon (at most 500 points)")
    if g["ha"] > MAX_AREA_HA:
        raise HTTPException(status_code=422, detail=f"the area is {g['ha']:.0f} ha; at most {MAX_AREA_HA:.0f} ha")
    if not g["in_area"]:
        raise HTTPException(status_code=422, detail="outside the demo area (Mazowieckie)")
    uid = secrets.token_hex(5)
    fid, cid = f"f-{owner}-{uid}", f"ca-{owner}-{uid}"
    con.execute("INSERT INTO app.field (field_id, name, owner_id, data_status) VALUES (%s, %s, %s, %s)",
                (fid, body.name or "My field", owner, "mock"))
    con.execute("INSERT INTO app.crop_area (crop_area_id, field_id, geom, farmer_crop_id, sowing_date, bbch_override) "
                "VALUES (%s, %s, ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326), %s, %s, %s)",
                (cid, fid, json.dumps(body.geometry), body.farmer_crop_id, body.sowing_date - timedelta(days=shift),
                 body.bbch_override))
    _recompute(con, cid, "sowing")
    con.commit()
    return _feature(con, cid)


@router.post("/crop-areas/{crop_area_id}/sprays", status_code=201, summary="Save a spray (recomputes the crop area)")
def add_spray(crop_area_id: str, body: SprayIn, user=Depends(current_user), con=Depends(get_db_rw)):
    _require_writes(user)
    crop_area_id = _require_area(con, user, crop_area_id)               # the id of GET /fields or the stored one
    shift, today = _shift(con), _today(con)
    if body.spray_date > today:
        raise HTTPException(status_code=422, detail="the spray date cannot be in the future")
    spray_id = con.execute("INSERT INTO app.spray (crop_area_id, spray_date, protection_duration_days) VALUES (%s, %s, %s) "
                           "RETURNING spray_id", (crop_area_id, body.spray_date - timedelta(days=shift),
                                                  body.protection_duration_days)).fetchone()["spray_id"]
    con.execute("UPDATE app.crop_area SET sprays_confirmed = true WHERE crop_area_id = %s", (crop_area_id,))
    _recompute(con, crop_area_id, "spray", what="risk")       # a spray changes nothing in the crop map or the soil
    changed = con.execute("SELECT count(*) AS n FROM curated.risk_change WHERE crop_area_id = %s AND reason = 'spray' "
                          "AND computed_at = now()", (crop_area_id,)).fetchone()["n"]
    con.commit()
    return {"crop_area": _feature(con, crop_area_id), "changed_days": changed,
            "spray": {"spray_id": spray_id, "date": body.spray_date, "protection_duration_days": body.protection_duration_days}}


@router.delete("/crop-areas/{crop_area_id}", status_code=204, summary="Delete a crop area")
def delete_crop_area(crop_area_id: str, user=Depends(current_user), con=Depends(get_db_rw)):
    _require_writes(user)
    crop_area_id = _require_area(con, user, crop_area_id)
    con.execute("DELETE FROM app.field WHERE field_id = (SELECT field_id FROM app.crop_area WHERE crop_area_id = %s)",
                (crop_area_id,))
    con.commit()
    return Response(status_code=204)
