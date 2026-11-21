from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
import re
from typing import Literal
import zipfile

import duckdb
import geopandas as gpd
import h3
import numpy as np
import pandas as pd
from shapely import force_2d


Status = Literal["ZIELONY", "ZOLTY", "CZERWONY"]
Fertilizer = Literal["saletra_amonowa", "mocznik_inhibitor", "rsm_32", "saletrosan_26"]
Crop = str

SOIL_METHOD_NOTE = (
    "Parametry retencji wodnej (WP, FC, AWC) obliczone równaniami Saxtona & Rawlsa (2006) "
    "z frakcji SoilGrids 250m oraz natywnych klas ISRIC BAND_pH / BAND_om / BAND_cec "
    "(brak urzędowej polskiej klasy bonitacyjnej I–VI z IUNG-PIB/EGiB)."
)

CLMS_CROP_CODE_TO_NAME = {
    1110: "pszenica",
    1120: "jeczmien",
    1130: "kukurydza",
    1310: "ziemniak",
    1320: "burak_cukrowy",
    1410: "slonecznik",
    1420: "soja",
    1430: "rzepak",
}


@dataclass
class SoilProfile:
    field_id: str
    area_ha: float
    centroid_lat: float
    centroid_lon: float
    h3_cells_count: int
    sand_pct: float
    silt_pct: float
    clay_pct: float
    soilTexture: str
    ph: float
    permeability: Literal["wysoka", "srednia", "niska"]
    water_retention: Literal["niska", "srednia", "wysoka"]
    wilting_point: float
    field_capacity: float
    awc_mm_per_m: float
    soil_method_note: str = SOIL_METHOD_NOTE
    band_ph: str | None = None
    band_om: str | None = None
    band_cec: str | None = None
    zone: str | None = None
    crop_code: int | None = None
    crop: str | None = None
    om: float | None = None
    cec: float | None = None
    bulk_density: float | None = None
    sand_min_pct: float | None = None
    sand_max_pct: float | None = None
    ph_min: float | None = None
    ph_max: float | None = None
    soil_variability: Literal["niska", "umiarkowana", "wysoka"] = "niska"


# Zachowane aliasy dla wygody i czytelności wywołań per pole oraz per strefa
FieldSoilProfile = SoilProfile
ZoneSoilProfile = SoilProfile


# ==============================================================================
# ETAP 1: ROZPAKOWANIE SOILGRIDS + PROFILE GLEBOWE PER POLE, PER STREFA I H3
# ==============================================================================

def ensure_parquets_unpacked(soil_dir: str | Path) -> list[str]:
    """
    Przeszukuje folder soil_data/, rozpakowuje wszystkie pliki soil_*_isric_250_v2.zip
    (jeśli jeszcze nie są rozpakowane) i zwraca listę ścieżek do plików .parquet.
    """
    soil_dir = Path(soil_dir)
    for zip_path in sorted(soil_dir.glob("soil_*_isric_250_v2.zip")):
        extract_dir = soil_dir / zip_path.stem
        if not extract_dir.exists() or not list(extract_dir.glob("*.parquet")):
            print(f"[UNZIP] Rozpakowuję {zip_path.name}...")
            extract_dir.mkdir(exist_ok=True)
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(extract_dir)

    parquets = [p.as_posix() for p in sorted(soil_dir.rglob("*.parquet"))]
    if not parquets:
        raise FileNotFoundError(f"Brak plików .parquet w {soil_dir} (ani w podfolderach).")
    print(f"[ETAP 1] Znaleziono {len(parquets)} plików .parquet z województwami.")
    return parquets


