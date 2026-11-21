from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path
import sys
import urllib.parse
import zipfile

import duckdb
import geopandas as gpd
import h3
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from env_config import (
    detect_voivodeships_for_bbox,
    get_soil_urls,
    load_env_file,
    normalize_voivodeship_key,
)
from kw.soil import (
    CLMS_CROP_CODE_TO_NAME,
    Crop,
    DEFAULT_FIELDS_PROFILES_JSON,
    DEFAULT_FIELDS_PROFILES_PARQUET,
    DEFAULT_H3_CELLS_PARQUET,
    DEFAULT_SOIL_DIR,
    DEFAULT_SOIL_SQL,
    DEFAULT_ZONE_PROFILES_JSON,
    DEFAULT_ZONE_PROFILES_PARQUET,
    Fertilizer,
    FieldSoilProfile,
    SOIL_METHOD_NOTE,
    SoilProfile,
    Status,
    ZoneSoilProfile,
    _attach_crops,
    _compute_soil_physical_metrics,
    _polyfill_h3_mapping,
    _prepare_geodataframe,
    _query_soil_for_h3_mapping,
    evaluate_fertilization_day,
    evaluate_field_calendar,
    evaluate_water_stress,
    export_soil_profiles_to_sql,
    load_field_profile,
    load_zone_profiles,
)

DEFAULT_SOIL_AWS_CACHE_DIR = DEFAULT_SOIL_DIR / "aws_cache"


def _find_cached_voivodeship_parquets(cache_dir: Path, voiv_key: str) -> list[Path]:
    voiv_dir = cache_dir / voiv_key.lower()
    if not voiv_dir.exists():
        return []
    return sorted(p for p in voiv_dir.rglob("*.parquet") if not p.name.startswith("._"))


def fetch_voivodeship_soil_parquet(
    voivodeship: str,
    url: str,
    cache_dir: str | Path = DEFAULT_SOIL_AWS_CACHE_DIR,
    force_refresh: bool = False,
    keep_zip: bool = False,
    timeout: int = 180,
) -> Path:
    """
    Pobiera i zapisuje w cache lokalnym plik .parquet SoilGrids dla wskazanego województwa
    na podstawie linku z .env (obsługuje zarówno bezpośrednie .parquet, jak i archiwa .zip).
    """
    v_key = normalize_voivodeship_key(voivodeship)
    base_cache = Path(cache_dir)
    voiv_dir = base_cache / v_key.lower()

    cached = _find_cached_voivodeship_parquets(base_cache, v_key)
    if cached and not force_refresh:
        print(f"[AWS CACHE] Używam zcache'owanego pliku gleby dla {v_key}: {cached[0]}")
        return cached[0]

    voiv_dir.mkdir(parents=True, exist_ok=True)
    url_path = urllib.parse.urlparse(url).path
    raw_name = Path(url_path).name or f"soil_{v_key.lower()}_isric_250_v2.parquet"
    part_path = voiv_dir / f".{v_key.lower()}.download.part"

    print(f"[AWS SOIL] Pobieram SoilGrids dla województwa {v_key}...")
    try:
        with requests.get(url, stream=True, timeout=timeout) as resp:
            resp.raise_for_status()
            with open(part_path, "wb") as dst:
                for chunk in resp.iter_content(chunk_size=1 << 20):
                    if chunk:
                        dst.write(chunk)

        is_zip = raw_name.lower().endswith(".zip") or zipfile.is_zipfile(part_path)
        if is_zip:
            extracted: list[Path] = []
            with zipfile.ZipFile(part_path, "r") as zf:
                for member in zf.namelist():
                    if member.endswith("/") or member.startswith("__MACOSX/") or Path(member).name.startswith("._"):
                        continue
                    if not member.lower().endswith(".parquet"):
                        continue
                    dest = voiv_dir / Path(member).name
                    with zf.open(member) as src, open(dest, "wb") as out:
                        while True:
                            buf = src.read(1 << 20)
                            if not buf:
                                break
                            out.write(buf)
                    extracted.append(dest)

            if keep_zip:
                zip_name = raw_name if raw_name.lower().endswith(".zip") else f"soil_{v_key.lower()}_isric_250_v2.zip"
                part_path.replace(voiv_dir / zip_name)
            else:
                part_path.unlink(missing_ok=True)

            if not extracted:
                raise ValueError(f"Archiwum AWS dla {v_key} nie zawiera pliku .parquet.")
            extracted.sort()
            print(f"[AWS SOIL] Zapisano i wypakowano {extracted[0].name} -> {voiv_dir}")
            return extracted[0]

        dest_name = raw_name if raw_name.lower().endswith(".parquet") else f"soil_{v_key.lower()}_isric_250_v2.parquet"
        dest_parquet = voiv_dir / dest_name
        part_path.replace(dest_parquet)
        print(f"[AWS SOIL] Zapisano {dest_parquet.name} -> {voiv_dir}")
        return dest_parquet
    except BaseException:
        part_path.unlink(missing_ok=True)
        raise


