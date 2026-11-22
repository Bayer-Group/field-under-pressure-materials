# -*- coding: utf-8 -*-
"""Search of places (towns and villages) for the map search box.

Two sources, merged:
* GUGiK UUG (https://services.gugik.gov.pl/uug/): the geocoder of the national register of localities. It matches the WHOLE name only
  (no prefix), answers for the whole country and returns several places with the same name, so the answer is limited to one
  voivodeship (PLACES_VOIVODESHIP, Mazowieckie by default), ordered and cached in memory for a day (a room of phones must not hammer a
  public service);
* our own names (app.parcel: cadastral precincts and communes of the parcels seen so far): prefix matching, so the search box can
  suggest while the user types.
A failure of the GUGiK service is not an error: the answer then has only our own names.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.parse
import urllib.request

UUG_URL = os.environ.get("GUGIK_UUG_URL", "https://services.gugik.gov.pl/uug/")
VOIVODESHIP = os.environ.get("PLACES_VOIVODESHIP", "mazowieckie")
ZOOM = 16                                  # the zoom from which the parcel boundaries of GUGiK are drawn
CACHE_SECONDS = 24 * 3600
CACHE_MAX = 2000

_cache: dict[str, tuple[float, list[dict]]] = {}
_lock = threading.Lock()


def _label(city: str, commune: str, county: str) -> str:
    """"Płońsk, pow. płoński", "Sadkowice, gm. Solec nad Wisłą, pow. lipski"; a town with the rights of a county is just its name."""
    if county.lower() == city.lower():
        return city
    if commune.lower() == city.lower():
        return f"{city}, pow. {county}"
    return f"{city}, gm. {commune}, pow. {county}"


def parse_uug(payload: dict, voivodeship: str = VOIVODESHIP) -> list[dict]:
    """Places of one voivodeship from an UUG answer (requested with srid=4326: x is the longitude, y the latitude)."""
    out = []
    for v in (payload.get("results") or {}).values():
        if (v.get("voivodeship") or "").lower() != voivodeship.lower():
            continue
        try:
            lon, lat = float(v["x"]), float(v["y"])
        except (KeyError, TypeError, ValueError):
            continue
        city, commune, county = v.get("city") or "", v.get("commune") or "", v.get("county") or ""
        if not city:
            continue
        out.append({"name": city, "label": _label(city, commune, county), "lon": lon, "lat": lat, "zoom": ZOOM, "source": "gugik",
                    "_town": county.lower() == city.lower()})
    return out


def _uug(q: str) -> list[dict]:
    key = q.lower()
    now = time.time()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < CACHE_SECONDS:
            return hit[1]
    url = UUG_URL + "?" + urllib.parse.urlencode({"request": "GetAddress", "address": q, "srid": 4326})
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "field-under-pressure/1.0"}), timeout=6) as r:
            places = parse_uug(json.loads(r.read().decode("utf-8")))
    except Exception:                                      # the service is a bonus: do not fail the search
        return []
    with _lock:
        if len(_cache) >= CACHE_MAX:
            _cache.clear()
        _cache[key] = (now, places)
    return places


def _known(con, q: str, limit: int) -> list[dict]:
    """Prefix matches among the names of the parcels we have seen (a village is a cadastral precinct; towns have numbers, skipped)."""
    rows = con.execute(
        "SELECT region, commune, county, ST_X(c) AS lon, ST_Y(c) AS lat FROM ("
        " SELECT region, commune, county, ST_Centroid(ST_Collect(geom)) AS c FROM app.parcel"
        " WHERE source = 'uldk' AND region IS NOT NULL AND region !~ '^[0-9]+(-[0-9]+)*$' AND lower(region) LIKE lower(%s) || '%%'"
        " GROUP BY region, commune, county) x ORDER BY region, commune LIMIT %s", (q, limit)).fetchall()
    out = []
    for r in rows:
        commune = (r["commune"] or "").replace(" (miasto)", "")
        out.append({"name": r["region"], "label": _label(r["region"], commune, (r["county"] or "").replace("powiat ", "")),
                    "lon": r["lon"], "lat": r["lat"], "zoom": ZOOM, "source": "parcels", "_town": False})
    return out


def search(con, q: str, limit: int = 8) -> list[dict]:
    """[{name, label, lon, lat, zoom, source}]: exact names from GUGiK first (towns with the rights of a county before villages), then
    prefix matches among the names we know; one entry per place."""
    q = " ".join(q.split())
    if len(q) < 2:
        return []
    exact = _uug(q) if len(q) >= 3 else []
    exact.sort(key=lambda p: (not p["_town"], p["label"]))
    merged, seen = [], set()
    for p in exact + _known(con, q, limit):
        key = (p["name"].lower(), p["label"].lower())
        if key in seen:
            continue
        seen.add(key)
        merged.append({k: v for k, v in p.items() if not k.startswith("_")})
    return merged[:limit]