def _prepare_geodataframe(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    gdf = gdf.copy()
    gdf["geometry"] = force_2d(gdf.geometry)

    minx, miny, maxx, maxy = gdf.total_bounds
    if max(abs(minx), abs(maxx)) > 180 or max(abs(miny), abs(maxy)) > 90:
        gdf = gdf.set_crs("EPSG:2180", allow_override=True)
    elif gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")

    gdf_2180 = gdf.to_crs("EPSG:2180")
    gdf["area_ha"] = (gdf_2180.geometry.area / 10_000.0).round(2)
    centroids_4326 = gdf_2180.geometry.centroid.to_crs("EPSG:4326")
    gdf["centroid_lon"] = centroids_4326.x.round(6)
    gdf["centroid_lat"] = centroids_4326.y.round(6)
    return gdf.to_crs("EPSG:4326")


def _map_crop_columns(gdf: gpd.GeoDataFrame) -> tuple[pd.Series, pd.Series]:
    """Wyciąga parę (crop_code, crop) z kolumn obecnych w GeoDataFrame."""
    crop_code = (
        pd.to_numeric(gdf["crop_code"], errors="coerce")
        if "crop_code" in gdf.columns
        else pd.Series(np.nan, index=gdf.index, dtype="float64")
    )
    crop_code = crop_code.map(lambda c: int(round(float(c))) if pd.notna(c) else None).astype("Int64")

    if "crop" in gdf.columns and gdf["crop"].notna().any():
        crop_name = gdf["crop"].astype("object")
        return crop_code, crop_name

    if "crop_type" in gdf.columns and gdf["crop_type"].notna().any():
        raw = gdf["crop_type"].astype("object")
        mapping = {
            "wheat": "pszenica",
            "barley": "jeczmien",
            "maize": "kukurydza",
            "corn": "kukurydza",
            "rapeseed": "rzepak",
            "sugar beet": "burak_cukrowy",
            "potatoes": "ziemniak",
            "sunflower": "slonecznik",
            "soybeans": "soja",
        }
        crop_name = raw.map(
            lambda v: mapping.get(str(v).strip().lower(), str(v).strip().lower()) if pd.notna(v) else None
        )
        return crop_code, crop_name

    if "crop_code" in gdf.columns and crop_code.notna().any():
        crop_name = crop_code.map(
            lambda c: CLMS_CROP_CODE_TO_NAME.get(int(c), "inne") if pd.notna(c) else None
        ).astype("object")
        return crop_code, crop_name

    return crop_code, pd.Series([None] * len(gdf), index=gdf.index, dtype="object")


def _attach_crops(
    gdf: gpd.GeoDataFrame,
    geojson_path: str | Path | None = None,
    crops_geojson: str | Path | None = None,
    assign_crops_year: int | None = None,
) -> tuple[pd.Series, pd.Series]:
    """
    Dołącza kody i nazwy upraw z trzech możliwych źródeł:
    1) kolumny już obecne w wejściowym GeoJSON (crop_code / crop_type / crop),
    2) zewnętrzny plik crops_geojson wygenerowany przez bk/assign_crops.py (np. bk/fields_crops.geojson),
    3) bezpośrednie uruchomienie CropDetector z bk/assign_crops.py, jeśli podano assign_crops_year.
    """
    crop_code, crop_name = _map_crop_columns(gdf)
    if crop_name.notna().any() or crop_code.notna().any():
        return crop_code, crop_name

    if crops_geojson is not None:
        crops_path = Path(crops_geojson)
        if not crops_path.exists():
            raise FileNotFoundError(f"Nie znaleziono pliku z uprawami: {crops_path}")
        crops_gdf = _prepare_geodataframe(gpd.read_file(crops_path))
        c_code, c_name = _map_crop_columns(crops_gdf)
        crops_lookup = gpd.GeoDataFrame(
            {"_crop_code": c_code, "_crop": c_name, "geometry": crops_gdf.geometry},
            crs=crops_gdf.crs,
        ).to_crs("EPSG:2180")

        points = gpd.GeoDataFrame(
            {"_orig_idx": gdf.index, "geometry": gdf.to_crs("EPSG:2180").geometry.representative_point()},
            crs="EPSG:2180",
        )
        joined = gpd.sjoin(points, crops_lookup, how="left", predicate="within")
        joined = joined.drop_duplicates(subset=["_orig_idx"]).set_index("_orig_idx")

        matched_code = joined["_crop_code"].reindex(gdf.index).astype("Int64")
        matched_name = joined["_crop"].reindex(gdf.index).astype("object")
        if matched_name.notna().any() or matched_code.notna().any():
            return matched_code, matched_name

    if assign_crops_year is not None and geojson_path is not None:
        from bk.assign_crops import CropDetector

        detector = CropDetector(year=assign_crops_year)
        detected_gdf = detector.detect(str(geojson_path))
        return _map_crop_columns(detected_gdf)

    return crop_code, crop_name


def _normalize_band(val) -> str | None:
    if val is None or (isinstance(val, float) and np.isnan(val)) or pd.isna(val):
        return None
    s = str(val).strip().lower()
    return None if s in ("", "nan", "none", "null") else s


def _geom_to_h3_cells(geom) -> list[str]:
    cells: list[str] = []
    if geom is None or geom.is_empty:
        return cells
    parts = list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom]
    for part in parts:
        try:
            cells.extend(h3.geo_to_cells(part.__geo_interface__, res=10))
        except Exception:
            pass
    if not cells:
        c = geom.centroid
        cells = [h3.latlng_to_cell(c.y, c.x, 10)]
    return [str(c).strip().lower() for c in cells]


def _polyfill_h3_mapping(gdf_4326: gpd.GeoDataFrame, key_cols: list[str]) -> pd.DataFrame:
    rows = []
    for _, row in gdf_4326.iterrows():
        cells = _geom_to_h3_cells(row.geometry)
        base = {col: row[col] for col in key_cols}
        for cell in cells:
            rows.append({**base, "h3_index_10": cell})
    return pd.DataFrame(rows).drop_duplicates()


def _query_soil_for_h3_mapping(
    mapping_df: pd.DataFrame,
    group_cols: list[str],
    parquet_files: list[str],
) -> pd.DataFrame:
    con = duckdb.connect()
    con.register("h3_map", mapping_df)

    group_select = ", ".join(f"m.{c}" for c in group_cols)
    group_by = ", ".join(f"m.{c}" for c in group_cols)

    return con.execute(
        f"""
        SELECT
            {group_select},
            COUNT(s.h3_index_10) AS h3_cells_count,
            ROUND(CASE WHEN AVG(s.sand) <= 1.0 THEN AVG(s.sand) * 100.0 ELSE AVG(s.sand) END, 1) AS sand_pct,
            ROUND(CASE WHEN AVG(s.silt) <= 1.0 THEN AVG(s.silt) * 100.0 ELSE AVG(s.silt) END, 1) AS silt_pct,
            ROUND(CASE WHEN AVG(s.clay) <= 1.0 THEN AVG(s.clay) * 100.0 ELSE AVG(s.clay) END, 1) AS clay_pct,
            ROUND(CASE WHEN AVG(s.sand) <= 1.0 THEN MIN(s.sand) * 100.0 ELSE MIN(s.sand) END, 1) AS sand_min_pct,
            ROUND(CASE WHEN AVG(s.sand) <= 1.0 THEN MAX(s.sand) * 100.0 ELSE MAX(s.sand) END, 1) AS sand_max_pct,
            ROUND(AVG(s.ph), 2) AS ph,
            ROUND(MIN(s.ph), 2) AS ph_min,
            ROUND(MAX(s.ph), 2) AS ph_max,
            ROUND(AVG(s.om), 2) AS om,
            ROUND(AVG(s.cec), 2) AS cec,
            ROUND(AVG(s.bulk_density), 2) AS bulk_density,
            MODE(s.soilTexture) AS soilTexture,
            MODE(s.BAND_pH) AS band_ph,
            MODE(s.BAND_om) AS band_om,
            MODE(s.BAND_cec) AS band_cec,
            COUNT(DISTINCT s.soilTexture) AS distinct_textures_count
        FROM h3_map m
        JOIN read_parquet($1) s
          ON m.h3_index_10 = LOWER(TRIM(CAST(s.h3_index_10 AS VARCHAR)))
        GROUP BY {group_by}
        """,
        [parquet_files],
    ).df()