def ensure_aws_soil_parquets(
    bounds: tuple[float, float, float, float] | list[float],
    env_path: str | Path = ".env",
    cache_dir: str | Path = DEFAULT_SOIL_AWS_CACHE_DIR,
    voivodeships: list[str] | tuple[str, ...] | None = None,
    soil_urls: dict[str, str] | None = None,
    force_refresh: bool = False,
) -> list[str]:
    """
    Zwraca listę ścieżek do lokalnych plików .parquet pobranych (i zcache'owanych) z AWS S3
    dla województw przecinających zadany bounding box [min_lon, min_lat, max_lon, max_lat].
    """
    load_env_file(env_path)
    base_cache = Path(cache_dir)

    target_voivs = (
        [normalize_voivodeship_key(v) for v in voivodeships]
        if voivodeships
        else detect_voivodeships_for_bbox(bounds)
    )
    if not target_voivs:
        raise ValueError(f"Nie dopasowano żadnego województwa w Polsce dla bbox={bounds}.")

    urls_map = (
        {normalize_voivodeship_key(k): v for k, v in soil_urls.items() if v}
        if soil_urls is not None
        else get_soil_urls(env_path)
    )

    resolved: list[Path] = []
    missing_env: list[str] = []

    for v_key in target_voivs:
        cached = _find_cached_voivodeship_parquets(base_cache, v_key)
        if cached and not force_refresh:
            print(f"[AWS CACHE] {v_key}: {cached[0]}")
            resolved.extend(cached)
            continue

        url = urls_map.get(v_key, "")
        if url:
            resolved.append(
                fetch_voivodeship_soil_parquet(
                    v_key,
                    url=url,
                    cache_dir=base_cache,
                    force_refresh=force_refresh,
                )
            )
        else:
            missing_env.append(f"SOIL_URL_{v_key}")
            print(f"[UWAGA] Brak linku SOIL_URL_{v_key} w {env_path} ani cache w {base_cache / v_key.lower()} — pomijam.")

    if not resolved:
        raise ValueError(
            "Brak plików SoilGrids dla wykrytych województw "
            f"({', '.join(target_voivs)}). Uzupełnij w {env_path}: {', '.join(missing_env)}"
        )

    parquets = sorted({p.as_posix() for p in resolved})
    print(f"[ETAP 1 - AWS] Aktywne pliki .parquet ({len(parquets)}): {[Path(p).name for p in parquets]}")
    return parquets


