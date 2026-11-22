import argparse
from datetime import date, timedelta
from pathlib import Path
import re
import sys
from typing import Iterable

import duckdb
import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.enums import Resampling
import rasterio.features
from rasterio.features import geometry_mask
import rasterio.mask
import rasterio.transform
import rasterio.warp
from rasterio.vrt import WarpedVRT
from shapely.geometry import box

if __package__ in (None, ""):
    _repo_root = str(Path(__file__).resolve().parent.parent)
    if _repo_root not in sys.path:
        sys.path.insert(0, _repo_root)

from ml.config import (
    DEFAULT_DATA_DIR,
    MVP_CROP_CODE_TO_NAME,
    STATIC_SOIL_COLS,
    WEATHER_COLS,
)


def _map_crop_name(crop_code_val) -> str:
    if pd.isna(crop_code_val):
        return "inne"
    try:
        return MVP_CROP_CODE_TO_NAME.get(int(round(float(crop_code_val))), "inne")
    except (TypeError, ValueError):
        return "inne"


def build_fields_master(
    fields_crops_geojson: str | Path = "bk/fields_crops.geojson",
    soil_profiles_parquet: str | Path = Path("data/soil/fields_soil_profiles.parquet"),
    out_path: str | Path = DEFAULT_DATA_DIR / "fields_master.parquet",
    id_col: str = "id",
    min_area_ha: float = 3.0,
    only_mvp_crops: bool = False,
) -> pd.DataFrame:
    """
    Łączy granice + kody upraw z bk/assign_crops.py (fields_crops.geojson)
    z profilami glebowymi z kw/soil.py (data/soil/fields_soil_profiles.parquet).
    """
    gdf = gpd.read_file(fields_crops_geojson)
    if id_col and id_col in gdf.columns:
        gdf["field_id"] = gdf[id_col].astype(str)
    else:
        gdf["field_id"] = [f"field_{i}" for i in range(len(gdf))]

    if "crop_code" in gdf.columns:
        crop_code = pd.to_numeric(gdf["crop_code"], errors="coerce")
    else:
        crop_code = pd.Series(np.nan, index=gdf.index, dtype="float64")

    crops_df = pd.DataFrame(
        {
            "field_id": gdf["field_id"],
            "crop_code": crop_code,
            "crop": [_map_crop_name(v) for v in crop_code],
        }
    )

    soil_df = pd.read_parquet(soil_profiles_parquet)
    soil_df["field_id"] = soil_df["field_id"].astype(str)
    soil_df = soil_df.drop(columns=[c for c in ("crop", "crop_code") if c in soil_df.columns])

    merged = soil_df.merge(crops_df, on="field_id", how="inner")
    merged = merged[merged["area_ha"] >= min_area_ha].copy()
    if only_mvp_crops:
        merged = merged[merged["crop"] != "inne"].copy()

    ordered_cols = [
        "field_id",
        "area_ha",
        "centroid_lat",
        "centroid_lon",
        "crop_code",
        "crop",
        "sand_pct",
        "silt_pct",
        "clay_pct",
        "ph",
        "om",
        "cec",
        "bulk_density",
        "band_ph",
        "band_om",
        "band_cec",
        "soil_variability",
        "permeability",
        "water_retention",
        "wilting_point",
        "field_capacity",
        "awc_mm_per_m",
        "soilTexture",
    ]
    present_cols = [c for c in ordered_cols if c in merged.columns]
    out = merged[present_cols].sort_values("field_id").reset_index(drop=True)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(out_path, index=False)
    print(f"[ML PREP] Zapisano fields_master ({len(out)} pól) -> {out_path}")
    return out


def parse_date_from_filename(path: str | Path) -> str:
    """
    Wyciąga datę YYYY-MM-DD z nazwy pliku GeoTIFF (np. scene_2024-06-24.tif
    lub S2A_33UWU_20220624_0_L2A.tif).
    """
    name = Path(path).name
    m_dash = re.search(r"(20\d{2})[-_](\d{2})[-_](\d{2})", name)
    if m_dash:
        y, m, d = map(int, m_dash.groups())
        return date(y, m, d).isoformat()

    m_compact = re.search(r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)", name)
    if m_compact:
        y, m, d = map(int, m_compact.groups())
        return date(y, m, d).isoformat()

    raise ValueError(
        f"Nie udało się odczytać daty YYYY-MM-DD ani YYYYMMDD z nazwy pliku '{name}'. "
        "Przekaż listę krotek (date_str, path) lub dodaj datę do nazwy pliku."
    )


def _normalize_tiff_inputs(
    tiff_inputs: str | Path | Iterable[str | Path | tuple[str, str | Path]],
) -> list[tuple[str, Path]]:
    if isinstance(tiff_inputs, (str, Path)):
        tdir = Path(tiff_inputs)
        paths = sorted(list(tdir.glob("*.tif")) + list(tdir.glob("*.tiff")))
        return [(parse_date_from_filename(p), p) for p in paths]

    normalized: list[tuple[str, Path]] = []
    for item in tiff_inputs:
        if isinstance(item, (tuple, list)) and len(item) == 2:
            d_str = date.fromisoformat(str(item[0]).strip()).isoformat()
            normalized.append((d_str, Path(item[1])))
        else:
            p = Path(item)
            normalized.append((parse_date_from_filename(p), p))
    return normalized


PIXEL_SOIL_VALUE_COLS: tuple[str, ...] = tuple(c for c in STATIC_SOIL_COLS if c != "area_ha")


