from __future__ import annotations

from contextlib import ExitStack
import json
import os
from pathlib import Path
import sys
from typing import Iterable


def _sanitize_proj_env() -> None:
    """Clear external PROJ_LIB/PROJ_DATA so venv wheels use their bundled proj.db."""
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
from rasterio.windows import Window
from scipy.ndimage import label as nd_label
from shapely.geometry import mapping, shape
from shapely.ops import unary_union
import sklearn
from sklearn.cluster import KMeans

from kw.soil import (
    _compute_saxton_rawls_2006,
    _geom_to_h3_cells,
    _prepare_geodataframe,
    _query_soil_for_h3_mapping,
    ensure_parquets_unpacked,
)

ZONE_LABELS_3 = {1: "slaba", 2: "srednia", 3: "mocna"}
_STRUCT4 = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], dtype=bool)
_zone_label = lambda z, k: ZONE_LABELS_3[z] if k == 3 and z in ZONE_LABELS_3 else f"strefa_{z}"


# 1. POLA, RASTRY NDVI I NORMALIZACJA Z-SCORE (MEDIANA + MAD)

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
    paths = sorted(list(ndvi_path.glob("*.tif")) + list(ndvi_path.glob("*.tiff")))
    if not paths:
        raise FileNotFoundError(f"Nie znaleziono plikow GeoTIFF (*.tif) w katalogu: {ndvi_path}")
    return paths


def normalize_ndvi_zscore(
    arr: np.ndarray, valid_mask: np.ndarray, clip_limit: float | None = 3.0
) -> np.ndarray | None:
    """Compute per-field robust z-score (median + MAD) over valid pixels."""
    if not np.any(valid_mask):
        return None
    vals = arr[valid_mask].astype(np.float64)
    median = float(np.median(vals))
    scale = 1.4826 * float(np.median(np.abs(vals - median)))
    if not np.isfinite(scale) or scale < 1e-6:
        return None
    zv = (vals - median) / scale
    if clip_limit is not None:
        zv = np.clip(zv, -clip_limit, clip_limit)
    out = np.full(arr.shape, np.nan, dtype=np.float32)
    out[valid_mask] = zv.astype(np.float32)
    return out


def _read_aligned_band(src: rasterio.DatasetReader, ref_crs, ref_tf, ref_h: int, ref_w: int) -> np.ndarray:
    """Read band 1 aligned to the reference grid (fast direct window when aligned)."""
    same_grid = (
        src.crs == ref_crs and np.issubdtype(np.dtype(src.dtypes[0]), np.floating)
        and src.transform.b == 0 and src.transform.d == 0 and ref_tf.b == 0 and ref_tf.d == 0
        and np.isclose(src.transform.a, ref_tf.a) and np.isclose(src.transform.e, ref_tf.e)
    )
    if same_grid:
        cf, rf = (ref_tf.c - src.transform.c) / src.transform.a, (ref_tf.f - src.transform.f) / src.transform.e
        col, row = int(round(cf)), int(round(rf))
        if abs(cf - col) < 1e-6 and abs(rf - row) < 1e-6:
            in_b = 0 <= col and 0 <= row and col + ref_w <= src.width and row + ref_h <= src.height
            arr = src.read(1, window=Window(col, row, ref_w, ref_h), boundless=not in_b, fill_value=np.nan if not in_b else None).astype(np.float32)
            nodata = src.nodata
            if nodata is not None and np.isfinite(nodata):
                arr[arr == np.float32(nodata)] = np.nan
            return arr
    with WarpedVRT(src, crs=ref_crs, transform=ref_tf, width=ref_w, height=ref_h, resampling=Resampling.nearest) as vrt:
        arr, nodata = vrt.read(1).astype(np.float32), vrt.nodata
    if nodata is not None and np.isfinite(nodata):
        arr[arr == np.float32(nodata)] = np.nan
    return arr


