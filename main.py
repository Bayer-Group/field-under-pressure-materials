from __future__ import annotations

import argparse
from datetime import date, datetime
import os
from pathlib import Path
import sys
import urllib.parse
import urllib.request
import zipfile

# Wymagane PRZED importem rasterio (publiczne COG Sentinel-2 / GeoParquet z AWS)
os.environ.setdefault("AWS_NO_SIGN_REQUEST", "YES")

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import geopandas as gpd
import numpy as np
import pandas as pd

from env_config import (
    VOIVODESHIP_BAYER_NAMES,
    detect_voivodeships_for_bbox,
    get_bayer_daily_url,
    get_bayer_grids_url,
    get_bayer_imerg_urls,
    get_cropland_urls,
    get_service_urls,
    get_soil_urls,
    load_env_file,
)
from ml.config import DEFAULT_DATA_DIR as DEFAULT_ML_DIR
from ml.prepare_dataset import (
    build_fields_master,
    build_weather_table_from_bayer,
    build_weather_table_from_open_meteo,
    extract_pixel_dataset_from_tiffs,
    extract_satellite_indices_from_tiffs,
)

# ==============================================================================
# KONFIGURACJA DOMYŚLNA PIPELINE'U (możesz zmieniać tutaj lub przez argumenty CLI)
# ==============================================================================

DEFAULT_POWIAT = "lowicki"
DEFAULT_START_DATE = "2024-03-01"
DEFAULT_END_DATE = "2024-06-30"
DEFAULT_FIELDS_YEAR = 2024
DEFAULT_CROP_YEAR = 2024
DEFAULT_MIN_AREA_HA = 3.0
DEFAULT_N_SCENES = 8
DEFAULT_MAX_CLOUD = 20.0

# Przykładowe bounding boxy [min_lon, min_lat, max_lon, max_lat] (WGS84) dla powiatów
POWIAT_BBOXES: dict[str, tuple[float, float, float, float]] = {
    # Powiat łowicki (woj. łódzkie, wschodni pas graniczy z mazowieckim)
    "lowicki": (19.72, 52.00, 20.12, 52.23),
    # Mniejszy wycinek powiatu łowickiego (bezpieczniejszy limit 2048 px w FieldsClassificator)
    "lowicki_small": (19.84, 52.06, 20.02, 52.18),
    # Powiat pułtuski / okolice z dotychczasowego bk/fields_crops.geojson (woj. mazowieckie)
    "pultuski": (20.697, 52.584, 20.946, 52.675),
    # Powiat międzyrzecki (kw/fields.geojson, woj. lubuskie)
    "miedzyrzecki": (15.697, 52.584, 15.846, 52.675),
    # Powiat puławski (woj. lubelskie)
    "pulawski": (22.155, 51.438, 22.300, 51.529),
}


def _year_range(start_date: str, end_date: str) -> list[int]:
    y0 = date.fromisoformat(start_date).year
    y1 = date.fromisoformat(end_date).year
    return list(range(y0, y1 + 1))


def _resolve_bbox_and_tag(args: argparse.Namespace) -> tuple[tuple[float, float, float, float], str]:
    if args.bbox is not None:
        bbox = tuple(float(v) for v in args.bbox)
        tag = args.tag or f"bbox_{bbox[0]:.3f}_{bbox[1]:.3f}_{bbox[2]:.3f}_{bbox[3]:.3f}".replace(".", "_")
        return bbox, tag  # type: ignore[return-value]
    bbox = POWIAT_BBOXES[args.powiat]
    tag = args.tag or args.powiat
    return bbox, tag


def _download_zip_or_parquet(url: str, dest_dir: Path, fallback_stem: str) -> list[Path]:
    dest_dir.mkdir(parents=True, exist_ok=True)
    name = Path(urllib.parse.urlparse(url).path).name or f"{fallback_stem}.zip"
    tmp_path = dest_dir / f".{fallback_stem}.part"
    try:
        urllib.request.urlretrieve(url, tmp_path)
        if name.lower().endswith(".zip") or zipfile.is_zipfile(tmp_path):
            extracted: list[Path] = []
            with zipfile.ZipFile(tmp_path, "r") as zf:
                for member in zf.namelist():
                    if member.endswith("/") or member.startswith("__MACOSX/") or Path(member).name.startswith("._"):
                        continue
                    target = dest_dir / Path(member).name
                    with zf.open(member) as src, open(target, "wb") as dst:
                        while True:
                            chunk = src.read(1 << 20)
                            if not chunk:
                                break
                            dst.write(chunk)
                    if target.suffix.lower() == ".parquet":
                        extracted.append(target)
            tmp_path.unlink(missing_ok=True)
            return sorted(extracted)
        out_name = name if name.lower().endswith(".parquet") else f"{fallback_stem}.parquet"
        out_path = dest_dir / out_name
        tmp_path.replace(out_path)
        return [out_path]
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def _bbox_coords_grid(bbox: tuple[float, float, float, float], step_deg: float = 0.25) -> list[tuple[float, float]]:
    min_lon, min_lat, max_lon, max_lat = bbox
    lats = np.arange(min_lat, max_lat + 1e-9, step_deg)
    lons = np.arange(min_lon, max_lon + 1e-9, step_deg)
    pts = [(round(float(lat), 4), round(float(lon), 4)) for lat in lats for lon in lons]
    c_lat = round(0.5 * (min_lat + max_lat), 4)
    c_lon = round(0.5 * (min_lon + max_lon), 4)
    if (c_lat, c_lon) not in pts:
        pts.append((c_lat, c_lon))
    return pts


