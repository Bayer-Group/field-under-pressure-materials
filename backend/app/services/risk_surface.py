# -*- coding: utf-8 -*-
"""Smoothed risk surface of the voivodeship grid (a heatmap) for GET /grid/risk/surface (PROPOSAL, issue #49).

Pure Python (standard library only), no database: the endpoint passes the cell centres and their risk index.

Method: on a regular lon/lat grid, every pixel gets the Gaussian-weighted mean of the risk index of the cells around it
(Nadaraya-Watson). The weights are normalised, so the value stays on the 0-1 index scale (a colour means the same class
everywhere) and the surface does not fade at the edge of the data. A pixel farther than `max_distance_km` from every cell
centre has no value (outside the data). It is a way to show the cell results smoothly; it adds no new assessment.
"""
from __future__ import annotations

import math
import struct
import zlib
from typing import Iterable, Optional, Sequence

KM_PER_DEG_LAT = 110.574
KM_PER_DEG_LON_EQUATOR = 111.320

# Colours of the PNG (the same as the QGIS plugin): index 0 low green, 0.5 medium amber, 1 high red.
RAMP = ((0.0, (79, 154, 118)), (0.5, (240, 168, 48)), (1.0, (215, 48, 39)))
PNG_ALPHA = 210


def surface(points: Iterable[tuple[float, float, Optional[float]]], *, resolution_deg: float = 0.02,
            sigma_km: float = 5.0, max_distance_km: float = 4.0) -> Optional[dict]:
    """points: (lon, lat, value 0-1 or None). Returns the grid as a dict, or None when there are no valid points.

    The grid is in EPSG:4326, row 0 is the northern edge; values[row][col] is the index at the pixel centre or None."""
    pts = [(lon, lat, v) for lon, lat, v in points if v is not None]
    if not pts:
        return None
    lat0 = sum(p[1] for p in pts) / len(pts)
    kx = KM_PER_DEG_LON_EQUATOR * math.cos(math.radians(lat0))      # km per degree of longitude at the mean latitude
    ky = KM_PER_DEG_LAT
    cutoff = 3.0 * sigma_km                                          # weights beyond 3 sigma are negligible
    reach = max(cutoff, max_distance_km)

    # Spatial hash of the points in km, so each pixel only looks at the cells near it.
    bins: dict[tuple[int, int], list[tuple[float, float, float]]] = {}
    for lon, lat, v in pts:
        x, y = lon * kx, lat * ky
        bins.setdefault((int(x // reach), int(y // reach)), []).append((x, y, v))

    pad = max_distance_km
    west = min(p[0] for p in pts) - pad / kx
    east = max(p[0] for p in pts) + pad / kx
    south = min(p[1] for p in pts) - pad / ky
    north = max(p[1] for p in pts) + pad / ky
    width = max(1, int(math.ceil((east - west) / resolution_deg)))
    height = max(1, int(math.ceil((north - south) / resolution_deg)))
    east, south = west + width * resolution_deg, north - height * resolution_deg

    two_s2 = 2.0 * sigma_km * sigma_km
    cut2, near2 = cutoff * cutoff, max_distance_km * max_distance_km
    values: list[list[Optional[float]]] = []
    for row in range(height):
        lat = north - (row + 0.5) * resolution_deg
        y = lat * ky
        line: list[Optional[float]] = []
        for col in range(width):
            x = (west + (col + 0.5) * resolution_deg) * kx
            bx, by = int(x // reach), int(y // reach)
            wsum = vsum = 0.0
            nearest = math.inf
            for i in (bx - 1, bx, bx + 1):
                for j in (by - 1, by, by + 1):
                    for px, py, v in bins.get((i, j), ()):
                        d2 = (px - x) ** 2 + (py - y) ** 2
                        if d2 < nearest:
                            nearest = d2
                        if d2 <= cut2:
                            w = math.exp(-d2 / two_s2)
                            wsum += w
                            vsum += w * v
            line.append(round(vsum / wsum, 3) if (nearest <= near2 and wsum > 0) else None)
        values.append(line)
    return {
        "crs": "EPSG:4326",
        "bounds": [round(west, 6), round(south, 6), round(east, 6), round(north, 6)],   # west, south, east, north
        "resolution_deg": resolution_deg,
        "width": width,
        "height": height,
        "sigma_km": sigma_km,
        "max_distance_km": max_distance_km,
        "values": values,
    }


def colour(v: Optional[float]) -> tuple[int, int, int, int]:
    """RGBA of an index value on the fixed ramp; None is transparent."""
    if v is None:
        return 0, 0, 0, 0
    v = min(max(v, 0.0), 1.0)
    for (v0, c0), (v1, c1) in zip(RAMP, RAMP[1:]):
        if v <= v1:
            t = (v - v0) / (v1 - v0)
            return (*(round(a + (b - a) * t) for a, b in zip(c0, c1)), PNG_ALPHA)
    return (*RAMP[-1][1], PNG_ALPHA)


def to_png(values: Sequence[Sequence[Optional[float]]]) -> bytes:
    """RGBA PNG of the grid (row 0 at the top), with the standard library only."""
    height, width = len(values), len(values[0]) if values else 0
    raw = bytearray()
    for line in values:
        raw.append(0)                                   # filter type 0 (none) for each scanline
        for v in line:
            raw.extend(colour(v))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)    # 8-bit RGBA
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(bytes(raw), 6)) + chunk(b"IEND", b"")
