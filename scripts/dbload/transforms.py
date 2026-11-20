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


def dedupe(t: pa.Table, keys: list[str]) -> tuple[pa.Table, int]:
    """Keep the first row per key. Returns (table, rows_removed)."""
    n = t.num_rows
    if n == 0:
        return t, 0
    probe = t.select(keys).append_column("__i", pa.array(np.arange(n, dtype=np.int64)))
    agg = probe.group_by(keys, use_threads=False).aggregate([("__i", "min")])
    if agg.num_rows == n:
        return t, 0
    first = np.sort(agg["__i_min"].to_numpy())
    return t.take(pa.array(first)), n - agg.num_rows
