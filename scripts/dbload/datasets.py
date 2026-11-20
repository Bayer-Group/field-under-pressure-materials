"""Dataset registry: for each target table, how to discover source units and produce Arrow tables.

Targets are the tables of the `fup` DDL: grid_cell, weather_hourly, field, field_crop_share.
Everything here is engine-free: it reads data/raw (and the fields GeoJSON) and yields pyarrow Tables.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

import pyarrow as pa

from . import transforms as T
from .config import Settings
from .fields import Field, load_fields
from .raster_agg import field_class_counts
from .readers import iter_parquet_tables, read_parquet_table, slices
from .sources import SourceFile, apply_filters, discover_parquet, parse_parquet_path


class Context:
    """Shared state for one run: settings, backend (for reading crop_class), caches, stats."""

    def __init__(self, settings: Settings, backend=None, log=print):
        self.s = settings
        self.backend = backend
        self.log = log
        self.stats: dict[str, dict] = {}
        self.cache: dict = {}
        self._fields: list[Field] | None = None

    @property
    def raw(self) -> Path:
        return self.s.raw

    def note(self, table: str, key: str, value=1) -> None:
        d = self.stats.setdefault(table, {})
        d[key] = d.get(key, 0) + value

    def fields(self) -> list[Field]:
        if self._fields is None:
            self._fields = load_fields(self.s.fields) if self.s.fields else []
        return self._fields


@dataclass
class DatasetSpec:
    table: str
    discover: Callable[[Context], list[SourceFile]]
    produce: Callable[[SourceFile, Context], Iterator[pa.Table]]
    depends_on: tuple[str, ...] = ()
    dependents: tuple[str, ...] = ()       # tables whose ingest_log entries become stale on --mode replace


# ---- grid_cell ------------------------------------------------------------------------------------
def d_grid_cell(ctx: Context) -> list[SourceFile]:
    return [SourceFile(p) for p in sorted((ctx.raw / "weather_grids").rglob("*.parquet"))]


def p_grid_cell(u: SourceFile, ctx: Context):
    t = T.decimals_to_float(read_parquet_table(u.path, ["grid_id", "lat", "lon"]))
    lat, lon = t["lat"].to_pylist(), t["lon"].to_pylist()
    t = t.append_column("geom", pa.array([T.ewkt_point(x, y) for x, y in zip(lon, lat)], pa.string()))
    t = t.append_column("geohash4", pa.array([T.geohash(y, x, 4) for x, y in zip(lon, lat)], pa.string()))
    yield t                      # time_zone: not in the source, left NULL


# ---- weather_hourly: ERA5 hourly + IMERG precipitation ----------------------------------------------
def d_weather_hourly(ctx: Context) -> list[SourceFile]:
    return discover_parquet(ctx.raw / "weather_hourly")


def _imerg_hourly(ctx: Context, year, voiv) -> pa.Table | None:
    """(grid_id, utc_time, precipitation) for one year + voivodeship; None if there is no IMERG file."""
    key = ("imerg", year, voiv)
    if key in ctx.cache:
        return ctx.cache[key]
    ctx.cache.clear()                                        # keep at most one (it is ~300 MB)
    files = [p for p in sorted((ctx.raw / "imerg_hourly").rglob("*.parquet"))
             if parse_parquet_path(p) == (year, voiv)]
    tbl = None
    if files:
        tbl = pa.concat_tables([read_parquet_table(p, ["grid_id", "utc_time", "precipitation"]) for p in files])
        tbl, removed = T.dedupe(tbl, ["grid_id", "utc_time"])   # a join would multiply duplicated keys
        if removed:
            ctx.note("weather_hourly", "imerg_duplicate_rows_removed", removed)
    ctx.cache[key] = tbl
    return tbl


def p_weather_hourly(u: SourceFile, ctx: Context):
    precip = _imerg_hourly(ctx, u.year, u.voivodeship)
    if precip is None:
        ctx.log(f"    no IMERG hourly file for {u.year}/{u.voivodeship}: precipitation stays NULL")
        ctx.note("weather_hourly", "units_without_precipitation")
    for t in iter_parquet_tables(u.path, None, ctx.s.batch_size):
        t = T.drop_cols(t, ("year", "voivodeship"))
        if ctx.s.months:
            t = T.filter_months(t, "date", ctx.s.months)
            if t.num_rows == 0:
                continue
        if precip is not None:
            t = t.join(precip, keys=["grid_id", "utc_time"], join_type="left outer")
        yield t       # columns not in the table (elevation, wind u/v, voivodeship) are dropped by the pipeline


# ---- field / field_crop_share -------------------------------------------------------------------------
def d_field(ctx: Context) -> list[SourceFile]:
    return [SourceFile(ctx.s.fields)] if ctx.s.fields else []


def p_field(u: SourceFile, ctx: Context):
    fs = ctx.fields()
    yield pa.table({
        "field_id": pa.array([f.field_id for f in fs], pa.string()),
        "name": pa.array([f.name for f in fs], pa.string()),
        "source": pa.array([ctx.s.fields_source or u.path.name] * len(fs), pa.string()),
        "geom": pa.array([f.ewkt for f in fs], pa.string()),
    })


def d_field_crop_share(ctx: Context) -> list[SourceFile]:
    if not ctx.s.fields:
        return []
    units = []
    for yd in sorted((ctx.raw / "cropland").glob("year=*")):
        tifs = sorted(yd.glob("*.tif"))
        if tifs and yd.name[5:].isdigit():
            units.append(SourceFile(yd, year=int(yd.name[5:]), paths=tuple(tifs)))
    return units


def p_field_crop_share(u: SourceFile, ctx: Context):
    fields = ctx.fields()
    valid = None
    if ctx.backend is not None:
        valid = {int(r[0]) for r in ctx.backend.query(f"SELECT code FROM {ctx.backend.tq('crop_class')}")}
    counts = field_class_counts(list(u.files()), fields, ctx.log)
    ids, codes, pix, share, unknown = [], [], [], [], 0
    for fid, ctr in counts.items():
        total = sum(ctr.values())
        for code, n in sorted(ctr.items()):
            if valid is not None and code not in valid:
                unknown += n
                continue                                     # would violate the FK to crop_class
            ids.append(fid); codes.append(code); pix.append(n); share.append(n / total)
    if unknown:
        ctx.log(f"    WARNING: {unknown:,} pixels have class codes missing from crop_class (not stored)")
        ctx.note("field_crop_share", "pixels_with_unknown_class", unknown)
    missing = [f.field_id for f in fields if f.field_id not in counts]
    if missing:
        ctx.log(f"    note: {len(missing)} field(s) fall outside the {u.year} cropland tiles: {missing[:5]}")
    n = len(ids)
    t = pa.table({"field_id": pa.array(ids, pa.string()), "year": pa.array([u.year] * n, pa.int32()),
                  "class_code": pa.array(codes, pa.int32()), "pixel_count": pa.array(pix, pa.int64()),
                  "share": pa.array(share, pa.float64())})
    yield from slices(t, ctx.s.batch_size)


# ---- registry (order = default load order) ----------------------------------------------------------------
REGISTRY: dict[str, DatasetSpec] = {s.table: s for s in [
    DatasetSpec("grid_cell", d_grid_cell, p_grid_cell, dependents=("weather_hourly",)),
    DatasetSpec("weather_hourly", d_weather_hourly, p_weather_hourly, depends_on=("grid_cell",)),
    DatasetSpec("field", d_field, p_field, dependents=("field_crop_share",)),
    DatasetSpec("field_crop_share", d_field_crop_share, p_field_crop_share, depends_on=("field",)),
]}
