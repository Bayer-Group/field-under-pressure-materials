"""Pure Arrow -> Arrow transforms (no database, no file I/O)."""
from __future__ import annotations

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.types as pat

_B32 = "0123456789bcdefghjkmnpqrstuvwxyz"


def geohash(lat: float, lon: float, precision: int = 4) -> str:
    """Standard geohash (base32, longitude bit first)."""
    lat_lo, lat_hi, lon_lo, lon_hi = -90.0, 90.0, -180.0, 180.0
    out, bits, bit, even = [], 0, 0, True
    while len(out) < precision:
        if even:
            mid = (lon_lo + lon_hi) / 2
            if lon >= mid:
                bits, lon_lo = bits * 2 + 1, mid
            else:
                bits, lon_hi = bits * 2, mid
        else:
            mid = (lat_lo + lat_hi) / 2
            if lat >= mid:
                bits, lat_lo = bits * 2 + 1, mid
            else:
                bits, lat_hi = bits * 2, mid
        even = not even
        bit += 1
        if bit == 5:
            out.append(_B32[bits])
            bits, bit = 0, 0
    return "".join(out)


def ewkt_point(lon: float, lat: float) -> str:
    return f"SRID=4326;POINT({lon:.9f} {lat:.9f})"


def drop_cols(t: pa.Table, names) -> pa.Table:
    return t.drop_columns([n for n in names if n in t.column_names])


def decimals_to_float(t: pa.Table) -> pa.Table:
    for i, f in enumerate(t.schema):
        if pat.is_decimal(f.type):
            t = t.set_column(i, f.name, t.column(i).cast(pa.float64()))
    return t


def filter_months(t: pa.Table, date_col: str, months: set[int]) -> pa.Table:
    return t.filter(pc.is_in(pc.month(t[date_col]), value_set=pa.array(sorted(months), pa.int64())))


def _key_codes(col) -> np.ndarray:
    """A key column as int64 codes (equal values <-> equal codes; NULL gets its own code)."""
    col = col.combine_chunks() if isinstance(col, pa.ChunkedArray) else col
    if pat.is_string(col.type) or pat.is_large_string(col.type):
        col = col.dictionary_encode().indices
    elif pat.is_date32(col.type):
        col = col.cast(pa.int32())
    elif pat.is_temporal(col.type):
        col = col.cast(pa.int64())
    return col.fill_null(-1).to_numpy(zero_copy_only=False).astype(np.int64, copy=False)


def duplicate_row_indices(keys: pa.Table) -> np.ndarray:
    """0-based numbers of the rows that repeat an earlier key (the first occurrence is kept).

    Works on the key columns only (a stable sort of int64 codes, a few hundred MB for 10 million rows), so a big
    file can be checked without reading its other columns."""
    n = keys.num_rows
    if n < 2:
        return np.empty(0, dtype=np.int64)
    cols = [_key_codes(keys[c]) for c in keys.column_names]
    order = np.lexsort(tuple(reversed(cols)))                 # stable: equal keys stay in file order
    same = np.ones(n - 1, dtype=bool)
    for c in cols:
        s = c[order]
        same &= s[1:] == s[:-1]
    return np.sort(order[np.flatnonzero(same) + 1])


def wkb_to_ewkb_hex(wkb: bytes | None, srid: int = 4326) -> str | None:
    """WKB bytes -> hex EWKB with an SRID, the text form PostGIS accepts in COPY for a typed geometry column."""
    if wkb is None:
        return None
    order = "little" if wkb[0] == 1 else "big"
    gtype = int.from_bytes(wkb[1:5], order)
    if gtype & 0x20000000:                                   # already carries an SRID
        return wkb.hex()
    return (wkb[:1] + (gtype | 0x20000000).to_bytes(4, order) + srid.to_bytes(4, order) + wkb[5:]).hex()


def ewkb_hex_column(col, srid: int = 4326) -> pa.Array:
    return pa.array([wkb_to_ewkb_hex(v, srid) for v in col.to_pylist()], pa.string())


def dedupe(t: pa.Table, keys: list[str]) -> tuple[pa.Table, int]:
    """Keep the first row per key. Returns (table, rows_removed)."""
    drop = duplicate_row_indices(t.select(keys))
    if not drop.size:
        return t, 0
    keep = np.ones(t.num_rows, dtype=bool)
    keep[drop] = False
    return t.filter(pa.array(keep)), int(drop.size)
