# -*- coding: utf-8 -*-
"""Cadastral parcels from GUGiK ULDK with a cache in app.parcel.

A lookup by point first asks the database (a stored parcel that contains the point is the answer: parcels do not overlap), and only
calls ULDK when nothing is stored; a lookup by number always asks ULDK. Every parcel returned by ULDK is stored (upsert by
parcel_id), so a repeated click or a service outage does not matter for parcels already seen. The connection must return dict rows
and the caller commits.
"""
from __future__ import annotations

from backend.app.ingestion.uldk_connector import UldkConnector

SOURCE = "uldk"

_SELECT = "SELECT parcel_id, parcel_number, ST_AsGeoJSON(geom, 7)::jsonb AS geometry FROM app.parcel"


def _store(con, parcels: list[dict]) -> list[str]:
    ids = []
    for p in parcels:
        try:
            with con.transaction():                           # a savepoint: one bad geometry does not spoil the others
                con.execute(
                    "INSERT INTO app.parcel (parcel_id, parcel_number, source, geom) "
                    "VALUES (%s, %s, %s, ST_GeomFromEWKT(%s)) "
                    "ON CONFLICT (parcel_id) DO UPDATE SET parcel_number = EXCLUDED.parcel_number, geom = EXCLUDED.geom",
                    (p["parcel_id"], p["parcel_number"], SOURCE, p["ewkt"]))
            ids.append(p["parcel_id"])
        except Exception:                                      # not polygonal or unreadable: skip this parcel
            continue
    return ids


def _by_ids(con, ids: list[str]) -> list[dict]:
    if not ids:
        return []
    return con.execute(_SELECT + " WHERE parcel_id = ANY(%s) ORDER BY parcel_id", (ids,)).fetchall()


def find_by_xy(con, lon: float, lat: float) -> list[dict]:
    """[{parcel_id, parcel_number, geometry}] of the parcel at the point (GeoJSON, EPSG:4326). Raises UldkError when the
    service is needed and does not answer."""
    hit = con.execute(
        _SELECT + " WHERE source = %s AND ST_Covers(geom, ST_SetSRID(ST_MakePoint(%s, %s), 4326)) ORDER BY parcel_id LIMIT 5",
        (SOURCE, lon, lat)).fetchall()
    if hit:
        return hit
    return _by_ids(con, _store(con, UldkConnector.lookup_by_xy(lon, lat)))


def find_by_number(con, text: str) -> list[dict]:
    """Parcels matching an identifier or a number, always asked from ULDK (several matches are possible)."""
    return _by_ids(con, _store(con, UldkConnector.lookup_by_number(text)))