# ==============================================================================
# ETAP 1: GRANICE PÓL (bk/fields_downloader lub bk/fields_classificator)
# ==============================================================================

def run_stage_fields(
    bbox: tuple[float, float, float, float],
    tag: str,
    fields_year: int,
    fields_source: str,
    min_area_ha: float,
    fields_geojson_arg: Path | None,
    service_urls: dict[str, str],
    skip_download: bool,
    force: bool,
) -> Path:
    print("\n--- [1/6] GRANICE PÓL ---")
    out_dir = ROOT / "data/fields"
    out_dir.mkdir(parents=True, exist_ok=True)
    default_out = out_dir / f"{tag}_fields.geojson"

    if fields_source == "existing":
        cand = fields_geojson_arg
        if cand is None:
            for p in (out_dir / f"{tag}_fields_crops.geojson", default_out, ROOT / "bk/fields_crops.geojson", ROOT / "bk/fields.geojson"):
                if p.exists():
                    cand = p
                    break
        if cand is None or not cand.exists():
            raise FileNotFoundError(
                f"Brak istniejącego pliku granic pól ({fields_geojson_arg or default_out}). "
                "Użyj `--fields-source downloader` albo podaj `--fields-geojson`."
            )
        print(f"[1/6] Używam istniejących granic pól: {cand}")
        return cand

    if default_out.exists() and not force:
        print(f"[1/6] Znaleziono istniejący plik granic (cache): {default_out.relative_to(ROOT)}")
        return default_out

    if skip_download:
        raise FileNotFoundError(
            f"[1/6] Tryb --skip-download, a plik {default_out.relative_to(ROOT)} nie istnieje. "
            "Podaj `--fields-source existing --fields-geojson ...`."
        )

    if fields_source == "downloader":
        import bk.fields_downloader as fd

        fd.GRID_URL = service_urls["FTW_GRID_URL"]
        fd.PARQUET_URL = service_urls["FTW_PARQUET_URL_TEMPLATE"]
        downloader = fd.FieldsDownloader(
            bbox=list(bbox),
            year=fields_year,
            data_dir=out_dir / "ftw_tiles",
            verbose=True,
        )
        gdf = downloader.download()
        if "area_ha" in gdf.columns:
            downloader.fields = gdf[gdf["area_ha"] >= min_area_ha].reset_index(drop=True)
        downloader.save(str(default_out))
        return default_out

    if fields_source == "classificator":
        import bk.fields_classificator as fc

        fc.STAC_URL = service_urls["SENTINEL_STAC_URL"]
        fc.MODEL_URL = service_urls["FTW_MODEL_URL"]
        classifier = fc.FieldsClassificator(
            year=fields_year,
            min_area_m2=min_area_ha * 10_000.0,
        )
        res = classifier.generate(list(bbox)).simplify(30)
        res.save(str(default_out))
        return default_out

    raise ValueError(f"Nieznany fields_source: {fields_source}")


# ==============================================================================
# ETAP 2: KLASYFIKACJA UPRAW CLMS (bk/crop_detector.py)
# ==============================================================================

def _sync_cropland_urls_file(env_path: Path) -> Path:
    cropland_urls = get_cropland_urls(env_path)
    if cropland_urls:
        target = ROOT / "data/cropland/cropland_urls.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        lines = [cropland_urls[y] for y in sorted(cropland_urls)]
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return target
    fallback = ROOT / "bk/cropland_urls.txt"
    if fallback.exists():
        return fallback
    raise FileNotFoundError(
        f"Brak linków CROPLAND_URL_<ROK> w {env_path} oraz brak pliku {fallback}."
    )


