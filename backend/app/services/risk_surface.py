# -*- coding: utf-8 -*-
"""Risk surface of the voivodeship grid (a heatmap) for GET /grid/risk/surface (issue #49).

Pure Python (standard library only), no database: the endpoint passes the cell centres and H, the hours of continuous leaf wetness
(`h_low`). The surface is built from the HOURS, and the 0-1 risk index (septoria.risk_index) is applied to each pixel afterwards.
Two reasons (measured on 2024-05-24, 2,428 cells, 13 % of them high): the index is capped at 20 h, so interpolating or averaging
the index lowers the values next to a peak (the high class vanished from the Gaussian surface of the first version: 0 % of the pixels
against 13 % of the cells), while the hours keep the whole range and the class boundaries stay where the thresholds are.

Methods:
* `interpolate` (default): bilinear interpolation on the regular lattice of the grid (0.044 degrees). Exact at the cell centres, local,
  with no parameter to tune; on the check day it gives 33 / 55 / 12 % of low / medium / high pixels against 31 / 55 / 13 % of cells.
* `smooth`: the Gaussian-weighted mean of the cells around each pixel (Nadaraya-Watson), with a radius `sigma_km`; a low-pass filter
  that blurs peaks. Also the fallback when the cells do not form a regular lattice.

A pixel farther than `max_distance_km` from every cell centre has no value (outside the data). It shows the cell results
continuously and is not a new assessment: the classes belong to the cells (septoria.classify).
"""
from __future__ import annotations

import math
import statistics
import struct
import threading
import zlib
from collections import OrderedDict
from typing import Callable, Iterable, Optional, Sequence

KM_PER_DEG_LAT = 110.574
KM_PER_DEG_LON_EQUATOR = 111.320

# Colours of the PNG (the same as the QGIS plugin): index 0 low green, 0.5 medium amber, 1 high red.
RAMP = ((0.0, (79, 154, 118)), (0.5, (240, 168, 48)), (1.0, (215, 48, 39)))
PNG_ALPHA = 210
ASC_NODATA = -9999


def _frame(pts: list, resolution_deg: float, max_distance_km: float) -> tuple:
    """(kx, ky, west, south, east, north, width, height): the km per degree at the mean latitude and the pixel grid around the data."""
    lat0 = sum(p[1] for p in pts) / len(pts)
    kx = KM_PER_DEG_LON_EQUATOR * math.cos(math.radians(lat0))
    ky = KM_PER_DEG_LAT
    west = min(p[0] for p in pts) - max_distance_km / kx
    east = max(p[0] for p in pts) + max_distance_km / kx
    south = min(p[1] for p in pts) - max_distance_km / ky
    north = max(p[1] for p in pts) + max_distance_km / ky
    width = max(1, int(math.ceil((east - west) / resolution_deg)))
    height = max(1, int(math.ceil((north - south) / resolution_deg)))
    return kx, ky, west, north - height * resolution_deg, west + width * resolution_deg, north, width, height


def _result(method: str, resolution_deg: float, max_distance_km: float, frame: tuple, values: list, **extra) -> dict:
    _, _, west, south, east, north, width, height = frame
    out = {"crs": "EPSG:4326", "bounds": [round(west, 6), round(south, 6), round(east, 6), round(north, 6)],   # west, south, east, north
           "resolution_deg": resolution_deg, "width": width, "height": height, "method": method,
           "max_distance_km": max_distance_km, "values": values}
    out.update(extra)
    return out