def compute_field_zscore_median(
    field_geom_wgs84, raster_paths: Iterable[str | Path], inner_buffer_m: float = 10.0,
    min_valid_pixels: int = 15, *, datasets: list[rasterio.DatasetReader] | None = None,
    geom_by_crs: dict[str, object] | None = None,
) -> tuple[np.ndarray | None, dict | None]:
    """Normalize each NDVI scene via per-field robust z-score and return temporal median."""
    with ExitStack() as stack:
        if datasets is None:
            paths = [Path(p) for p in raster_paths]
            if not paths:
                return None, None
            datasets = [stack.enter_context(rasterio.open(p)) for p in paths]
        if not datasets:
            return None, None

        grid, geom_wgs_series = None, None
        for src in datasets:
            if src.crs is None:
                continue
            key = src.crs.to_string()
            if geom_by_crs and key in geom_by_crs:
                geom_utm = geom_by_crs[key]
            else:
                if geom_wgs_series is None:
                    geom_wgs_series = gpd.GeoSeries([field_geom_wgs84], crs="EPSG:4326")
                geom_utm = geom_wgs_series.to_crs(src.crs).iloc[0]
            buf = geom_utm.buffer(-inner_buffer_m) if inner_buffer_m > 0 else geom_utm
            if buf.is_empty or buf.area <= 0:
                buf = geom_utm
            geom_iface = [mapping(buf if buf.is_valid else buf.buffer(0))]
            try:
                win = geometry_window(src, geom_iface)
            except (WindowError, ValueError):
                continue
            ref_h, ref_w = int(win.height), int(win.width)
            if ref_h <= 0 or ref_w <= 0:
                continue
            ref_tf = src.window_transform(win)
            mask = geometry_mask(geom_iface, out_shape=(ref_h, ref_w), transform=ref_tf, invert=True)
            if not np.any(mask):
                mask = geometry_mask(geom_iface, out_shape=(ref_h, ref_w), transform=ref_tf, invert=True, all_touched=True)
            grid = (src.crs, ref_tf, ref_h, ref_w, mask)
            break
        if grid is None:
            return None, None

        ref_crs, ref_tf, ref_h, ref_w, in_field_mask = grid
        z_scenes = []
        for src in datasets:
            if src.crs is None:
                continue
            arr = _read_aligned_band(src, ref_crs, ref_tf, ref_h, ref_w)
            arr[~in_field_mask] = np.nan
            vmask = in_field_mask & np.isfinite(arr)
            if int(np.sum(vmask)) >= min_valid_pixels:
                z = normalize_ndvi_zscore(arr, vmask)
                if z is not None:
                    z_scenes.append(z)
    if not z_scenes:
        return None, None

    stack_arr = np.stack(z_scenes, axis=0)
    any_valid = in_field_mask & np.any(np.isfinite(stack_arr), axis=0)
    median_z = np.full((ref_h, ref_w), np.nan, dtype=np.float32)
    if np.any(any_valid):
        median_z[any_valid] = np.nanmedian(stack_arr[:, any_valid], axis=0).astype(np.float32)
    median_z[~in_field_mask] = np.nan
    return median_z, {"crs": ref_crs, "transform": ref_tf, "height": ref_h, "width": ref_w, "n_scenes_used": len(z_scenes)}


def load_h3_awc_lookup(
    soil_source: str | Path, fields_wgs84: gpd.GeoDataFrame | None = None, env_path: str | Path = ".env"
) -> dict[str, float]:
    """Load native H3 level 10 awc_mm_per_m lookup without aggregating to fields."""
    src_str, src_path = str(soil_source), Path(soil_source)
    if src_path.is_file() and src_path.suffix.lower() == ".parquet":
        if {"h3_index_10", "awc_mm_per_m"}.issubset(pq.read_schema(src_path).names):
            df = pd.read_parquet(src_path, columns=["h3_index_10", "awc_mm_per_m"]).dropna()
            df["h3_index_10"] = df["h3_index_10"].astype(str).str.strip().str.lower()
            return {str(k): float(v) for k, v in df.groupby("h3_index_10")["awc_mm_per_m"].mean().items()}

    if fields_wgs84 is None or fields_wgs84.empty:
        raise ValueError("Surowe zrodlo gleby wymaga podania niepustej warstwy pol (fields_wgs84).")

    if src_str.lower() == "aws":
        from kw.soil_aws import ensure_aws_soil_parquets

        parquet_files = ensure_aws_soil_parquets(bounds=tuple(map(float, fields_wgs84.total_bounds)), env_path=env_path)
    elif src_path.is_file() and src_path.suffix.lower() == ".parquet":
        parquet_files = [src_path.as_posix()]
    elif src_path.is_dir():
        parquet_files = sorted(p.as_posix() for p in src_path.rglob("*.parquet") if not p.name.startswith("._")) or ensure_parquets_unpacked(src_path)
    else:
        raise FileNotFoundError(f"Nieprawidlowe zrodlo gleby: {soil_source}")

    cells = sorted({nbr for g in fields_wgs84.geometry for c in _geom_to_h3_cells(g) for nbr in h3.grid_disk(c, 1)})
    if not cells:
        return {}
    cells_df = _query_soil_for_h3_mapping(pd.DataFrame({"h3_index_10": cells}), ["h3_index_10"], parquet_files)
    if cells_df.empty:
        return {}
    _, _, awc = _compute_saxton_rawls_2006(cells_df["sand_pct"], cells_df["clay_pct"], cells_df["om"])
    return {str(c): float(v) for c, v in zip(cells_df["h3_index_10"], awc) if np.isfinite(v)}


