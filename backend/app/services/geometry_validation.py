# -*- coding: utf-8 -*-
"""Geometry validation of farmer-drawn crop areas against the selected cadastral parcels (GEOMETRY_VALIDATION_CONTRACT.md).

Everything geometric is done in PostGIS. The parcel geometries are the authoritative ones from app.parcel (a missing parcel is
fetched from GUGiK); crop areas are validated against the UNION of the selected parcels. Findings:

* repair of an invalid geometry (ST_MakeValid): silent only when the boundary moved at most 0.25 m, the area changed at most 0.5 %
  and no part disappeared; otherwise `requires_review`; when the measurements fail the repair is also left for review;
* outside: the part of a crop area outside the parcels (clipped only after a confirmation);
* overlaps between crop areas (they block saving; touching along an edge is allowed);
* gaps: parcel surface that no crop area covers (each needs a confirmation that it is excluded from the analysis);
* errors: machine-readable `code`, optional `crop_area_id`, `message`.

Ids (repair, outside, gap, overlap) are derived from the content of the geometry, so they are stable. `validation_id` is a signed token
of the hash of the request and of the set of findings, so a stale one is rejected at the save without storing anything.
"""
from __future__ import annotations

import hashlib
import json
from typing import Optional

import psycopg

from backend.app.core.config import AUTH_SECRET
from backend.app.core.security import make_token, read_token
from backend.app.ingestion.uldk_connector import UldkError
from backend.app.services import parcels as parcel_service

# Limits of the contract and of the calculation (square metres in EPSG:2180 unless the name says otherwise)
MAX_DISPLACEMENT_M = 0.25
MAX_AREA_CHANGE_PERCENT = 0.5
OUTSIDE_MIN_M2 = 0.1          # smaller clipped slivers are dropped without a confirmation
OVERLAP_MIN_M2 = 0.1
GAP_MIN_M2 = 1.0
EMPTY_MIN_M2 = 0.1            # a crop area smaller than this after clipping is empty
OPEN_M = 0.05                 # findings thinner than this are noise (GeoJSON is rounded to 7 decimals, about 1 cm) and are removed


def _opened(expr: str) -> str:
    """SQL: a geometry (EPSG:4326) with the parts thinner than 2 * OPEN_M removed (morphological opening in EPSG:2180)."""
    return (f"ST_CollectionExtract(ST_Transform(ST_Buffer(ST_Buffer(ST_Transform({expr}, 2180), -{OPEN_M}), {OPEN_M}), 4326), 3)")
VALIDATION_TTL_SECONDS = 3600


def _h(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:10]