def run_stage_crops(
    fields_geojson: Path,
    tag: str,
    crop_year: int,
    env_path: Path,
    skip_download: bool,
    force: bool,
) -> Path:
    print("\n--- [2/6] KLASYFIKACJA UPRAW (CLMS) ---")
    gdf_head = gpd.read_file(fields_geojson, rows=5)
    if "crop_code" in gdf_head.columns and not force:
        full_gdf = gpd.read_file(fields_geojson)
        if full_gdf["crop_code"].notna().any():
            print(
                f"[2/6] Plik {fields_geojson} zawiera już kody upraw (`crop_code`, niepustych: "
                f"{int(full_gdf['crop_code'].notna().sum())}/{len(full_gdf)}) — pomijam ponowne wykrywanie."
            )
            return fields_geojson

    out_crops = ROOT / f"data/fields/{tag}_fields_crops.geojson"
    if out_crops.exists() and not force:
        print(f"[2/6] Znaleziono istniejący plik upraw (cache): {out_crops.relative_to(ROOT)}")
        return out_crops

    cropland_dir = ROOT / "data/cropland"
    tiles_index = cropland_dir / f"cropland_{crop_year}/index.json"
    legacy_tiles_index = ROOT / f"bk/data/cropland_{crop_year}/index.json"
    if not tiles_index.exists() and legacy_tiles_index.exists():
        print(f"[INFO] Używam zcache'owanych kafli CLMS z {legacy_tiles_index.parent.relative_to(ROOT)}.")
        cropland_dir = ROOT / "bk/data"
        tiles_index = legacy_tiles_index

    urls_file = _sync_cropland_urls_file(env_path)
    if skip_download and not tiles_index.exists():
        print(
            f"[SKIP] --skip-download: brak rozpakowanych kafli CLMS w {tiles_index.parent.relative_to(ROOT)} — "
            "przekazuję granice pól bez kolumny crop_code."
        )
        return fields_geojson

    from bk.crop_detector import CropDetector

    detector = CropDetector(
        year=crop_year,
        urls_file=urls_file,
        data_dir=cropland_dir,
    )
    detected = detector.detect(fields_geojson)
    out_crops.parent.mkdir(parents=True, exist_ok=True)
    save_gdf = detected.drop(columns=[c for c in ("crop_share", "candidates") if c in detected.columns])
    save_gdf.to_file(out_crops, driver="GeoJSON")
    print(f"[2/6] Zapisano pola z uprawami -> {out_crops.relative_to(ROOT)}")
    return out_crops


# ==============================================================================
# ETAP 3: GLEBA SOILGRIDS (kw/soil_aws.py lub kw/soil.py)
# ==============================================================================

def _resolve_soil_mode(
    soil_source: str,
    voivs: list[str],
    env_path: Path,
    aws_cache_dir: Path,
) -> str:
    if soil_source in ("aws", "local"):
        return soil_source
    soil_urls = get_soil_urls(env_path)
    has_aws_url = any(v in soil_urls for v in voivs)
    has_aws_cache = any((aws_cache_dir / v.lower()).exists() and any((aws_cache_dir / v.lower()).rglob("*.parquet")) for v in voivs)
    if has_aws_url or has_aws_cache:
        return "aws"
    return "local"


def run_stage_soil(
    fields_crops_geojson: Path,
    bbox: tuple[float, float, float, float],
    voivs: list[str],
    soil_source: str,
    min_area_ha: float,
    env_path: Path,
    force: bool,
) -> tuple[Path, pd.DataFrame, str]:
    print("\n--- [3/6] GLEBA (ISRIC SoilGrids 250m + Saxton & Rawls 2006) ---")
    soil_out_dir = ROOT / "data/soil"
    aws_cache_dir = soil_out_dir / "aws_cache"
    out_parquet = soil_out_dir / "fields_soil_profiles.parquet"
    out_json = soil_out_dir / "fields_soil_profiles.json"
    out_h3 = soil_out_dir / "field_soil_h3_cells.parquet"
    out_sql = soil_out_dir / "field_soil_profiles.sql"

    mode = _resolve_soil_mode(soil_source, voivs, env_path, aws_cache_dir)
    print(f"[3/6] Tryb źródła gleby: {mode.upper()} (województwa: {voivs})")

    if mode == "aws":
        from kw import soil_aws

        soil_df = soil_aws.prepare_all_soil_profiles(
            geojson_path=fields_crops_geojson,
            cache_dir=aws_cache_dir,
            env_path=env_path,
            voivodeships=voivs,
            force_refresh=force,
            min_area_ha=min_area_ha,
            output_parquet=out_parquet,
            output_json=out_json,
        )
        soil_aws.prepare_field_h3_soil_cells(
            geojson_path=fields_crops_geojson,
            cache_dir=aws_cache_dir,
            env_path=env_path,
            voivodeships=voivs,
            force_refresh=force,
            min_area_ha=min_area_ha,
            output_parquet=out_h3,
        )
        soil_aws.export_soil_profiles_to_sql(soil_df, table_name="field_soil_profiles", sql_path=out_sql)
        return out_parquet, soil_df, mode

    from kw import soil as soil_local

    raw_dir = soil_out_dir / "raw"
    if not (raw_dir.exists() and (any(raw_dir.rglob("*.parquet")) or any(raw_dir.glob("*.zip")))):
        legacy_dir = ROOT / "soil_data"
        if legacy_dir.exists():
            print("[INFO] Brak plików w data/soil/raw/ — tymczasowo wczytuję z soil_data/.")
            raw_dir = legacy_dir

    soil_df = soil_local.prepare_all_soil_profiles(
        geojson_path=fields_crops_geojson,
        soil_dir=raw_dir,
        min_area_ha=min_area_ha,
        output_parquet=out_parquet,
        output_json=out_json,
    )
    soil_local.prepare_field_h3_soil_cells(
        geojson_path=fields_crops_geojson,
        soil_dir=raw_dir,
        min_area_ha=min_area_ha,
        output_parquet=out_h3,
    )
    soil_local.export_soil_profiles_to_sql(soil_df, table_name="field_soil_profiles", sql_path=out_sql)
    return out_parquet, soil_df, mode