def build_field_awc_grid(
    valid_mask: np.ndarray, transform, raster_crs, awc_lookup: dict[str, float], transformer_cache: dict | None = None
) -> np.ndarray:
    """Map each valid 10 m pixel directly to its native H3 level 10 awc_mm_per_m."""
    awc_grid = np.full(valid_mask.shape, np.nan, dtype=np.float32)
    rs, cs = np.where(valid_mask)
    if rs.size == 0 or not awc_lookup:
        return awc_grid

    key = str(raster_crs)
    tf = transformer_cache.get(key) if transformer_cache is not None else None
    if tf is None:
        tf = Transformer.from_crs(raster_crs, "EPSG:4326", always_xy=True)
        if transformer_cache is not None:
            transformer_cache[key] = tf

    lons, lats = tf.transform(*rasterio.transform.xy(transform, rs, cs))
    cell_cache: dict[str, float | None] = {}
    for r, c, lat, lon in zip(rs, cs, lats, lons):
        cell = h3.latlng_to_cell(float(lat), float(lon), 10)
        if cell not in cell_cache:
            val = awc_lookup.get(cell)
            if val is None:
                for ring in (1, 2):
                    nbrs = [awc_lookup[n] for n in h3.grid_disk(cell, ring) if n in awc_lookup]
                    if nbrs:
                        val = float(np.mean(nbrs))
                        break
            cell_cache[cell] = val
        if cell_cache[cell] is not None:
            awc_grid[r, c] = np.float32(cell_cache[cell])
    return awc_grid


def normalize_awc_grid(awc_grid: np.ndarray, valid_mask: np.ndarray, mode: str = "within_field", min_std: float = 2.5) -> np.ndarray:
    """Standardize per-pixel AWC within field (with min_std floor) for 2D K-Means."""
    if mode != "within_field":
        raise ValueError(f"Obslugiwany jest tylko tryb awc_norm='within_field', otrzymano: {mode}")
    mask = valid_mask & np.isfinite(awc_grid)
    awc_z = np.full(awc_grid.shape, np.nan, dtype=np.float32)
    if np.any(mask):
        vals = awc_grid[mask].astype(np.float64)
        awc_z[mask] = ((vals - float(np.mean(vals))) / max(float(np.std(vals)), float(min_std))).astype(np.float32)
    return awc_z


