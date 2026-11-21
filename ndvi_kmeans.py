from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Iterable
import geopandas as gpd
import joblib
import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.features import geometry_mask, shapes
from rasterio.mask import mask
from rasterio.vrt import WarpedVRT
from shapely.geometry import mapping, shape
from shapely.ops import unary_union
import sklearn
from sklearn.cluster import KMeans

ZONE_LABELS_3 = {
    1: "slaba",
    2: "srednia",
    3: "mocna",
}


def load_fields(boundary_file: str | Path, min_area_ha: float = 3.0) -> gpd.GeoDataFrame:
    """Load field boundaries, ensure field_id and area_ha exist, and filter by min_area_ha."""
    gdf = gpd.read_file(boundary_file)
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()

    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")

    if "field_id" not in gdf.columns:
        gdf["field_id"] = np.arange(1, len(gdf) + 1, dtype=int)

    if "area_ha" not in gdf.columns:
        gdf_2180 = gdf.to_crs("EPSG:2180")
        gdf["area_ha"] = gdf_2180.geometry.area / 10_000.0

    gdf = gdf[gdf["area_ha"] >= min_area_ha].reset_index(drop=True)
    return gdf


def normalize_ndvi_zscore(
    arr: np.ndarray, valid_mask: np.ndarray
) -> np.ndarray | None:
    if int(np.sum(valid_mask)) == 0:
        return None
    vals = arr[valid_mask].astype(np.float64)
    mean = float(np.mean(vals))
    std = float(np.std(vals))

    if not np.isfinite(std) or std < 1e-6:
        return None

    z = np.full(arr.shape, np.nan, dtype=np.float32)
    z[valid_mask] = ((arr[valid_mask] - mean) / std).astype(np.float32)
    return z


def _establish_reference_grid(
    field_geom_wgs84,
    raster_paths: list[Path],
    inner_buffer_m: float,
):
    """Find first overlapping raster and build the clipped reference grid and mask."""
    geom_series_wgs84 = gpd.GeoSeries([field_geom_wgs84], crs="EPSG:4326")

    for path in raster_paths:
        with rasterio.open(path) as src:
            if src.crs is None:
                continue
            ref_crs = src.crs
            geom_utm = geom_series_wgs84.to_crs(ref_crs).iloc[0]

            if inner_buffer_m > 0:
                buffered = geom_utm.buffer(-inner_buffer_m)
                if buffered.is_empty or buffered.area <= 0:
                    buffered = geom_utm
            else:
                buffered = geom_utm

            if not buffered.is_valid:
                buffered = buffered.buffer(0)

            try:
                img, ref_transform = mask(
                    src, [mapping(buffered)], crop=True, filled=False
                )
            except ValueError:
                continue

            ref_height, ref_width = img.shape[1], img.shape[2]
            if ref_height == 0 or ref_width == 0:
                continue

            in_field_mask = geometry_mask(
                [mapping(buffered)],
                out_shape=(ref_height, ref_width),
                transform=ref_transform,
                invert=True,
            )
            if int(np.sum(in_field_mask)) == 0:
                in_field_mask = geometry_mask(
                    [mapping(buffered)],
                    out_shape=(ref_height, ref_width),
                    transform=ref_transform,
                    invert=True,
                    all_touched=True,
                )
            return ref_crs, ref_transform, ref_height, ref_width, in_field_mask

    return None


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

    grid = _establish_reference_grid(field_geom_wgs84, paths, inner_buffer_m)
    if grid is None:
        return None, None

    ref_crs, ref_transform, ref_height, ref_width, in_field_mask = grid
    z_scenes: list[np.ndarray] = []

    for path in paths:
        with rasterio.open(path) as src:
            if src.crs is None:
                continue
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

    filtered = np.where(valid, np.where(keep_orig, zones, best), 0)
    return filtered.astype(zones.dtype)


def fit_ordered_kmeans(
    values: np.ndarray,
    n_clusters: int = 3,
    random_state: int = 42,
) -> KMeans:
    """Fit 1D KMeans and sort cluster centers ascending so 0=slaba .. k-1=mocna."""
    vals = np.asarray(values, dtype=np.float32).reshape(-1, 1)
    kmeans = KMeans(n_clusters=n_clusters, n_init=10, random_state=random_state)
    kmeans.fit(vals)

    order = np.argsort(kmeans.cluster_centers_.ravel())
    kmeans.cluster_centers_ = kmeans.cluster_centers_[order].copy()
    inv_order = np.empty(n_clusters, dtype=np.int32)
    for new_label, old_label in enumerate(order):
        inv_order[old_label] = new_label
    kmeans.labels_ = inv_order[kmeans.labels_]
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

    centers = [float(c) for c in np.sort(model.cluster_centers_.ravel())]
    thresholds = [
        float((centers[i] + centers[i + 1]) / 2.0) for i in range(len(centers) - 1)
    ]
    n_clusters = int(model.n_clusters)
    zone_mapping = (
        {str(k): v for k, v in ZONE_LABELS_3.items()}
        if n_clusters == 3
        else {str(i): f"strefa_{i}" for i in range(1, n_clusters + 1)}
    )

    payload = {
        "n_clusters": n_clusters,
        "cluster_centers": centers,
        "decision_thresholds": thresholds,
        "zone_mapping": zone_mapping,
        "predict_note": "zone = model.predict(ndvi_z.reshape(-1, 1)) + 1",
        "sklearn_version": sklearn.__version__,
    }
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


