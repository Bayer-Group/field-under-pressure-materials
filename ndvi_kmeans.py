from __future__ import annotations

from contextlib import ExitStack
import json
import os
from pathlib import Path
import sys
from typing import Iterable


def _sanitize_proj_env() -> None:
    """Clear external PROJ_LIB/PROJ_DATA so venv wheels use their bundled proj.db"""
    prefix = Path(sys.prefix).resolve()
    for var in ("PROJ_LIB", "PROJ_DATA"):
        val = os.environ.get(var)
        if not val:
            continue
        try:
            if not Path(val).resolve().is_relative_to(prefix):
                os.environ.pop(var, None)
        except OSError:
            os.environ.pop(var, None)


_sanitize_proj_env()

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import duckdb
import geopandas as gpd
import h3
import joblib
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from pyproj import Transformer
import rasterio
from rasterio.enums import Resampling
from rasterio.errors import WindowError
from rasterio.features import geometry_mask, geometry_window, shapes
from rasterio.vrt import WarpedVRT
from rasterio.warp import reproject
from rasterio.windows import Window
from scipy.ndimage import binary_dilation, find_objects, label as nd_label
from shapely.geometry import mapping, shape
from shapely.ops import unary_union
import sklearn
from sklearn.cluster import KMeans
from sklearn.metrics import (
    adjusted_rand_score,
    calinski_harabasz_score,
    cohen_kappa_score,
    confusion_matrix,
    davies_bouldin_score,
    normalized_mutual_info_score,
    silhouette_score,
)

from kw.soil import (
    _compute_saxton_rawls_2006,
    _geom_to_h3_cells,
    _prepare_geodataframe,
    _query_soil_for_h3_mapping,
    ensure_parquets_unpacked,
)

ZONE_LABELS_3 = {
    1: "slaba",
    2: "srednia",
    3: "mocna",
}

_STRUCT4 = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], dtype=bool)


def _zone_label(zone_id: int, n_clusters: int) -> str:
    if n_clusters == 3 and zone_id in ZONE_LABELS_3:
        return ZONE_LABELS_3[zone_id]
    return f"strefa_{zone_id}"


# ==============================================================================
# 1. POLA I EKSTRAKCJA CECH Z RASTROW NDVI
# ==============================================================================


def load_fields(boundary_file: str | Path, min_area_ha: float = 3.0) -> gpd.GeoDataFrame:
    """Load field boundaries via kw.soil._prepare_geodataframe and filter by min_area_ha."""
    gdf = gpd.read_file(boundary_file)
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
    if gdf.empty:
        return gdf.assign(field_id=pd.Series(dtype=int), area_ha=pd.Series(dtype=float))

    if "field_id" not in gdf.columns:
        gdf["field_id"] = np.arange(1, len(gdf) + 1, dtype=int)

    gdf = _prepare_geodataframe(gdf)
    return gdf[gdf["area_ha"] >= min_area_ha].reset_index(drop=True)


def _load_raster_paths(ndvi_dir: str | Path) -> list[Path]:
    ndvi_path = Path(ndvi_dir)
    raster_paths = sorted(
        list(ndvi_path.glob("*.tif")) + list(ndvi_path.glob("*.tiff"))
    )
    if not raster_paths:
        raise FileNotFoundError(
            f"Nie znaleziono plikow GeoTIFF (*.tif) w katalogu: {ndvi_path}"
        )
    return raster_paths


def normalize_ndvi_zscore(
    arr: np.ndarray,
    valid_mask: np.ndarray,
    clip_limit: float | None = 3.0,
) -> np.ndarray | None:
    """Compute per-field robust z-score (median + MAD) over valid pixels."""
    if int(np.sum(valid_mask)) == 0:
        return None

    vals = arr[valid_mask].astype(np.float64)
    median = float(np.median(vals))
    mad = float(np.median(np.abs(vals - median)))
    scale = 1.4826 * mad

    if not np.isfinite(scale) or scale < 1e-6:
        return None

    z_vals = (vals - median) / scale
    if clip_limit is not None:
        z_vals = np.clip(z_vals, -clip_limit, clip_limit)

    z = np.full(arr.shape, np.nan, dtype=np.float32)
    z[valid_mask] = z_vals.astype(np.float32)
    return z


def _establish_reference_grid_from_datasets(
    field_geom_wgs84,
    datasets: list[rasterio.DatasetReader],
    inner_buffer_m: float,
    geom_by_crs: dict[str, object] | None = None,
):
    """Find first overlapping opened raster and build the clipped reference grid and mask."""
    geom_series_wgs84 = None

    for src in datasets:
        if src.crs is None:
            continue
        ref_crs = src.crs
        crs_key = ref_crs.to_string()
        if geom_by_crs is not None and crs_key in geom_by_crs:
            geom_utm = geom_by_crs[crs_key]
        else:
            if geom_series_wgs84 is None:
                geom_series_wgs84 = gpd.GeoSeries([field_geom_wgs84], crs="EPSG:4326")
            geom_utm = geom_series_wgs84.to_crs(ref_crs).iloc[0]

        buffered = geom_utm.buffer(-inner_buffer_m) if inner_buffer_m > 0 else geom_utm
        if buffered.is_empty or buffered.area <= 0:
            buffered = geom_utm
        if not buffered.is_valid:
            buffered = buffered.buffer(0)

        geom_iface = [mapping(buffered)]
        try:
            win = geometry_window(src, geom_iface)
        except (WindowError, ValueError):
            continue

        ref_height, ref_width = int(win.height), int(win.width)
        if ref_height <= 0 or ref_width <= 0:
            continue
        ref_transform = src.window_transform(win)

        in_field_mask = geometry_mask(
            geom_iface,
            out_shape=(ref_height, ref_width),
            transform=ref_transform,
            invert=True,
        )
        if not np.any(in_field_mask):
            in_field_mask = geometry_mask(
                geom_iface,
                out_shape=(ref_height, ref_width),
                transform=ref_transform,
                invert=True,
                all_touched=True,
            )
        return ref_crs, ref_transform, ref_height, ref_width, in_field_mask

    return None


def _read_aligned_band(
    src: rasterio.DatasetReader,
    ref_crs,
    ref_transform,
    ref_height: int,
    ref_width: int,
) -> np.ndarray:
    """Read band 1 aligned to the reference grid using a direct window read when aligned."""
    if (
        src.crs == ref_crs
        and np.issubdtype(np.dtype(src.dtypes[0]), np.floating)
        and src.transform.b == 0
        and src.transform.d == 0
        and ref_transform.b == 0
        and ref_transform.d == 0
        and np.isclose(src.transform.a, ref_transform.a)
        and np.isclose(src.transform.e, ref_transform.e)
    ):
        col_off_f = (ref_transform.c - src.transform.c) / src.transform.a
        row_off_f = (ref_transform.f - src.transform.f) / src.transform.e
        col_off, row_off = int(round(col_off_f)), int(round(row_off_f))
        if abs(col_off_f - col_off) < 1e-6 and abs(row_off_f - row_off) < 1e-6:
            win = Window(col_off, row_off, ref_width, ref_height)
            in_bounds = (
                col_off >= 0
                and row_off >= 0
                and col_off + ref_width <= src.width
                and row_off + ref_height <= src.height
            )
            arr = src.read(
                1,
                window=win,
                boundless=not in_bounds,
                fill_value=np.nan if not in_bounds else None,
            ).astype(np.float32)
            src_nodata = src.nodata
            if src_nodata is not None and np.isfinite(src_nodata):
                arr[arr == np.float32(src_nodata)] = np.nan
            return arr

    with WarpedVRT(
        src,
        crs=ref_crs,
        transform=ref_transform,
        width=ref_width,
        height=ref_height,
        resampling=Resampling.nearest,
    ) as vrt:
        arr = vrt.read(1).astype(np.float32)
        src_nodata = vrt.nodata
    if src_nodata is not None and np.isfinite(src_nodata):
        arr[arr == np.float32(src_nodata)] = np.nan
    return arr