# ==============================================================================
# ETAP 4: SATELITA SENTINEL-2 (NDVI, NDMI + opcjonalnie strefy K-Means)
# ==============================================================================

def run_stage_satellite(
    fields_crops_geojson: Path,
    tag: str,
    start_date: str,
    end_date: str,
    n_scenes: int,
    max_cloud: float,
    min_area_ha: float,
    soil_mode: str,
    voivs: list[str],
    env_path: Path,
    run_zones: bool,
    prepare_pixels: bool,
    pixels_per_field: int,
    skip_download: bool,
    force: bool,
) -> Path | None:
    print("\n--- [4/6] SATELITA SENTINEL-2 (NDVI & NDMI) ---")
    sat_dir = ROOT / f"data/satellite/{tag}_{start_date}_to_{end_date}"
    out_sat_parquet = ROOT / "data/ml/satellite_indices.parquet"

    existing_tifs = sorted(list(sat_dir.glob("*.tif")) + list(sat_dir.glob("*.tiff"))) if sat_dir.exists() else []
    if (not existing_tifs or force) and not skip_download:
        from ndvi_ndmi_downloader import download_clip_sentinel_ndvi_ndmi

        download_clip_sentinel_ndvi_ndmi(
            boundary_file=fields_crops_geojson,
            start_date=start_date,
            end_date=end_date,
            out_dir=sat_dir,
            max_cc=max_cloud,
            n_scenes=n_scenes,
        )
        existing_tifs = sorted(list(sat_dir.glob("*.tif")) + list(sat_dir.glob("*.tiff"))) if sat_dir.exists() else []
    elif skip_download and not existing_tifs:
        print(f"[SKIP] --skip-download: brak lokalnych plików .tif w {sat_dir.relative_to(ROOT)} — pomijam Sentinel-2.")
        return None
    else:
        print(f"[4/6] Znaleziono {len(existing_tifs)} zcache'owanych scen .tif w {sat_dir.relative_to(ROOT)}.")

    if not existing_tifs:
        print("[UWAGA] Brak scen Sentinel-2 po etapie pobierania — pomijam satellite_indices.parquet.")
        return None

    extract_satellite_indices_from_tiffs(
        fields_geojson=fields_crops_geojson,
        tiff_inputs=sat_dir,
        out_path=out_sat_parquet,
    )

    if prepare_pixels:
        ml_dir = out_sat_parquet.parent
        extract_pixel_dataset_from_tiffs(
            fields_geojson=fields_crops_geojson,
            tiff_inputs=sat_dir,
            soil_h3_parquet=ROOT / "data/soil/field_soil_h3_cells.parquet",
            fields_master_parquet=ml_dir / "fields_master.parquet",
            out_master_path=ml_dir / "pixel_master.parquet",
            out_sat_path=ml_dir / "pixel_satellite_indices.parquet",
            min_area_ha=min_area_ha,
            pixels_per_field=pixels_per_field,
        )

    if run_zones:
        try:
            from ndvi_kmeans import process_fields_ndvi_kmeans
        except ImportError as exc:
            print(f"[UWAGA] Pomijam klasteryzację stref K-Means (brak zależności: {exc}).")
        else:
            zones_dir = ROOT / "data/zones"
            zones_gdf = process_fields_ndvi_kmeans(
                boundary_file=fields_crops_geojson,
                ndvi_dir=sat_dir,
                out_dir=zones_dir,
                model_path=zones_dir / "ndvi_kmeans_model.joblib",
                min_area_ha=min_area_ha,
            )
            zones_geojson = zones_dir / "field_zones.geojson"
            if not zones_gdf.empty and zones_geojson.exists():
                if soil_mode == "aws":
                    from kw import soil_aws

                    soil_aws.prepare_zone_soil_profiles(
                        zones_input=zones_geojson,
                        cache_dir=ROOT / "data/soil/aws_cache",
                        env_path=env_path,
                        voivodeships=voivs,
                        crops_geojson=fields_crops_geojson,
                    )
                else:
                    from kw import soil as soil_local

                    raw_dir = ROOT / "data/soil/raw"
                    if not raw_dir.exists() and (ROOT / "soil_data").exists():
                        raw_dir = ROOT / "soil_data"
                    soil_local.prepare_zone_soil_profiles(
                        zones_input=zones_geojson,
                        soil_dir=raw_dir,
                        crops_geojson=fields_crops_geojson,
                    )

    return out_sat_parquet if out_sat_parquet.exists() else None