def request_hash(parcel_ids: list[str], crop_areas: list[dict]) -> str:
    """Hash of exactly the submitted selection and geometries (order of the ids does not matter)."""
    canon = {"p": sorted(parcel_ids),
             "c": sorted(([a["crop_area_id"], json.dumps(a["geometry"], sort_keys=True, separators=(",", ":"))] for a in crop_areas))}
    return hashlib.sha256(json.dumps(canon, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _err(code: str, message: str, crop_area_id: Optional[str] = None) -> dict:
    e = {"code": code, "message": message}
    if crop_area_id is not None:
        e["crop_area_id"] = crop_area_id
    return e


def _ensure_parcels(con, parcel_ids: list[str], errors: list[dict]) -> list[str]:
    """The ids that exist in app.parcel after fetching the missing ones from GUGiK; the others are reported in `errors`."""
    have = {r["parcel_id"] for r in con.execute("SELECT parcel_id FROM app.parcel WHERE parcel_id = ANY(%s)", (parcel_ids,)).fetchall()}
    for pid in [p for p in parcel_ids if p not in have]:
        try:
            parcel_service.find_by_number(con, pid)
        except UldkError:
            errors.append(_err("parcel_service_unavailable", f"parcel {pid} is not stored and the GUGiK service does not answer"))
    have = {r["parcel_id"] for r in con.execute("SELECT parcel_id FROM app.parcel WHERE parcel_id = ANY(%s)", (parcel_ids,)).fetchall()}
    for pid in parcel_ids:
        if pid not in have and not any(e["code"] == "parcel_service_unavailable" and pid in e["message"] for e in errors):
            errors.append(_err("unknown_parcel", f"parcel {pid} was not found"))
    return [p for p in parcel_ids if p in have]


def _prepare(con, crop_area_id: str, geometry: dict, union_hex: str, errors: list[dict]) -> Optional[dict]:
    """Repair, measure and clip one crop area. Returns the data for the response and for the save, or None (errors filled)."""
    gj = json.dumps(geometry)
    try:
        with con.transaction():
            r = con.execute(
                "WITH i AS (SELECT ST_SetSRID(ST_GeomFromGeoJSON(%(gj)s), 4326) AS g0), "
                "r AS (SELECT g0, ST_IsValid(g0) AS was_valid, CASE WHEN ST_IsValid(g0) THEN g0 "
                "      ELSE ST_CollectionExtract(ST_MakeValid(g0), 3) END AS g1 FROM i) "
                "SELECT GeometryType(g0) AS gtype, ST_NPoints(g0) AS pts, was_valid, ST_IsEmpty(g1) AS empty1, "
                "ST_IsValid(g1) AS valid1, ST_NumGeometries(g0) AS n0, ST_NumGeometries(g1) AS n1, "
                "encode(ST_AsEWKB(g0), 'hex') AS g0, encode(ST_AsEWKB(g1), 'hex') AS g1 FROM r", {"gj": gj}).fetchone()
    except (psycopg.errors.DataError, psycopg.errors.InternalError, psycopg.errors.InvalidParameterValue, psycopg.errors.SyntaxError):
        errors.append(_err("invalid_geometry", "the geometry is not valid GeoJSON", crop_area_id))
        return None
    if r["gtype"] not in ("POLYGON", "MULTIPOLYGON") or r["pts"] > 2000:
        errors.append(_err("invalid_geometry", "a crop area must be a Polygon or MultiPolygon of at most 2000 points", crop_area_id))
        return None
    if r["empty1"] or not r["valid1"]:
        errors.append(_err("unrepairable_geometry", "the geometry cannot be repaired into a valid surface", crop_area_id))
        return None

    # Repair measurements: the maximum boundary displacement (Hausdorff distance) and the change of the area, in metres.
    repair = {"performed": False, "max_boundary_displacement_m": 0, "area_change_percent": 0, "requires_review": False}
    if not r["was_valid"]:
        repair["performed"] = True
        repair["repair_id"] = "repair-" + _h(crop_area_id, r["g0"])
        try:
            with con.transaction():
                m = con.execute(
                    "WITH x AS (SELECT ST_Transform(ST_GeomFromEWKB(decode(%(a)s, 'hex')), 2180) AS a, "
                    "ST_Transform(ST_GeomFromEWKB(decode(%(b)s, 'hex')), 2180) AS b) "
                    "SELECT ST_HausdorffDistance(a, b) AS disp, ST_Area(a) AS a0, ST_Area(b) AS a1 FROM x",
                    {"a": r["g0"], "b": r["g1"]}).fetchone()
            disp, a0, a1 = m["disp"], m["a0"], m["a1"]
            if disp is None or not a0 or a0 < 1e-6 * max(a1, 1.0):      # the original surface is not meaningful (a bow-tie)
                raise ValueError("cannot measure")
            change = abs(a1 - a0) / a0 * 100
            repair["max_boundary_displacement_m"] = round(float(disp), 3)
            repair["area_change_percent"] = round(float(change), 3)
            silent = (disp <= MAX_DISPLACEMENT_M and change <= MAX_AREA_CHANGE_PERCENT and r["n1"] >= r["n0"])
            repair["requires_review"] = not silent
        except (psycopg.Error, ValueError, ZeroDivisionError):
            repair["max_boundary_displacement_m"] = None          # not measurable: never silent
            repair["area_change_percent"] = None
            repair["requires_review"] = True

    with con.transaction():
        c = con.execute(
            "WITH g AS (SELECT ST_GeomFromEWKB(decode(%(g1)s, 'hex')) AS g1, ST_GeomFromEWKB(decode(%(u)s, 'hex')) AS u), "
            "p AS (SELECT ST_CollectionExtract(ST_Intersection(g1, u), 3) AS ins, " + _opened("ST_Difference(g1, u)") + " AS outp FROM g) "
            "SELECT ST_Area(ST_Transform(ins, 2180)) AS ins_m2, ST_Area(ST_Transform(outp, 2180)) AS out_m2, "
            "ST_IsEmpty(ins) AS ins_empty, encode(ST_AsEWKB(ins), 'hex') AS ins_hex, encode(ST_AsEWKB(outp), 'hex') AS out_hex, "
            "ST_AsGeoJSON(ins, 7)::jsonb AS ins_json, ST_AsGeoJSON(outp, 7)::jsonb AS out_json FROM p",
            {"g1": r["g1"], "u": union_hex}).fetchone()
    if c["ins_empty"] or (c["ins_m2"] or 0) < EMPTY_MIN_M2:
        errors.append(_err("empty_area", "nothing of the crop area lies on the selected parcels", crop_area_id))
        return None
    outside = None
    if (c["out_m2"] or 0) >= OUTSIDE_MIN_M2:
        outside = {"outside_id": "outside-" + _h(crop_area_id, c["out_hex"]), "crop_area_id": crop_area_id, "geometry": c["out_json"]}
    return {"hex": c["ins_hex"], "geometry": c["ins_json"], "repair": repair, "outside": outside}


def validate(con, parcel_ids: list[str], crop_areas: list[dict]) -> tuple[dict, dict]:
    """(response of the contract, internals for the save: {crop_area_id: proposed geometry as EWKB hex, issues: [...]}).

    The connection must return dict rows; the caller commits (parcels fetched from GUGiK are cached)."""
    errors: list[dict] = []
    known = _ensure_parcels(con, parcel_ids, errors)
    out_areas: list[dict] = []
    overlaps: list[dict] = []
    gaps: list[dict] = []
    outside: list[dict] = []
    proposed: dict[str, str] = {}
    if known:
        union_hex = con.execute("SELECT encode(ST_AsEWKB(ST_Union(geom)), 'hex') AS u FROM app.parcel WHERE parcel_id = ANY(%s)",
                                (known,)).fetchone()["u"]
        for a in crop_areas:
            p = _prepare(con, a["crop_area_id"], a["geometry"], union_hex, errors)
            if p is None:
                out_areas.append({"crop_area_id": a["crop_area_id"], "geometry": None, "repair": None})
                continue
            proposed[a["crop_area_id"]] = p["hex"]
            out_areas.append({"crop_area_id": a["crop_area_id"], "geometry": p["geometry"], "repair": p["repair"]})
            if p["outside"]:
                outside.append(p["outside"])
        ids = list(proposed)
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                o = con.execute(
                    "WITH x AS (SELECT " + _opened("ST_Intersection(ST_GeomFromEWKB(decode(%s, 'hex')), "
                    "ST_GeomFromEWKB(decode(%s, 'hex')))") + " AS g) SELECT ST_Area(ST_Transform(g, 2180)) AS m2, "
                    "encode(ST_AsEWKB(g), 'hex') AS h, ST_AsGeoJSON(g, 7)::jsonb AS j FROM x",
                    (proposed[ids[i]], proposed[ids[j]])).fetchone()
                if (o["m2"] or 0) >= OVERLAP_MIN_M2:
                    overlaps.append({"overlap_id": "overlap-" + _h(ids[i], ids[j], o["h"]), "crop_area_ids": [ids[i], ids[j]],
                                     "geometry": o["j"]})
        if proposed:
            for g in con.execute(
                    "WITH d AS (SELECT (ST_Dump(" + _opened("ST_Difference(ST_GeomFromEWKB(decode(%(u)s, 'hex')), "
                    "(SELECT ST_Union(ST_GeomFromEWKB(decode(h, 'hex'))) FROM unnest(%(hs)s::text[]) AS h))") + ")).geom AS g) "
                    "SELECT ST_Area(ST_Transform(g, 2180)) AS m2, encode(ST_AsEWKB(g), 'hex') AS h, ST_AsGeoJSON(g, 7)::jsonb AS j "
                    "FROM d ORDER BY h", {"u": union_hex, "hs": list(proposed.values())}).fetchall():
                if (g["m2"] or 0) >= GAP_MIN_M2:
                    gaps.append({"gap_id": "gap-" + _h(g["h"]), "geometry": g["j"]})
    else:
        out_areas = [{"crop_area_id": a["crop_area_id"], "geometry": None, "repair": None} for a in crop_areas]

    needed = ([f"gap:{g['gap_id']}" for g in gaps] + [f"outside:{o['outside_id']}" for o in outside] +
              [f"repair:{a['repair']['repair_id']}" for a in out_areas
               if a["repair"] and a["repair"].get("performed") and a["repair"]["requires_review"]])
    token = make_token({"h": request_hash(parcel_ids, crop_areas), "i": sorted(needed)}, AUTH_SECRET, VALIDATION_TTL_SECONDS)
    response = {"validation_id": token, "crop_areas": out_areas, "overlaps": overlaps, "gaps": gaps, "outside": outside,
                "errors": errors, "data_status": "live"}
    return response, {"proposed": proposed, "needed": sorted(needed)}


def check_validation_id(validation_id: Optional[str], parcel_ids: list[str], crop_areas: list[dict],
                        needed: list[str]) -> Optional[str]:
    """None when the validation id belongs to exactly this request and findings, else a reason (stale, missing, ...)."""
    if not validation_id:
        return "validation_id is required"
    claims = read_token(validation_id, AUTH_SECRET)
    if claims is None:
        return "the validation id is invalid or expired; validate again"
    if claims.get("h") != request_hash(parcel_ids, crop_areas):
        return "the validation id belongs to another geometry or parcel selection; validate again"
    if sorted(claims.get("i", [])) != sorted(needed):
        return "the findings changed since the validation (for example the parcel data); validate again"
    return None