def predict_field_zones(
    median_z: np.ndarray,
    model: KMeans,
    apply_majority_filter: bool = True,
    filter_size: int = 3,
) -> tuple[np.ndarray | None, dict[int, float] | None]:
    """Assign zones 1..n_clusters using a fitted ordered KMeans model."""
    valid_mask = np.isfinite(median_z)
    if not np.any(valid_mask):
        return None, None

    vals = median_z[valid_mask].reshape(-1, 1).astype(np.float32)
    preds = (model.predict(vals) + 1).astype(np.uint8)

    zones = np.zeros(median_z.shape, dtype=np.uint8)
    zones[valid_mask] = preds

    if apply_majority_filter:
        zones = majority_filter_zones(zones, size=filter_size)

    n_clusters = int(model.n_clusters)
    centroids = {
        z: float(np.nanmean(median_z[zones == z]))
        for z in range(1, n_clusters + 1)
        if np.any(zones == z)
    }
    return zones, centroids


def cluster_field_kmeans(
    median_z: np.ndarray,
    n_clusters: int = 3,
    random_state: int = 42,
    apply_majority_filter: bool = True,
    filter_size: int = 3,
) -> tuple[np.ndarray | None, dict[int, float] | None]:
    """Cluster normalized median NDVI pixels into ordered zones 1..n_clusters."""
    valid_mask = np.isfinite(median_z)
    values = median_z[valid_mask]

    if values.size < n_clusters or np.unique(values).size < n_clusters:
        return None, None

    model = fit_ordered_kmeans(
        values, n_clusters=n_clusters, random_state=random_state
    )
    return predict_field_zones(
        median_z,
        model,
        apply_majority_filter=apply_majority_filter,
        filter_size=filter_size,
    )


def _pick_merge_neighbor(small_geom, candidates: list[dict]) -> int:
    """Select the adjacent (or nearest) candidate polygon with largest border overlap."""
    buffered = small_geom.buffer(0.01)
    touching_scores: list[tuple[float, int]] = []
    for idx, cand in enumerate(candidates):
        if buffered.intersects(cand["geometry"]):
            overlap_area = buffered.intersection(cand["geometry"]).area
            touching_scores.append((overlap_area, idx))

    if touching_scores:
        touching_scores.sort(key=lambda item: item[0], reverse=True)
        return touching_scores[0][1]

    distances = [small_geom.distance(cand["geometry"]) for cand in candidates]
    return int(np.argmin(distances))