# ==============================================================================
# ETAP 5: POGODA (Bayer + IMERG oraz/lub Open-Meteo -> data/ml/weather_daily.parquet)
# ==============================================================================

def _run_bayer_weather(
    fields_master_parquet: Path,
    voivs: list[str],
    start_date: str,
    end_date: str,
    env_path: Path,
    out_parquet: Path,
    skip_download: bool,
) -> Path | None:
    bayer_root = ROOT / "data/meteo/bayer"
    grids_dir = bayer_root / "grids"
    daily_dir = bayer_root / "daily"
    imerg_dir = bayer_root / "imerg"

    # 1. Siatka weather_grids
    grid_files = sorted(grids_dir.rglob("*.parquet")) if grids_dir.exists() else []
    if not grid_files and not skip_download:
        grids_url = get_bayer_grids_url(env_path)
        if grids_url:
            print("[5/6 - BAYER] Pobieram weather_grids z linku w .env...")
            grid_files = _download_zip_or_parquet(grids_url, grids_dir, "weather_grids")
    if not grid_files:
        print("[5/6 - BAYER] Brak pliku weather_grids.parquet ani BAYER_WEATHER_GRIDS_URL.")
        return None

    # 2. Dzienne pliki Bayera dla lat z [start_date..end_date] i wykrytych województw
    years = _year_range(start_date, end_date)
    daily_files = sorted(daily_dir.rglob("*.parquet")) if daily_dir.exists() else []
    if not daily_files and not skip_download:
        downloaded: list[Path] = []
        for yr in years:
            for v_key in voivs:
                url = get_bayer_daily_url(yr, v_key, env_path)
                if url:
                    print(f"[5/6 - BAYER] Pobieram pogodę dzienną {yr}/{v_key}...")
                    downloaded.extend(_download_zip_or_parquet(url, daily_dir / str(yr), f"{v_key.lower()}_{yr}"))
        daily_files = sorted(daily_dir.rglob("*.parquet")) if daily_dir.exists() else downloaded

    if not daily_files:
        print("[5/6 - BAYER] Brak dziennych plików Parquet Bayera oraz pasujących BAYER_WEATHER_DAILY_<ROK>_<WOJ> w .env.")
        return None

    # 3. Opady IMERG (opcjonalne, lecz zalecane bo w tabelach Bayera często brakuje total_precipitation)
    imerg_files = sorted(imerg_dir.rglob("*.parquet")) if imerg_dir.exists() else []
    if not imerg_files and not skip_download:
        imerg_daily_url, _ = get_bayer_imerg_urls(env_path)
        if imerg_daily_url:
            print("[5/6 - BAYER] Pobieram opady NASA IMERG z linku w .env...")
            try:
                from weather_bayer import get_presip

                voiv_name = VOIVODESHIP_BAYER_NAMES.get(voivs[0], voivs[0].title())
                res_path = get_presip(imerg_daily_url, years[0], voiv_name, output_dir=imerg_dir)
                if res_path:
                    imerg_files = sorted(imerg_dir.rglob("*.parquet"))
            except FileNotFoundError:
                imerg_files = _download_zip_or_parquet(imerg_daily_url, imerg_dir, "imerg_precipitation_daily")

    imerg_arg: str | Path | None = None
    if len(imerg_files) == 1:
        imerg_arg = imerg_files[0]
    elif len(imerg_files) > 1:
        print(f"[INFO] Znaleziono {len(imerg_files)} plików IMERG — używam pierwszego: {imerg_files[0].name}")
        imerg_arg = imerg_files[0]

    build_weather_table_from_bayer(
        fields_master_parquet=fields_master_parquet,
        bayer_weather_parquets=[str(p) for p in daily_files],
        weather_grids_parquet=grid_files[0],
        imerg_daily_parquet=imerg_arg,
        out_path=out_parquet,
        start_date=start_date,
        end_date=end_date,
    )
    return out_parquet if out_parquet.exists() else None


def _run_open_meteo_weather(
    fields_master_parquet: Path,
    bbox: tuple[float, float, float, float],
    start_date: str,
    end_date: str,
    out_parquet: Path,
    skip_download: bool,
    force: bool,
) -> Path | None:
    meteo_dir = ROOT / "data/meteo"
    expected_range = meteo_dir / f"open_meteo_poland_daily_{start_date}_to_{end_date}.parquet"
    om_source: Path | None = expected_range if expected_range.exists() and not force else None

    if om_source is None and not skip_download:
        from kw.meteo import fetch_poland_weather_daily

        coords = _bbox_coords_grid(bbox, step_deg=0.25)
        print(f"[5/6 - OPEN-METEO] Pobieram pogodę {start_date}..{end_date} dla {len(coords)} pkt bbox...")
        fetch_poland_weather_daily(
            output_parquet=expected_range,
            coords=coords,
            start_date=start_date,
            end_date=end_date,
            force_refresh=force,
        )
        om_source = expected_range
    elif om_source is None:
        any_daily = sorted(meteo_dir.glob("open_meteo_poland_daily_*.parquet"))
        if any_daily:
            om_source = any_daily[-1]
            print(f"[5/6 - OPEN-METEO] --skip-download: używam lokalnego cache {om_source.name}")

    if om_source is None or not om_source.exists():
        print("[SKIP] Brak lokalnego pliku Open-Meteo w data/meteo/ oraz tryb --skip-download — pomijam weather_daily.")
        return None

    build_weather_table_from_open_meteo(
        fields_master_parquet=fields_master_parquet,
        open_meteo_parquet=om_source,
        out_path=out_parquet,
    )
    return out_parquet if out_parquet.exists() else None