def detect_lattice(pts: Sequence[tuple]) -> Optional[dict]:
    """The regular lattice of the points (the grid of the weather data), or None when they do not form one.

    {lon0, lat0, dlon, dlat, nodes: {(i, j): value}}; every point must sit within a quarter of a step of its node and no two may
    share a node."""
    lons = sorted({p[0] for p in pts})
    lats = sorted({p[1] for p in pts})
    if len(lons) < 2 or len(lats) < 2:
        return None
    dlon = statistics.median(b - a for a, b in zip(lons, lons[1:]))
    dlat = statistics.median(b - a for a, b in zip(lats, lats[1:]))
    if dlon <= 0 or dlat <= 0:
        return None
    lon0, lat0 = lons[0], lats[0]
    nodes: dict[tuple[int, int], float] = {}
    for lon, lat, v in pts:
        fi, fj = (lon - lon0) / dlon, (lat - lat0) / dlat
        i, j = round(fi), round(fj)
        if abs(fi - i) > 0.25 or abs(fj - j) > 0.25 or (i, j) in nodes:
            return None
        nodes[(i, j)] = v
    return {"lon0": lon0, "lat0": lat0, "dlon": dlon, "dlat": dlat, "nodes": nodes}


def interpolate(pts: list, lattice: dict, *, resolution_deg: float, max_distance_km: float) -> dict:
    """Bilinear interpolation on the lattice. Where some of the four surrounding nodes have no data the weights of the others are
    renormalised, so the surface follows the outline of the data."""
    frame = _frame(pts, resolution_deg, max_distance_km)
    kx, ky, west, south, east, north, width, height = frame
    lon0, lat0, dlon, dlat, nodes = (lattice[k] for k in ("lon0", "lat0", "dlon", "dlat", "nodes"))
    near2 = max_distance_km * max_distance_km
    values: list[list[Optional[float]]] = []
    for row in range(height):
        lat = north - (row + 0.5) * resolution_deg
        fy = (lat - lat0) / dlat
        j0 = math.floor(fy)
        ty = fy - j0
        line: list[Optional[float]] = []
        for col in range(width):
            lon = west + (col + 0.5) * resolution_deg
            fx = (lon - lon0) / dlon
            i0 = math.floor(fx)
            tx = fx - i0
            wsum = vsum = 0.0
            nearest = math.inf
            for (i, j, w) in ((i0, j0, (1 - tx) * (1 - ty)), (i0 + 1, j0, tx * (1 - ty)),
                              (i0, j0 + 1, (1 - tx) * ty), (i0 + 1, j0 + 1, tx * ty)):
                v = nodes.get((i, j))
                if v is None:
                    continue
                d2 = ((lon - (lon0 + i * dlon)) * kx) ** 2 + ((lat - (lat0 + j * dlat)) * ky) ** 2
                nearest = min(nearest, d2)
                wsum += w
                vsum += w * v
            line.append(round(vsum / wsum, 3) if (wsum > 0 and nearest <= near2) else None)
        values.append(line)
    return _result("interpolate", resolution_deg, max_distance_km, frame, values)


