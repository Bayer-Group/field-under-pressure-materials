from datetime import date, timedelta
from pathlib import Path
import re
from typing import Iterable

import duckdb
import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import geometry_mask
import rasterio.mask
from shapely.geometry import box

from .config import (
    DEFAULT_DATA_DIR,
    MVP_CROP_CODE_TO_NAME,
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
    soil_profiles_parquet: str | Path = "fields_soil_profiles.parquet",
    out_path: str | Path = DEFAULT_DATA_DIR / "fields_master.parquet",
    id_col: str = "id",
    min_area_ha: float = 3.0,
    only_mvp_crops: bool = False,
) -> pd.DataFrame:
    """
    Łączy granice + kody upraw z bk/assign_crops.py (fields_crops.geojson)
    z profilami glebowymi z kw/soil_bonification.py (fields_soil_profiles.parquet).
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
            desc_map = {
                (src.descriptions[i] or "").strip().lower(): i + 1
                for i in range(src.count)
                if src.descriptions[i]
            }
            has_precomputed = "ndvi" in desc_map and "ndmi" in desc_map
            has_raw = {"red", "nir", "swir16"}.issubset(desc_map)
            if not has_precomputed and not has_raw:
                raise ValueError(
                    f"Plik {tif_path} musi zawierać opisane pasma ('NDVI', 'NDMI') "
                    "lub ('red', 'nir', 'swir16')."
                )

            fields_crs = gdf.to_crs(src.crs)
            raster_box = box(*src.bounds)
            band_indexes = (
                [desc_map["ndvi"], desc_map["ndmi"]]
                if has_precomputed
                else [desc_map["red"], desc_map["nir"], desc_map["swir16"]]
            )

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

                if has_precomputed:
                    ndvi_arr, ndmi_arr = arr[0], arr[1]
                else:
                    red_arr = np.where(arr[0] == 0, np.nan, arr[0])
                    nir_arr = np.where(arr[1] == 0, np.nan, arr[1])
                    swir_arr = np.where(arr[2] == 0, np.nan, arr[2])
                    d_ndvi = nir_arr + red_arr
                    d_ndmi = nir_arr + swir_arr
                    ndvi_arr = np.where((d_ndvi != 0) & np.isfinite(d_ndvi), (nir_arr - red_arr) / d_ndvi, np.nan)
                    ndmi_arr = np.where((d_ndmi != 0) & np.isfinite(d_ndmi), (nir_arr - swir_arr) / d_ndmi, np.nan)

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