def run_stage_weather(
    fields_master_parquet: Path,
    bbox: tuple[float, float, float, float],
    voivs: list[str],
    start_date: str,
    end_date: str,
    weather_source: str,
    env_path: Path,
    skip_download: bool,
    force: bool,
) -> Path | None:
    print("\n--- [5/6] POGODA DZIENNA ---")
    ml_dir = DEFAULT_ML_DIR
    primary_out = ml_dir / "weather_daily.parquet"

    if weather_source == "bayer":
        return _run_bayer_weather(fields_master_parquet, voivs, start_date, end_date, env_path, primary_out, skip_download)

    if weather_source == "open_meteo":
        return _run_open_meteo_weather(fields_master_parquet, bbox, start_date, end_date, primary_out, skip_download, force)

    if weather_source == "both":
        bayer_ok = _run_bayer_weather(fields_master_parquet, voivs, start_date, end_date, env_path, primary_out, skip_download)
        om_out = ml_dir / "weather_daily_open_meteo.parquet" if bayer_ok else primary_out
        _run_open_meteo_weather(fields_master_parquet, bbox, start_date, end_date, om_out, skip_download, force)
        return primary_out if primary_out.exists() else None

    # auto: prefer Bayer gdy dostępne są linki / pliki lokalne, w przeciwnym razie Open-Meteo
    bayer_ok = _run_bayer_weather(fields_master_parquet, voivs, start_date, end_date, env_path, primary_out, skip_download)
    if bayer_ok is not None:
        return bayer_ok
    print("[5/6] Przechodzę na Open-Meteo (brak pełnego zestawu Bayera).")
    return _run_open_meteo_weather(fields_master_parquet, bbox, start_date, end_date, primary_out, skip_download, force)


# ==============================================================================
# ETAP 7 (OPCJONALNY): MODUŁ 2 — OCHRONA ROŚLIN I OKNO OPRYSKU
# ==============================================================================

def run_stage_protection(
    soil_df: pd.DataFrame,
    bbox: tuple[float, float, float, float],
    start_date: str,
    end_date: str,
    skip_download: bool,
) -> None:
    print("\n--- [7] MODUŁ 2: PRESJA CHORÓB I OKNO OPRYSKU ---")
    from kw.disease_risk import build_fields_protection_tables, export_protection_to_sql
    from kw.meteo import fetch_weather_hourly

    meteo_dir = ROOT / "data/meteo"
    prot_dir = ROOT / "data/protection"
    cached_hourly = sorted(meteo_dir.glob("open_meteo_hourly_*.parquet"))

    if cached_hourly:
        w_hourly = pd.read_parquet(cached_hourly[-1])
        print(f"[7] Wczytano pogodę godzinową z {cached_hourly[-1].relative_to(ROOT)}")
    elif not skip_download:
        c_lat = round(0.5 * (bbox[1] + bbox[3]), 4)
        c_lon = round(0.5 * (bbox[0] + bbox[2]), 4)
        w_hourly = fetch_weather_hourly(
            coords=[(c_lat, c_lon)],
            start_date=start_date,
            end_date=end_date,
            output_dir=meteo_dir,
        )
    else:
        print("[SKIP] --skip-download i brak plików open_meteo_hourly_*.parquet w data/meteo/ — pomijam Moduł 2.")
        return

    disease_df, spray_df = build_fields_protection_tables(
        soil_df,
        w_hourly,
        start_date=start_date,
        end_date=end_date,
        output_dir=prot_dir,
    )
    export_protection_to_sql(disease_df, spray_df, prot_dir / "field_disease_dump.sql")


# ==============================================================================
# CLI I ORKIESTRACJA CAŁEGO PIPELINE'U
# ==============================================================================

