# -*- coding: utf-8 -*-
"""Cadastral parcels from GUGiK ULDK with a cache in app.parcel.

A lookup by point first asks the database (a stored parcel that contains the point is the answer: parcels do not overlap), and only
calls ULDK when nothing is stored; a lookup by number always asks ULDK. Every parcel returned by ULDK is stored (upsert by
parcel_id) with the names of its place (cadastral precinct, commune, county, voivodeship), so a repeated click or a service outage
does not matter for parcels already seen. The connection must return dict rows and the caller commits.
"""
from __future__ import annotations

import re

from backend.app.ingestion.uldk_connector import UldkConnector, UldkError

SOURCE = "uldk"

_COLUMNS = "parcel_id, parcel_number, region, commune, county, voivodeship, ST_AsGeoJSON(geom, 7)::jsonb AS geometry"
_SELECT = f"SELECT {_COLUMNS} FROM app.parcel"
_NUMERIC_PRECINCT = re.compile(r"^\d+(-\d+)*$")           # in a town the precinct is a number such as 1-01-16


def location_label(region: str | None, commune: str | None) -> str | None:
    """The place of a parcel for display: "Krępica, gm. Płońsk" for a village, "Warszawa" for a town with a numbered precinct,
    "Śródmieście 2, Radom" for a named district of a town."""
    commune = (commune or "").strip()
    town = commune.endswith("(miasto)")
    commune = re.sub(r"\s*\(miasto\)$", "", commune)
    region = (region or "").strip()
    if not region or _NUMERIC_PRECINCT.match(region) or region.lower() == commune.lower():
        return commune or region or None
    if town:                                                  # a named precinct of a town is a district: "Śródmieście 2, Radom"
        return f"{region}, {commune}"
    return f"{region}, gm. {commune}" if commune else region


def _with_location(row: dict) -> dict:
    row["location"] = location_label(row.get("region"), row.get("commune"))
    return row


def _store(con, parcels: list[dict]) -> list[str]:
    ids = []
    for p in parcels:
        try:
            with con.transaction():                           # a savepoint: one bad geometry does not spoil the others
                con.execute(
                    "INSERT INTO app.parcel (parcel_id, parcel_number, source, geom, region, commune, county, voivodeship) "
                    "VALUES (%s, %s, %s, ST_GeomFromEWKT(%s), %s, %s, %s, %s) "
                    "ON CONFLICT (parcel_id) DO UPDATE SET parcel_number = EXCLUDED.parcel_number, geom = EXCLUDED.geom, "
                    "region = EXCLUDED.region, commune = EXCLUDED.commune, county = EXCLUDED.county, "
                    "voivodeship = EXCLUDED.voivodeship",
                    (p["parcel_id"], p["parcel_number"], SOURCE, p["ewkt"], p.get("region"), p.get("commune"), p.get("county"),
                     p.get("voivodeship")))
            ids.append(p["parcel_id"])
        except Exception:                                      # not polygonal or unreadable: skip this parcel
            continue
    return ids


def _by_ids(con, ids: list[str]) -> list[dict]:
    if not ids:
        return []
    return [_with_location(r) for r in con.execute(_SELECT + " WHERE parcel_id = ANY(%s) ORDER BY parcel_id", (ids,)).fetchall()]


def find_by_xy(con, lon: float, lat: float) -> list[dict]:
    """[{parcel_id, parcel_number, region, commune, county, voivodeship, location, geometry}] of the parcel at the point (GeoJSON,
    EPSG:4326). Raises UldkError when the service is needed and does not answer."""
    hit = con.execute(
        _SELECT + " WHERE source = %s AND ST_Covers(geom, ST_SetSRID(ST_MakePoint(%s, %s), 4326)) ORDER BY parcel_id LIMIT 5",
        (SOURCE, lon, lat)).fetchall()
    if hit:
        if any(r["region"] is None and r["commune"] is None for r in hit):     # stored before the names were kept: fill them in
            try:
                for r in hit:
                    if r["commune"] is None:
                        _store(con, UldkConnector.lookup_by_number(r["parcel_id"]))
                return _by_ids(con, [r["parcel_id"] for r in hit])
            except UldkError:
                pass                                                          # the names are a bonus: answer with what is stored
        return [_with_location(r) for r in hit]
    return _by_ids(con, _store(con, UldkConnector.lookup_by_xy(lon, lat)))


def find_by_number(con, text: str) -> list[dict]:
    """Parcels matching an identifier or a number, always asked from ULDK (several matches are possible)."""
    return _by_ids(con, _store(con, UldkConnector.lookup_by_number(text)))