def vectorize_and_merge_zones(
    zones: np.ndarray,
    median_z: np.ndarray,
    transform,
    raster_crs,
    field_id: int | str,
    target_crs: str = "EPSG:2180",
    min_zone_area_ha: float = 0.15,
    n_clusters: int = 3,
) -> gpd.GeoDataFrame:
    """Vectorize zone raster and merge fragments smaller than min_zone_area_ha."""
    valid_mask = zones > 0
    if not np.any(valid_mask):
        return gpd.GeoDataFrame(
            columns=["field_id", "zone", "zone_label", "area_ha", "ndvi_z", "geometry"],
            geometry="geometry",
            crs=target_crs,
        )

    raw_records = []
    for geom_dict, val in shapes(zones, mask=valid_mask, transform=transform):
        zone_id = int(val)
        if zone_id <= 0:
            continue
        poly = shape(geom_dict)
        if poly.is_empty:
            continue
        if not poly.is_valid:
            poly = poly.buffer(0)

        px_mask = (
            geometry_mask(
                [geom_dict],
                out_shape=zones.shape,
                transform=transform,
                invert=True,
            )
            & (zones == zone_id)
            & np.isfinite(median_z)
        )
        if np.any(px_mask):
            mean_z = float(np.mean(median_z[px_mask]))
        else:
            zone_vals = median_z[(zones == zone_id) & np.isfinite(median_z)]
            mean_z = float(np.mean(zone_vals)) if zone_vals.size > 0 else 0.0

        raw_records.append({"zone": zone_id, "ndvi_z": mean_z, "geometry": poly})

    if not raw_records:
        return gpd.GeoDataFrame(
            columns=["field_id", "zone", "zone_label", "area_ha", "ndvi_z", "geometry"],
            geometry="geometry",
            crs=target_crs,
        )

    gdf_target = gpd.GeoDataFrame(raw_records, crs=raster_crs).to_crs(target_crs)
    polys: list[dict] = []
    for row in gdf_target.itertuples():
        geom = row.geometry if row.geometry.is_valid else row.geometry.buffer(0)
        area_ha = float(geom.area / 10_000.0)
        if area_ha <= 0:
            continue
        polys.append(
            {
                "zone": int(row.zone),
                "ndvi_z": float(row.ndvi_z),
                "area_ha": area_ha,
                "geometry": geom,
            }
        )

    while len(polys) > 1:
        small_idx = int(np.argmin([p["area_ha"] for p in polys]))
        if polys[small_idx]["area_ha"] >= min_zone_area_ha:
            break

        small = polys.pop(small_idx)
        neighbor_idx = _pick_merge_neighbor(small["geometry"], polys)
        target = polys[neighbor_idx]

        total_area = target["area_ha"] + small["area_ha"]
        if total_area > 0:
            target["ndvi_z"] = (
                target["ndvi_z"] * target["area_ha"]
                + small["ndvi_z"] * small["area_ha"]
            ) / total_area
        merged_geom = unary_union([target["geometry"], small["geometry"]])
        if not merged_geom.is_valid:
            merged_geom = merged_geom.buffer(0)
        target["geometry"] = merged_geom
        target["area_ha"] = float(merged_geom.area / 10_000.0)

    out_rows = []
    for p in polys:
        z_id = p["zone"]
        label = (
            ZONE_LABELS_3.get(z_id, f"strefa_{z_id}")
            if n_clusters == 3
            else f"strefa_{z_id}"
        )
        out_rows.append(
            {
                "field_id": field_id,
                "zone": z_id,
                "zone_label": label,
                "area_ha": round(float(p["geometry"].area / 10_000.0), 4),
                "ndvi_z": round(float(p["ndvi_z"]), 4),
                "geometry": p["geometry"],
            }
        )

    return gpd.GeoDataFrame(out_rows, geometry="geometry", crs=target_crs)


def _save_field_rasters(
    raster_dir: Path,
    field_id: int | str,
    zones: np.ndarray,
    median_z: np.ndarray,
    meta: dict,
) -> None:
    raster_dir.mkdir(parents=True, exist_ok=True)
    common = {
        "driver": "GTiff",
        "height": meta["height"],
        "width": meta["width"],
        "transform": meta["transform"],
        "crs": meta["crs"],
        "count": 1,
    }

    zones_path = raster_dir / f"field_{field_id}_zones.tif"
    with rasterio.open(zones_path, "w", dtype="uint8", nodata=0, **common) as dst:
        dst.write(zones.astype(np.uint8), 1)
        dst.set_band_description(1, "KMeans_Zone")

    ndvi_z_path = raster_dir / f"field_{field_id}_ndvi_z.tif"
    with rasterio.open(
        ndvi_z_path, "w", dtype="float32", nodata=np.nan, **common
    ) as dst:
        dst.write(median_z.astype(np.float32), 1)
        dst.set_band_description(1, "NDVI_ZScore_Median")


def _compute_all_field_medians(
    fields_wgs84: gpd.GeoDataFrame,
    raster_paths: list[Path],
    inner_buffer_m: float,
) -> list[tuple[int | str, np.ndarray, dict]]:
    """Compute per-field z-score temporal median NDVI arrays for all valid fields."""
    results: list[tuple[int | str, np.ndarray, dict]] = []
    for row in fields_wgs84.itertuples():
        field_id = row.field_id
        median_z, meta = compute_field_zscore_median(
            row.geometry,
            raster_paths=raster_paths,
            inner_buffer_m=inner_buffer_m,
        )
        if median_z is None or meta is None:
            print(f"Pole {field_id}: pominieto (brak wystarczajacych pikseli NDVI).")
            continue
        results.append((field_id, median_z, meta))
    return results


def _fit_pooled_kmeans_model(
    field_medians: list[tuple[int | str, np.ndarray, dict]],
    raster_paths: list[Path],
    n_clusters: int,
    inner_buffer_m: float,
    min_area_ha: float,
    random_state: int,
) -> tuple[KMeans, dict]:
    """Pool finite z-score pixels across fields and fit an ordered KMeans model."""
    if not field_medians:
        raise ValueError("Brak pol z poprawnymi pikselami NDVI do treningu modelu.")

    pooled = np.concatenate(
        [mz[np.isfinite(mz)] for _, mz, _ in field_medians]
    ).astype(np.float32)
    if pooled.size < n_clusters or np.unique(pooled).size < n_clusters:
        raise ValueError("Za malo unikalnych wartosci NDVI z-score do treningu KMeans.")

    model = fit_ordered_kmeans(
        pooled, n_clusters=n_clusters, random_state=random_state
    )
    metadata = {
        "n_fields": len(field_medians),
        "n_pixels": int(pooled.size),
        "n_scenes": len(raster_paths),
        "inner_buffer_m": float(inner_buffer_m),
        "min_area_ha": float(min_area_ha),
        "random_state": int(random_state),
    }
    return model, metadata