def prepare_all_soil_profiles(
    geojson_path: str | Path,
    soil_dir: str | Path = DEFAULT_SOIL_AWS_CACHE_DIR,
    output_parquet: str | Path = DEFAULT_FIELDS_PROFILES_PARQUET,
    output_json: str | Path = DEFAULT_FIELDS_PROFILES_JSON,
    id_col: str | None = "id",
    min_area_ha: float = 3.0,
    crops_geojson: str | Path | None = None,
    assign_crops_year: int | None = None,
    *,
    env_path: str | Path = ".env",
    cache_dir: str | Path | None = None,
    voivodeships: list[str] | tuple[str, ...] | None = None,
    soil_urls: dict[str, str] | None = None,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """
    Wersja AWS z cache: pobiera brakujące województwa z linków SOIL_URL_<WOJ> w .env
    do data/soil/aws_cache/ i liczy profile glebowe pól >= min_area_ha.
    """
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

    effective_cache = Path(cache_dir) if cache_dir is not None else Path(soil_dir)
    bounds = tuple(map(float, gdf_valid.to_crs("EPSG:4326").total_bounds))
    parquet_files = ensure_aws_soil_parquets(
        bounds=bounds,
        env_path=env_path,
        cache_dir=effective_cache,
        voivodeships=voivodeships,
        soil_urls=soil_urls,
        force_refresh=force_refresh,
    )

    mapping_df = _polyfill_h3_mapping(gdf_valid, ["field_id"])
    agg_df = _query_soil_for_h3_mapping(mapping_df, ["field_id"], parquet_files)

    base_cols = ["field_id", "area_ha", "centroid_lat", "centroid_lon", "crop_code", "crop"]
    out = gdf_valid[base_cols].merge(agg_df, on="field_id", how="inner")
    if out.empty:
        raise LookupError("JOIN zwrócił 0 pól – sprawdź bbox/województwa w cache AWS oraz współrzędne GeoJSON.")

    out = _compute_soil_physical_metrics(out)
    out_parquet_path = Path(output_parquet)
    out_json_path = Path(output_json)
    out_parquet_path.parent.mkdir(parents=True, exist_ok=True)
    out_json_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(out_parquet_path, index=False)
    out.to_json(out_json_path, orient="records", force_ascii=False)
    print(f"[ETAP 1 - AWS] Zapisano {len(out)} profili pól do {out_parquet_path} oraz {out_json_path}.")
    return out


def prepare_zone_soil_profiles(
    zones_input: str | Path | gpd.GeoDataFrame,
    soil_dir: str | Path = DEFAULT_SOIL_AWS_CACHE_DIR,
    output_parquet: str | Path = DEFAULT_ZONE_PROFILES_PARQUET,
    output_json: str | Path = DEFAULT_ZONE_PROFILES_JSON,
    field_id_col: str = "field_id",
    zone_col: str = "zone",
    min_zone_area_ha: float = 0.0,
    crops_geojson: str | Path | None = None,
    assign_crops_year: int | None = None,
    *,
    env_path: str | Path = ".env",
    cache_dir: str | Path | None = None,
    voivodeships: list[str] | tuple[str, ...] | None = None,
    soil_urls: dict[str, str] | None = None,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """
    Profilowanie gleby PER STREFA na danych SoilGrids pobieranych i cache'owanych z AWS.
    """
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

    effective_cache = Path(cache_dir) if cache_dir is not None else Path(soil_dir)
    bounds = tuple(map(float, gdf_valid.to_crs("EPSG:4326").total_bounds))
    parquet_files = ensure_aws_soil_parquets(
        bounds=bounds,
        env_path=env_path,
        cache_dir=effective_cache,
        voivodeships=voivodeships,
        soil_urls=soil_urls,
        force_refresh=force_refresh,
    )

    mapping_df = _polyfill_h3_mapping(gdf_valid, ["field_id", "zone"])
    agg_df = _query_soil_for_h3_mapping(mapping_df, ["field_id", "zone"], parquet_files)

    keep_cols = ["field_id", "zone", "area_ha", "centroid_lat", "centroid_lon", "crop_code", "crop"]
    for extra in ("ndvi_z", "dose_kg_n_ha", "dose_kg_product_ha"):
        if extra in gdf_valid.columns:
            keep_cols.append(extra)

    out = gdf_valid[keep_cols].merge(agg_df, on=["field_id", "zone"], how="inner")
    if out.empty:
        raise LookupError("JOIN stref z SoilGrids (AWS) zwrócił 0 rekordów.")

    out = _compute_soil_physical_metrics(out)
    out = out.sort_values(["field_id", "zone"]).reset_index(drop=True)
    out_parquet_path = Path(output_parquet)
    out_json_path = Path(output_json)
    out_parquet_path.parent.mkdir(parents=True, exist_ok=True)
    out_json_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(out_parquet_path, index=False)
    out.to_json(out_json_path, orient="records", force_ascii=False)
    print(f"[ETAP 1 - STREFY AWS] Zapisano {len(out)} profili stref do {out_parquet_path} oraz {out_json_path}.")
    return out


def prepare_field_h3_soil_cells(
    geojson_path: str | Path,
    soil_dir: str | Path = DEFAULT_SOIL_AWS_CACHE_DIR,
    output_parquet: str | Path = DEFAULT_H3_CELLS_PARQUET,
    id_col: str | None = "id",
    min_area_ha: float = 3.0,
    *,
    env_path: str | Path = ".env",
    cache_dir: str | Path | None = None,
    voivodeships: list[str] | tuple[str, ...] | None = None,
    soil_urls: dict[str, str] | None = None,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """
    Zwraca warstwę podpolową H3 poziomu 10 z parquetów SoilGrids pobieranych i cache'owanych z AWS.
    """
    gdf = _prepare_geodataframe(gpd.read_file(geojson_path))
    if id_col and id_col in gdf.columns:
        gdf["field_id"] = gdf[id_col].astype(str)
    else:
        gdf["field_id"] = [f"field_{i}" for i in range(len(gdf))]

    gdf_valid = gdf[gdf["area_ha"] >= min_area_ha].copy()
    if gdf_valid.empty:
        raise ValueError(f"Brak pól spełniających warunek powierzchni >= {min_area_ha} ha.")

    effective_cache = Path(cache_dir) if cache_dir is not None else Path(soil_dir)
    bounds = tuple(map(float, gdf_valid.to_crs("EPSG:4326").total_bounds))
    parquet_files = ensure_aws_soil_parquets(
        bounds=bounds,
        env_path=env_path,
        cache_dir=effective_cache,
        voivodeships=voivodeships,
        soil_urls=soil_urls,
        force_refresh=force_refresh,
    )

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
        raise LookupError("Brak komórek H3 pasujących do SoilGrids (AWS).")

    latlons = [h3.cell_to_latlng(c) for c in cells_df["h3_index_10"]]
    cells_df["cell_lat"] = [round(lat, 6) for lat, _ in latlons]
    cells_df["cell_lon"] = [round(lon, 6) for _, lon in latlons]

    out = _compute_soil_physical_metrics(cells_df).sort_values(["field_id", "h3_index_10"]).reset_index(drop=True)
    out_parquet_path = Path(output_parquet)
    out_parquet_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(out_parquet_path, index=False)
    print(f"[ETAP 1 - H3 AWS] Zapisano {len(out)} komórek H3 gleby do {out_parquet_path}.")
    return out


__all__ = [
    "CLMS_CROP_CODE_TO_NAME",
    "Crop",
    "DEFAULT_FIELDS_PROFILES_JSON",
    "DEFAULT_FIELDS_PROFILES_PARQUET",
    "DEFAULT_H3_CELLS_PARQUET",
    "DEFAULT_SOIL_AWS_CACHE_DIR",
    "DEFAULT_SOIL_DIR",
    "DEFAULT_SOIL_SQL",
    "DEFAULT_ZONE_PROFILES_JSON",
    "DEFAULT_ZONE_PROFILES_PARQUET",
    "Fertilizer",
    "FieldSoilProfile",
    "SOIL_METHOD_NOTE",
    "SoilProfile",
    "Status",
    "ZoneSoilProfile",
    "ensure_aws_soil_parquets",
    "evaluate_fertilization_day",
    "evaluate_field_calendar",
    "evaluate_water_stress",
    "export_soil_profiles_to_sql",
    "fetch_voivodeship_soil_parquet",
    "load_field_profile",
    "load_zone_profiles",
    "prepare_all_soil_profiles",
    "prepare_field_h3_soil_cells",
    "prepare_zone_soil_profiles",
]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Profilowanie gleby SoilGrids z cache AWS (.env).")
    parser.add_argument(
        "--geojson",
        type=Path,
        default=Path("bk/fields_crops.geojson") if Path("bk/fields_crops.geojson").exists() else Path("kw/fields.geojson"),
    )
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_SOIL_AWS_CACHE_DIR)
    parser.add_argument("--voivodeships", nargs="*", default=None)
    parser.add_argument("--force-refresh", action="store_true")
    args = parser.parse_args()

    df_profiles = prepare_all_soil_profiles(
        geojson_path=args.geojson,
        cache_dir=args.cache_dir,
        env_path=args.env_file,
        voivodeships=args.voivodeships,
        force_refresh=args.force_refresh,
        output_parquet=DEFAULT_FIELDS_PROFILES_PARQUET,
        output_json=DEFAULT_FIELDS_PROFILES_JSON,
    )
    print(
        df_profiles[
            ["field_id", "area_ha", "crop", "sand_pct", "soilTexture", "ph", "band_ph", "awc_mm_per_m", "soil_variability"]
        ].head()
    )
    sample_id = df_profiles["field_id"].iloc[0]
    profile = load_field_profile(sample_id, DEFAULT_FIELDS_PROFILES_PARQUET)
    print("PRZYKŁADOWY PROFIL:", asdict(profile))