def detect_scene_bands(src: rasterio.DatasetReader) -> tuple[bool, list[int]]:
    """
    Rozpoznaje układ pasm w GeoTIFF Sentinel-2 ('NDVI'/'NDMI' vs raw 'red'/'nir'/'swir16').
    """
    desc_map = {
        (src.descriptions[i] or "").strip().lower(): i + 1
        for i in range(src.count)
        if src.descriptions[i]
    }
    has_precomputed = "ndvi" in desc_map and "ndmi" in desc_map
    has_raw = {"red", "nir", "swir16"}.issubset(desc_map)
    if not has_precomputed and not has_raw:
        raise ValueError(
            f"Plik {src.name} musi zawierać opisane pasma ('NDVI', 'NDMI') "
            "lub ('red', 'nir', 'swir16')."
        )
    band_indexes = (
        [desc_map["ndvi"], desc_map["ndmi"]]
        if has_precomputed
        else [desc_map["red"], desc_map["nir"], desc_map["swir16"]]
    )
    return has_precomputed, band_indexes


def arrays_to_ndvi_ndmi(
    arr: np.ndarray,
    has_precomputed: bool,
    nodata: float | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Konwertuje surowe lub gotowe pasma rastra (C, H, W) na pary 2D (ndvi, ndmi) float32."""
    work = arr.astype(np.float32, copy=True)
    if nodata is not None and np.isfinite(nodata):
        work = np.where(work == float(nodata), np.nan, work)

    if has_precomputed:
        ndvi_arr, ndmi_arr = work[0], work[1]
    else:
        red_arr = np.where(work[0] == 0, np.nan, work[0])
        nir_arr = np.where(work[1] == 0, np.nan, work[1])
        swir_arr = np.where(work[2] == 0, np.nan, work[2])
        d_ndvi = nir_arr + red_arr
        d_ndmi = nir_arr + swir_arr
        ndvi_arr = np.where((d_ndvi != 0) & np.isfinite(d_ndvi), (nir_arr - red_arr) / d_ndvi, np.nan)
        ndmi_arr = np.where((d_ndmi != 0) & np.isfinite(d_ndmi), (nir_arr - swir_arr) / d_ndmi, np.nan)

    ndvi_out = np.where(np.isfinite(ndvi_arr), np.clip(ndvi_arr, -1.0, 1.0), np.nan).astype(np.float32)
    ndmi_out = np.where(np.isfinite(ndmi_arr), np.clip(ndmi_arr, -1.0, 1.0), np.nan).astype(np.float32)
    return ndvi_out, ndmi_out


def load_h3_soil_lookup(
    soil_h3_parquet: str | Path = Path("data/soil/field_soil_h3_cells.parquet"),
) -> dict[str, tuple[np.ndarray, np.ndarray, dict[str, np.ndarray]]]:
    """
    Buduje szybki słownik komórek H3 pogrupowanych wg `field_id` do przypisywania
    gleby dla pojedynczych pikseli 10 m.
    """
    h3_path = Path(soil_h3_parquet)
    if not h3_path.exists():
        return {}

    df = pd.read_parquet(h3_path)
    required = {"field_id", "cell_lat", "cell_lon"}
    if df.empty or not required.issubset(df.columns):
        return {}

    df = df.copy()
    df["field_id"] = df["field_id"].astype(str)
    df["cell_lat"] = pd.to_numeric(df["cell_lat"], errors="coerce")
    df["cell_lon"] = pd.to_numeric(df["cell_lon"], errors="coerce")
    df = df[df["cell_lat"].notna() & df["cell_lon"].notna()].reset_index(drop=True)
    if df.empty:
        return {}

    for col in PIXEL_SOIL_VALUE_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    lookup: dict[str, tuple[np.ndarray, np.ndarray, dict[str, np.ndarray]]] = {}
    present_soil_cols = [c for c in PIXEL_SOIL_VALUE_COLS if c in df.columns]
    has_h3_idx = "h3_index_10" in df.columns

    for fid, grp in df.groupby("field_id", sort=False):
        lats = grp["cell_lat"].to_numpy(dtype=np.float64)
        lons = grp["cell_lon"].to_numpy(dtype=np.float64)
        cols_data: dict[str, np.ndarray] = {
            col: grp[col].to_numpy(dtype=np.float32) for col in present_soil_cols
        }
        if has_h3_idx:
            cols_data["h3_index_10"] = grp["h3_index_10"].astype(str).to_numpy()
        lookup[fid] = (lats, lons, cols_data)

    return lookup


def assign_pixels_to_h3_soil(
    field_id: str,
    pixel_lats: np.ndarray,
    pixel_lons: np.ndarray,
    h3_lookup: dict[str, tuple[np.ndarray, np.ndarray, dict[str, np.ndarray]]],
    fallback_row: dict,
) -> dict[str, np.ndarray]:
    """
    Przypisuje każdy piksel (pixel_lats, pixel_lons) do najbliższej komórki H3 w ramach
    tego samego pola, z bezpiecznym fallbackiem na profil całego pola.
    """
    n_px = len(pixel_lats)
    entry = h3_lookup.get(str(field_id))

    if entry is not None and n_px > 0:
        c_lats, c_lons, c_cols = entry
        cos_lat = float(np.cos(np.deg2rad(np.mean(c_lats))))
        d2 = (pixel_lats[:, None] - c_lats[None, :]) ** 2 + (
            (pixel_lons[:, None] - c_lons[None, :]) * cos_lat
        ) ** 2
        nearest = np.argmin(d2, axis=1)
    else:
        c_cols = {}
        nearest = None

    out: dict[str, np.ndarray] = {}
    if nearest is not None and "h3_index_10" in c_cols:
        out["h3_index_10"] = c_cols["h3_index_10"][nearest]
    else:
        out["h3_index_10"] = np.asarray([None] * n_px, dtype=object)

    for col in PIXEL_SOIL_VALUE_COLS:
        raw_fb = fallback_row.get(col, 0.0)
        try:
            fb_val = float(raw_fb)
        except (TypeError, ValueError):
            fb_val = 0.0
        if not np.isfinite(fb_val):
            fb_val = 0.0

        if nearest is not None and col in c_cols:
            vals = c_cols[col][nearest].astype(np.float32, copy=True)
            vals = np.where(np.isfinite(vals), vals, fb_val).astype(np.float32)
        else:
            vals = np.full(n_px, fb_val, dtype=np.float32)
        out[col] = vals

    return out


def extract_satellite_indices_from_tiffs(
    fields_geojson: str | Path,
    tiff_inputs: str | Path | Iterable[str | Path | tuple[str, str | Path]],
    out_path: str | Path = DEFAULT_DATA_DIR / "satellite_indices.parquet",
    id_col: str = "id",
    min_valid_ratio: float = 0.5,
) -> pd.DataFrame:
    """
    Wyciąga średnie NDVI i NDMI dla każdego pola z plików GeoTIFF wygenerowanych
    przez satelite_img_downloader.ipynb (pasma NDVI/NDMI albo raw red/nir/swir16).
    Odrzuca obserwacje z udziałem poprawnych pikseli < min_valid_ratio (zachmurzenie).
    """
    gdf = gpd.read_file(fields_geojson)
    if id_col and id_col in gdf.columns:
        gdf["field_id"] = gdf[id_col].astype(str)
    else:
        gdf["field_id"] = [f"field_{i}" for i in range(len(gdf))]
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")

    items = _normalize_tiff_inputs(tiff_inputs)
    rows: list[dict] = []

    for obs_date, tif_path in items:
        with rasterio.open(tif_path) as src:
            has_precomputed, band_indexes = detect_scene_bands(src)
            fields_crs = gdf.to_crs(src.crs)
            raster_box = box(*src.bounds)

            for field_row in fields_crs.itertuples():
                geom = field_row.geometry
                if geom is None or geom.is_empty or not geom.intersects(raster_box):
                    continue

                try:
                    masked, out_transform = rasterio.mask.mask(
                        src, [geom], indexes=band_indexes, crop=True, filled=False
                    )
                except ValueError:
                    continue

                arr = np.where(masked.mask, np.nan, masked.data.astype(np.float32))
                poly_mask = geometry_mask(
                    [geom],
                    out_shape=(arr.shape[1], arr.shape[2]),
                    transform=out_transform,
                    invert=True,
                )
                total_poly_px = int(poly_mask.sum())
                if total_poly_px == 0:
                    continue

                ndvi_arr, ndmi_arr = arrays_to_ndvi_ndmi(arr, has_precomputed=has_precomputed)
                valid_mask = poly_mask & np.isfinite(ndvi_arr) & np.isfinite(ndmi_arr)
                valid_px = int(valid_mask.sum())
                valid_ratio = valid_px / float(total_poly_px)
                if valid_px == 0 or valid_ratio < min_valid_ratio:
                    continue

                ndvi_val = float(np.clip(np.mean(ndvi_arr[valid_mask]), -1.0, 1.0))
                ndmi_val = float(np.clip(np.mean(ndmi_arr[valid_mask]), -1.0, 1.0))
                rows.append(
                    {
                        "field_id": field_row.field_id,
                        "date": obs_date,
                        "ndvi": round(ndvi_val, 4),
                        "ndmi": round(ndmi_val, 4),
                        "valid_pixel_ratio": round(valid_ratio, 3),
                    }
                )

    cols = ["field_id", "date", "ndvi", "ndmi", "valid_pixel_ratio"]
    out = pd.DataFrame(rows, columns=cols)
    if not out.empty:
        out = (
            out.sort_values(["field_id", "date", "valid_pixel_ratio"])
            .drop_duplicates(subset=["field_id", "date"], keep="last")
            .reset_index(drop=True)
        )

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(out_path, index=False)
    print(f"[ML PREP] Zapisano satellite_indices ({len(out)} obserwacji) -> {out_path}")
    return out


def extract_pixel_dataset_from_tiffs(
    fields_geojson: str | Path,
    tiff_inputs: str | Path | Iterable[str | Path | tuple[str, str | Path]],
    soil_h3_parquet: str | Path = Path("data/soil/field_soil_h3_cells.parquet"),
    fields_master_parquet: str | Path = DEFAULT_DATA_DIR / "fields_master.parquet",
    out_master_path: str | Path = DEFAULT_DATA_DIR / "pixel_master.parquet",
    out_sat_path: str | Path = DEFAULT_DATA_DIR / "pixel_satellite_indices.parquet",
    id_col: str = "id",
    min_area_ha: float = 3.0,
    pixels_per_field: int = 32,
    min_valid_scenes: int = 3,
    seed: int = 42,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Próbkuje stratyfikowane piksele 10 m z wnętrza każdego pola na bazie scen Sentinel-2,
    łączy każdy piksel z najbliższą komórką glebową H3 (`field_soil_h3_cells.parquet`)
    i zapisuje tabele `pixel_master.parquet` oraz `pixel_satellite_indices.parquet`.
    """
    items = _normalize_tiff_inputs(tiff_inputs)
    if not items:
        raise ValueError("Brak plików GeoTIFF do ekstrakcji zestawu pikselowego.")

    gdf = gpd.read_file(fields_geojson)
    if id_col and id_col in gdf.columns:
        gdf["field_id"] = gdf[id_col].astype(str)
    else:
        gdf["field_id"] = [f"field_{i}" for i in range(len(gdf))]
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")

    master_path = Path(fields_master_parquet)
    fields_meta_by_id: dict[str, dict] = {}
    if master_path.exists():
        fm_df = pd.read_parquet(master_path)
        fm_df["field_id"] = fm_df["field_id"].astype(str)
        fields_meta_by_id = {row["field_id"]: row for row in fm_df.to_dict("records")}
        gdf = gdf[gdf["field_id"].isin(fields_meta_by_id)].copy()

    if gdf.empty:
        raise ValueError("Brak pasujących pól między GeoJSON a fields_master.parquet.")

    with rasterio.open(items[0][1]) as ref_src:
        ref_crs = ref_src.crs
        ref_transform = ref_src.transform
        ref_height = ref_src.height
        ref_width = ref_src.width

    gdf_utm = gdf.to_crs(ref_crs).reset_index(drop=True)
    field_records: list[dict] = []
    shapes: list[tuple] = []

    for row in gdf_utm.itertuples():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        fid = str(row.field_id)
        meta = fields_meta_by_id.get(fid)
        if meta is not None:
            area_ha = float(meta.get("area_ha", geom.area / 10000.0))
            crop_code = meta.get("crop_code", np.nan)
            crop_name = str(meta.get("crop", "inne"))
            fallback = dict(meta)
        else:
            area_ha = float(getattr(row, "area_ha", geom.area / 10000.0))
            crop_code = getattr(row, "crop_code", np.nan)
            crop_name = _map_crop_name(crop_code)
            fallback = {"area_ha": area_ha, "crop_code": crop_code, "crop": crop_name}

        if area_ha < min_area_ha:
            continue

        label_idx = len(field_records) + 1
        shapes.append((geom, label_idx))
        field_records.append(
            {
                "field_id": fid,
                "area_ha": area_ha,
                "crop_code": crop_code,
                "crop": crop_name,
                "fallback": fallback,
            }
        )

    if not shapes:
        raise ValueError("Brak ważnych poligonów pól po filtrowaniu min_area_ha.")

    label_grid = rasterio.features.rasterize(
        shapes=shapes,
        out_shape=(ref_height, ref_width),
        transform=ref_transform,
        fill=0,
        dtype=np.int32,
    )
    rows_all, cols_all = np.nonzero(label_grid > 0)
    if len(rows_all) == 0:
        raise ValueError("Żaden piksel Sentinel-2 nie leży wewnątrz geometrii pól.")

    labels_1d = label_grid[rows_all, cols_all]
    order = np.argsort(labels_1d, kind="mergesort")
    labels_sorted = labels_1d[order]
    rows_sorted = rows_all[order].astype(np.int32)
    cols_sorted = cols_all[order].astype(np.int32)

    n_scenes = len(items)
    n_px_total = len(rows_sorted)
    ndvi_seq = np.full((n_scenes, n_px_total), np.nan, dtype=np.float32)
    ndmi_seq = np.full((n_scenes, n_px_total), np.nan, dtype=np.float32)
    scene_dates: list[str] = []

    for t_idx, (obs_date, tif_path) in enumerate(items):
        scene_dates.append(obs_date)
        with rasterio.open(tif_path) as src:
            has_precomputed, band_indexes = detect_scene_bands(src)
            same_grid = (
                src.crs == ref_crs
                and src.transform == ref_transform
                and src.width == ref_width
                and src.height == ref_height
            )
            if same_grid:
                ma = src.read(band_indexes, masked=True)
            else:
                with WarpedVRT(
                    src,
                    crs=ref_crs,
                    transform=ref_transform,
                    width=ref_width,
                    height=ref_height,
                    resampling=Resampling.bilinear,
                    nodata=np.nan,
                ) as vrt:
                    ma = vrt.read(band_indexes, masked=True)

            arr = np.where(ma.mask, np.nan, ma.data.astype(np.float32))
            ndvi_2d, ndmi_2d = arrays_to_ndvi_ndmi(arr, has_precomputed=has_precomputed, nodata=src.nodata)
            ndvi_seq[t_idx] = ndvi_2d[rows_sorted, cols_sorted]
            ndmi_seq[t_idx] = ndmi_2d[rows_sorted, cols_sorted]

    rng = np.random.default_rng(seed)
    eff_min_valid = min(max(1, int(min_valid_scenes)), n_scenes)
    h3_lookup = load_h3_soil_lookup(soil_h3_parquet)

    split_pts = np.flatnonzero(np.diff(labels_sorted)) + 1
    starts = np.concatenate(([0], split_pts))
    ends = np.concatenate((split_pts, [n_px_total]))

    sel_global_idxs: list[np.ndarray] = []
    sel_field_meta_idxs: list[int] = []
    sel_n_valid: list[np.ndarray] = []

    for start_i, end_i in zip(starts, ends):
        label_idx = int(labels_sorted[start_i]) - 1
        f_ndvi = ndvi_seq[:, start_i:end_i]
        f_ndmi = ndmi_seq[:, start_i:end_i]
        valid_tp = np.isfinite(f_ndvi) & np.isfinite(f_ndmi)
        n_valid_px = valid_tp.sum(axis=0)
        cand_local = np.flatnonzero(n_valid_px >= eff_min_valid)
        if len(cand_local) == 0:
            continue

        if len(cand_local) <= pixels_per_field:
            chosen_local = cand_local
        else:
            mean_ndvi = np.nanmean(np.where(valid_tp[:, cand_local], f_ndvi[:, cand_local], np.nan), axis=0)
            sorted_cand = cand_local[np.argsort(mean_ndvi, kind="mergesort")]
            strata = np.array_split(sorted_cand, pixels_per_field)
            chosen_local = np.asarray(
                [int(chunk[rng.integers(0, len(chunk))]) for chunk in strata if len(chunk) > 0],
                dtype=np.int64,
            )

        sel_global_idxs.append(start_i + chosen_local)
        sel_field_meta_idxs.extend([label_idx] * len(chosen_local))
        sel_n_valid.append(n_valid_px[chosen_local])

    if not sel_global_idxs:
        raise ValueError("Żaden piksel nie spełnił kryterium min_valid_scenes obserwacji.")

    all_sel_idx = np.concatenate(sel_global_idxs)
    all_sel_rows = rows_sorted[all_sel_idx]
    all_sel_cols = cols_sorted[all_sel_idx]
    all_sel_nvalid = np.concatenate(sel_n_valid).astype(np.int32)
    all_meta_idxs = np.asarray(sel_field_meta_idxs, dtype=np.int32)

    xs_utm, ys_utm = rasterio.transform.xy(ref_transform, all_sel_rows, all_sel_cols, offset="center")
    lons, lats = rasterio.warp.transform(
        ref_crs,
        "EPSG:4326",
        np.asarray(xs_utm, dtype=np.float64),
        np.asarray(ys_utm, dtype=np.float64),
    )
    pixel_lons = np.asarray(lons, dtype=np.float64)
    pixel_lats = np.asarray(lats, dtype=np.float64)

    n_selected = len(all_sel_idx)
    pixel_ids = [
        f"{field_records[m_idx]['field_id']}_r{int(r)}_c{int(c)}"
        for m_idx, r, c in zip(all_meta_idxs, all_sel_rows, all_sel_cols)
    ]
    field_ids_col = [field_records[m_idx]["field_id"] for m_idx in all_meta_idxs]
    area_col = np.asarray([field_records[m_idx]["area_ha"] for m_idx in all_meta_idxs], dtype=np.float32)
    crop_code_col = np.asarray([field_records[m_idx]["crop_code"] for m_idx in all_meta_idxs], dtype=np.float64)
    crop_col = [field_records[m_idx]["crop"] for m_idx in all_meta_idxs]

    soil_arrays: dict[str, np.ndarray] = {
        col: np.zeros(n_selected, dtype=np.float32) for col in PIXEL_SOIL_VALUE_COLS
    }
    h3_col = np.asarray([None] * n_selected, dtype=object)

    # Grupowane przypisanie gleby H3 wg field_id (1 macierz odległości na pole)
    pos_by_meta: dict[int, list[int]] = {}
    for pos_i, m_idx in enumerate(all_meta_idxs):
        pos_by_meta.setdefault(int(m_idx), []).append(pos_i)

    for m_idx, pos_list in pos_by_meta.items():
        pos_arr = np.asarray(pos_list, dtype=np.int64)
        rec = field_records[m_idx]
        assigned = assign_pixels_to_h3_soil(
            field_id=rec["field_id"],
            pixel_lats=pixel_lats[pos_arr],
            pixel_lons=pixel_lons[pos_arr],
            h3_lookup=h3_lookup,
            fallback_row=rec["fallback"],
        )
        h3_col[pos_arr] = assigned["h3_index_10"]
        for col in PIXEL_SOIL_VALUE_COLS:
            soil_arrays[col][pos_arr] = assigned[col]

    pixel_master_df = pd.DataFrame(
        {
            "pixel_id": pixel_ids,
            "field_id": field_ids_col,
            "h3_index_10": h3_col,
            "row": all_sel_rows,
            "col": all_sel_cols,
            "pixel_lat": np.round(pixel_lats, 6),
            "pixel_lon": np.round(pixel_lons, 6),
            "area_ha": area_col,
            "crop_code": crop_code_col,
            "crop": crop_col,
            **soil_arrays,
            "n_valid_scenes": all_sel_nvalid,
        }
    )

    sel_ndvi = ndvi_seq[:, all_sel_idx]
    sel_ndmi = ndmi_seq[:, all_sel_idx]
    valid_sel = np.isfinite(sel_ndvi) & np.isfinite(sel_ndmi)
    t_idxs, p_idxs = np.nonzero(valid_sel)

    pixel_id_arr = np.asarray(pixel_ids, dtype=object)
    field_id_arr = np.asarray(field_ids_col, dtype=object)
    date_arr = np.asarray(scene_dates, dtype=object)

    pixel_sat_df = pd.DataFrame(
        {
            "pixel_id": pixel_id_arr[p_idxs],
            "field_id": field_id_arr[p_idxs],
            "date": date_arr[t_idxs],
            "ndvi": np.round(sel_ndvi[t_idxs, p_idxs], 4).astype(np.float32),
            "ndmi": np.round(sel_ndmi[t_idxs, p_idxs], 4).astype(np.float32),
        }
    )
    if len(set(scene_dates)) < len(scene_dates) and not pixel_sat_df.empty:
        pixel_sat_df = pixel_sat_df.drop_duplicates(subset=["pixel_id", "date"], keep="last").reset_index(drop=True)

    out_master_path = Path(out_master_path)
    out_sat_path = Path(out_sat_path)
    out_master_path.parent.mkdir(parents=True, exist_ok=True)
    out_sat_path.parent.mkdir(parents=True, exist_ok=True)
    pixel_master_df.to_parquet(out_master_path, index=False)
    pixel_sat_df.to_parquet(out_sat_path, index=False)
    print(
        f"[ML PREP] Zapisano pixel_master ({len(pixel_master_df)} pikseli / {len(pos_by_meta)} pól) -> {out_master_path}"
    )
    print(
        f"[ML PREP] Zapisano pixel_satellite_indices ({len(pixel_sat_df)} obserwacji) -> {out_sat_path}"
    )
    return pixel_master_df, pixel_sat_df


def _map_fields_to_nearest_grid(
    fields_df: pd.DataFrame,
    grid_df: pd.DataFrame,
    grid_key_cols: list[str],
) -> pd.DataFrame:
    cols = list(dict.fromkeys([*grid_key_cols, "lat", "lon"]))
    g_pts = grid_df[cols].drop_duplicates().reset_index(drop=True)
    g_lats = g_pts["lat"].to_numpy(dtype=np.float64)
    g_lons = g_pts["lon"].to_numpy(dtype=np.float64)

    mapped_rows = []
    for row in fields_df.itertuples():
        cos_lat = float(np.cos(np.radians(row.centroid_lat)))
        dist2 = (g_lats - row.centroid_lat) ** 2 + ((g_lons - row.centroid_lon) * cos_lat) ** 2
        best = g_pts.iloc[int(np.argmin(dist2))]
        rec = {"field_id": row.field_id}
        for col in grid_key_cols:
            val = best[col]
            rec[col] = val.item() if hasattr(val, "item") else val
        mapped_rows.append(rec)
    return pd.DataFrame(mapped_rows)


def build_weather_table_from_bayer(
    fields_master_parquet: str | Path,
    bayer_weather_parquets: str | Path | list[str | Path],
    weather_grids_parquet: str | Path,
    imerg_daily_parquet: str | Path | None = None,
    out_path: str | Path = DEFAULT_DATA_DIR / "weather_daily.parquet",
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    """
    Buduje kanoniczną tabelę pogody dziennej dla pól na bazie historycznych
    plików Bayer (2020-2025). Obsługuje przypadek braku kolumny total_precipitation
    w plikach Bayera, podpinając wtedy opady satelitarne IMERG (imerg_precipitation_daily).
    """
    fields_df = pd.read_parquet(fields_master_parquet)
    grids_df = pd.read_parquet(weather_grids_parquet)
    field_grid_df = _map_fields_to_nearest_grid(fields_df, grids_df, ["grid_id"])

    if isinstance(bayer_weather_parquets, (str, Path)):
        p = Path(bayer_weather_parquets)
        parquet_list = [str(f) for f in sorted(p.rglob("*.parquet"))] if p.is_dir() else [str(p)]
    else:
        parquet_list = [str(Path(f)) for f in bayer_weather_parquets]

    if not parquet_list:
        raise FileNotFoundError("Brak plików Parquet z danymi pogodowymi Bayera.")

    con = duckdb.connect()
    con.register("field_grid_map", field_grid_df)

    bayer_cols = set(
        con.execute("DESCRIBE SELECT * FROM read_parquet($1)", [parquet_list[0]])
        .df()["column_name"]
        .tolist()
    )
    has_bayer_precip = "total_precipitation" in bayer_cols

    imerg_join = ""
    if imerg_daily_parquet is not None:
        imerg_p = Path(imerg_daily_parquet).as_posix()
        imerg_join = (
            f"LEFT JOIN read_parquet('{imerg_p}') AS i "
            "ON b.grid_id = i.grid_id AND CAST(b.date AS DATE) = CAST(i.date AS DATE)"
        )
        if has_bayer_precip:
            precip_expr = "COALESCE(CAST(b.total_precipitation AS DOUBLE), CAST(i.total_precipitation AS DOUBLE), 0.0)"
        else:
            precip_expr = "COALESCE(CAST(i.total_precipitation AS DOUBLE), 0.0)"
    else:
        if has_bayer_precip:
            precip_expr = "COALESCE(CAST(b.total_precipitation AS DOUBLE), 0.0)"
        else:
            print(
                "[UWAGA] W plikach Bayera brakuje kolumny total_precipitation i nie podano "
                "imerg_daily_parquet — wypełniam precip_sum_mm zerami."
            )
            precip_expr = "0.0"

    where_clauses = []
    params: list = [parquet_list]
    if start_date is not None:
        where_clauses.append("CAST(b.date AS DATE) >= CAST($2 AS DATE)")
        params.append(start_date)
    if end_date is not None:
        idx = len(params) + 1
        where_clauses.append(f"CAST(b.date AS DATE) <= CAST(${idx} AS DATE)")
        params.append(end_date)
    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    sql = f"""
        SELECT
            m.field_id,
            strftime(CAST(b.date AS DATE), '%Y-%m-%d') AS date,
            CAST(b.avg_temperature AS DOUBLE) AS temp_mean_c,
            CAST(b.min_temperature AS DOUBLE) AS temp_min_c,
            CAST(b.max_temperature AS DOUBLE) AS temp_max_c,
            {precip_expr} AS precip_sum_mm,
            CAST(b.avg_soil_moisture_level_1 AS DOUBLE) AS sm_l1,
            CAST(b.avg_soil_moisture_level_2 AS DOUBLE) AS sm_l2,
            CAST(b.avg_soil_moisture_level_3 AS DOUBLE) AS sm_l3
        FROM field_grid_map AS m
        JOIN read_parquet($1) AS b
          ON m.grid_id = b.grid_id
        {imerg_join}
        {where_sql}
        ORDER BY m.field_id, date
    """
    out = con.execute(sql, params).df()
    out = out[["field_id", "date", *WEATHER_COLS]]

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(out_path, index=False)
    print(f"[ML PREP] Zapisano weather_daily z Bayera ({len(out)} wierszy) -> {out_path}")
    return out


def build_weather_table_from_open_meteo(
    fields_master_parquet: str | Path,
    open_meteo_parquet: str | Path,
    out_path: str | Path = DEFAULT_DATA_DIR / "weather_daily_open_meteo.parquet",
) -> pd.DataFrame:
    """
    Mapuje dzienne dane Open-Meteo (z kw/meteo.py) na najbliższe punkty siatki
    dla każdego pola i zapisuje w tym samym schemacie co Bayer.
    """
    fields_df = pd.read_parquet(fields_master_parquet)
    om_df = pd.read_parquet(open_meteo_parquet)
    if "sm_l3" not in om_df.columns and "sm_l2" in om_df.columns:
        print("[INFO] Brak kolumny sm_l3 w danych Open-Meteo — podstawiam sm_l2 jako przybliżenie głębszej warstwy.")
        om_df = om_df.copy()
        om_df["sm_l3"] = om_df["sm_l2"]
    field_pt_df = _map_fields_to_nearest_grid(fields_df, om_df, ["lat", "lon"])

    merged = field_pt_df.merge(om_df, on=["lat", "lon"], how="inner")
    out = merged[["field_id", "date", *WEATHER_COLS]].sort_values(["field_id", "date"]).reset_index(drop=True)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(out_path, index=False)
    print(f"[ML PREP] Zapisano weather_daily z Open-Meteo ({len(out)} wierszy) -> {out_path}")
    return out


def generate_synthetic_demo_dataset(
    out_dir: str | Path = DEFAULT_DATA_DIR / "demo",
    n_fields: int = 12,
    n_days: int = 140,
    seed: int = 42,
) -> Path:
    """
    Generuje kompletny syntetyczny zbiór treningowy (fields_master, weather_daily,
    satellite_indices) zgodny ze schematem produkcyjnym do testów end-to-end.
    """
    rng = np.random.default_rng(seed)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    crops = ["pszenica", "kukurydza", "rzepak"]
    crop_codes = {"pszenica": 1110, "kukurydza": 1130, "rzepak": 1430}

    field_rows = []
    for i in range(n_fields):
        crop = crops[i % len(crops)]
        sand = float(rng.uniform(35.0, 75.0))
        clay = float(rng.uniform(8.0, 25.0))
        silt = round(100.0 - sand - clay, 1)
        is_sandy = sand >= 65.0
        field_rows.append(
            {
                "field_id": f"demo_field_{i}",
                "area_ha": round(float(rng.uniform(4.0, 25.0)), 2),
                "centroid_lat": round(52.6 + float(rng.uniform(-0.04, 0.04)), 6),
                "centroid_lon": round(20.8 + float(rng.uniform(-0.08, 0.08)), 6),
                "crop_code": crop_codes[crop],
                "crop": crop,
                "sand_pct": round(sand, 1),
                "silt_pct": silt,
                "clay_pct": round(clay, 1),
                "ph": round(float(rng.uniform(5.4, 7.1)), 2),
                "om": round(float(rng.uniform(2.5, 5.5)), 2),
                "cec": round(float(rng.uniform(12.0, 22.0)), 2),
                "bulk_density": round(float(rng.uniform(1.25, 1.48)), 2),
                "band_ph": "moderate",
                "band_om": "high",
                "band_cec": "moderate",
                "permeability": "wysoka" if is_sandy else "srednia",
                "water_retention": "niska" if is_sandy else "srednia",
                "wilting_point": 0.08 if is_sandy else 0.13,
                "field_capacity": 0.18 if is_sandy else 0.28,
                "awc_mm_per_m": 100.0 if is_sandy else 150.0,
                "soilTexture": "Sandy Loam" if is_sandy else "Loam",
            }
        )
    fields_df = pd.DataFrame(field_rows)
    fields_df.to_parquet(out_dir / "fields_master.parquet", index=False)

    start_d = date(2024, 3, 15)
    weather_rows = []
    sat_rows = []

    for f_row in field_rows:
        fid = f_row["field_id"]
        crop = f_row["crop"]
        wp, fc = f_row["wilting_point"], f_row["field_capacity"]
        sm1 = 0.5 * (wp + fc)
        sm2 = 0.55 * (wp + fc)
        sm3 = 0.6 * (wp + fc)
        phase = 0.0 if crop == "pszenica" else (15.0 if crop == "kukurydza" else -10.0)

        for d_idx in range(n_days):
            cur_d = start_d + timedelta(days=d_idx)
            doy = cur_d.timetuple().tm_yday
            temp_mean = 12.0 + 8.0 * np.sin(2 * np.pi * (doy - 95) / 365.0) + float(rng.normal(0, 1.8))
            temp_min = temp_mean - float(rng.uniform(3.0, 6.0))
            temp_max = temp_mean + float(rng.uniform(3.5, 7.0))
            precip = float(rng.exponential(3.5)) if rng.random() < 0.25 else 0.0

            sm1 = float(np.clip(sm1 + 0.008 * precip - 0.0025 * max(temp_mean, 0.0), wp * 0.85, fc * 1.1))
            sm2 = float(np.clip(0.92 * sm2 + 0.08 * sm1 + 0.002 * precip, wp * 0.9, fc * 1.05))
            sm3 = float(np.clip(0.96 * sm3 + 0.04 * sm2, wp, fc))

            weather_rows.append(
                {
                    "field_id": fid,
                    "date": cur_d.isoformat(),
                    "temp_mean_c": round(temp_mean, 2),
                    "temp_min_c": round(temp_min, 2),
                    "temp_max_c": round(temp_max, 2),
                    "precip_sum_mm": round(precip, 2),
                    "sm_l1": round(sm1, 3),
                    "sm_l2": round(sm2, 3),
                    "sm_l3": round(sm3, 3),
                }
            )

            # Nieregularne obserwacje Sentinel-2 co ~5 dni z losowym zachmurzeniem
            if d_idx % 5 == 0 and rng.random() > 0.22:
                moisture_norm = (sm2 - wp) / max(fc - wp, 0.05)
                ndvi = float(
                    np.clip(
                        0.30 + 0.45 * np.exp(-((d_idx - 75 - phase) / 42.0) ** 2) + 0.08 * (moisture_norm - 0.5)
                        + rng.normal(0, 0.015),
                        0.05,
                        0.92,
                    )
                )
                ndmi = float(
                    np.clip(
                        -0.05 + 0.35 * np.exp(-((d_idx - 70 - phase) / 40.0) ** 2) + 0.16 * (moisture_norm - 0.5)
                        + rng.normal(0, 0.015),
                        -0.4,
                        0.65,
                    )
                )
                sat_rows.append(
                    {
                        "field_id": fid,
                        "date": cur_d.isoformat(),
                        "ndvi": round(ndvi, 4),
                        "ndmi": round(ndmi, 4),
                        "valid_pixel_ratio": round(float(rng.uniform(0.7, 1.0)), 3),
                    }
                )

    pd.DataFrame(weather_rows).to_parquet(out_dir / "weather_daily.parquet", index=False)
    pd.DataFrame(sat_rows).to_parquet(out_dir / "satellite_indices.parquet", index=False)
    print(f"[ML DEMO] Wygenerowano dane demo ({n_fields} pól x {n_days} dni) -> {out_dir}")
    return out_dir


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Przygotowanie tabel ML (fields_master / pixel_master / --demo)."
    )
    parser.add_argument("--demo", action="store_true", help="Wygeneruj syntetyczny zestaw demo w data/ml/demo.")
    parser.add_argument("--pixels", action="store_true", help="Zbuduj tabele pikselowe pixel_master i pixel_satellite_indices.")
    parser.add_argument("--fields-geojson", type=Path, default=Path("data/fields/lowicki_fields_crops.geojson"))
    parser.add_argument("--tiff-dir", type=Path, default=Path("data/satellite/lowicki_2024-03-01_to_2024-10-31"))
    parser.add_argument("--soil-h3-parquet", type=Path, default=Path("data/soil/field_soil_h3_cells.parquet"))
    parser.add_argument("--pixels-per-field", type=int, default=9)
    parser.add_argument("--out-dir", type=Path, default=None, help="Katalog wyjściowy (domyślnie data/ml lub data/ml/demo).")
    args = parser.parse_args()

    if args.demo:
        target_dir = args.out_dir or (DEFAULT_DATA_DIR / "demo")
        generate_synthetic_demo_dataset(out_dir=target_dir)
    elif args.pixels:
        target_dir = args.out_dir or DEFAULT_DATA_DIR
        extract_pixel_dataset_from_tiffs(
            fields_geojson=args.fields_geojson,
            tiff_inputs=args.tiff_dir,
            soil_h3_parquet=args.soil_h3_parquet,
            fields_master_parquet=target_dir / "fields_master.parquet",
            out_master_path=target_dir / "pixel_master.parquet",
            out_sat_path=target_dir / "pixel_satellite_indices.parquet",
            pixels_per_field=args.pixels_per_field,
        )
    else:
        crops_geojson = Path("bk/fields_crops.geojson")
        soil_parquet = Path("data/soil/fields_soil_profiles.parquet")
        if crops_geojson.exists() and soil_parquet.exists():
            out_master = (args.out_dir or DEFAULT_DATA_DIR) / "fields_master.parquet"
            fm = build_fields_master(
                fields_crops_geojson=crops_geojson,
                soil_profiles_parquet=soil_parquet,
                out_path=out_master,
            )
            print("Kształt fields_master:", fm.shape)
            print("Uprawy:", fm["crop"].value_counts(dropna=False).to_dict())
        else:
            print(
                "[INFO] Brak wymaganych plików (bk/fields_crops.geojson i/lub data/soil/fields_soil_profiles.parquet).\n"
                "Najpierw uruchom `.venv/bin/python kw/soil.py` "
                "albo użyj `--demo`: `.venv/bin/python ml/prepare_dataset.py --demo`."
            )
