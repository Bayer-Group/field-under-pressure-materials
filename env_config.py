from __future__ import annotations

import os
from pathlib import Path
import re


VOIVODESHIPS: tuple[str, ...] = (
    "DOLNOSLASKIE",
    "KUJAWSKO_POMORSKIE",
    "LUBELSKIE",
    "LUBUSKIE",
    "LODZKIE",
    "MALOPOLSKIE",
    "MAZOWIECKIE",
    "OPOLSKIE",
    "PODKARPACKIE",
    "PODLASKIE",
    "POMORSKIE",
    "SLASKIE",
    "SWIETOKRZYSKIE",
    "WARMINSKO_MAZURSKIE",
    "WIELKOPOLSKIE",
    "ZACHODNIOPOMORSKIE",
)

# Przybliżone zasięgi WGS84 (min_lon, min_lat, max_lon, max_lat) województw w Polsce
VOIVODESHIP_BBOXES: dict[str, tuple[float, float, float, float]] = {
    "DOLNOSLASKIE": (14.82, 50.09, 17.79, 51.80),
    "KUJAWSKO_POMORSKIE": (17.25, 52.33, 19.76, 53.78),
    "LUBELSKIE": (21.62, 50.25, 24.15, 52.29),
    "LUBUSKIE": (14.53, 51.36, 16.42, 53.12),
    "LODZKIE": (18.07, 50.84, 20.66, 52.39),
    "MALOPOLSKIE": (19.08, 49.18, 21.42, 50.52),
    "MAZOWIECKIE": (19.26, 51.01, 23.13, 53.48),
    "OPOLSKIE": (16.90, 49.97, 18.70, 51.19),
    "PODKARPACKIE": (21.14, 49.00, 23.55, 50.82),
    "PODLASKIE": (21.59, 52.28, 23.95, 54.41),
    "POMORSKIE": (16.70, 53.49, 19.65, 54.84),
    "SLASKIE": (18.03, 49.39, 19.97, 51.10),
    "SWIETOKRZYSKIE": (19.70, 50.19, 21.87, 51.34),
    "WARMINSKO_MAZURSKIE": (19.13, 53.14, 22.81, 54.45),
    "WIELKOPOLSKIE": (15.78, 51.10, 19.10, 53.66),
    "ZACHODNIOPOMORSKIE": (14.12, 52.62, 16.99, 54.57),
}

# Nazwy województw używane w paczkach Bayer weather_data/
VOIVODESHIP_BAYER_NAMES: dict[str, str] = {
    "DOLNOSLASKIE": "Dolnoslaskie",
    "KUJAWSKO_POMORSKIE": "Kujawsko-Pomorskie",
    "LUBELSKIE": "Lubelskie",
    "LUBUSKIE": "Lubuskie",
    "LODZKIE": "Lodzkie",
    "MALOPOLSKIE": "Malopolskie",
    "MAZOWIECKIE": "Mazowieckie",
    "OPOLSKIE": "Opolskie",
    "PODKARPACKIE": "Podkarpackie",
    "PODLASKIE": "Podlaskie",
    "POMORSKIE": "Pomorskie",
    "SLASKIE": "Slaskie",
    "SWIETOKRZYSKIE": "Swietokrzyskie",
    "WARMINSKO_MAZURSKIE": "Warminsko-Mazurskie",
    "WIELKOPOLSKIE": "Wielkopolskie",
    "ZACHODNIOPOMORSKIE": "Zachodniopomorskie",
}

DEFAULT_SERVICE_URLS: dict[str, str] = {
    "SENTINEL_STAC_URL": "https://earth-search.aws.element84.com/v1",
    "FTW_GRID_URL": "https://data.source.coop/ftw/global-field-boundaries/download-tiles/ftw-download-grid-v2.geojson",
    "FTW_PARQUET_URL_TEMPLATE": "https://data.source.coop/ftw/global-field-boundaries/download-tiles/geoparquet/{year}/{year}_{tile_id}.parquet",
    "FTW_MODEL_URL": "https://github.com/fieldsoftheworld/ftw-baselines/releases/download/v3.1/prue_efnetb3_ccby_checkpoint.ckpt",
    "OPEN_METEO_FORECAST_URL": "https://api.open-meteo.com/v1/forecast",
    "OPEN_METEO_ARCHIVE_URL": "https://archive-api.open-meteo.com/v1/archive",
}