def _compute_field_zscore_from_datasets(
    field_geom_wgs84,
    datasets: list[rasterio.DatasetReader],
    inner_buffer_m: float = 10.0,
    min_valid_pixels: int = 15,
    geom_by_crs: dict[str, object] | None = None,
) -> tuple[np.ndarray | None, dict | None]:
    """Compute per-field z-score temporal median NDVI from already-opened datasets."""
    if not datasets:
        return None, None

    grid = _establish_reference_grid_from_datasets(
        field_geom_wgs84, datasets, inner_buffer_m, geom_by_crs=geom_by_crs
    )
    if grid is None:
        return None, None

    ref_crs, ref_transform, ref_height, ref_width, in_field_mask = grid
    z_scenes: list[np.ndarray] = []

    for src in datasets:
        if src.crs is None:
            continue
        arr = _read_aligned_band(src, ref_crs, ref_transform, ref_height, ref_width)
        arr[~in_field_mask] = np.nan
        valid_mask = in_field_mask & np.isfinite(arr)
        if int(np.sum(valid_mask)) < min_valid_pixels:
            continue

        z = normalize_ndvi_zscore(arr, valid_mask)
        if z is not None:
            z_scenes.append(z)

    if not z_scenes:
        return None, None

    stack = np.stack(z_scenes, axis=0)
    any_valid = in_field_mask & np.any(np.isfinite(stack), axis=0)
    median_z = np.full((ref_height, ref_width), np.nan, dtype=np.float32)
    if np.any(any_valid):
        median_z[any_valid] = np.nanmedian(stack[:, any_valid], axis=0).astype(
            np.float32
        )
    median_z[~in_field_mask] = np.nan

    meta = {
        "crs": ref_crs,
        "transform": ref_transform,
        "height": ref_height,
        "width": ref_width,
        "n_scenes_used": len(z_scenes),
    }
    return median_z, meta


def compute_field_zscore_median(
    field_geom_wgs84,
    raster_paths: Iterable[str | Path],
    inner_buffer_m: float = 10.0,
    min_valid_pixels: int = 15,
) -> tuple[np.ndarray | None, dict | None]:
    """Normalize each NDVI scene via per-field z-score and return temporal median."""
    paths = [Path(p) for p in raster_paths]
    if not paths:
        return None, None

    with ExitStack() as stack:
        datasets = [stack.enter_context(rasterio.open(p)) for p in paths]
        return _compute_field_zscore_from_datasets(
            field_geom_wgs84=field_geom_wgs84,
            datasets=datasets,
            inner_buffer_m=inner_buffer_m,
            min_valid_pixels=min_valid_pixels,
        )


# ==============================================================================
# 2. GLEBA PODPOLOWA AWC (H3 POZIOM 10) PRZEZ KW.SOIL / KW.SOIL_AWS
# ==============================================================================


def load_h3_awc_lookup(
    soil_source: str | Path,
    fields_wgs84: gpd.GeoDataFrame | None = None,
    env_path: str | Path = ".env",
) -> dict[str, float]:
    """Load native H3 level 10 awc_mm_per_m lookup without aggregating to fields."""
    source_str = str(soil_source)
    source_path = Path(soil_source)

    if source_path.is_file() and source_path.suffix.lower() == ".parquet":
        schema_cols = set(pq.read_schema(source_path).names)
        if {"h3_index_10", "awc_mm_per_m"}.issubset(schema_cols):
            df = pd.read_parquet(
                source_path, columns=["h3_index_10", "awc_mm_per_m"]
            ).dropna(subset=["h3_index_10", "awc_mm_per_m"])
            df["h3_index_10"] = df["h3_index_10"].astype(str).str.strip().str.lower()
            grouped = df.groupby("h3_index_10", as_index=True)["awc_mm_per_m"].mean()
            return {str(idx): float(val) for idx, val in grouped.items()}

    if source_str.lower() == "aws":
        if fields_wgs84 is None or fields_wgs84.empty:
            raise ValueError("soil_source='aws' wymaga podania niepustej warstwy pol.")
        from kw.soil_aws import ensure_aws_soil_parquets

        bounds = tuple(map(float, fields_wgs84.total_bounds))
        parquet_files = ensure_aws_soil_parquets(bounds=bounds, env_path=env_path)
    elif source_path.is_file() and source_path.suffix.lower() == ".parquet":
        parquet_files = [source_path.as_posix()]
    elif source_path.is_dir():
        parquet_files = sorted(
            p.as_posix()
            for p in source_path.rglob("*.parquet")
            if not p.name.startswith("._")
        )
        if not parquet_files:
            parquet_files = ensure_parquets_unpacked(source_path)
    else:
        raise FileNotFoundError(f"Nieprawidlowe zrodlo gleby: {soil_source}")

    if fields_wgs84 is not None and not fields_wgs84.empty:
        candidate_cells = sorted(
            {
                nbr
                for geom in fields_wgs84.geometry
                for cell in _geom_to_h3_cells(geom)
                for nbr in h3.grid_disk(cell, 1)
            }
        )
        if not candidate_cells:
            return {}
        cells_df = _query_soil_for_h3_mapping(
            pd.DataFrame({"h3_index_10": candidate_cells}),
            ["h3_index_10"],
            parquet_files,
        )
    else:
        con = duckdb.connect()
        cells_df = con.execute(
            """
            SELECT
                LOWER(TRIM(CAST(s.h3_index_10 AS VARCHAR))) AS h3_index_10,
                ROUND(CASE WHEN AVG(s.sand) <= 1.0 THEN AVG(s.sand) * 100.0 ELSE AVG(s.sand) END, 1) AS sand_pct,
                ROUND(CASE WHEN AVG(s.clay) <= 1.0 THEN AVG(s.clay) * 100.0 ELSE AVG(s.clay) END, 1) AS clay_pct,
                ROUND(AVG(s.om), 2) AS om
            FROM read_parquet($1) s
            GROUP BY LOWER(TRIM(CAST(s.h3_index_10 AS VARCHAR)))
            """,
            [parquet_files],
        ).df()

    if cells_df.empty:
        return {}

    _, _, awc = _compute_saxton_rawls_2006(
        cells_df["sand_pct"], cells_df["clay_pct"], cells_df["om"]
    )
    return {
        str(cell): float(val)
        for cell, val in zip(cells_df["h3_index_10"], awc)
        if np.isfinite(val)
    }


def build_field_awc_grid(
    valid_mask: np.ndarray,
    transform,
    raster_crs,
    awc_lookup: dict[str, float],
    transformer_cache: dict | None = None,
) -> np.ndarray:
    """Map each valid 10 m pixel directly to its native H3 level 10 awc_mm_per_m."""
    awc_grid = np.full(valid_mask.shape, np.nan, dtype=np.float32)
    rs, cs = np.where(valid_mask)
    if rs.size == 0 or not awc_lookup:
        return awc_grid

    crs_key = str(raster_crs)
    tf = transformer_cache.get(crs_key) if transformer_cache is not None else None
    if tf is None:
        tf = Transformer.from_crs(raster_crs, "EPSG:4326", always_xy=True)
        if transformer_cache is not None:
            transformer_cache[crs_key] = tf

    xs, ys = rasterio.transform.xy(transform, rs, cs)
    lons, lats = tf.transform(xs, ys)
    cell_cache: dict[str, float | None] = {}

    for r, c, lat, lon in zip(rs, cs, lats, lons):
        cell = h3.latlng_to_cell(float(lat), float(lon), 10)
        if cell not in cell_cache:
            val = awc_lookup.get(cell)
            if val is None:
                for ring in (1, 2):
                    nbrs = [
                        awc_lookup[n] for n in h3.grid_disk(cell, ring) if n in awc_lookup
                    ]
                    if nbrs:
                        val = float(np.mean(nbrs))
                        break
            cell_cache[cell] = val
        else:
            val = cell_cache[cell]

        if val is not None:
            awc_grid[r, c] = np.float32(val)

    return awc_grid


def normalize_awc_grid(
    awc_grid: np.ndarray,
    valid_mask: np.ndarray,
    mode: str = "within_field",
    min_std: float = 2.5,
    global_mean: float | None = None,
    global_std: float | None = None,
) -> np.ndarray:
    """Normalize per-pixel AWC values for 2D K-Means clustering."""
    mask = valid_mask & np.isfinite(awc_grid)
    awc_z = np.full(awc_grid.shape, np.nan, dtype=np.float32)
    if not np.any(mask):
        return awc_z

    vals = awc_grid[mask].astype(np.float64)
    if mode == "within_field":
        mean = float(np.mean(vals))
        denom = max(float(np.std(vals)), float(min_std))
    elif mode == "global":
        if global_mean is None or global_std is None:
            raise ValueError("Tryb awc_norm='global' wymaga global_mean i global_std.")
        mean = float(global_mean)
        denom = max(float(global_std), 1e-6)
    else:
        raise ValueError(f"Nieznany tryb normalizacji AWC: {mode}")

    awc_z[mask] = ((vals - mean) / denom).astype(np.float32)
    return awc_z