def _load_raster_paths(ndvi_dir: str | Path) -> list[Path]:
    ndvi_path = Path(ndvi_dir)
    raster_paths = sorted(ndvi_path.glob("*.tif"))
    if not raster_paths:
        raise FileNotFoundError(
            f"Nie znaleziono plikow GeoTIFF (*.tif) w katalogu: {ndvi_path}"
        )
    return raster_paths


def train_kmeans_model(
    boundary_file: str | Path,
    ndvi_dir: str | Path,
    model_path: str | Path,
    n_clusters: int = 3,
    inner_buffer_m: float = 10.0,
    min_area_ha: float = 3.0,
    random_state: int = 42,
) -> tuple[KMeans, dict]:
    """Train a global KMeans model on per-field z-score median NDVI and save it."""
    raster_paths = _load_raster_paths(ndvi_dir)
    fields = load_fields(boundary_file, min_area_ha=min_area_ha)
    fields_wgs84 = fields.to_crs("EPSG:4326")
    field_medians = _compute_all_field_medians(
        fields_wgs84, raster_paths, inner_buffer_m
    )
    model, metadata = _fit_pooled_kmeans_model(
        field_medians=field_medians,
        raster_paths=raster_paths,
        n_clusters=n_clusters,
        inner_buffer_m=inner_buffer_m,
        min_area_ha=min_area_ha,
        random_state=random_state,
    )
    save_kmeans_model(model, model_path, metadata=metadata)
    return model, metadata


def process_fields_ndvi_kmeans(
    boundary_file: str | Path,
    ndvi_dir: str | Path,
    out_dir: str | Path,
    model_path: str | Path,
    n_clusters: int = 3,
    inner_buffer_m: float = 10.0,
    min_area_ha: float = 3.0,
    min_zone_area_ha: float = 0.15,
    apply_majority_filter: bool = True,
    random_state: int = 42,
    load_model: bool = False,
) -> gpd.GeoDataFrame:
    """Run full per-field z-score NDVI normalization and K-Means zoning pipeline."""
    raster_paths = _load_raster_paths(ndvi_dir)
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    fields = load_fields(boundary_file, min_area_ha=min_area_ha)
    fields_wgs84 = fields.to_crs("EPSG:4326")
    field_medians = _compute_all_field_medians(
        fields_wgs84, raster_paths, inner_buffer_m
    )
    if model_path is not None:
        if load_model:
            global_model = load_kmeans_model(model_path)
            n_clusters = int(global_model.n_clusters)
        elif field_medians:
            global_model, metadata = _fit_pooled_kmeans_model(
                field_medians=field_medians,
                raster_paths=raster_paths,
                n_clusters=n_clusters,
                inner_buffer_m=inner_buffer_m,
                min_area_ha=min_area_ha,
                random_state=random_state,
            )

    zone_frames: list[gpd.GeoDataFrame] = []

    for field_id, median_z, meta in field_medians:
        if global_model is not None:
            zones, centroids = predict_field_zones(
                median_z,
                global_model,
                apply_majority_filter=apply_majority_filter,
            )
        else:
            zones, centroids = cluster_field_kmeans(
                median_z,
                n_clusters=n_clusters,
                random_state=random_state,
                apply_majority_filter=apply_majority_filter,
            )

        if zones is None or centroids is None:
            print(f"Pole {field_id}: pominieto (za malo unikalnych wartosci NDVI).")
            continue


        gdf_field = vectorize_and_merge_zones(
            zones=zones,
            median_z=median_z,
            transform=meta["transform"],
            raster_crs=meta["crs"],
            field_id=field_id,
            target_crs="EPSG:2180",
            min_zone_area_ha=min_zone_area_ha,
            n_clusters=n_clusters,
        )
        if not gdf_field.empty:
            zone_frames.append(gdf_field)

    if not zone_frames:
        return gpd.GeoDataFrame(
            columns=["field_id", "zone", "zone_label", "area_ha", "ndvi_z", "geometry"],
            geometry="geometry",
            crs="EPSG:2180",
        )

    all_zones = gpd.GeoDataFrame(
        gpd.concat(zone_frames, ignore_index=True),
        geometry="geometry",
        crs="EPSG:2180",
    )

    all_zones.to_file(
        out_path / "field_zones.geojson", driver="GeoJSON"
    )