def load_env_file(
    env_path: str | Path = ".env",
    override: bool = False,
) -> dict[str, str]:
    """
    Lekki parser pliku .env bez zależności zewnętrznych (python-dotenv nie jest wymagany).
    Dzieli po pierwszym znaku '=' (zachowując znaki '=' w presigned linkach AWS S3)
    i wpisuje niepuste wartości do os.environ.
    """
    path = Path(env_path)
    parsed: dict[str, str] = {}
    if not path.exists():
        return parsed

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip()
        if not key:
            continue
        if len(val) >= 2 and ((val[0] == '"' and val[-1] == '"') or (val[0] == "'" and val[-1] == "'")):
            val = val[1:-1]
        parsed[key] = val
        if val and (override or key not in os.environ):
            os.environ[key] = val

    return parsed


def _merged_env(env_path: str | Path = ".env") -> dict[str, str]:
    merged = load_env_file(env_path, override=False)
    for k, v in os.environ.items():
        if v:
            merged[k] = v
    return merged


def normalize_voivodeship_key(name: str) -> str:
    txt = str(name).strip().upper().replace("-", "_").replace(" ", "_")
    pl_map = str.maketrans("ĄĆĘŁŃÓŚŹŻ", "ACELNOSZZ")
    return txt.translate(pl_map)


def detect_voivodeships_for_bbox(
    bbox: tuple[float, float, float, float] | list[float],
) -> list[str]:
    """
    Zwraca listę kluczy województw przecinających zadany bbox [min_lon, min_lat, max_lon, max_lat],
    posortowaną malejąco po powierzchni części wspólnej (główne województwo jako pierwsze).
    """
    min_lon, min_lat, max_lon, max_lat = map(float, bbox)
    bbox_area = max((max_lon - min_lon) * (max_lat - min_lat), 1e-12)

    hits: list[tuple[float, float, str]] = []
    for key, (v_minx, v_miny, v_maxx, v_maxy) in VOIVODESHIP_BBOXES.items():
        ix = min(max_lon, v_maxx) - max(min_lon, v_minx)
        iy = min(max_lat, v_maxy) - max(min_lat, v_miny)
        if ix > 0.0 and iy > 0.0:
            inter_frac = (ix * iy) / bbox_area
            v_area = (v_maxx - v_minx) * (v_maxy - v_miny)
            hits.append((-inter_frac, v_area, key))

    hits.sort()
    return [item[2] for item in hits]


def get_soil_urls(env_path: str | Path = ".env") -> dict[str, str]:
    env = _merged_env(env_path)
    out: dict[str, str] = {}
    for key, val in env.items():
        if key.startswith("SOIL_URL_") and val.strip():
            v_key = normalize_voivodeship_key(key[len("SOIL_URL_") :])
            out[v_key] = val.strip()
    return out


def get_cropland_urls(env_path: str | Path = ".env") -> dict[int, str]:
    env = _merged_env(env_path)
    out: dict[int, str] = {}
    for key, val in env.items():
        m = re.fullmatch(r"CROPLAND_URL_(\d{4})", key)
        if m and val.strip():
            out[int(m.group(1))] = val.strip()
    return out


def get_bayer_daily_url(
    year: int,
    voivodeship: str,
    env_path: str | Path = ".env",
) -> str | None:
    env = _merged_env(env_path)
    v_key = normalize_voivodeship_key(voivodeship)
    for cand in (
        f"BAYER_WEATHER_DAILY_{int(year)}_{v_key}",
        f"BAYER_WEATHER_DAILY_{int(year)}",
    ):
        val = env.get(cand, "").strip()
        if val:
            return val
    return None


def get_bayer_hourly_url(
    year: int,
    voivodeship: str,
    env_path: str | Path = ".env",
) -> str | None:
    env = _merged_env(env_path)
    v_key = normalize_voivodeship_key(voivodeship)
    for cand in (
        f"BAYER_WEATHER_HOURLY_{int(year)}_{v_key}",
        f"BAYER_WEATHER_HOURLY_{int(year)}",
    ):
        val = env.get(cand, "").strip()
        if val:
            return val
    return None


def get_bayer_grids_url(env_path: str | Path = ".env") -> str | None:
    val = _merged_env(env_path).get("BAYER_WEATHER_GRIDS_URL", "").strip()
    return val or None


def get_bayer_imerg_urls(env_path: str | Path = ".env") -> tuple[str | None, str | None]:
    env = _merged_env(env_path)
    daily = env.get("BAYER_IMERG_DAILY_URL", "").strip() or None
    hourly = env.get("BAYER_IMERG_HOURLY_URL", "").strip() or None
    return daily, hourly


def get_service_urls(env_path: str | Path = ".env") -> dict[str, str]:
    env = _merged_env(env_path)
    return {
        key: (env.get(key, "").strip() or default_url)
        for key, default_url in DEFAULT_SERVICE_URLS.items()
    }