def build_feature_matrix(median_z: np.ndarray, awc_z: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Construct 1D (ndvi_z) or 2D (ndvi_z, awc_z) KMeans feature matrix."""
    mask = np.isfinite(median_z)
    if awc_z is None:
        return median_z[mask].reshape(-1, 1).astype(np.float32), mask
    av = awc_z[mask].astype(np.float32)
    return np.column_stack([median_z[mask], np.where(np.isfinite(av), av, 0.0)]).astype(np.float32), mask


def extract_field_features(
    boundary_file: str | Path, ndvi_dir: str | Path, inner_buffer_m: float = 10.0,
    min_area_ha: float = 3.0, soil_source: str | Path | None = None,
    awc_norm: str = "within_field", awc_min_std: float = 2.5, env_path: str | Path = ".env",
) -> tuple[list[Path], dict[str, float] | None, list[tuple], dict]:
    """Extract per-field normalized NDVI and pixel-level H3 L10 AWC features."""
    raster_paths = _load_raster_paths(ndvi_dir)
    fields = load_fields(boundary_file, min_area_ha=min_area_ha)
    awc_lookup = load_h3_awc_lookup(soil_source, fields_wgs84=fields, env_path=env_path) if soil_source is not None else None

    features, tf_cache, skipped = [], {}, 0
    with ExitStack() as stack:
        datasets = [stack.enter_context(rasterio.open(p)) for p in raster_paths]
        crs_geoms = {src.crs.to_string(): list(fields.to_crs(src.crs).geometry) for src in datasets if src.crs is not None}
        for idx, row in enumerate(fields.itertuples()):
            median_z, meta = compute_field_zscore_median(
                row.geometry, raster_paths, inner_buffer_m=inner_buffer_m,
                datasets=datasets, geom_by_crs={k: g[idx] for k, g in crs_geoms.items()},
            )
            if median_z is None or meta is None:
                skipped += 1
                continue
            awc_grid = awc_z = None
            if awc_lookup is not None:
                vm = np.isfinite(median_z)
                awc_grid = build_field_awc_grid(vm, meta["transform"], meta["crs"], awc_lookup, tf_cache)
                awc_z = normalize_awc_grid(awc_grid, vm, mode=awc_norm, min_std=awc_min_std)
            features.append((row.field_id, median_z, awc_grid, awc_z, meta))

    if skipped:
        print(f"Pominieto {skipped} pol bez wystarczajacych pikseli NDVI.")
    awc_meta = {"awc_unit": "h3_index_10", "awc_norm": awc_norm, "awc_min_std": float(awc_min_std)} if awc_lookup is not None else {}
    return raster_paths, awc_lookup, features, awc_meta


# 3. KLASTERYZACJA K-MEANS, ZAPIS MODELU I PREDYKCJA STREF

def majority_filter_zones(zones: np.ndarray, size: int = 3) -> np.ndarray:
    """Apply a modal filter over valid zone pixels (> 0), ignoring nodata (0)."""
    if size < 1 or size % 2 == 0:
        raise ValueError("Filter size must be a positive odd integer.")
    max_c = int(zones.max())
    if size == 1 or max_c == 0:
        return zones.copy()
    wins = np.lib.stride_tricks.sliding_window_view(
        np.pad(zones, pad_width=size // 2, mode="constant", constant_values=0), (size, size)
    ).reshape(zones.shape[0], zones.shape[1], size * size)
    counts = np.stack([(wins == c).sum(axis=-1) for c in range(1, max_c + 1)], axis=-1)
    max_cnt, best = counts.max(axis=-1), (counts.argmax(axis=-1) + 1).astype(zones.dtype)
    valid = zones > 0
    orig_cnt = np.take_along_axis(counts, np.clip(zones.astype(np.int64) - 1, 0, max_c - 1)[..., None], axis=-1)[..., 0]
    return np.where(valid, np.where(valid & (orig_cnt == max_cnt), zones, best), 0).astype(zones.dtype)


def fit_ordered_kmeans(values: np.ndarray, n_clusters: int = 3, random_state: int = 42, awc_weight: float = 0.5) -> KMeans:
    """Fit 1D or monotonic directional 2D KMeans with ordered cluster centers."""
    vals = np.asarray(values, dtype=np.float32).reshape(len(values), -1)
    if vals.shape[1] == 2:
        w = float(awc_weight)
        km_1d = KMeans(n_clusters=n_clusters, n_init=10, random_state=random_state).fit((vals[:, 0] + w * vals[:, 1]).reshape(-1, 1))
        order = np.argsort(km_1d.cluster_centers_.ravel())
        mu, labels = km_1d.cluster_centers_.ravel()[order], np.argsort(order).astype(np.int32)[km_1d.labels_]
        km_2d = KMeans(n_clusters=n_clusters, n_init=1, max_iter=1, random_state=random_state).fit(vals[: max(n_clusters, 10)])
        denom = 1.0 + w * w
        km_2d.cluster_centers_ = np.column_stack([mu / denom, (w * mu) / denom]).astype(np.float32)
        km_2d.labels_, km_2d.inertia_ = labels, float(np.sum((vals - km_2d.cluster_centers_[labels]) ** 2))
        return km_2d

    km = KMeans(n_clusters=n_clusters, n_init=10, random_state=random_state).fit(vals)
    order = np.argsort(km.cluster_centers_.sum(axis=1))
    km.cluster_centers_, km.labels_ = km.cluster_centers_[order].copy(), np.argsort(order).astype(np.int32)[km.labels_]
    return km


def save_kmeans_model(model: KMeans, model_path: str | Path, metadata: dict | None = None) -> Path:
    """Serialize KMeans model (.joblib) and companion _meta.json next to it."""
    path = Path(model_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, path)
    centers, k = np.asarray(model.cluster_centers_, dtype=np.float64), int(model.n_clusters)
    n_feat = int(centers.shape[1]) if centers.ndim == 2 else 1
    payload: dict = {
        "n_clusters": k, "n_features": n_feat, "sklearn_version": sklearn.__version__,
        "zone_mapping": {str(i): _zone_label(i, k) for i in range(1, k + 1)},
        "feature_names": ["ndvi_z"] if n_feat == 1 else ["ndvi_z", "awc_z"],
        "cluster_centers": [float(c) for c in np.sort(centers.ravel())] if n_feat == 1 else centers.tolist(),
    }
    if metadata:
        payload.update(metadata)
    path.with_name(f"{path.stem}_meta.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


load_kmeans_model = lambda model_path: joblib.load(Path(model_path))
load_kmeans_metadata = lambda model_path: json.loads(p.read_text(encoding="utf-8")) if (p := Path(model_path).with_name(f"{Path(model_path).stem}_meta.json")).exists() else {}


def predict_field_zones(
    median_z: np.ndarray, model: KMeans, awc_z: np.ndarray | None = None, apply_majority_filter: bool = True, filter_size: int = 3
) -> tuple[np.ndarray | None, dict[int, float] | None]:
    """Assign zones 1..n_clusters using a fitted ordered KMeans model (1D or 2D)."""
    if not np.any(np.isfinite(median_z)):
        return None, None
    n_feat = int(getattr(model, "n_features_in_", 1))
    if n_feat == 2 and awc_z is None:
        raise ValueError("Model KMeans wymaga 2 cech (ndvi_z + awc_z), ale nie podano awc_z (soil_source).")
    X, mask = build_feature_matrix(median_z, awc_z=awc_z if n_feat == 2 else None)
    zones = np.zeros(median_z.shape, dtype=np.uint8)
    zones[mask] = (model.predict(X) + 1).astype(np.uint8)
    if apply_majority_filter:
        zones = majority_filter_zones(zones, size=filter_size)
    return zones, {z: float(np.nanmean(median_z[zones == z])) for z in range(1, int(model.n_clusters) + 1) if np.any(zones == z)}


def cluster_field_kmeans(
    median_z: np.ndarray, n_clusters: int = 3, random_state: int = 42, apply_majority_filter: bool = True,
    filter_size: int = 3, awc_z: np.ndarray | None = None, awc_weight: float = 0.5,
) -> tuple[np.ndarray | None, dict[int, float] | None]:
    """Cluster normalized field pixels (1D NDVI or 2D NDVI+AWC) into ordered zones."""
    vals = median_z[np.isfinite(median_z)]
    if vals.size < n_clusters or np.unique(vals).size < n_clusters:
        return None, None
    X, _ = build_feature_matrix(median_z, awc_z=awc_z)
    model = fit_ordered_kmeans(X, n_clusters=n_clusters, random_state=random_state, awc_weight=awc_weight)
    return predict_field_zones(median_z, model, awc_z=awc_z, apply_majority_filter=apply_majority_filter, filter_size=filter_size)


def _fit_pooled_kmeans_model(
    field_features: list[tuple], raster_paths: list[Path], n_clusters: int, inner_buffer_m: float,
    min_area_ha: float, random_state: int, awc_weight: float = 0.5, awc_meta: dict | None = None,
) -> tuple[KMeans, dict]:
    if not field_features:
        raise ValueError("Brak pol z poprawnymi pikselami NDVI do treningu modelu.")
    pooled = np.vstack([build_feature_matrix(mz, awc_z=az)[0] for _, mz, _, az, _ in field_features]).astype(np.float32)
    if pooled.shape[0] < n_clusters or np.unique(pooled, axis=0).shape[0] < n_clusters:
        raise ValueError("Za malo unikalnych wartosci cech do treningu KMeans.")
    model = fit_ordered_kmeans(pooled, n_clusters=n_clusters, random_state=random_state, awc_weight=awc_weight)
    labels = model.labels_ + 1
    zone_emp = {
        str(z): ({"ndvi_z": round(float(np.mean(pooled[labels == z, 0])), 4), "awc_z": round(float(np.mean(pooled[labels == z, 1])), 4)} if pooled.shape[1] == 2
                 else {"ndvi_z": round(float(np.mean(pooled[labels == z, 0])), 4)})
        for z in range(1, n_clusters + 1) if np.any(labels == z)
    }
    meta: dict = {
        "n_fields": len(field_features), "n_pixels": int(pooled.shape[0]), "n_scenes": len(raster_paths),
        "inner_buffer_m": float(inner_buffer_m), "min_area_ha": float(min_area_ha),
        "random_state": int(random_state), "zone_empirical_means": zone_emp,
    }
    if pooled.shape[1] == 2:
        meta.update({"awc_weight": float(awc_weight), **(awc_meta or {})})
    return model, meta


# 4. WEKTORYZACJA STREF, LACZENIE DROBNYCH FRAGMENTOW I ZAPIS RASTROW

def vectorize_and_merge_zones(
    zones: np.ndarray, median_z: np.ndarray, transform, raster_crs, field_id: int | str,
    target_crs: str = "EPSG:2180", min_zone_area_ha: float = 0.15, n_clusters: int = 3, awc_grid: np.ndarray | None = None,
) -> gpd.GeoDataFrame:
    """Vectorize zone raster and merge fragments smaller than min_zone_area_ha."""
    cols = ["field_id", "zone", "zone_label", "area_ha", "ndvi_z"] + (["awc_mm_per_m"] if awc_grid is not None else []) + ["geometry"]
    if not np.any(zones > 0):
        return gpd.GeoDataFrame(columns=cols, geometry="geometry", crs=target_crs)

    comp_grid, comp_zone, next_id = np.zeros(zones.shape, dtype=np.int32), [0], 1
    for z_id in np.unique(zones):
        if z_id > 0:
            labeled, count = nd_label(zones == z_id, structure=_STRUCT4)
            if count > 0:
                nz = labeled > 0
                comp_grid[nz] = labeled[nz] + next_id - 1
                comp_zone.extend([int(z_id)] * int(count))
                next_id += int(count)
    n_comp, cz_arr = next_id - 1, np.asarray(comp_zone, dtype=zones.dtype)
    if n_comp == 0:
        return gpd.GeoDataFrame(columns=cols, geometry="geometry", crs=target_crs)

    def _comp_means(vals: np.ndarray, default: float = np.nan) -> np.ndarray:
        fin = np.isfinite(vals) & (comp_grid > 0)
        cnt, sm = np.bincount(comp_grid[fin], minlength=n_comp + 1), np.bincount(comp_grid[fin], weights=vals[fin].astype(np.float64), minlength=n_comp + 1)
        out = np.full(n_comp + 1, default, dtype=np.float64)
        out[cnt > 0] = sm[cnt > 0] / cnt[cnt > 0]
        for cid in np.flatnonzero(cnt == 0):
            if cid > 0 and np.any(zv := vals[(zones == cz_arr[cid]) & np.isfinite(vals)]):
                out[cid] = float(np.mean(zv))
        return out

    ndvi_m = _comp_means(median_z, 0.0)
    awc_m = _comp_means(awc_grid) if awc_grid is not None else None
    raw = []
    for g_dict, val in shapes(comp_grid, mask=comp_grid > 0, transform=transform):
        cid = int(val)
        if 1 <= cid <= n_comp and not (poly := shape(g_dict)).is_empty:
            rec = {"zone": int(cz_arr[cid]), "ndvi_z": float(ndvi_m[cid]), "geometry": poly if poly.is_valid else poly.buffer(0)}
            if awc_m is not None:
                rec["awc_mm_per_m"] = float(awc_m[cid])
            raw.append(rec)
    if not raw:
        return gpd.GeoDataFrame(columns=cols, geometry="geometry", crs=target_crs)

    polys = []
    for row in gpd.GeoDataFrame(raw, crs=raster_crs).to_crs(target_crs).itertuples():
        geom = row.geometry if row.geometry.is_valid else row.geometry.buffer(0)
        if (area_ha := float(geom.area / 10_000.0)) > 0:
            item = {"zone": int(row.zone), "ndvi_z": float(row.ndvi_z), "area_ha": area_ha, "geometry": geom}
            if awc_grid is not None:
                item["awc_mm_per_m"] = float(row.awc_mm_per_m)
            polys.append(item)

    _wavg = lambda v1, a1, v2, a2: ((v1 * a1 + v2 * a2) / (a1 + a2) if (a1 + a2) > 0 else v1) if np.isfinite(v1) and np.isfinite(v2) else (v1 if np.isfinite(v1) else (v2 if np.isfinite(v2) else float("nan")))
    while len(polys) > 1:
        idx = int(np.argmin([p["area_ha"] for p in polys]))
        if polys[idx]["area_ha"] >= min_zone_area_ha:
            break
        small = polys.pop(idx)
        buf = small["geometry"].buffer(0.01)
        touch = [(buf.intersection(c["geometry"]).area, i) for i, c in enumerate(polys) if buf.intersects(c["geometry"])]
        tgt = polys[max(touch)[1] if touch else int(np.argmin([small["geometry"].distance(c["geometry"]) for c in polys]))]
        tgt["ndvi_z"] = _wavg(tgt["ndvi_z"], tgt["area_ha"], small["ndvi_z"], small["area_ha"])
        if awc_grid is not None:
            tgt["awc_mm_per_m"] = _wavg(tgt["awc_mm_per_m"], tgt["area_ha"], small["awc_mm_per_m"], small["area_ha"])
        mg = unary_union([tgt["geometry"], small["geometry"]])
        tgt["geometry"] = mg if mg.is_valid else mg.buffer(0)
        tgt["area_ha"] = float(tgt["geometry"].area / 10_000.0)

    out_rows = [{
        "field_id": field_id, "zone": p["zone"], "zone_label": _zone_label(p["zone"], n_clusters),
        "area_ha": round(float(p["geometry"].area / 10_000.0), 4), "ndvi_z": round(float(p["ndvi_z"]), 4),
        **({"awc_mm_per_m": round(float(p["awc_mm_per_m"]), 1) if np.isfinite(p["awc_mm_per_m"]) else np.nan} if awc_grid is not None else {}),
        "geometry": p["geometry"],
    } for p in polys]
    return gpd.GeoDataFrame(out_rows, geometry="geometry", crs=target_crs)


def _save_field_rasters(raster_dir: Path, field_id: int | str, zones: np.ndarray, median_z: np.ndarray, meta: dict, awc_grid: np.ndarray | None = None) -> None:
    raster_dir.mkdir(parents=True, exist_ok=True)
    specs = [(f"field_{field_id}_zones.tif", zones, "uint8", 0, "KMeans_Zone"), (f"field_{field_id}_ndvi_z.tif", median_z, "float32", np.nan, "NDVI_ZScore_Median")]
    if awc_grid is not None:
        specs.append((f"field_{field_id}_awc.tif", awc_grid, "float32", np.nan, "AWC_mm_per_m_H3_L10"))
    for fname, arr, dtype, nodata, desc in specs:
        with rasterio.open(raster_dir / fname, "w", driver="GTiff", height=meta["height"], width=meta["width"], transform=meta["transform"], crs=meta["crs"], count=1, dtype=dtype, nodata=nodata) as dst:
            dst.write(arr.astype(dtype), 1)
            dst.set_band_description(1, desc)


# 5. PIPELINE TRENINGU I GENEROWANIA STREF ZARZADZANIA

def train_kmeans_model(
    boundary_file: str | Path, ndvi_dir: str | Path, model_path: str | Path, n_clusters: int = 3,
    inner_buffer_m: float = 10.0, min_area_ha: float = 3.0, random_state: int = 42,
    soil_source: str | Path | None = None, awc_weight: float = 0.5, awc_norm: str = "within_field",
    awc_min_std: float = 2.5, env_path: str | Path = ".env",
) -> tuple[KMeans, dict]:
    """Train a global 1D (NDVI) or 2D (NDVI + H3 L10 AWC) KMeans model and save it."""
    raster_paths, _, field_features, awc_meta = extract_field_features(
        boundary_file, ndvi_dir, inner_buffer_m, min_area_ha, soil_source, awc_norm, awc_min_std, env_path
    )
    model, metadata = _fit_pooled_kmeans_model(field_features, raster_paths, n_clusters, inner_buffer_m, min_area_ha, random_state, awc_weight, awc_meta)
    save_kmeans_model(model, model_path, metadata=metadata)
    return model, metadata


def process_fields_ndvi_kmeans(
    boundary_file: str | Path, ndvi_dir: str | Path, out_dir: str | Path, model_path: str | Path | None = None,
    n_clusters: int = 3, inner_buffer_m: float = 10.0, min_area_ha: float = 3.0, min_zone_area_ha: float = 0.15,
    apply_majority_filter: bool = True, save_rasters: bool = False, random_state: int = 42,
    load_model: bool = False, save_model: bool = True, soil_source: str | Path | None = None,
    awc_weight: float = 0.5, awc_norm: str = "within_field", awc_min_std: float = 2.5, env_path: str | Path = ".env",
) -> gpd.GeoDataFrame:
    """Run per-field z-score NDVI (+ optional H3 L10 AWC) K-Means zoning pipeline."""
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    global_model = load_kmeans_model(model_path) if (model_path is not None and load_model) else None
    if global_model is not None:
        n_clusters = int(global_model.n_clusters)

    raster_paths, awc_lookup, field_features, awc_meta = extract_field_features(
        boundary_file, ndvi_dir, inner_buffer_m, min_area_ha, soil_source, awc_norm, awc_min_std, env_path
    )
    if model_path is not None and not load_model and field_features:
        global_model, metadata = _fit_pooled_kmeans_model(field_features, raster_paths, n_clusters, inner_buffer_m, min_area_ha, random_state, awc_weight, awc_meta)
        if save_model:
            save_kmeans_model(global_model, model_path, metadata=metadata)

    zone_frames = []
    for fid, median_z, awc_grid, awc_z, meta in field_features:
        zones, centroids = (
            predict_field_zones(median_z, global_model, awc_z=awc_z, apply_majority_filter=apply_majority_filter)
            if global_model is not None
            else cluster_field_kmeans(median_z, n_clusters=n_clusters, random_state=random_state, apply_majority_filter=apply_majority_filter, awc_z=awc_z, awc_weight=awc_weight)
        )
        if zones is None or centroids is None:
            continue
        if save_rasters:
            _save_field_rasters(out_path / "rasters", fid, zones, median_z, meta, awc_grid=awc_grid)
        gdf_f = vectorize_and_merge_zones(zones, median_z, meta["transform"], meta["crs"], fid, "EPSG:2180", min_zone_area_ha, n_clusters, awc_grid)
        if not gdf_f.empty:
            zone_frames.append(gdf_f)

    cols = ["field_id", "zone", "zone_label", "area_ha", "ndvi_z"] + (["awc_mm_per_m"] if awc_lookup is not None else []) + ["geometry"]
    if not zone_frames:
        return gpd.GeoDataFrame(columns=cols, geometry="geometry", crs="EPSG:2180")
    all_zones = gpd.GeoDataFrame(pd.concat(zone_frames, ignore_index=True), geometry="geometry", crs="EPSG:2180")
    all_zones.to_file(out_path / "field_zones.geojson", driver="GeoJSON")
    return all_zones