def build_feature_matrix(
    median_z: np.ndarray,
    awc_z: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Construct 1D (ndvi_z) or 2D (ndvi_z, awc_z) KMeans feature matrix."""
    mask = np.isfinite(median_z)
    if awc_z is None:
        return median_z[mask].reshape(-1, 1).astype(np.float32), mask

    awc_vals = awc_z[mask].astype(np.float32)
    awc_filled = np.where(np.isfinite(awc_vals), awc_vals, 0.0).astype(np.float32)
    return np.column_stack([median_z[mask], awc_filled]).astype(np.float32), mask


def _compute_all_field_features(
    fields_wgs84: gpd.GeoDataFrame,
    raster_paths: list[Path],
    inner_buffer_m: float,
    awc_lookup: dict[str, float] | None = None,
    awc_norm: str = "within_field",
    awc_min_std: float = 2.5,
) -> tuple[list[tuple[int | str, np.ndarray, np.ndarray | None, np.ndarray | None, dict]], dict]:
    """Compute per-field NDVI z-score median and optional pixel-level H3 AWC features."""
    global_mean: float | None = None
    global_std: float | None = None
    if awc_lookup and awc_norm == "global":
        vals = np.fromiter(awc_lookup.values(), dtype=np.float64)
        global_mean = float(np.mean(vals))
        global_std = float(np.std(vals))

    results: list[
        tuple[int | str, np.ndarray, np.ndarray | None, np.ndarray | None, dict]
    ] = []
    transformer_cache: dict = {}
    skipped_ids: list[int | str] = []

    with ExitStack() as stack:
        datasets = [stack.enter_context(rasterio.open(p)) for p in raster_paths]
        crs_geoms: dict[str, list] = {}
        for src in datasets:
            if src.crs is not None:
                key = src.crs.to_string()
                if key not in crs_geoms:
                    crs_geoms[key] = list(fields_wgs84.to_crs(src.crs).geometry)

        for idx, row in enumerate(fields_wgs84.itertuples()):
            field_id = row.field_id
            geom_by_crs = {k: geoms[idx] for k, geoms in crs_geoms.items()}
            median_z, meta = _compute_field_zscore_from_datasets(
                row.geometry,
                datasets=datasets,
                inner_buffer_m=inner_buffer_m,
                geom_by_crs=geom_by_crs,
            )
            if median_z is None or meta is None:
                skipped_ids.append(field_id)
                continue

            awc_grid: np.ndarray | None = None
            awc_z: np.ndarray | None = None
            if awc_lookup is not None:
                valid_mask = np.isfinite(median_z)
                awc_grid = build_field_awc_grid(
                    valid_mask=valid_mask,
                    transform=meta["transform"],
                    raster_crs=meta["crs"],
                    awc_lookup=awc_lookup,
                    transformer_cache=transformer_cache,
                )
                awc_z = normalize_awc_grid(
                    awc_grid=awc_grid,
                    valid_mask=valid_mask,
                    mode=awc_norm,
                    min_std=awc_min_std,
                    global_mean=global_mean,
                    global_std=global_std,
                )

            results.append((field_id, median_z, awc_grid, awc_z, meta))

    if skipped_ids:
        print(f"Pominieto {len(skipped_ids)} pol bez wystarczajacych pikseli NDVI.")

    awc_meta: dict = {}
    if awc_lookup is not None:
        awc_meta = {
            "awc_unit": "h3_index_10",
            "awc_norm": awc_norm,
            "awc_min_std": float(awc_min_std),
        }
        if global_mean is not None and global_std is not None:
            awc_meta["awc_global_mean"] = round(global_mean, 4)
            awc_meta["awc_global_std"] = round(global_std, 4)

    return results, awc_meta


def _prepare_field_features(
    boundary_file: str | Path,
    ndvi_dir: str | Path,
    inner_buffer_m: float,
    min_area_ha: float,
    soil_source: str | Path | None,
    awc_norm: str,
    awc_min_std: float,
    env_path: str | Path,
):
    raster_paths = _load_raster_paths(ndvi_dir)
    fields_wgs84 = load_fields(boundary_file, min_area_ha=min_area_ha)
    awc_lookup = (
        load_h3_awc_lookup(soil_source, fields_wgs84=fields_wgs84, env_path=env_path)
        if soil_source is not None
        else None
    )
    field_features, awc_meta = _compute_all_field_features(
        fields_wgs84=fields_wgs84,
        raster_paths=raster_paths,
        inner_buffer_m=inner_buffer_m,
        awc_lookup=awc_lookup,
        awc_norm=awc_norm,
        awc_min_std=awc_min_std,
    )
    return raster_paths, awc_lookup, field_features, awc_meta


# ==============================================================================
# 3. KLASTERYZACJA K-MEANS, ZAPIS MODELU I PREDYKCJA STREF
# ==============================================================================


def majority_filter_zones(zones: np.ndarray, size: int = 3) -> np.ndarray:
    """Apply a modal filter over valid zone pixels (> 0), ignoring nodata (0)."""
    if size < 1 or size % 2 == 0:
        raise ValueError("Filter size must be a positive odd integer.")

    max_class = int(zones.max())
    if size == 1 or max_class == 0:
        return zones.copy()

    pad = size // 2
    padded = np.pad(zones, pad_width=pad, mode="constant", constant_values=0)
    windows = np.lib.stride_tricks.sliding_window_view(padded, (size, size)).reshape(
        zones.shape[0], zones.shape[1], size * size
    )

    counts = np.stack(
        [(windows == c).sum(axis=-1) for c in range(1, max_class + 1)], axis=-1
    )
    max_counts = counts.max(axis=-1)
    best = (counts.argmax(axis=-1) + 1).astype(zones.dtype)

    valid = zones > 0
    orig_idx = np.clip(zones.astype(np.int64) - 1, 0, max_class - 1)
    orig_counts = np.take_along_axis(counts, orig_idx[..., None], axis=-1)[..., 0]
    keep_orig = valid & (orig_counts == max_counts)

    return np.where(valid, np.where(keep_orig, zones, best), 0).astype(zones.dtype)


def fit_ordered_kmeans(
    values: np.ndarray,
    n_clusters: int = 3,
    random_state: int = 42,
    awc_weight: float = 0.5,
) -> KMeans:
    """Fit 1D or monotonic directional 2D KMeans with ordered cluster centers."""
    vals = np.asarray(values, dtype=np.float32)
    if vals.ndim == 1:
        vals = vals.reshape(-1, 1)

    if vals.shape[1] == 2:
        w = float(awc_weight)
        score = (vals[:, 0] + w * vals[:, 1]).reshape(-1, 1).astype(np.float32)
        km_1d = KMeans(n_clusters=n_clusters, n_init=10, random_state=random_state).fit(score)
        order = np.argsort(km_1d.cluster_centers_.ravel())
        mu = km_1d.cluster_centers_.ravel()[order]
        ordered_labels = np.argsort(order).astype(np.int32)[km_1d.labels_]

        km_2d = KMeans(
            n_clusters=n_clusters, n_init=1, max_iter=1, random_state=random_state
        ).fit(vals[: max(n_clusters, 10)])
        denom = 1.0 + w * w
        centers_2d = np.column_stack([mu / denom, (w * mu) / denom]).astype(np.float32)
        km_2d.cluster_centers_ = centers_2d
        km_2d.labels_ = ordered_labels
        km_2d.inertia_ = float(np.sum((vals - centers_2d[ordered_labels]) ** 2))
        return km_2d

    kmeans = KMeans(n_clusters=n_clusters, n_init=10, random_state=random_state).fit(vals)
    order = np.argsort(kmeans.cluster_centers_.sum(axis=1))
    kmeans.cluster_centers_ = kmeans.cluster_centers_[order].copy()
    kmeans.labels_ = np.argsort(order).astype(np.int32)[kmeans.labels_]
    return kmeans


def save_kmeans_model(
    model: KMeans,
    model_path: str | Path,
    metadata: dict | None = None,
) -> Path:
    """Serialize KMeans model (.joblib) and companion _meta.json next to it."""
    path = Path(model_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, path)

    centers_arr = np.asarray(model.cluster_centers_, dtype=np.float64)
    n_features = int(centers_arr.shape[1]) if centers_arr.ndim == 2 else 1
    n_clusters = int(model.n_clusters)
    payload: dict = {
        "n_clusters": n_clusters,
        "n_features": n_features,
        "zone_mapping": {str(i): _zone_label(i, n_clusters) for i in range(1, n_clusters + 1)},
        "sklearn_version": sklearn.__version__,
    }

    if n_features == 1:
        centers = [float(c) for c in np.sort(centers_arr.ravel())]
        payload.update(
            {
                "feature_names": ["ndvi_z"],
                "cluster_centers": centers,
                "decision_thresholds": [
                    float((centers[i] + centers[i + 1]) / 2.0)
                    for i in range(len(centers) - 1)
                ],
                "predict_note": "zone = model.predict(ndvi_z.reshape(-1, 1)) + 1",
            }
        )
    else:
        payload.update(
            {
                "feature_names": ["ndvi_z", "awc_z"],
                "cluster_centers": [[float(v) for v in row] for row in centers_arr],
                "predict_note": "zone = model.predict(np.column_stack([ndvi_z, awc_z])) + 1",
            }
        )

    if metadata:
        payload.update(metadata)

    meta_path = path.with_name(f"{path.stem}_meta.json")
    meta_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return path


def load_kmeans_model(model_path: str | Path) -> KMeans:
    """Load a serialized KMeans model from a .joblib file."""
    return joblib.load(Path(model_path))


def load_kmeans_metadata(model_path: str | Path) -> dict:
    """Load companion _meta.json next to a saved KMeans .joblib model if present."""
    path = Path(model_path)
    meta_path = path.with_name(f"{path.stem}_meta.json")
    return json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}


def predict_field_zones(
    median_z: np.ndarray,
    model: KMeans,
    awc_z: np.ndarray | None = None,
    apply_majority_filter: bool = True,
    filter_size: int = 3,
) -> tuple[np.ndarray | None, dict[int, float] | None]:
    """Assign zones 1..n_clusters using a fitted ordered KMeans model (1D or 2D)."""
    if not np.any(np.isfinite(median_z)):
        return None, None

    n_features = int(getattr(model, "n_features_in_", 1))
    if n_features == 2 and awc_z is None:
        raise ValueError(
            "Model KMeans wymaga 2 cech (ndvi_z + awc_z), ale nie podano awc_z (soil_source)."
        )

    X, mask = build_feature_matrix(median_z, awc_z=awc_z if n_features == 2 else None)
    zones = np.zeros(median_z.shape, dtype=np.uint8)
    zones[mask] = (model.predict(X) + 1).astype(np.uint8)

    if apply_majority_filter:
        zones = majority_filter_zones(zones, size=filter_size)

    centroids = {
        z: float(np.nanmean(median_z[zones == z]))
        for z in range(1, int(model.n_clusters) + 1)
        if np.any(zones == z)
    }
    return zones, centroids


def cluster_field_kmeans(
    median_z: np.ndarray,
    n_clusters: int = 3,
    random_state: int = 42,
    apply_majority_filter: bool = True,
    filter_size: int = 3,
    awc_z: np.ndarray | None = None,
    awc_weight: float = 0.5,
) -> tuple[np.ndarray | None, dict[int, float] | None]:
    """Cluster normalized field pixels (1D NDVI or 2D NDVI+AWC) into ordered zones."""
    values = median_z[np.isfinite(median_z)]
    if values.size < n_clusters or np.unique(values).size < n_clusters:
        return None, None

    X, _ = build_feature_matrix(median_z, awc_z=awc_z)
    model = fit_ordered_kmeans(
        X, n_clusters=n_clusters, random_state=random_state, awc_weight=awc_weight
    )
    return predict_field_zones(
        median_z,
        model,
        awc_z=awc_z,
        apply_majority_filter=apply_majority_filter,
        filter_size=filter_size,
    )


def _fit_pooled_kmeans_model(
    field_features: list[
        tuple[int | str, np.ndarray, np.ndarray | None, np.ndarray | None, dict]
    ],
    raster_paths: list[Path],
    n_clusters: int,
    inner_buffer_m: float,
    min_area_ha: float,
    random_state: int,
    awc_weight: float = 0.5,
    awc_meta: dict | None = None,
) -> tuple[KMeans, dict]:
    """Pool pixels across fields and fit an ordered 1D or 2D KMeans model."""
    if not field_features:
        raise ValueError("Brak pol z poprawnymi pikselami NDVI do treningu modelu.")

    pooled = np.vstack(
        [build_feature_matrix(mz, awc_z=az)[0] for _, mz, _, az, _ in field_features]
    ).astype(np.float32)

    if pooled.shape[0] < n_clusters or np.unique(pooled, axis=0).shape[0] < n_clusters:
        raise ValueError("Za malo unikalnych wartosci cech do treningu KMeans.")

    model = fit_ordered_kmeans(
        pooled, n_clusters=n_clusters, random_state=random_state, awc_weight=awc_weight
    )
    labels_1based = model.labels_ + 1
    zone_emp: dict[str, dict[str, float]] = {}
    for z in range(1, n_clusters + 1):
        z_mask = labels_1based == z
        if np.any(z_mask):
            entry = {"ndvi_z": round(float(np.mean(pooled[z_mask, 0])), 4)}
            if pooled.shape[1] == 2:
                entry["awc_z"] = round(float(np.mean(pooled[z_mask, 1])), 4)
            zone_emp[str(z)] = entry

    metadata: dict = {
        "n_fields": len(field_features),
        "n_pixels": int(pooled.shape[0]),
        "n_scenes": len(raster_paths),
        "inner_buffer_m": float(inner_buffer_m),
        "min_area_ha": float(min_area_ha),
        "random_state": int(random_state),
        "zone_empirical_means": zone_emp,
    }
    if pooled.shape[1] == 2:
        metadata["awc_weight"] = float(awc_weight)
        if awc_meta:
            metadata.update(awc_meta)

    return model, metadata


# ==============================================================================
# 4. WEKTORYZACJA STREF, LACZENIE DROBNYCH FRAGMENTOW I ZAPIS RASTROW
# ==============================================================================


def _label_zone_components(zones: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Label 4-connected zone patches and return (component_grid, component_to_zone)."""
    comp_grid = np.zeros(zones.shape, dtype=np.int32)
    comp_zone_list = [0]
    next_id = 1
    for z_id in np.unique(zones):
        if z_id <= 0:
            continue
        labeled, count = nd_label(zones == z_id, structure=_STRUCT4)
        if count > 0:
            nz = labeled > 0
            comp_grid[nz] = labeled[nz] + next_id - 1
            comp_zone_list.extend([int(z_id)] * int(count))
            next_id += int(count)
    return comp_grid, np.asarray(comp_zone_list, dtype=zones.dtype)


def _merge_small_raster_patches(zones: np.ndarray, min_px: int) -> np.ndarray:
    """Fast raster-level merge of adjacent tiny patches below min_px."""
    if min_px <= 1 or not np.any(zones > 0):
        return zones.copy()

    comp_grid, comp_zone = _label_zone_components(zones)
    areas = np.bincount(comp_grid.ravel())
    if areas.size <= 2:
        return zones.copy()

    boxes = [None] + find_objects(comp_grid)
    remaining = int(np.sum(areas[1:] > 0))
    for cid in np.argsort(areas):
        if remaining <= 1:
            break
        if cid == 0 or not 0 < areas[cid] < min_px:
            continue
        rows, cols = boxes[cid]
        win = (
            slice(max(rows.start - 1, 0), rows.stop + 1),
            slice(max(cols.start - 1, 0), cols.stop + 1),
        )
        part = comp_grid[win]
        region = part == cid
        nbrs = part[binary_dilation(region, structure=_STRUCT4) & ~region]
        nbrs = nbrs[nbrs > 0]
        if nbrs.size == 0:
            continue
        target = int(np.bincount(nbrs).argmax())
        part[region] = target
        areas[target] += areas[cid]
        areas[cid] = 0
        remaining -= 1
        boxes[target] = tuple(
            slice(min(a.start, b.start), max(a.stop, b.stop))
            for a, b in zip(boxes[target], (rows, cols))
        )

    return comp_zone[comp_grid]


def _component_means(
    comp_grid: np.ndarray,
    n_comp: int,
    values: np.ndarray,
    zones: np.ndarray,
    comp_zone: np.ndarray,
    default: float = np.nan,
) -> np.ndarray:
    """Compute per-component mean feature values in one vectorized bincount pass."""
    finite = np.isfinite(values) & (comp_grid > 0)
    counts = np.bincount(comp_grid[finite], minlength=n_comp + 1)
    sums = np.bincount(
        comp_grid[finite],
        weights=values[finite].astype(np.float64),
        minlength=n_comp + 1,
    )
    means = np.full(n_comp + 1, default, dtype=np.float64)
    has = counts > 0
    means[has] = sums[has] / counts[has]

    for cid in np.flatnonzero(~has):
        if cid == 0:
            continue
        zv = values[(zones == comp_zone[cid]) & np.isfinite(values)]
        if zv.size > 0:
            means[cid] = float(np.mean(zv))
    return means


def _pick_merge_neighbor(small_geom, candidates: list[dict]) -> int:
    """Select the adjacent (or nearest) candidate polygon with largest border overlap."""
    buffered = small_geom.buffer(0.01)
    touching = [
        (buffered.intersection(cand["geometry"]).area, idx)
        for idx, cand in enumerate(candidates)
        if buffered.intersects(cand["geometry"])
    ]
    if touching:
        return max(touching, key=lambda item: item[0])[1]
    return int(np.argmin([small_geom.distance(cand["geometry"]) for cand in candidates]))


def _weighted_nan_avg(v1: float, a1: float, v2: float, a2: float) -> float:
    f1, f2 = np.isfinite(v1), np.isfinite(v2)
    if f1 and f2:
        total = a1 + a2
        return (v1 * a1 + v2 * a2) / total if total > 0 else v1
    return v1 if f1 else (v2 if f2 else float("nan"))


def vectorize_and_merge_zones(
    zones: np.ndarray,
    median_z: np.ndarray,
    transform,
    raster_crs,
    field_id: int | str,
    target_crs: str = "EPSG:2180",
    min_zone_area_ha: float = 0.15,
    n_clusters: int = 3,
    awc_grid: np.ndarray | None = None,
) -> gpd.GeoDataFrame:
    """Vectorize zone raster and merge fragments smaller than min_zone_area_ha."""
    base_cols = ["field_id", "zone", "zone_label", "area_ha", "ndvi_z"]
    if awc_grid is not None:
        base_cols.append("awc_mm_per_m")
    base_cols.append("geometry")

    if not np.any(zones > 0):
        return gpd.GeoDataFrame(columns=base_cols, geometry="geometry", crs=target_crs)

    work_zones = zones
    if getattr(raster_crs, "is_projected", True):
        px_area_ha = abs(float(transform.a) * float(transform.e)) / 10_000.0
        if px_area_ha > 0:
            min_px = max(1, int(np.floor(0.8 * min_zone_area_ha / px_area_ha)))
            work_zones = _merge_small_raster_patches(zones, min_px=min_px)

    comp_grid, comp_zone = _label_zone_components(work_zones)
    n_comp = int(comp_zone.size - 1)
    if n_comp == 0:
        return gpd.GeoDataFrame(columns=base_cols, geometry="geometry", crs=target_crs)

    ndvi_means = _component_means(
        comp_grid, n_comp, median_z, work_zones, comp_zone, default=0.0
    )
    awc_means = (
        _component_means(
            comp_grid, n_comp, awc_grid, work_zones, comp_zone, default=np.nan
        )
        if awc_grid is not None
        else None
    )

    raw_records = []
    for geom_dict, val in shapes(comp_grid, mask=comp_grid > 0, transform=transform):
        cid = int(val)
        if cid <= 0 or cid > n_comp:
            continue
        poly = shape(geom_dict)
        if poly.is_empty:
            continue
        if not poly.is_valid:
            poly = poly.buffer(0)
        rec = {
            "zone": int(comp_zone[cid]),
            "ndvi_z": float(ndvi_means[cid]),
            "geometry": poly,
        }
        if awc_means is not None:
            rec["awc_mm_per_m"] = float(awc_means[cid])
        raw_records.append(rec)

    if not raw_records:
        return gpd.GeoDataFrame(columns=base_cols, geometry="geometry", crs=target_crs)

    gdf_target = gpd.GeoDataFrame(raw_records, crs=raster_crs).to_crs(target_crs)
    polys: list[dict] = []
    for row in gdf_target.itertuples():
        geom = row.geometry if row.geometry.is_valid else row.geometry.buffer(0)
        area_ha = float(geom.area / 10_000.0)
        if area_ha <= 0:
            continue
        item = {
            "zone": int(row.zone),
            "ndvi_z": float(row.ndvi_z),
            "area_ha": area_ha,
            "geometry": geom,
        }
        if awc_grid is not None:
            item["awc_mm_per_m"] = float(row.awc_mm_per_m)
        polys.append(item)

    while len(polys) > 1:
        small_idx = int(np.argmin([p["area_ha"] for p in polys]))
        if polys[small_idx]["area_ha"] >= min_zone_area_ha:
            break

        small = polys.pop(small_idx)
        target = polys[_pick_merge_neighbor(small["geometry"], polys)]
        target["ndvi_z"] = _weighted_nan_avg(
            target["ndvi_z"], target["area_ha"], small["ndvi_z"], small["area_ha"]
        )
        if awc_grid is not None:
            target["awc_mm_per_m"] = _weighted_nan_avg(
                target["awc_mm_per_m"],
                target["area_ha"],
                small["awc_mm_per_m"],
                small["area_ha"],
            )
        merged_geom = unary_union([target["geometry"], small["geometry"]])
        if not merged_geom.is_valid:
            merged_geom = merged_geom.buffer(0)
        target["geometry"] = merged_geom
        target["area_ha"] = float(merged_geom.area / 10_000.0)

    out_rows = []
    for p in polys:
        z_id = p["zone"]
        out_row = {
            "field_id": field_id,
            "zone": z_id,
            "zone_label": _zone_label(z_id, n_clusters),
            "area_ha": round(float(p["geometry"].area / 10_000.0), 4),
            "ndvi_z": round(float(p["ndvi_z"]), 4),
        }
        if awc_grid is not None:
            awc_val = p["awc_mm_per_m"]
            out_row["awc_mm_per_m"] = (
                round(float(awc_val), 1) if np.isfinite(awc_val) else np.nan
            )
        out_row["geometry"] = p["geometry"]
        out_rows.append(out_row)

    return gpd.GeoDataFrame(out_rows, geometry="geometry", crs=target_crs)


def _write_single_band_tif(
    path: Path,
    arr: np.ndarray,
    meta: dict,
    dtype: str,
    nodata,
    description: str,
) -> None:
    profile = {
        "driver": "GTiff",
        "height": meta["height"],
        "width": meta["width"],
        "transform": meta["transform"],
        "crs": meta["crs"],
        "count": 1,
        "dtype": dtype,
        "nodata": nodata,
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(arr.astype(dtype), 1)
        dst.set_band_description(1, description)


def _save_field_rasters(
    raster_dir: Path,
    field_id: int | str,
    zones: np.ndarray,
    median_z: np.ndarray,
    meta: dict,
    awc_grid: np.ndarray | None = None,
) -> None:
    raster_dir.mkdir(parents=True, exist_ok=True)
    _write_single_band_tif(
        raster_dir / f"field_{field_id}_zones.tif",
        zones,
        meta,
        "uint8",
        0,
        "KMeans_Zone",
    )
    _write_single_band_tif(
        raster_dir / f"field_{field_id}_ndvi_z.tif",
        median_z,
        meta,
        "float32",
        np.nan,
        "NDVI_ZScore_Median",
    )
    if awc_grid is not None:
        _write_single_band_tif(
            raster_dir / f"field_{field_id}_awc.tif",
            awc_grid,
            meta,
            "float32",
            np.nan,
            "AWC_mm_per_m_H3_L10",
        )


# ==============================================================================
# 5. PIPELINE TRENINGU I GENEROWANIA STREF ZARZADZANIA
# ==============================================================================


def train_kmeans_model(
    boundary_file: str | Path,
    ndvi_dir: str | Path,
    model_path: str | Path,
    n_clusters: int = 3,
    inner_buffer_m: float = 10.0,
    min_area_ha: float = 3.0,
    random_state: int = 42,
    soil_source: str | Path | None = None,
    awc_weight: float = 0.5,
    awc_norm: str = "within_field",
    awc_min_std: float = 2.5,
    env_path: str | Path = ".env",
) -> tuple[KMeans, dict]:
    """Train a global 1D (NDVI) or 2D (NDVI + H3 L10 AWC) KMeans model and save it."""
    raster_paths, _, field_features, awc_meta = _prepare_field_features(
        boundary_file=boundary_file,
        ndvi_dir=ndvi_dir,
        inner_buffer_m=inner_buffer_m,
        min_area_ha=min_area_ha,
        soil_source=soil_source,
        awc_norm=awc_norm,
        awc_min_std=awc_min_std,
        env_path=env_path,
    )
    model, metadata = _fit_pooled_kmeans_model(
        field_features=field_features,
        raster_paths=raster_paths,
        n_clusters=n_clusters,
        inner_buffer_m=inner_buffer_m,
        min_area_ha=min_area_ha,
        random_state=random_state,
        awc_weight=awc_weight,
        awc_meta=awc_meta,
    )
    save_kmeans_model(model, model_path, metadata=metadata)
    return model, metadata


def process_fields_ndvi_kmeans(
    boundary_file: str | Path,
    ndvi_dir: str | Path,
    out_dir: str | Path,
    model_path: str | Path | None = None,
    n_clusters: int = 3,
    inner_buffer_m: float = 10.0,
    min_area_ha: float = 3.0,
    min_zone_area_ha: float = 0.15,
    apply_majority_filter: bool = True,
    save_rasters: bool = False,
    random_state: int = 42,
    load_model: bool = False,
    save_model: bool = True,
    soil_source: str | Path | None = None,
    awc_weight: float = 0.5,
    awc_norm: str = "within_field",
    awc_min_std: float = 2.5,
    env_path: str | Path = ".env",
) -> gpd.GeoDataFrame:
    """Run per-field z-score NDVI (+ optional H3 L10 AWC) K-Means zoning pipeline."""
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    global_model: KMeans | None = None
    if model_path is not None and load_model:
        global_model = load_kmeans_model(model_path)
        n_clusters = int(global_model.n_clusters)

    raster_paths, awc_lookup, field_features, awc_meta = _prepare_field_features(
        boundary_file=boundary_file,
        ndvi_dir=ndvi_dir,
        inner_buffer_m=inner_buffer_m,
        min_area_ha=min_area_ha,
        soil_source=soil_source,
        awc_norm=awc_norm,
        awc_min_std=awc_min_std,
        env_path=env_path,
    )

    if model_path is not None and not load_model and field_features:
        global_model, metadata = _fit_pooled_kmeans_model(
            field_features=field_features,
            raster_paths=raster_paths,
            n_clusters=n_clusters,
            inner_buffer_m=inner_buffer_m,
            min_area_ha=min_area_ha,
            random_state=random_state,
            awc_weight=awc_weight,
            awc_meta=awc_meta,
        )
        if save_model:
            save_kmeans_model(global_model, model_path, metadata=metadata)

    zone_frames: list[gpd.GeoDataFrame] = []
    raster_dir = out_path / "rasters"

    for field_id, median_z, awc_grid, awc_z, meta in field_features:
        if global_model is not None:
            zones, centroids = predict_field_zones(
                median_z,
                global_model,
                awc_z=awc_z,
                apply_majority_filter=apply_majority_filter,
            )
        else:
            zones, centroids = cluster_field_kmeans(
                median_z,
                n_clusters=n_clusters,
                random_state=random_state,
                apply_majority_filter=apply_majority_filter,
                awc_z=awc_z,
                awc_weight=awc_weight,
            )

        if zones is None or centroids is None:
            continue

        if save_rasters:
            _save_field_rasters(
                raster_dir, field_id, zones, median_z, meta, awc_grid=awc_grid
            )

        gdf_field = vectorize_and_merge_zones(
            zones=zones,
            median_z=median_z,
            transform=meta["transform"],
            raster_crs=meta["crs"],
            field_id=field_id,
            target_crs="EPSG:2180",
            min_zone_area_ha=min_zone_area_ha,
            n_clusters=n_clusters,
            awc_grid=awc_grid,
        )
        if not gdf_field.empty:
            zone_frames.append(gdf_field)

    empty_cols = ["field_id", "zone", "zone_label", "area_ha", "ndvi_z"]
    if awc_lookup is not None:
        empty_cols.append("awc_mm_per_m")
    empty_cols.append("geometry")

    if not zone_frames:
        return gpd.GeoDataFrame(columns=empty_cols, geometry="geometry", crs="EPSG:2180")

    all_zones = gpd.GeoDataFrame(
        pd.concat(zone_frames, ignore_index=True),
        geometry="geometry",
        crs="EPSG:2180",
    )
    all_zones.to_file(out_path / "field_zones.gpkg", driver="GPKG")
    all_zones.to_file(out_path / "field_zones.geojson", driver="GeoJSON")
    return all_zones


# ==============================================================================
# 6. TESTOWANIE, WALIDACJA I ANALIZA STABILNOSCI MODELU
# ==============================================================================


def compute_clustering_metrics(
    X: np.ndarray,
    labels: np.ndarray,
    model: KMeans | None = None,
    awc_weight: float | None = None,
    sample_size: int = 20_000,
    random_state: int = 42,
) -> dict:
    """Compute unsupervised clustering quality metrics (2D and optional 1D directional)."""
    X_arr = np.asarray(X, dtype=np.float32)
    if X_arr.ndim == 1:
        X_arr = X_arr.reshape(-1, 1)
    y = np.asarray(labels, dtype=np.int32).ravel()

    n_pixels = int(X_arr.shape[0])
    if n_pixels < 2 or np.unique(y).size < 2:
        raise ValueError("Do obliczenia metryk potrzebne sa co najmniej 2 unikalne klastry.")

    ss = int(sample_size) if sample_size and sample_size < n_pixels else None
    metrics: dict = {
        "n_pixels": n_pixels,
        "silhouette_2d": float(
            silhouette_score(X_arr, y, sample_size=ss, random_state=random_state)
        ),
        "davies_bouldin_2d": float(davies_bouldin_score(X_arr, y)),
        "calinski_harabasz_2d": float(calinski_harabasz_score(X_arr, y)),
    }

    if model is not None:
        centers = np.asarray(model.cluster_centers_, dtype=np.float32)
        if int(y.min()) >= 1 and int(y.max()) <= centers.shape[0]:
            metrics["inertia_per_pixel"] = float(
                np.mean(np.sum((X_arr - centers[y - 1]) ** 2, axis=1))
            )
        else:
            metrics["inertia_per_pixel"] = float("nan")

    if X_arr.shape[1] == 2 and awc_weight is not None:
        score_1d = (X_arr[:, 0] + float(awc_weight) * X_arr[:, 1]).reshape(-1, 1)
        metrics["silhouette_1d"] = float(
            silhouette_score(score_1d, y, sample_size=ss, random_state=random_state)
        )
        metrics["davies_bouldin_1d"] = float(davies_bouldin_score(score_1d, y))
        metrics["calinski_harabasz_1d"] = float(calinski_harabasz_score(score_1d, y))

    return metrics


def _build_zone_summary_df(
    X_all: np.ndarray,
    labels_filtered: np.ndarray,
    n_clusters: int,
    awc_raw_all: np.ndarray | None = None,
) -> tuple[pd.DataFrame, dict[str, bool | None]]:
    """Aggregate per-zone feature statistics and verify strict zone monotonicity."""
    total_px = max(1, int(labels_filtered.size))
    has_awc_z = X_all.shape[1] >= 2
    rows: list[dict] = []

    for z in range(1, n_clusters + 1):
        mask = labels_filtered == z
        cnt = int(np.sum(mask))
        if cnt == 0:
            continue
        ndvi_vals = X_all[mask, 0]
        rec: dict = {
            "zone": z,
            "zone_label": _zone_label(z, n_clusters),
            "n_pixels": cnt,
            "share_pct": round(100.0 * cnt / total_px, 2),
            "mean_ndvi_z": float(np.mean(ndvi_vals)),
            "std_ndvi_z": float(np.std(ndvi_vals)),
        }
        if has_awc_z:
            awc_vals = X_all[mask, 1]
            rec["mean_awc_z"] = float(np.mean(awc_vals))
            rec["std_awc_z"] = float(np.std(awc_vals))
        if awc_raw_all is not None:
            raw_vals = awc_raw_all[mask]
            finite_raw = raw_vals[np.isfinite(raw_vals)]
            rec["mean_awc_mm_per_m"] = (
                float(np.mean(finite_raw)) if finite_raw.size > 0 else float("nan")
            )
            rec["std_awc_mm_per_m"] = (
                float(np.std(finite_raw)) if finite_raw.size > 0 else float("nan")
            )
        rows.append(rec)

    df = pd.DataFrame(rows)
    full_zones = len(df) == n_clusters
    mono: dict[str, bool | None] = {
        "monotonic_ndvi_z": bool(full_zones and np.all(np.diff(df["mean_ndvi_z"]) > 0)),
        "monotonic_awc_z": (
            bool(full_zones and np.all(np.diff(df["mean_awc_z"]) > 0))
            if has_awc_z and "mean_awc_z" in df.columns
            else None
        ),
        "monotonic_awc_raw": (
            bool(
                full_zones
                and np.all(np.isfinite(df["mean_awc_mm_per_m"]))
                and np.all(np.diff(df["mean_awc_mm_per_m"]) > 0)
            )
            if "mean_awc_mm_per_m" in df.columns
            else None
        ),
    }
    return df, mono


def evaluate_dataset_with_model(
    boundary_file: str | Path,
    ndvi_dir: str | Path,
    model_path: str | Path,
    soil_source: str | Path | None = None,
    inner_buffer_m: float = 10.0,
    min_area_ha: float = 3.0,
    awc_norm: str = "within_field",
    awc_min_std: float = 2.5,
    apply_majority_filter: bool = True,
    filter_size: int = 3,
    silhouette_sample_size: int = 20_000,
    random_state: int = 42,
    env_path: str | Path = ".env",
) -> dict:
    """Evaluate a saved KMeans model on a satellite dataset without modifying the model."""
    model = load_kmeans_model(model_path)
    model_meta = load_kmeans_metadata(model_path)
    n_clusters = int(model.n_clusters)
    n_features = int(getattr(model, "n_features_in_", 1))
    awc_weight = float(model_meta.get("awc_weight", 0.5)) if n_features == 2 else None

    if n_features == 2 and soil_source is None:
        raise ValueError(
            "Model wymaga 2 cech (ndvi_z + awc_z), ale nie podano soil_source."
        )

    raster_paths, _, field_features, _ = _prepare_field_features(
        boundary_file=boundary_file,
        ndvi_dir=ndvi_dir,
        inner_buffer_m=inner_buffer_m,
        min_area_ha=min_area_ha,
        soil_source=soil_source,
        awc_norm=awc_norm,
        awc_min_std=awc_min_std,
        env_path=env_path,
    )
    if not field_features:
        raise ValueError(f"Brak poprawnych pikseli NDVI w katalogu: {ndvi_dir}")

    X_parts: list[np.ndarray] = []
    raw_parts: list[np.ndarray] = []
    filt_parts: list[np.ndarray] = []
    awc_raw_parts: list[np.ndarray] = []
    field_predictions: dict[int | str, dict] = {}
    fields_all_zones = 0

    for field_id, median_z, awc_grid, awc_z, meta in field_features:
        az_arg = awc_z if n_features == 2 else None
        X_field, valid_mask = build_feature_matrix(median_z, awc_z=az_arg)
        if X_field.shape[0] == 0:
            continue

        raw_preds = (model.predict(X_field) + 1).astype(np.uint8)
        zones = np.zeros(median_z.shape, dtype=np.uint8)
        zones[valid_mask] = raw_preds
        if apply_majority_filter:
            zones = majority_filter_zones(zones, size=filter_size)

        filt_preds = zones[valid_mask].astype(np.uint8)
        if int(np.unique(filt_preds[filt_preds > 0]).size) == n_clusters:
            fields_all_zones += 1

        X_parts.append(X_field)
        raw_parts.append(raw_preds)
        filt_parts.append(filt_preds)
        if awc_grid is not None:
            awc_raw_parts.append(awc_grid[valid_mask].astype(np.float32))

        field_predictions[field_id] = {
            "zones": zones,
            "ndvi_z": median_z,
            "awc_grid": awc_grid,
            "awc_z": awc_z,
            "meta": meta,
        }

    X_all = np.vstack(X_parts).astype(np.float32)
    labels_raw = np.concatenate(raw_parts).astype(np.uint8)
    labels_filtered = np.concatenate(filt_parts).astype(np.uint8)
    awc_raw_all = np.concatenate(awc_raw_parts).astype(np.float32) if awc_raw_parts else None

    metrics = compute_clustering_metrics(
        X_all,
        labels_raw,
        model=model,
        awc_weight=awc_weight,
        sample_size=silhouette_sample_size,
        random_state=random_state,
    )
    zone_summary_df, mono = _build_zone_summary_df(
        X_all, labels_filtered, n_clusters=n_clusters, awc_raw_all=awc_raw_all
    )

    n_valid_fields = len(field_predictions)
    metrics.update(
        {
            "n_scenes": len(raster_paths),
            "n_fields": n_valid_fields,
            "fields_with_all_zones": fields_all_zones,
            "pct_fields_all_zones": round(
                100.0 * fields_all_zones / max(1, n_valid_fields), 2
            ),
            "filter_changed_pct": round(
                100.0 * float(np.mean(labels_raw != labels_filtered)), 2
            ),
            "awc_weight": awc_weight,
            **mono,
        }
    )

    rng = np.random.default_rng(random_state)
    n_sample = min(int(silhouette_sample_size), int(X_all.shape[0]))
    sample_idx = rng.choice(X_all.shape[0], size=n_sample, replace=False)
    sample_data: dict = {
        "ndvi_z": X_all[sample_idx, 0],
        "zone_raw": labels_raw[sample_idx],
        "zone_filtered": labels_filtered[sample_idx],
    }
    if X_all.shape[1] >= 2:
        sample_data["awc_z"] = X_all[sample_idx, 1]
    if awc_raw_all is not None:
        sample_data["awc_mm_per_m"] = awc_raw_all[sample_idx]

    return {
        "model": model,
        "model_meta": model_meta,
        "metrics": metrics,
        "zone_summary_df": zone_summary_df,
        "sample_df": pd.DataFrame(sample_data),
        "X": X_all,
        "labels": labels_raw,
        "labels_filtered": labels_filtered,
        "field_predictions": field_predictions,
    }


def _reproject_to_meta(
    arr: np.ndarray,
    src_meta: dict,
    dst_meta: dict,
    nodata,
) -> np.ndarray:
    dst = np.full(
        (dst_meta["height"], dst_meta["width"]), nodata, dtype=arr.dtype
    )
    reproject(
        source=arr,
        destination=dst,
        src_transform=src_meta["transform"],
        src_crs=src_meta["crs"],
        dst_transform=dst_meta["transform"],
        dst_crs=dst_meta["crs"],
        resampling=Resampling.nearest,
        src_nodata=nodata,
        dst_nodata=nodata,
    )
    return dst


def align_field_prediction_pair(
    train_pred: dict,
    test_pred: dict,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray | None]:
    """Align a field's test zone and NDVI arrays onto the training reference grid."""
    tr_zones, tr_ndvi, tr_meta = (
        train_pred["zones"],
        train_pred["ndvi_z"],
        train_pred["meta"],
    )
    te_zones, te_ndvi, te_meta = (
        test_pred["zones"],
        test_pred["ndvi_z"],
        test_pred["meta"],
    )
    awc_grid = (
        train_pred["awc_grid"]
        if train_pred.get("awc_grid") is not None
        else test_pred.get("awc_grid")
    )

    same_grid = (
        tr_meta["crs"] == te_meta["crs"]
        and tr_meta["transform"] == te_meta["transform"]
        and tr_zones.shape == te_zones.shape
    )
    if same_grid:
        return tr_zones, te_zones, tr_ndvi, te_ndvi, awc_grid

    aligned_te_zones = _reproject_to_meta(te_zones, te_meta, tr_meta, nodata=0)
    aligned_te_ndvi = _reproject_to_meta(
        te_ndvi.astype(np.float32), te_meta, tr_meta, nodata=np.nan
    )
    return tr_zones, aligned_te_zones, tr_ndvi, aligned_te_ndvi, awc_grid


def _safe_pearson_r(a: np.ndarray, b: np.ndarray) -> float:
    valid = np.isfinite(a) & np.isfinite(b)
    if int(np.sum(valid)) < 3:
        return float("nan")
    av, bv = a[valid], b[valid]
    if float(np.std(av)) <= 1e-6 or float(np.std(bv)) <= 1e-6:
        return float("nan")
    return float(np.corrcoef(av, bv)[0, 1])


def _evaluate_boundary_generalization(
    train_model: KMeans,
    test_eval: dict,
    n_clusters: int,
    awc_weight: float,
    random_state: int,
) -> tuple[dict, np.ndarray]:
    refit_model = fit_ordered_kmeans(
        test_eval["X"],
        n_clusters=n_clusters,
        random_state=random_state,
        awc_weight=awc_weight,
    )
    frozen_preds = test_eval["labels"]
    refit_preds = (refit_model.labels_ + 1).astype(np.uint8)
    centroid_shifts = np.linalg.norm(
        np.asarray(train_model.cluster_centers_, dtype=np.float64)
        - np.asarray(refit_model.cluster_centers_, dtype=np.float64),
        axis=1,
    )
    generalization = {
        "frozen_vs_refit_agreement_pct": round(
            100.0 * float(np.mean(frozen_preds == refit_preds)), 2
        ),
        "frozen_vs_refit_kappa": round(
            float(cohen_kappa_score(frozen_preds, refit_preds)), 4
        ),
        "max_centroid_shift_l2": round(float(np.max(centroid_shifts)), 4),
        "centroid_shifts_l2": [round(float(v), 4) for v in centroid_shifts],
    }
    return generalization, refit_model.cluster_centers_.copy()


def _evaluate_temporal_stability(
    train_eval: dict,
    test_eval: dict,
    n_clusters: int,
) -> tuple[dict, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    tr_preds = train_eval["field_predictions"]
    te_preds = test_eval["field_predictions"]
    common_ids = sorted(set(tr_preds.keys()) & set(te_preds.keys()))

    y_tr_parts: list[np.ndarray] = []
    y_te_parts: list[np.ndarray] = []
    ndvi_tr_parts: list[np.ndarray] = []
    ndvi_te_parts: list[np.ndarray] = []
    per_field_rows: list[dict] = []
    extreme_gap = max(1, n_clusters - 1)

    for fid in common_ids:
        tr_z, te_z, tr_ndvi, te_ndvi, _ = align_field_prediction_pair(
            tr_preds[fid], te_preds[fid]
        )
        overlap = (tr_z > 0) & (te_z > 0)
        if not np.any(overlap):
            continue

        yt = tr_z[overlap].astype(np.int16)
        yp = te_z[overlap].astype(np.int16)
        nt, np_ = tr_ndvi[overlap], te_ndvi[overlap]
        corr = _safe_pearson_r(nt, np_)
        diff = np.abs(yt - yp)

        per_field_rows.append(
            {
                "field_id": fid,
                "n_pixels": int(yt.size),
                "agreement_pct": round(100.0 * float(np.mean(yt == yp)), 2),
                "adjacent_or_exact_pct": round(100.0 * float(np.mean(diff <= 1)), 2),
                "extreme_flip_pct": round(100.0 * float(np.mean(diff >= extreme_gap)), 2),
                "ndvi_z_corr": round(corr, 4) if np.isfinite(corr) else np.nan,
                "train_n_zones": int(np.unique(yt).size),
                "test_n_zones": int(np.unique(yp).size),
            }
        )
        y_tr_parts.append(yt)
        y_te_parts.append(yp)
        ndvi_tr_parts.append(nt)
        ndvi_te_parts.append(np_)

    if not y_tr_parts:
        raise ValueError("Brak nakladajacych sie pikseli miedzy zbiorem Train i Test.")

    y_tr = np.concatenate(y_tr_parts)
    y_te = np.concatenate(y_te_parts)
    ndvi_r = _safe_pearson_r(
        np.concatenate(ndvi_tr_parts), np.concatenate(ndvi_te_parts)
    )
    abs_diff = np.abs(y_tr - y_te)

    stability = {
        "n_common_fields": len(per_field_rows),
        "n_common_pixels": int(y_tr.size),
        "exact_agreement_pct": round(100.0 * float(np.mean(y_tr == y_te)), 2),
        "adjacent_or_exact_pct": round(100.0 * float(np.mean(abs_diff <= 1)), 2),
        "extreme_flip_pct": round(100.0 * float(np.mean(abs_diff >= extreme_gap)), 2),
        "cohen_kappa": round(float(cohen_kappa_score(y_tr, y_te)), 4),
        "weighted_kappa_quadratic": round(
            float(cohen_kappa_score(y_tr, y_te, weights="quadratic")), 4
        ),
        "adjusted_rand_index": round(float(adjusted_rand_score(y_tr, y_te)), 4),
        "normalized_mutual_info": round(
            float(normalized_mutual_info_score(y_tr, y_te)), 4
        ),
        "ndvi_z_pearson_r": round(ndvi_r, 4) if np.isfinite(ndvi_r) else np.nan,
    }

    labels_list = list(range(1, n_clusters + 1))
    zone_names = [f"{z} ({_zone_label(z, n_clusters)})" for z in labels_list]
    cm = confusion_matrix(y_tr, y_te, labels=labels_list)
    row_sums = np.maximum(cm.sum(axis=1, keepdims=True), 1)
    confusion_counts_df = pd.DataFrame(
        cm,
        index=[f"Train: {n}" for n in zone_names],
        columns=[f"Test: {n}" for n in zone_names],
    )
    confusion_norm_df = pd.DataFrame(
        np.round(100.0 * cm / row_sums, 2),
        index=confusion_counts_df.index,
        columns=confusion_counts_df.columns,
    )
    return stability, confusion_counts_df, confusion_norm_df, pd.DataFrame(per_field_rows)


def _build_comparison_summary_df(tr_m: dict, te_m: dict) -> pd.DataFrame:
    metric_keys = [
        "n_scenes",
        "n_fields",
        "n_pixels",
        "silhouette_2d",
        "davies_bouldin_2d",
        "calinski_harabasz_2d",
        "silhouette_1d",
        "davies_bouldin_1d",
        "calinski_harabasz_1d",
        "inertia_per_pixel",
        "pct_fields_all_zones",
        "filter_changed_pct",
        "monotonic_ndvi_z",
        "monotonic_awc_z",
        "monotonic_awc_raw",
    ]
    rows: list[dict] = []
    for key in metric_keys:
        if key not in tr_m and key not in te_m:
            continue
        v_tr, v_te = tr_m.get(key), te_m.get(key)
        is_num = (
            not isinstance(v_tr, bool)
            and not isinstance(v_te, bool)
            and isinstance(v_tr, (int, float, np.number))
            and isinstance(v_te, (int, float, np.number))
        )
        rows.append(
            {
                "metric": key,
                "train_2023_2024": (
                    round(float(v_tr), 4)
                    if isinstance(v_tr, (float, np.floating))
                    else v_tr
                ),
                "test_2025": (
                    round(float(v_te), 4)
                    if isinstance(v_te, (float, np.floating))
                    else v_te
                ),
                "delta": round(float(v_te) - float(v_tr), 4) if is_num else "",
            }
        )
    return pd.DataFrame(rows)


def compare_train_test_evaluations(
    train_eval: dict,
    test_eval: dict,
    n_clusters: int = 3,
    random_state: int = 42,
) -> dict:
    """Compare frozen-model generalization and pixel-level temporal stability (Train vs Test)."""
    awc_weight = float(train_eval["metrics"].get("awc_weight") or 0.5)
    generalization, refit_centers = _evaluate_boundary_generalization(
        train_eval["model"], test_eval, n_clusters, awc_weight, random_state
    )
    stability, cm_counts, cm_norm, per_field_df = _evaluate_temporal_stability(
        train_eval, test_eval, n_clusters
    )
    summary_df = _build_comparison_summary_df(
        train_eval["metrics"], test_eval["metrics"]
    )
    return {
        "summary_comparison_df": summary_df,
        "generalization": generalization,
        "stability": stability,
        "confusion_counts_df": cm_counts,
        "confusion_norm_df": cm_norm,
        "per_field_stability_df": per_field_df,
        "refit_centers": refit_centers,
    }


__all__ = [
    "ZONE_LABELS_3",
    "align_field_prediction_pair",
    "build_feature_matrix",
    "build_field_awc_grid",
    "cluster_field_kmeans",
    "compare_train_test_evaluations",
    "compute_clustering_metrics",
    "compute_field_zscore_median",
    "evaluate_dataset_with_model",
    "fit_ordered_kmeans",
    "load_fields",
    "load_h3_awc_lookup",
    "load_kmeans_metadata",
    "load_kmeans_model",
    "majority_filter_zones",
    "normalize_awc_grid",
    "normalize_ndvi_zscore",
    "predict_field_zones",
    "process_fields_ndvi_kmeans",
    "save_kmeans_model",
    "train_kmeans_model",
    "vectorize_and_merge_zones",
]