def build_cli() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Główny pipeline pobierania i łączenia danych pod trening sieci NDVI/NDMI (VegetationLSTM)."
    )
    p.add_argument(
        "--powiat",
        choices=tuple(POWIAT_BBOXES.keys()),
        default=DEFAULT_POWIAT,
        help=f"Gotowy powiat z bazy bounding boxów (domyślnie: {DEFAULT_POWIAT}).",
    )
    p.add_argument(
        "--bbox",
        nargs=4,
        type=float,
        metavar=("MIN_LON", "MIN_LAT", "MAX_LON", "MAX_LAT"),
        default=None,
        help="Własny bounding box WGS84 [min_lon min_lat max_lon max_lat] (nadpisuje --powiat).",
    )
    p.add_argument("--tag", type=str, default=None, help="Etykieta obszaru używana w nazwach plików w data/.")
    p.add_argument("--start-date", type=str, default=DEFAULT_START_DATE, help="Początek zakresu dat YYYY-MM-DD.")
    p.add_argument("--end-date", type=str, default=DEFAULT_END_DATE, help="Koniec zakresu dat YYYY-MM-DD.")
    p.add_argument("--fields-year", type=int, default=DEFAULT_FIELDS_YEAR, help="Rok granic pól (FTW / Sentinel).")
    p.add_argument("--crop-year", type=int, default=DEFAULT_CROP_YEAR, help="Rok mapy upraw Copernicus CLMS.")
    p.add_argument(
        "--fields-source",
        choices=("downloader", "classificator", "existing"),
        default="downloader",
        help="Źródło granic pól: FTW downloader, sieć FTW FieldsClassificator, lub istniejący GeoJSON.",
    )
    p.add_argument("--fields-geojson", type=Path, default=None, help="Ścieżka do istniejącego GeoJSON pól.")
    p.add_argument(
        "--soil-source",
        choices=("auto", "aws", "local"),
        default="auto",
        help="Źródło SoilGrids: aws (kw/soil_aws.py z cache), local (kw/soil.py), lub auto.",
    )
    p.add_argument(
        "--weather-source",
        choices=("auto", "bayer", "open_meteo", "both"),
        default="auto",
        help="Źródło pogody dziennej dla ML: bayer (+IMERG), open_meteo, both lub auto.",
    )
    p.add_argument("--n-scenes", type=int, default=DEFAULT_N_SCENES, help="Liczba scen Sentinel-2 do pobrania.")
    p.add_argument("--max-cloud", type=float, default=DEFAULT_MAX_CLOUD, help="Maks. zachmurzenie sceny Sentinel-2 (%%).")
    p.add_argument("--min-area-ha", type=float, default=DEFAULT_MIN_AREA_HA, help="Minimalna powierzchnia pola w ha.")
    p.add_argument("--env-file", type=Path, default=ROOT / ".env", help="Ścieżka do pliku .env z linkami.")
    p.add_argument("--run-zones", action="store_true", help="Uruchom klasteryzację stref NDVI 10m + glebę per strefa.")
    p.add_argument("--prepare-pixels", action="store_true", help="Przygotuj próbki pikseli 10 m z komórek glebowych H3 (pixel_master + pixel_satellite_indices).")
    p.add_argument("--pixels-per-field", type=int, default=9, help="Liczba stratyfikowanych pikseli 10 m na pole (domyślnie 9).")
    p.add_argument("--run-protection", action="store_true", help="Uruchom Moduł 2 (choroby + okna oprysku).")
    p.add_argument("--skip-download", action="store_true", help="Bez pobierania z sieci — użyj wyłącznie lokalnego cache.")
    p.add_argument("--force", action="store_true", help="Nadpisz istniejące pliki pośrednie / cache.")
    p.add_argument("--dry-run", action="store_true", help="Pokaż plan wykonania, wykryte województwa i status .env bez uruchamiania.")
    return p


def _print_ml_readiness_summary() -> None:
    print("\n================ PODSUMOWANIE GOTOWOŚCI DO TRENINGU ML ================")
    ml_dir = ROOT / DEFAULT_ML_DIR
    expected = [
        ("fields_master", ml_dir / "fields_master.parquet"),
        ("satellite_indices", ml_dir / "satellite_indices.parquet"),
        ("weather_daily", ml_dir / "weather_daily.parquet"),
    ]
    ready_all = True
    for label, p in expected:
        if p.exists():
            n_rows = len(pd.read_parquet(p))
            print(f"  [OK]   {label:20s} -> {p.relative_to(ROOT)} ({n_rows} wierszy)")
        else:
            ready_all = False
            print(f"  [BRAK] {label:20s} -> {p.relative_to(ROOT)}")

    px_master = ml_dir / "pixel_master.parquet"
    px_sat = ml_dir / "pixel_satellite_indices.parquet"
    for label, p in (("pixel_master", px_master), ("pixel_sat_indices", px_sat)):
        if p.exists():
            n_rows = len(pd.read_parquet(p))
            print(f"  [OK]   {label:20s} -> {p.relative_to(ROOT)} ({n_rows} wierszy)")

    if ready_all:
        print("\nWszystkie 3 tabele są gotowe! Możesz odpalić trening sieci:")
        print("  .venv/bin/python -m ml.train --data-dir data/ml")
        if px_master.exists() and px_sat.exists():
            print("  .venv/bin/python -m ml.train --data-dir data/ml --mode pixel")
    else:
        print(
            "\nBrakuje części tabel czasowych (satelita lub pogoda). Po uzupełnieniu linków w .env "
            "i uruchomieniu bez --skip-download pojawią się w data/ml/."
        )