def _compute_saxton_rawls_2006(
    sand_pct: pd.Series,
    clay_pct: pd.Series,
    om_pct: pd.Series,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    Równania pedotransferowe Saxtona & Rawlsa (2006, Soil Sci. Soc. Am. J.)
    wyznaczające punkt trwałego więdnięcia (WP, 1500 kPa), polową pojemność wodną
    (FC, 33 kPa) oraz użyteczną pojemność wodną AWC [mm/m] z tekstury i próchnicy.
    Stosowane w zakresie gleb mineralnych (clay <= 60%, OM <= 8%).
    """
    s_frac = np.clip(pd.to_numeric(sand_pct, errors="coerce").fillna(50.0) / 100.0, 0.0, 1.0)
    c_frac = np.clip(pd.to_numeric(clay_pct, errors="coerce").fillna(15.0) / 100.0, 0.0, 0.60)
    om_val = np.clip(pd.to_numeric(om_pct, errors="coerce").fillna(2.5), 0.0, 8.0)

    t1500t = (
        -0.024 * s_frac
        + 0.487 * c_frac
        + 0.006 * om_val
        + 0.005 * (s_frac * om_val)
        - 0.013 * (c_frac * om_val)
        + 0.068 * (s_frac * c_frac)
        + 0.031
    )
    wp = np.clip(t1500t + (0.14 * t1500t - 0.02), 0.02, 0.45)

    t33t = (
        -0.251 * s_frac
        + 0.195 * c_frac
        + 0.011 * om_val
        + 0.006 * (s_frac * om_val)
        - 0.027 * (c_frac * om_val)
        + 0.452 * (s_frac * c_frac)
        + 0.299
    )
    fc = np.clip(t33t + (1.283 * (t33t**2) - 0.374 * t33t - 0.015), wp + 0.03, 0.60)

    awc_mm_per_m = (fc - wp) * 1000.0
    return (
        pd.Series(np.round(wp, 4), index=sand_pct.index),
        pd.Series(np.round(fc, 4), index=sand_pct.index),
        pd.Series(np.round(awc_mm_per_m, 1), index=sand_pct.index),
    )


def _compute_soil_physical_metrics(out: pd.DataFrame) -> pd.DataFrame:
    out = out.copy()
    om_series = out["om"] if "om" in out.columns else pd.Series(2.5, index=out.index)
    wp, fc, awc = _compute_saxton_rawls_2006(out["sand_pct"], out["clay_pct"], om_series)

    out["wilting_point"] = wp
    out["field_capacity"] = fc
    out["awc_mm_per_m"] = awc

    out["permeability"] = np.select(
        [out["sand_pct"] >= 65, out["clay_pct"] >= 30],
        ["wysoka", "niska"],
        default="srednia",
    )
    out["water_retention"] = np.select(
        [out["awc_mm_per_m"] < 110.0, out["awc_mm_per_m"] >= 150.0],
        ["niska", "wysoka"],
        default="srednia",
    )

    for band_col in ("band_ph", "band_om", "band_cec"):
        if band_col in out.columns:
            out[band_col] = out[band_col].map(_normalize_band)
        else:
            out[band_col] = None

    out["soil_method_note"] = SOIL_METHOD_NOTE

    if {"sand_min_pct", "sand_max_pct", "ph_min", "ph_max", "distinct_textures_count"}.issubset(out.columns):
        sand_span = (out["sand_max_pct"] - out["sand_min_pct"]).fillna(0.0)
        ph_span = (out["ph_max"] - out["ph_min"]).fillna(0.0)
        tex_n = out["distinct_textures_count"].fillna(1)
        out["soil_variability"] = np.select(
            [
                (sand_span >= 15.0) | (ph_span >= 0.6) | (tex_n >= 2),
                (sand_span >= 7.0) | (ph_span >= 0.3),
            ],
            ["wysoka", "umiarkowana"],
            default="niska",
        )
        out = out.drop(columns=["distinct_textures_count"])
    else:
        out["soil_variability"] = "niska"

    return out


def prepare_all_soil_profiles(
    geojson_path: str | Path,
    soil_dir: str | Path,
    output_parquet: str | Path = "fields_soil_profiles.parquet",
    output_json: str | Path = "fields_soil_profiles.json",
    id_col: str | None = "id",
    min_area_ha: float = 3.0,
    crops_geojson: str | Path | None = None,
    assign_crops_year: int | None = None,
) -> pd.DataFrame:
    """
    Łączy pola >= min_area_ha z GeoJSON ze wszystkimi województwami w soil_data/.
    Wylicza parametry retencji Saxtona & Rawlsa (2006), natywne klasy SoilGrids
    (BAND_pH, BAND_om, BAND_cec), zmienność wewnętrzną oraz dołącza uprawy
    z GeoJSON lub z modułu bk/assign_crops.py.
    """
    parquet_files = ensure_parquets_unpacked(soil_dir)

    gdf = _prepare_geodataframe(gpd.read_file(geojson_path))
    if id_col and id_col in gdf.columns:
        gdf["field_id"] = gdf[id_col].astype(str)
    else:
        gdf["field_id"] = [f"field_{i}" for i in range(len(gdf))]
    gdf["crop_code"], gdf["crop"] = _attach_crops(
        gdf,
        geojson_path=geojson_path,
        crops_geojson=crops_geojson,
        assign_crops_year=assign_crops_year,
    )

    gdf_valid = gdf[gdf["area_ha"] >= min_area_ha].copy()
    if gdf_valid.empty:
        raise ValueError(f"Brak pól spełniających warunek powierzchni >= {min_area_ha} ha.")

    mapping_df = _polyfill_h3_mapping(gdf_valid, ["field_id"])
    agg_df = _query_soil_for_h3_mapping(mapping_df, ["field_id"], parquet_files)

    base_cols = ["field_id", "area_ha", "centroid_lat", "centroid_lon", "crop_code", "crop"]
    out = gdf_valid[base_cols].merge(agg_df, on="field_id", how="inner")
    if out.empty:
        raise LookupError("JOIN zwrócił 0 pól – sprawdź czy GeoJSON ma poprawne współrzędne.")

    out = _compute_soil_physical_metrics(out)
    out.to_parquet(output_parquet, index=False)
    out.to_json(output_json, orient="records", force_ascii=False)
    print(f"[ETAP 1] Zapisano {len(out)} profili pól do {output_parquet} oraz {output_json}.")
    return out


def prepare_zone_soil_profiles(
    zones_input: str | Path | gpd.GeoDataFrame,
    soil_dir: str | Path,
    output_parquet: str | Path = "field_zone_soil_profiles.parquet",
    output_json: str | Path = "field_zone_soil_profiles.json",
    field_id_col: str = "field_id",
    zone_col: str = "zone",
    min_zone_area_ha: float = 0.0,
    crops_geojson: str | Path | None = None,
    assign_crops_year: int | None = None,
) -> pd.DataFrame:
    """
    Profilowanie gleby PER STREFA (kompatybilne z tabelą public.field_zones z Modułu 1:
    field_id, zone, area_ha, ndvi_z, dose_kg_n_ha, dose_kg_product_ha, geom).
    Zachowuje zmienność glebową wewnątrz pola i nie uśrednia całego pola.
    """
    parquet_files = ensure_parquets_unpacked(soil_dir)

    raw_gdf = zones_input if isinstance(zones_input, gpd.GeoDataFrame) else gpd.read_file(zones_input)
    gdf = _prepare_geodataframe(raw_gdf)

    if field_id_col not in gdf.columns:
        raise KeyError(f"Brak kolumny '{field_id_col}' w warstwie stref.")
    if zone_col not in gdf.columns:
        raise KeyError(f"Brak kolumny '{zone_col}' w warstwie stref.")

    gdf["field_id"] = gdf[field_id_col].astype(str)
    gdf["zone"] = gdf[zone_col].astype(str)
    gdf["crop_code"], gdf["crop"] = _attach_crops(
        gdf,
        geojson_path=None if isinstance(zones_input, gpd.GeoDataFrame) else zones_input,
        crops_geojson=crops_geojson,
        assign_crops_year=assign_crops_year,
    )

    gdf_valid = gdf[gdf["area_ha"] >= min_zone_area_ha].copy()
    if gdf_valid.empty:
        raise ValueError("Brak stref spełniających warunek powierzchni.")

    mapping_df = _polyfill_h3_mapping(gdf_valid, ["field_id", "zone"])
    agg_df = _query_soil_for_h3_mapping(mapping_df, ["field_id", "zone"], parquet_files)

    keep_cols = ["field_id", "zone", "area_ha", "centroid_lat", "centroid_lon", "crop_code", "crop"]
    for extra in ("ndvi_z", "dose_kg_n_ha", "dose_kg_product_ha"):
        if extra in gdf_valid.columns:
            keep_cols.append(extra)

    out = gdf_valid[keep_cols].merge(agg_df, on=["field_id", "zone"], how="inner")
    if out.empty:
        raise LookupError("JOIN stref z SoilGrids zwrócił 0 rekordów.")

    out = _compute_soil_physical_metrics(out)
    out = out.sort_values(["field_id", "zone"]).reset_index(drop=True)
    out.to_parquet(output_parquet, index=False)
    out.to_json(output_json, orient="records", force_ascii=False)
    print(f"[ETAP 1 - STREFY] Zapisano {len(out)} profili stref do {output_parquet} oraz {output_json}.")
    return out


def prepare_field_h3_soil_cells(
    geojson_path: str | Path,
    soil_dir: str | Path,
    output_parquet: str | Path = "field_soil_h3_cells.parquet",
    id_col: str | None = "id",
    min_area_ha: float = 3.0,
) -> pd.DataFrame:
    """
    Zwraca warstwę podpolową per pojedyncza komórka H3 poziomu 10 (~250 m SoilGrids)
    wewnątrz każdego pola >= 3 ha — do wizualizacji zmienności gleby na mapie ryzyka.
    """
    parquet_files = ensure_parquets_unpacked(soil_dir)
    gdf = _prepare_geodataframe(gpd.read_file(geojson_path))
    if id_col and id_col in gdf.columns:
        gdf["field_id"] = gdf[id_col].astype(str)
    else:
        gdf["field_id"] = [f"field_{i}" for i in range(len(gdf))]

    gdf_valid = gdf[gdf["area_ha"] >= min_area_ha].copy()
    if gdf_valid.empty:
        raise ValueError(f"Brak pól spełniających warunek powierzchni >= {min_area_ha} ha.")

    mapping_df = _polyfill_h3_mapping(gdf_valid, ["field_id"])
    con = duckdb.connect()
    con.register("h3_map", mapping_df)

    cells_df = con.execute(
        """
        SELECT
            m.field_id,
            m.h3_index_10,
            1 AS h3_cells_count,
            ROUND(CASE WHEN s.sand <= 1.0 THEN s.sand * 100.0 ELSE s.sand END, 1) AS sand_pct,
            ROUND(CASE WHEN s.silt <= 1.0 THEN s.silt * 100.0 ELSE s.silt END, 1) AS silt_pct,
            ROUND(CASE WHEN s.clay <= 1.0 THEN s.clay * 100.0 ELSE s.clay END, 1) AS clay_pct,
            ROUND(s.ph, 2) AS ph,
            ROUND(s.om, 2) AS om,
            ROUND(s.cec, 2) AS cec,
            ROUND(s.bulk_density, 2) AS bulk_density,
            s.soilTexture,
            s.BAND_pH AS band_ph,
            s.BAND_om AS band_om,
            s.BAND_cec AS band_cec
        FROM h3_map m
        JOIN read_parquet($1) s
          ON m.h3_index_10 = LOWER(TRIM(CAST(s.h3_index_10 AS VARCHAR)))
        """,
        [parquet_files],
    ).df()

    if cells_df.empty:
        raise LookupError("Brak komórek H3 pasujących do SoilGrids.")

    latlons = [h3.cell_to_latlng(c) for c in cells_df["h3_index_10"]]
    cells_df["cell_lat"] = [round(lat, 6) for lat, _ in latlons]
    cells_df["cell_lon"] = [round(lon, 6) for _, lon in latlons]

    out = _compute_soil_physical_metrics(cells_df).sort_values(["field_id", "h3_index_10"]).reset_index(drop=True)
    out.to_parquet(output_parquet, index=False)
    print(f"[ETAP 1 - H3] Zapisano {len(out)} komórek H3 gleby do {output_parquet}.")
    return out


def _row_to_soil_profile(r: pd.Series) -> SoilProfile:
    def _opt_float(col: str) -> float | None:
        return float(r[col]) if col in r.index and pd.notna(r[col]) else None

    def _opt_int(col: str) -> int | None:
        return int(round(float(r[col]))) if col in r.index and pd.notna(r[col]) else None

    def _opt_str(col: str) -> str | None:
        if col not in r.index or pd.isna(r[col]):
            return None
        txt = str(r[col]).strip()
        return None if txt.lower() in ("", "nan", "none", "null") else txt

    wp = float(r["wilting_point"])
    fc = float(r["field_capacity"])
    awc = (
        float(r["awc_mm_per_m"])
        if "awc_mm_per_m" in r.index and pd.notna(r["awc_mm_per_m"])
        else round((fc - wp) * 1000.0, 1)
    )

    return SoilProfile(
        field_id=str(r["field_id"]),
        area_ha=float(r["area_ha"]),
        centroid_lat=float(r["centroid_lat"]) if "centroid_lat" in r.index else 0.0,
        centroid_lon=float(r["centroid_lon"]) if "centroid_lon" in r.index else 0.0,
        h3_cells_count=int(r["h3_cells_count"]),
        sand_pct=float(r["sand_pct"]),
        silt_pct=float(r["silt_pct"]),
        clay_pct=float(r["clay_pct"]),
        soilTexture=str(r["soilTexture"]),
        ph=float(r["ph"]),
        permeability=r["permeability"],
        water_retention=r["water_retention"],
        wilting_point=wp,
        field_capacity=fc,
        awc_mm_per_m=awc,
        soil_method_note=_opt_str("soil_method_note") or SOIL_METHOD_NOTE,
        band_ph=_opt_str("band_ph"),
        band_om=_opt_str("band_om"),
        band_cec=_opt_str("band_cec"),
        zone=_opt_str("zone"),
        crop_code=_opt_int("crop_code"),
        crop=_opt_str("crop"),
        om=_opt_float("om"),
        cec=_opt_float("cec"),
        bulk_density=_opt_float("bulk_density"),
        sand_min_pct=_opt_float("sand_min_pct"),
        sand_max_pct=_opt_float("sand_max_pct"),
        ph_min=_opt_float("ph_min"),
        ph_max=_opt_float("ph_max"),
        soil_variability=_opt_str("soil_variability") or "niska",
    )


def load_field_profile(
    field_id: str,
    profiles_parquet: str | Path = "fields_soil_profiles.parquet",
) -> SoilProfile:
    """Wczytuje profil pojedynczego pola z pliku wygenerowanego w Etapie 1."""
    df = pd.read_parquet(profiles_parquet)
    row = df[df["field_id"].astype(str) == str(field_id)]
    if row.empty:
        raise KeyError(f"Nie znaleziono pola '{field_id}' w {profiles_parquet}.")
    return _row_to_soil_profile(row.iloc[0])


def load_zone_profiles(
    field_id: str,
    zone_profiles_parquet: str | Path = "field_zone_soil_profiles.parquet",
) -> list[ZoneSoilProfile]:
    """Wczytuje listę profili glebowych wszystkich stref dla wybranego pola."""
    df = pd.read_parquet(zone_profiles_parquet)
    sub = df[df["field_id"].astype(str) == str(field_id)].sort_values("zone")
    if sub.empty:
        raise KeyError(f"Nie znaleziono stref dla pola '{field_id}' w {zone_profiles_parquet}.")
    return [_row_to_soil_profile(row) for _, row in sub.iterrows()]


def export_soil_profiles_to_sql(
    df: pd.DataFrame,
    table_name: str = "field_soil_profiles",
    sql_path: str | Path = "field_soil_profiles.sql",
) -> Path:
    """
    Eksportuje profile glebowe (per pole lub per strefa) do pliku SQL dla PostgreSQL (public.<table_name>).
    """
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", table_name):
        raise ValueError(f"Nieprawidłowa nazwa tabeli SQL: {table_name!r}")

    def _pg_type(dtype) -> str:
        if pd.api.types.is_integer_dtype(dtype):
            return "INTEGER"
        if pd.api.types.is_float_dtype(dtype):
            return "DOUBLE PRECISION"
        return "TEXT"

    def _sql_literal(val) -> str:
        if val is None or (isinstance(val, float) and np.isnan(val)) or pd.isna(val):
            return "NULL"
        if isinstance(val, (int, np.integer)):
            return str(int(val))
        if isinstance(val, (float, np.floating)):
            return f"{float(val):.6g}"
        text = str(val).replace("'", "''")
        return f"'{text}'"

    cols_ddl = ",\n    ".join(f"{col} {_pg_type(df[col].dtype)}" for col in df.columns)
    lines = [
        f"CREATE TABLE IF NOT EXISTS public.{table_name} (",
        f"    {cols_ddl}",
        ");",
        "",
    ]

    col_names = ", ".join(df.columns)
    for _, row in df.iterrows():
        vals = ", ".join(_sql_literal(row[c]) for c in df.columns)
        lines.append(f"INSERT INTO public.{table_name} ({col_names}) VALUES ({vals});")

    out_path = Path(sql_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[SQL] Wyeksportowano {len(df)} wierszy do {out_path} (tabela public.{table_name}).")
    return out_path


# ==============================================================================
# ETAP 2: OCENA NAWOŻENIA, STRESU WODNEGO (BEZ NAWADNIANIA) I KALENDARZA
# ==============================================================================

def evaluate_fertilization_day(
    soil: SoilProfile,
    fertilizer: Fertilizer,
    crop: Crop,
    precip_24h_mm: float,
    precip_72h_mm: float,
    temp_c: float,
    sm_l1: float,
    sm_l2: float,
    sm_l3: float,
    day_date: str | date | datetime | None = None,
    wind_max_kmh: float | None = None,
    rh_mean_pct: float | None = None,
) -> dict:
    status: Status = "ZIELONY"
    reasons: list[str] = []

    def escalate(new_status: Status, msg: str):
        nonlocal status
        order = {"ZIELONY": 0, "ZOLTY": 1, "CZERWONY": 2}
        if order[new_status] > order[status]:
            status = new_status
        reasons.append(msg)

    if day_date is not None:
        if isinstance(day_date, datetime):
            d = day_date.date()
        elif isinstance(day_date, date):
            d = day_date
        else:
            d = date.fromisoformat(str(day_date).strip())
        if d.month in (11, 12, 1, 2):
            escalate(
                "CZERWONY",
                f"Okres zimowy ({d.isoformat()}) — zakaz stosowania nawozów azotowych wg Programu Azotanowego.",
            )

    if temp_c <= 0.0:
        escalate(
            "CZERWONY",
            f"Przymrozek / zamarznięta gleba ({temp_c:.1f}°C <= 0°C) — zakaz aplikacji nawozów.",
        )

    l1_saturated = sm_l1 >= soil.field_capacity * 1.05
    l2_saturated = sm_l2 >= soil.field_capacity * 1.05
    l1_dry = sm_l1 <= soil.wilting_point * 1.15

    if precip_24h_mm > 10.0:
        escalate(
            "CZERWONY",
            f"Prognozowany silny opad ({precip_24h_mm:.1f} mm/24h > 10 mm) – ryzyko spływu i strat nawozu.",
        )
    elif precip_72h_mm > 20.0:
        escalate(
            "ZOLTY",
            f"Wysoka suma opadów w 72h ({precip_72h_mm:.1f} mm > 20 mm) – podwyższone ryzyko przemieszczania składników.",
        )

    if l1_saturated and l2_saturated:
        escalate(
            "CZERWONY",
            "Gleba nasycona wodą w warstwach 1–2 – ryzyko podmakania, koleinowania i strat azotu.",
        )

    if fertilizer == "saletra_amonowa":
        if soil.permeability == "wysoka" and precip_72h_mm > 15.0:
            escalate("CZERWONY", "Gleba lekka/przepuszczalna + opady: wysokie ryzyko wymywania azotanów z saletry.")
        elif l1_dry:
            escalate("ZOLTY", "Przesuszona warstwa powierzchniowa (Poziom 1) – wolniejsze rozpuszczanie granul.")

    elif fertilizer == "mocznik_inhibitor":
        if soil.ph > 7.2 and temp_c > 20.0:
            escalate("CZERWONY", f"Wysokie pH gleby ({soil.ph}) i temperatura ({temp_c:.1f}°C) – wysokie ryzyko strat amoniaku.")
        elif soil.ph > 7.0:
            escalate("ZOLTY", f"Podwyższone pH gleby ({soil.ph}) zwiększa wrażliwość mocznika na ulatnianie amoniaku.")
        if l1_dry and precip_72h_mm < 3.0:
            escalate("ZOLTY", "Przesuszenie powierzchniowe (Poziom 1) bez prognozowanego lekkiego opadu po aplikacji.")

    elif fertilizer == "rsm_32":
        if wind_max_kmh is None and rh_mean_pct is None:
            escalate(
                "ZOLTY",
                "Ocena RSM 32 jest częściowa (brak danych o wietrze i wilgotności powietrza – sprawdź instrukcję aplikacji).",
            )
        else:
            if wind_max_kmh is not None:
                if wind_max_kmh > 18.0:
                    escalate("CZERWONY", f"Zbyt silny wiatr ({wind_max_kmh:.1f} km/h > 18 km/h) dla oprysku RSM 32 – ryzyko znoszenia.")
                elif wind_max_kmh > 14.4:
                    escalate("ZOLTY", f"Umiarkowanie silny wiatr ({wind_max_kmh:.1f} km/h) – wymagane rozpylacze antyznoszeniowe.")
            if rh_mean_pct is not None and rh_mean_pct < 50.0 and temp_c > 18.0:
                escalate("ZOLTY", f"Niska wilgotność powietrza ({rh_mean_pct:.0f}%) i ciepło – ryzyko krystalizacji i poparzeń RSM 32.")

        if temp_c > 22.0 or temp_c < 2.0:
            escalate("CZERWONY", f"Niekorzystna temperatura ({temp_c:.1f}°C) dla nawozu płynnego – ryzyko poparzenia roślin.")
        if soil.permeability == "wysoka" and precip_72h_mm > 15.0:
            escalate("ZOLTY", "Wysoka przepuszczalność gleby sprzyja szybkiemu przemieszczaniu azotu w głąb profilu.")

    elif fertilizer == "saletrosan_26":
        if soil.permeability == "wysoka" and precip_72h_mm > 15.0:
            escalate("CZERWONY", "Gleba przepuszczalna + opady: wysokie ryzyko wymywania azotu i siarki.")
        elif l1_dry:
            escalate("ZOLTY", "Niska wilgotność w warstwie 1 – ograniczone pobieranie N i S.")

    if not reasons:
        zone_txt = f", strefa {soil.zone}" if soil.zone else ""
        reasons.append(
            f"Korzystne warunki glebowe (tekstura: {soil.soilTexture}, pH: {soil.ph}{zone_txt}) i umiarkowana wilgotność dla {crop}."
        )

    return {"fertilizer": fertilizer, "crop": crop, "status": status, "reasons": reasons}


def evaluate_water_stress(
    soil: SoilProfile,
    crop: Crop,
    sm_l1: float,
    sm_l2: float,
    sm_l3: float,
    precip_72h_mm: float,
    ndmi_value: float | None = None,
) -> dict:
    """
    Moduł diagnostyki stresu wodnego (deficyt vs nadmiar wody w strefie korzeniowej).
    Nie generuje zaleceń ani dawek nawadniania.
    """
    paw_l2 = float(np.clip((sm_l2 - soil.wilting_point) / (soil.field_capacity - soil.wilting_point), 0.0, 1.0))
    paw_l3 = float(np.clip((sm_l3 - soil.wilting_point) / (soil.field_capacity - soil.wilting_point), 0.0, 1.0))

    crop_threshold = 0.35 if crop in ("kukurydza", "rzepak") else 0.30
    reasons: list[str] = []

    if sm_l1 >= soil.field_capacity * 1.05 and sm_l2 >= soil.field_capacity * 1.05:
        water_status = "NADMIAR"
        stress_level = "WYSOKI"
        reasons.append(
            f"Nasycenie wodą powyżej pojemności polowej w warstwach 1–2 (retencja: {soil.water_retention}) – "
            "ryzyko niedotlenienia korzeni i wymywania składników."
        )
    elif paw_l2 < crop_threshold and paw_l3 < 0.40 and precip_72h_mm < 5.0:
        water_status = "DEFICYT"
        stress_level = "WYSOKI"
        reasons.append(
            f"Silny deficyt wody dostępnej dla roślin w warstwach 2–3 (retencja gleby: {soil.water_retention}) przy braku opadów."
        )
    elif paw_l2 < crop_threshold + 0.15 and precip_72h_mm < 5.0:
        water_status = "DEFICYT"
        stress_level = "UMIARKOWANY"
        reasons.append(
            "Spadek dostępnej wody w płytszej strefie korzeniowej (Poziom 2) – umiarkowany stres suszowy i słabsze pobieranie azotu."
        )
    else:
        water_status = "OPTYMALNY"
        stress_level = "NISKI"
        reasons.append("Prawidłowe uwilgotnienie strefy korzeniowej (brak stresu wodnego).")

    if ndmi_value is not None and ndmi_value < 0.15 and water_status != "NADMIAR":
        if stress_level == "NISKI":
            stress_level = "UMIARKOWANY"
        elif stress_level == "UMIARKOWANY":
            stress_level = "WYSOKI"
        if water_status == "OPTYMALNY":
            water_status = "DEFICYT"
        reasons.append(
            f"Niski satelitarny wskaźnik NDMI ({ndmi_value:.2f}) potwierdza możliwy stres wodny łanu."
        )

    return {
        "water_stress_level": stress_level,
        "water_status": water_status,
        "paw_layer2_pct": round(paw_l2 * 100, 1),
        "paw_layer3_pct": round(paw_l3 * 100, 1),
        "reasons": reasons,
    }


def evaluate_field_calendar(
    soil: SoilProfile,
    field_weather_df: pd.DataFrame,
    fertilizer: Fertilizer,
    crop: Crop,
    ndmi_by_date: dict[str, float] | None = None,
    ndvi_by_date: dict[str, float] | None = None,
    disease_df: pd.DataFrame | None = None,
    spray_df: pd.DataFrame | None = None,
) -> list[dict]:
    """
    Łączy profil glebowy (pola lub strefy) z dzienną pogodą oraz opcjonalnymi
    wynikami chorób/oprysku (Moduł 2) w gotową listę pod kalendarz 7-dniowy.
    """
    risk_order = {"NISKI": 0, "SREDNI": 1, "WYSOKI": 2}
    calendar_days: list[dict] = []

    for _, row in field_weather_df.sort_values("date").iterrows():
        day_str = str(row["date"])[:10]
        precip_24h = float(row["precip_sum_mm"])
        precip_72h = (
            float(row["precip_72h_mm"])
            if "precip_72h_mm" in row and pd.notna(row["precip_72h_mm"])
            else precip_24h
        )
        temp_c = float(row["temp_mean_c"])
        sm_l1 = float(row["sm_l1"])
        sm_l2 = float(row["sm_l2"])
        sm_l3 = float(row["sm_l3"])
        wind_max = float(row["wind_max_kmh"]) if "wind_max_kmh" in row and pd.notna(row["wind_max_kmh"]) else None
        rh_mean = float(row["rh_mean_pct"]) if "rh_mean_pct" in row and pd.notna(row["rh_mean_pct"]) else None

        ndmi = ndmi_by_date.get(day_str) if ndmi_by_date else None
        ndvi = ndvi_by_date.get(day_str) if ndvi_by_date else None

        fert = evaluate_fertilization_day(
            soil=soil,
            fertilizer=fertilizer,
            crop=crop,
            precip_24h_mm=precip_24h,
            precip_72h_mm=precip_72h,
            temp_c=temp_c,
            sm_l1=sm_l1,
            sm_l2=sm_l2,
            sm_l3=sm_l3,
            day_date=day_str,
            wind_max_kmh=wind_max,
            rh_mean_pct=rh_mean,
        )
        stress = evaluate_water_stress(
            soil=soil,
            crop=crop,
            sm_l1=sm_l1,
            sm_l2=sm_l2,
            sm_l3=sm_l3,
            precip_72h_mm=precip_72h,
            ndmi_value=ndmi,
        )

        protection = None
        if disease_df is not None or spray_df is not None:
            protection = {"max_disease_risk": "BRAK_DANYCH", "diseases": [], "spray_status": "BRAK_DANYCH", "best_spray_window": "", "spray_reason": ""}
            if disease_df is not None and not disease_df.empty:
                d_sub = disease_df[disease_df["day"].astype(str).str.slice(0, 10) == day_str]
                if "field_id" in d_sub.columns:
                    d_sub = d_sub[d_sub["field_id"].astype(str) == str(soil.field_id)]
                if not d_sub.empty:
                    diseases_list = [
                        {
                            "disease": str(dr["disease"]),
                            "risk": str(dr["risk"]),
                            "wet_hours": int(dr["wet_hours"]),
                            "reason": str(dr["reason"]),
                        }
                        for _, dr in d_sub.iterrows()
                    ]
                    protection["diseases"] = diseases_list
                    protection["max_disease_risk"] = max(
                        (d["risk"] for d in diseases_list),
                        key=lambda r: risk_order.get(r, -1),
                    )
            if spray_df is not None and not spray_df.empty:
                s_sub = spray_df[spray_df["day"].astype(str).str.slice(0, 10) == day_str]
                if "field_id" in s_sub.columns:
                    s_sub = s_sub[s_sub["field_id"].astype(str) == str(soil.field_id)]
                if not s_sub.empty:
                    sr = s_sub.iloc[0]
                    protection["spray_status"] = str(sr["spray_status"])
                    protection["best_spray_window"] = str(sr["best_window"])
                    protection["spray_reason"] = str(sr["reason"])

        calendar_days.append(
            {
                "date": day_str,
                "field_id": soil.field_id,
                "zone": soil.zone,
                "crop": crop,
                "fertilizer": fertilizer,
                "status": fert["status"],
                "fertilization_reasons": fert["reasons"],
                "water_stress_level": stress["water_stress_level"],
                "water_status": stress["water_status"],
                "paw_layer2_pct": stress["paw_layer2_pct"],
                "paw_layer3_pct": stress["paw_layer3_pct"],
                "water_stress_reasons": stress["reasons"],
                "weather": {
                    "temp_mean_c": round(temp_c, 2),
                    "precip_24h_mm": round(precip_24h, 2),
                    "precip_72h_mm": round(precip_72h, 2),
                    "sm_l1": round(sm_l1, 3),
                    "sm_l2": round(sm_l2, 3),
                    "sm_l3": round(sm_l3, 3),
                },
                "ndvi_value": ndvi,
                "ndmi_value": ndmi,
                "protection": protection,
            }
        )
    return calendar_days


# ==============================================================================
# URUCHOMIENIE CAŁEGO PIPELINE'U (ETAP 1 -> ETAP 2)
# ==============================================================================

if __name__ == "__main__":
    if Path("bk/fields_crops.geojson").exists():
        default_geojson = Path("bk/fields_crops.geojson")
    elif Path("kw/fields.geojson").exists():
        default_geojson = Path("kw/fields.geojson")
    else:
        default_geojson = Path("fields.geojson")

    df_profiles = prepare_all_soil_profiles(
        geojson_path=default_geojson,
        soil_dir="soil_data",
        output_parquet="fields_soil_profiles.parquet",
        output_json="fields_soil_profiles.json",
        id_col="id",
    )
    print(
        df_profiles[
            [
                "field_id",
                "area_ha",
                "crop_code",
                "crop",
                "sand_pct",
                "soilTexture",
                "ph",
                "band_ph",
                "awc_mm_per_m",
                "water_retention",
                "soil_variability",
                "permeability",
            ]
        ].head()
    )

    known_crops = df_profiles[df_profiles["crop"].notna() & (df_profiles["crop"] != "inne")]
    sample_id = (known_crops if not known_crops.empty else df_profiles)["field_id"].iloc[0]
    soil_profile = load_field_profile(sample_id, "fields_soil_profiles.parquet")
    sample_crop = soil_profile.crop or "pszenica"

    fert_eval = evaluate_fertilization_day(
        soil=soil_profile,
        fertilizer="mocznik_inhibitor",
        crop=sample_crop,
        precip_24h_mm=0.0,
        precip_72h_mm=1.5,
        temp_c=23.0,
        sm_l1=0.09,
        sm_l2=0.12,
        sm_l3=0.14,
        wind_max_kmh=10.0,
        rh_mean_pct=65.0,
    )

    stress_eval = evaluate_water_stress(
        soil=soil_profile,
        crop=sample_crop,
        sm_l1=0.09,
        sm_l2=0.12,
        sm_l3=0.14,
        precip_72h_mm=1.5,
        ndmi_value=0.12,
    )

    print("\n--- WYNIK DLA POLA:", sample_id, "---")
    print("PROFIL:", asdict(soil_profile))
    print("NAWOŻENIE:", fert_eval)
    print("STRES WODNY:", stress_eval)