def smooth(pts: list, *, resolution_deg: float, sigma_km: float, max_distance_km: float) -> dict:
    """Gaussian-weighted mean of the cells around each pixel (weights normalised, so the value stays in the range of the data and the
    surface does not fade at the edge)."""
    frame = _frame(pts, resolution_deg, max_distance_km)
    kx, ky, west, south, east, north, width, height = frame
    cutoff = 3.0 * sigma_km                                          # weights beyond 3 sigma are negligible
    reach = max(cutoff, max_distance_km)
    bins: dict[tuple[int, int], list[tuple[float, float, float]]] = {}   # spatial hash in km: a pixel only looks at the cells near it
    for lon, lat, v in pts:
        x, y = lon * kx, lat * ky
        bins.setdefault((int(x // reach), int(y // reach)), []).append((x, y, v))
    two_s2 = 2.0 * sigma_km * sigma_km
    cut2, near2 = cutoff * cutoff, max_distance_km * max_distance_km
    values: list[list[Optional[float]]] = []
    for row in range(height):
        y = (north - (row + 0.5) * resolution_deg) * ky
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
    return _result("smooth", resolution_deg, max_distance_km, frame, values, sigma_km=sigma_km)


def build(points: Iterable[tuple[float, float, Optional[float]]], *, method: str = "interpolate", resolution_deg: float = 0.02,
          sigma_km: float = 5.0, max_distance_km: float = 4.0) -> Optional[dict]:
    """points: (lon, lat, H in hours or None). The grid in EPSG:4326 with the hours in `values` (row 0 is the northern edge, None
    outside the data), or None when there are no valid points. `interpolate` falls back to `smooth` when the points are not a lattice."""
    pts = [(lon, lat, float(v)) for lon, lat, v in points if v is not None]
    if not pts:
        return None
    if method == "interpolate":
        lattice = detect_lattice(pts)
        if lattice is not None:
            return interpolate(pts, lattice, resolution_deg=resolution_deg, max_distance_km=max_distance_km)
    return smooth(pts, resolution_deg=resolution_deg, sigma_km=sigma_km, max_distance_km=max_distance_km)


def to_index(values: Sequence[Sequence[Optional[float]]], index_fn: Callable[[Optional[float]], Optional[float]]) -> list:
    """The hours of the grid converted pixel by pixel with the risk index function."""
    return [[None if v is None else index_fn(v) for v in line] for line in values]


# ---------------------------------------------------------------- cache: one computation per day and parameters
_CACHE: "OrderedDict[tuple, dict]" = OrderedDict()
_LOCK = threading.Lock()
_BUILDING: dict[tuple, threading.Lock] = {}
_CACHE_MAX = 24


def cached(key: tuple, builder: Callable[[], Optional[dict]]) -> Optional[dict]:
    """The grid for `key`, built once: when several requests miss at the same moment one builds and the others wait for its result.
    The least recently used entry goes when there are more than 24. The key must contain everything the grid depends on, including a
    fingerprint of the input points."""
    with _LOCK:
        if key in _CACHE:
            _CACHE.move_to_end(key)
            return _CACHE[key]
        lock = _BUILDING.setdefault(key, threading.Lock())
    with lock:
        with _LOCK:
            grid = _CACHE.get(key)
        if grid is None:
            grid = builder()
            if grid is not None:
                with _LOCK:
                    _CACHE[key] = grid
                    while len(_CACHE) > _CACHE_MAX:
                        _CACHE.popitem(last=False)
    with _LOCK:
        _BUILDING.pop(key, None)
    return grid


def fingerprint(points: Sequence[tuple]) -> int:
    """A fingerprint of the input points (their positions and values), so that a cached grid is never used for other data."""
    return hash(tuple(sorted((round(lon, 5), round(lat, 5), v) for lon, lat, v in points)))


# ---------------------------------------------------------------- exports
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


def to_png(index_values: Sequence[Sequence[Optional[float]]]) -> bytes:
    """RGBA PNG of the index grid (row 0 at the top), with the standard library only."""
    height, width = len(index_values), len(index_values[0]) if index_values else 0
    raw = bytearray()
    for line in index_values:
        raw.append(0)                                   # filter type 0 (none) for each scanline
        for v in line:
            raw.extend(colour(v))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)    # 8-bit RGBA
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(bytes(raw), 6)) + chunk(b"IEND", b"")


def to_asc(values: Sequence[Sequence[Optional[float]]], bounds: Sequence[float], resolution_deg: float, decimals: int = 3) -> str:
    """ESRI ASCII Grid (QGIS reads it directly; the CRS is EPSG:4326, set it when asked). Row 0 is the northern edge."""
    west, south = bounds[0], bounds[1]
    head = (f"ncols {len(values[0]) if values else 0}\nnrows {len(values)}\nxllcorner {west}\nyllcorner {south}\n"
            f"cellsize {resolution_deg}\nNODATA_value {ASC_NODATA}\n")
    rows = (" ".join(str(ASC_NODATA) if v is None else f"{v:.{decimals}f}" for v in line) for line in values)
    return head + "\n".join(rows) + "\n"
