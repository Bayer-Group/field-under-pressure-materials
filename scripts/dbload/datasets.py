"""Dataset registry: for each target table, how to discover source units and produce Arrow tables.

Targets are the tables of the `raw` layer (grid_cell, weather_hourly, weather_daily, imerg_daily, soil_h3, cropland_cty)
and the farmer tables (field, field_crop_share). See docker/RAW_SCHEMA.md.
Everything here is engine-free except the raster load: it reads data/raw (and the fields GeoJSON) and yields pyarrow Tables.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

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
    load: Callable[[SourceFile, Context], int] | None = None   # own loading path (rasters): returns the rows written


# ---- helpers: duplicates inside a whole file --------------------------------------------------------------
def _rows_to_skip(path: Path, keys: list[str], ctx: Context, table: str) -> np.ndarray:
    """Row numbers that repeat an earlier key anywhere in the FILE (the first occurrence is kept)."""
    drop = T.duplicate_row_indices(read_parquet_table(path, keys))
    if drop.size:
        ctx.note(table, "duplicate_rows_removed", int(drop.size))
        ctx.log(f"    {path.name}: {drop.size:,} duplicate row(s) on {keys} removed")
    return drop


def _without_rows(tables, drop: np.ndarray) -> Iterator[pa.Table]:
    """Yield the batches with the rows whose global row number is in the sorted array `drop` left out."""
    offset = 0
    for t in tables:
        n = t.num_rows
        if drop.size:
            lo, hi = np.searchsorted(drop, offset), np.searchsorted(drop, offset + n)
            if hi > lo:
                mask = np.ones(n, dtype=bool)
                mask[drop[lo:hi] - offset] = False
                t = t.filter(pa.array(mask))
        offset += n
        yield t


# ---- grid_cell ------------------------------------------------------------------------------------
def d_grid_cell(ctx: Context) -> list[SourceFile]:
    return [SourceFile(p) for p in sorted((ctx.raw / "weather_grids").rglob("*.parquet"))]


def _cell_elevation(ctx: Context) -> dict[str, float]:
    """grid_id -> elevation, read from the daily weather files (the grid file has none); {} when there are none."""
    out: dict[str, float] = {}
    for p in sorted((ctx.raw / "weather_daily").rglob("*.parquet")):
        if "elevation" not in pq.read_schema(p).names:
            continue
        agg = pq.read_table(p, columns=["grid_id", "elevation"]).group_by("grid_id").aggregate([("elevation", "min")])
        out.update(zip(agg["grid_id"].to_pylist(), agg["elevation_min"].to_pylist()))
    return out


def p_grid_cell(u: SourceFile, ctx: Context):
    names = pq.read_schema(u.path).names
    t = T.decimals_to_float(read_parquet_table(u.path, [c for c in ("grid_id", "lat", "lon", "l1_name") if c in names]))
    lat, lon = t["lat"].to_pylist(), t["lon"].to_pylist()
    t = t.append_column("geom", pa.array([T.ewkt_point(x, y) for x, y in zip(lon, lat)], pa.string()))
    t = t.append_column("geohash4", pa.array([T.geohash(y, x, 4) for x, y in zip(lon, lat)], pa.string()))
    elevation = _cell_elevation(ctx)
    if elevation:
        t = t.append_column("elevation", pa.array([elevation.get(g) for g in t["grid_id"].to_pylist()], pa.float64()))
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
        cols, parts = ["grid_id", "utc_time", "precipitation"], []
        for p in files:
            if ctx.s.months and "local_date" in pq.read_schema(p).names:    # same local date as the weather `date`
                part = read_parquet_table(p, cols + ["local_date"])
                part = T.filter_months(part, "local_date", ctx.s.months).drop_columns(["local_date"])
            else:
                part = read_parquet_table(p, cols)
            parts.append(part)
        tbl = pa.concat_tables(parts)
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
    drop = _rows_to_skip(u.path, ["grid_id", "utc_time"], ctx, "weather_hourly")
    for t in _without_rows(iter_parquet_tables(u.path, None, ctx.s.batch_size), drop):
        t = T.drop_cols(t, ("year", "voivodeship"))
        if ctx.s.months:
            t = T.filter_months(t, "date", ctx.s.months)
            if t.num_rows == 0:
                continue
        if precip is not None:
            t = t.join(precip, keys=["grid_id", "utc_time"], join_type="left outer")
        yield t       # columns not in the table (elevation, wind u/v, voivodeship) are dropped by the pipeline


# ---- weather_daily ---------------------------------------------------------------------------------------
def d_weather_daily(ctx: Context) -> list[SourceFile]:
    return discover_parquet(ctx.raw / "weather_daily")


def p_weather_daily(u: SourceFile, ctx: Context):
    drop = _rows_to_skip(u.path, ["grid_id", "date"], ctx, "weather_daily")
    for t in _without_rows(iter_parquet_tables(u.path, None, ctx.s.batch_size), drop):
        t = T.drop_cols(t, ("year", "voivodeship"))
        if ctx.s.months:
            t = T.filter_months(t, "date", ctx.s.months)
            if t.num_rows == 0:
                continue
        yield t       # 'elevation' has no column here (it lives in grid_cell): dropped by the pipeline


# ---- imerg_daily -------------------------------------------------------------------------------------------
def d_imerg_daily(ctx: Context) -> list[SourceFile]:
    return discover_parquet(ctx.raw / "imerg_daily")


def p_imerg_daily(u: SourceFile, ctx: Context):
    t = read_parquet_table(u.path, ["grid_id", "date", "total_precipitation"])
    t, removed = T.dedupe(t, ["grid_id", "date"])
    if removed:
        ctx.note("imerg_daily", "duplicate_rows_removed", removed)
    if ctx.s.months:
        t = T.filter_months(t, "date", ctx.s.months)
    yield from slices(t, ctx.s.batch_size)


# ---- soil_h3: ISRIC SoilGrids, static, one row per H3 level-10 cell -------------------------------------
def d_soil_h3(ctx: Context) -> list[SourceFile]:
    return discover_parquet(ctx.raw / "soil")


def p_soil_h3(u: SourceFile, ctx: Context):
    for t in iter_parquet_tables(u.path, None, ctx.s.batch_size):
        t = T.decimals_to_float(t)
        for col in ("geom", "geom_point"):                      # WKB in the source -> hex EWKB with SRID 4326
            if col in t.column_names:
                t = t.set_column(t.column_names.index(col), col, T.ewkb_hex_column(t[col]))
        t = t.rename_columns(["soil_texture" if c == "soilTexture" else c for c in t.column_names])
        yield t                                                 # BAND_* match band_* case-insensitively


# ---- cropland_cty: CLMS crop types as PostGIS raster tiles ---------------------------------------------
def d_cropland_cty(ctx: Context) -> list[SourceFile]:
    units = []
    for yd in sorted((ctx.raw / "cropland").glob("year=*")):
        if not yd.name[5:].isdigit():
            continue
        for tif in sorted(yd.glob("*.tif")):
            m = re.search(r"_(\d+)\.tif$", tif.name)
            tile_no = int(m.group(1)) if m else None
            if ctx.s.tiles and tile_no not in ctx.s.tiles:
                continue
            units.append(SourceFile(tif, year=int(yd.name[5:]), extra={"tile": tile_no}))
    return units


def _compressed_geotiff_bytes(path: Path) -> bytes:
    """The tile as a tiled, losslessly compressed (DEFLATE) GeoTIFF in memory: 150-250 MB become 2-6 MB."""
    import rasterio
    from rasterio.io import MemoryFile
    with rasterio.open(path) as src:
        if src.count != 1:
            raise ValueError(f"{path.name}: expected one band, found {src.count}")
        profile, data = src.profile, src.read(1)
    profile.update(driver="GTiff", compress="deflate", tiled=True, blockxsize=256, blockysize=256, predictor=1)
    with MemoryFile() as mem:
        with mem.open(**profile) as dst:
            dst.write(data, 1)
        return mem.read()


def l_cropland_cty(u: SourceFile, ctx: Context) -> int:
    """Send the compressed tile as bytes; the server converts it to 256x256 raster tiles (no files, no raster2pgsql)."""
    b = ctx.backend
    payload = _compressed_geotiff_bytes(u.path)
    ctx.log(f"    {u.path.name}: {len(payload) / 2**20:.1f} MB compressed")
    b.execute("SET postgis.gdal_enabled_drivers = 'GTiff'")
    rows = b.query(
        f"WITH ins AS (INSERT INTO {b.tq('cropland_cty')} (tile, year, rast) "
        "SELECT ?::text, ?::int, ST_Tile(ST_FromGDALRaster(?::bytea), 256, 256, false) RETURNING 1) "
        "SELECT COUNT(*) FROM ins", (u.path.name, u.year, payload))
    return int(rows[0][0])


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
_CELL_CHILDREN = ("weather_hourly", "weather_daily", "imerg_daily")
REGISTRY: dict[str, DatasetSpec] = {s.table: s for s in [
    DatasetSpec("grid_cell", d_grid_cell, p_grid_cell, dependents=_CELL_CHILDREN),
    DatasetSpec("weather_hourly", d_weather_hourly, p_weather_hourly, depends_on=("grid_cell",)),
    DatasetSpec("weather_daily", d_weather_daily, p_weather_daily, depends_on=("grid_cell",)),
    DatasetSpec("imerg_daily", d_imerg_daily, p_imerg_daily, depends_on=("grid_cell",)),
    DatasetSpec("soil_h3", d_soil_h3, p_soil_h3),
    DatasetSpec("cropland_cty", d_cropland_cty, lambda u, ctx: iter(()), load=l_cropland_cty),
    DatasetSpec("field", d_field, p_field, dependents=("field_crop_share",)),
    DatasetSpec("field_crop_share", d_field_crop_share, p_field_crop_share, depends_on=("field",)),
]}
