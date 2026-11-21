# -*- coding: utf-8 -*-
"""
Konektor do ULDK GUGiK (Usługa Lokalizacji Działek Katastralnych), https://uldk.gugik.gov.pl/.

Odpowiedź ULDK to tekst: pierwsza linia to status (`0` lub liczba trafień przy wyniku, `-1 ...` gdy nie znaleziono), kolejne linie to
rekordy z polami rozdzielonymi znakiem `|` w kolejności z parametru `result`. Prosimy o `id,parcel,region,geom_wkt` w EPSG:4326, więc
ostatnie pole to EWKT w postaci `SRID=4326;POLYGON((lon lat, ...))`. Brak działki to pusty wynik; awaria usługi to `UldkError`.
"""
from __future__ import annotations

import re
import urllib.parse
import urllib.request

from backend.app.core.config import ULDK_API_URL

RESULT_FIELDS = "id,parcel,region,geom_wkt"


class UldkError(Exception):
    """The parcel service did not answer or answered something that is not ULDK."""


def parse_response(text: str) -> list[dict]:
    """Parcels of an ULDK answer: [{parcel_id, parcel_number, region, ewkt}]; [] when nothing was found."""
    lines = [ln for ln in text.strip().splitlines() if ln.strip()]
    if not lines:
        raise UldkError("empty answer from ULDK")
    status = lines[0].strip()
    if status.startswith("-1"):
        return []
    if not re.fullmatch(r"\d+", status):
        raise UldkError(f"unexpected ULDK answer: {lines[0][:120]}")
    parcels = []
    for line in lines[1:]:
        parts = line.split("|", 3)
        if len(parts) < 4:
            continue
        parcel_id, number, region, ewkt = (p.strip() for p in parts)
        if parcel_id and ewkt.upper().startswith("SRID=4326;"):
            parcels.append({"parcel_id": parcel_id, "parcel_number": number, "region": region, "ewkt": ewkt})
    return parcels


class UldkConnector:
    """Klient publicznego API GUGiK ULDK."""

    BASE_URL = ULDK_API_URL
    TIMEOUT = 8

    @classmethod
    def _get(cls, params: dict) -> str:
        url = f"{cls.BASE_URL}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"User-Agent": "PyQgisFastApiBridge/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=cls.TIMEOUT) as res:
                return res.read().decode("utf-8", errors="replace")
        except Exception as e:                                  # network, timeout, HTTP error
            raise UldkError(str(e)) from e

    @classmethod
    def lookup_by_xy(cls, lon: float, lat: float) -> list[dict]:
        """The parcel at a point (longitude, latitude, EPSG:4326)."""
        return parse_response(cls._get({"request": "GetParcelByXY", "xy": f"{lon},{lat},4326",
                                        "result": RESULT_FIELDS, "srid": 4326}))

    @classmethod
    def lookup_by_number(cls, text: str) -> list[dict]:
        """Parcels for an identifier or a number (TERYT identifier such as 146505_8.0116.5); several matches are possible."""
        return parse_response(cls._get({"request": "GetParcelByIdOrNr", "id": text,
                                        "result": RESULT_FIELDS, "srid": 4326}))

    # --- starsze metody używane przez /cadastre/uldk/... (kształt odpowiedzi zachowany, geometria jest teraz w EPSG:4326) ---
    @classmethod
    def get_parcel_by_id(cls, teryt_id: str):
        """Pobiera geometrię działki po identyfikatorze TERYT."""
        try:
            found = parse_response(cls._get({"request": "GetParcelById", "id": teryt_id,
                                             "result": RESULT_FIELDS, "srid": 4326}))
        except UldkError as e:
            return {"status": "ERROR", "message": str(e)}
        if not found:
            return {"status": "NOT_FOUND", "message": f"Działka {teryt_id} nie została znaleziona w ULDK."}
        p = found[0]
        return {"status": "OK", "teryt_id": p["parcel_id"], "wkt": p["ewkt"], "raw_info": [p["parcel_number"], p["region"]]}

    @classmethod
    def get_parcel_by_xy(cls, x: float, y: float, epsg: int = 2180):
        """Pobiera identyfikator działki i geometrię na podstawie współrzędnych punktu (x, y w układzie `epsg`)."""
        try:
            found = parse_response(cls._get({"request": "GetParcelByXY", "xy": f"{x},{y},{epsg}",
                                             "result": RESULT_FIELDS, "srid": 4326}))
        except UldkError as e:
            return {"status": "ERROR", "message": str(e)}
        if not found:
            return {"status": "NOT_FOUND", "message": "Brak działki w tym punkcie."}
        p = found[0]
        return {"status": "OK", "teryt_id": p["parcel_id"], "wkt": p["ewkt"]}