def main(argv: list[str] | None = None) -> None:
    args = build_cli().parse_args(argv)
    os.chdir(ROOT)
    load_env_file(args.env_file)

    # Walidacja dat
    d0 = date.fromisoformat(args.start_date)
    d1 = date.fromisoformat(args.end_date)
    if d0 > d1:
        raise ValueError(f"--start-date ({d0}) nie może być późniejsza niż --end-date ({d1}).")

    bbox, tag = _resolve_bbox_and_tag(args)
    voivs = detect_voivodeships_for_bbox(bbox)
    service_urls = get_service_urls(args.env_file)
    soil_urls = get_soil_urls(args.env_file)
    crop_urls = get_cropland_urls(args.env_file)

    print("==================== KONFIGURACJA MAIN PIPELINE ====================")
    print(f"Obszar (tag):      {tag}")
    print(f"Bounding box:      {list(bbox)} [min_lon, min_lat, max_lon, max_lat]")
    print(f"Województwa:       {voivs}")
    print(f"Zakres dat:        {args.start_date} .. {args.end_date} (pola: {args.fields_year}, uprawy: {args.crop_year})")
    print(f"Źródła:            fields={args.fields_source}, soil={args.soil_source}, weather={args.weather_source}")
    print(f"Plik .env:         {args.env_file} ({'istnieje' if args.env_file.exists() else 'BRAK'})")
    print(
        f"Linki w .env:      CROPLAND={len(crop_urls)} lat, SOIL={len(soil_urls)} woj., "
        f"BAYER_GRIDS={'TAK' if get_bayer_grids_url(args.env_file) else 'NIE'}"
    )

    if args.dry_run:
        soil_mode_preview = _resolve_soil_mode(args.soil_source, voivs, args.env_file, ROOT / "data/soil/aws_cache")
        print("\n[DRY-RUN] Planowane artefakty wyjściowe:")
        print(f"  - Granice pól:      data/fields/{tag}_fields.geojson")
        print(f"  - Uprawy CLMS:      data/fields/{tag}_fields_crops.geojson")
        print(f"  - Gleba ({soil_mode_preview}):    data/soil/fields_soil_profiles.parquet (+ H3 + SQL)")
        print(f"  - Satelita S2:      data/satellite/{tag}_{args.start_date}_to_{args.end_date}/ -> data/ml/satellite_indices.parquet")
        print(f"  - Zbiór ML:         data/ml/{{fields_master,satellite_indices,weather_daily}}.parquet")
        return

    fields_geojson = run_stage_fields(
        bbox=bbox,
        tag=tag,
        fields_year=args.fields_year,
        fields_source=args.fields_source,
        min_area_ha=args.min_area_ha,
        fields_geojson_arg=args.fields_geojson,
        service_urls=service_urls,
        skip_download=args.skip_download,
        force=args.force,
    )

    fields_crops_geojson = run_stage_crops(
        fields_geojson=fields_geojson,
        tag=tag,
        crop_year=args.crop_year,
        env_path=args.env_file,
        skip_download=args.skip_download,
        force=args.force,
    )

    soil_parquet, soil_df, effective_soil_mode = run_stage_soil(
        fields_crops_geojson=fields_crops_geojson,
        bbox=bbox,
        voivs=voivs,
        soil_source=args.soil_source,
        min_area_ha=args.min_area_ha,
        env_path=args.env_file,
        force=args.force,
    )

    print("\n--- [6/6] BUDOWA fields_master.parquet ---")
    fields_master_path = DEFAULT_ML_DIR / "fields_master.parquet"
    build_fields_master(
        fields_crops_geojson=fields_crops_geojson,
        soil_profiles_parquet=soil_parquet,
        out_path=fields_master_path,
        min_area_ha=args.min_area_ha,
    )

    run_stage_satellite(
        fields_crops_geojson=fields_crops_geojson,
        tag=tag,
        start_date=args.start_date,
        end_date=args.end_date,
        n_scenes=args.n_scenes,
        max_cloud=args.max_cloud,
        min_area_ha=args.min_area_ha,
        soil_mode=effective_soil_mode,
        voivs=voivs,
        env_path=args.env_file,
        run_zones=args.run_zones,
        prepare_pixels=args.prepare_pixels,
        pixels_per_field=args.pixels_per_field,
        skip_download=args.skip_download,
        force=args.force,
    )

    run_stage_weather(
        fields_master_parquet=fields_master_path,
        bbox=bbox,
        voivs=voivs,
        start_date=args.start_date,
        end_date=args.end_date,
        weather_source=args.weather_source,
        env_path=args.env_file,
        skip_download=args.skip_download,
        force=args.force,
    )

    if args.run_protection:
        run_stage_protection(
            soil_df=soil_df,
            bbox=bbox,
            start_date=args.start_date,
            end_date=args.end_date,
            skip_download=args.skip_download,
        )

    _print_ml_readiness_summary()


if __name__ == "__main__":
    main()
