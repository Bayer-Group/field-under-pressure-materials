from __future__ import annotations

from datetime import date, datetime, timedelta
import os
from pathlib import Path
import time
from typing import Literal

import duckdb
import numpy as np
import pandas as pd
import requests


OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

# Maks. 10 zmiennych na endpoint (brak mnożnika kosztu nVariables / 10 w Open-Meteo)
FORECAST_HOURLY_VARS = [
    "temperature_2m",
    "relative_humidity_2m",
    "dew_point_2m",
    "precipitation",
    "wind_speed_10m",
    "soil_moisture_0_to_1cm",
    "soil_moisture_1_to_3cm",
    "soil_moisture_3_to_9cm",
    "soil_moisture_9_to_27cm",
]

ARCHIVE_HOURLY_VARS = [
    "temperature_2m",
    "relative_humidity_2m",
    "dew_point_2m",
    "precipitation",
    "wind_speed_10m",
    "soil_moisture_0_to_7cm",
    "soil_moisture_7_to_28cm",
    "soil_moisture_28_to_100cm",
]

# Wspólne 5 zmiennych godzinowych do Modułu 2 (zwilżenie liści, choroby, okno oprysku)
HOURLY_CORE_VARS = [
    "temperature_2m",
    "relative_humidity_2m",
    "dew_point_2m",
    "precipitation",
    "wind_speed_10m",
]

DAILY_OUTPUT_COLS = [
    "lat",
    "lon",
    "date",
    "temp_mean_c",
    "temp_min_c",
    "temp_max_c",
    "rh_mean_pct",
    "dew_point_mean_c",
    "wind_mean_kmh",
    "wind_max_kmh",
    "precip_sum_mm",
    "precip_72h_mm",
    "sm_l1",
    "sm_l2",
]

HOURLY_OUTPUT_COLS = [
    "lat",
    "lon",
    "time",
    "date",
    "hour",
    "temp_c",
    "rh_pct",
    "dew_point_c",
    "precip_mm",
    "wind_kmh",
]

# Alias wsteczny dla kodu odwołującego się do starej nazwy
OUTPUT_COLS = DAILY_OUTPUT_COLS

MAX_BATCH_WEIGHT = 250.0
MAX_CHUNK_DAYS = 90
ARCHIVE_LAG_DAYS = 6
FORECAST_PAST_LIMIT_DAYS = 60
FORECAST_MAX_AHEAD_DAYS = 15


def _parse_date(value: str | date | datetime) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value.strip())
    raise TypeError(f"Nieobsługiwany typ daty: {type(value)!r}")


def generate_poland_grid(lat_step: float = 0.25, lon_step: float = 0.35) -> list[tuple[float, float]]:
    """
    Generuje regularną siatkę punktów pokrywającą Polskę (~25 km odstępu).
    Przy domyślnych krokach daje ~696 punktów.
    """
    lats = np.arange(49.0, 54.9 + 1e-6, lat_step)
    lons = np.arange(14.1, 24.2 + 1e-6, lon_step)
    return [(round(float(lat), 4), round(float(lon), 4)) for lat in lats for lon in lons]


def _weighted_mean(series_list: list[pd.Series], weights: list[float]) -> pd.Series:
    num = pd.Series(0.0, index=series_list[0].index, dtype="float64")
    den = pd.Series(0.0, index=series_list[0].index, dtype="float64")
    for series, w in zip(series_list, weights):
        s = pd.to_numeric(series, errors="coerce")
        valid = s.notna()
        num = num + s.fillna(0.0) * w
        den = den + valid.astype("float64") * w
    return num.where(den > 0.0, np.nan) / den.where(den > 0.0, np.nan)


def _plan_segments(
    start_d: date,
    end_d: date,
    today: str | date | datetime | None = None,
) -> list[tuple[Literal["archive", "forecast"], date, date]]:
    if start_d > end_d:
        raise ValueError(f"start_date ({start_d}) nie może być późniejsza niż end_date ({end_d}).")

    today_d = _parse_date(today) if today is not None else date.today()
    max_ahead = today_d + timedelta(days=FORECAST_MAX_AHEAD_DAYS)
    if end_d > max_ahead:
        raise ValueError(f"end_date ({end_d}) wykracza poza horyzont prognozy Open-Meteo ({max_ahead}).")

    archive_cutoff = today_d - timedelta(days=ARCHIVE_LAG_DAYS)
    forecast_min = today_d - timedelta(days=FORECAST_PAST_LIMIT_DAYS)

    raw_segments: list[tuple[Literal["archive", "forecast"], date, date]]
    if end_d <= archive_cutoff:
        raw_segments = [("archive", start_d, end_d)]
    elif start_d >= forecast_min:
        raw_segments = [("forecast", start_d, end_d)]
    else:
        raw_segments = [
            ("archive", start_d, archive_cutoff),
            ("forecast", archive_cutoff + timedelta(days=1), end_d),
        ]

    chunks: list[tuple[Literal["archive", "forecast"], date, date]] = []
    for src, seg_start, seg_end in raw_segments:
        cur = seg_start
        while cur <= seg_end:
            chunk_end = min(seg_end, cur + timedelta(days=MAX_CHUNK_DAYS - 1))
            chunks.append((src, cur, chunk_end))
            cur = chunk_end + timedelta(days=1)
    return chunks


def _request_open_meteo(
    url: str,
    params: dict,
    max_retries: int = 6,
    session: requests.Session | None = None,
) -> dict | list:
    http = session if session is not None else requests
    for attempt in range(max_retries):
        resp = http.get(url, params=params, timeout=60)
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code == 429:
            reason = ""
            try:
                reason = str(resp.json().get("reason", ""))
            except Exception:
                pass
            if "daily" in reason.lower():
                raise RuntimeError(f"Przekroczono dzienny limit Open-Meteo (429): {reason}")
            if attempt == max_retries - 1:
                raise RuntimeError(f"Przekroczono liczbę prób pobrania danych z Open-Meteo (429): {reason}")
            wait_s = 65 + 30 * attempt
            print(f"[RATE LIMIT 429] {reason or 'limit minutowy'} — czekam {wait_s}s przed ponowieniem...")
            time.sleep(wait_s)
        else:
            resp.raise_for_status()
    raise RuntimeError("Przekroczono liczbę prób pobrania danych z Open-Meteo (429).")


def _compute_batch_pacing(n_locs: int, n_days: int, batch_size: int, pause_sec: float) -> tuple[int, float]:
    weight_per_loc = max(1.0, n_days / 14.0)
    eff_bs = max(1, min(batch_size, int(MAX_BATCH_WEIGHT // weight_per_loc) or 1))
    return eff_bs, weight_per_loc


def _add_precip_72h(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.sort_values(["lat", "lon", "date"]).reset_index(drop=True)
    out["precip_72h_mm"] = (
        out.groupby(["lat", "lon"], sort=False)["precip_sum_mm"]
        .transform(lambda s: s.iloc[::-1].rolling(3, min_periods=1).sum().iloc[::-1])
        .round(3)
    )
    return out


def fetch_batch_daily(
    coords: list[tuple[float, float]],
    past_days: int = 14,
    forecast_days: int = 7,
    start_date: str | date | datetime | None = None,
    end_date: str | date | datetime | None = None,
    source: Literal["forecast", "archive"] | None = None,
    max_retries: int = 6,
    session: requests.Session | None = None,
) -> pd.DataFrame:
    """
    Pobiera paczkę lokalizacji z Open-Meteo w trybie bieżącym (past_days/forecast_days)
    lub historycznym/zakresowym (start_date/end_date -> automatyczny wybór Archive/Forecast).
    Agreguje do danych dziennych oraz mapuje wilgotność gleby na warstwy Bayer L1-L3.
    """
    if not coords:
        return pd.DataFrame(columns=DAILY_OUTPUT_COLS)

    use_range = start_date is not None or end_date is not None
    if use_range:
        if start_date is None or end_date is None:
            raise ValueError("Podaj oba parametry: start_date oraz end_date.")
        start_d = _parse_date(start_date)
        end_d = _parse_date(end_date)
        if source is None:
            source = "archive" if end_d <= date.today() - timedelta(days=ARCHIVE_LAG_DAYS) else "forecast"
        url = OPEN_METEO_ARCHIVE_URL if source == "archive" else OPEN_METEO_FORECAST_URL
        hourly_vars = ARCHIVE_HOURLY_VARS if source == "archive" else FORECAST_HOURLY_VARS
        params = {
            "latitude": ",".join(str(lat) for lat, _ in coords),
            "longitude": ",".join(str(lon) for _, lon in coords),
            "hourly": ",".join(hourly_vars),
            "start_date": start_d.isoformat(),
            "end_date": end_d.isoformat(),
            "timezone": "Europe/Warsaw",
        }
    else:
        source = source or "forecast"
        url = OPEN_METEO_FORECAST_URL
        hourly_vars = FORECAST_HOURLY_VARS
        params = {
            "latitude": ",".join(str(lat) for lat, _ in coords),
            "longitude": ",".join(str(lon) for _, lon in coords),
            "hourly": ",".join(hourly_vars),
            "past_days": past_days,
            "forecast_days": forecast_days,
            "timezone": "Europe/Warsaw",
        }

    payload = _request_open_meteo(url, params, max_retries=max_retries, session=session)
    items = [payload] if isinstance(payload, dict) else payload

    daily_frames = []
    for (req_lat, req_lon), item in zip(coords, items):
        hourly = item.get("hourly")
        if not hourly or "time" not in hourly:
            continue

        df_h = pd.DataFrame(hourly)
        for col in hourly_vars:
            if col not in df_h.columns:
                df_h[col] = np.nan
            df_h[col] = pd.to_numeric(df_h[col], errors="coerce")

        df_h["date"] = pd.to_datetime(df_h["time"]).dt.strftime("%Y-%m-%d")

        agg_spec: dict[str, tuple[str, object]] = {
            "temp_mean_c": ("temperature_2m", "mean"),
            "temp_min_c": ("temperature_2m", "min"),
            "temp_max_c": ("temperature_2m", "max"),
            "rh_mean_pct": ("relative_humidity_2m", "mean"),
            "dew_point_mean_c": ("dew_point_2m", "mean"),
            "wind_mean_kmh": ("wind_speed_10m", "mean"),
            "wind_max_kmh": ("wind_speed_10m", "max"),
            "precip_sum_mm": ("precipitation", lambda s: s.sum(min_count=1)),
        }

        if source == "archive":
            agg_spec.update(
                {
                    "sm_l1": ("soil_moisture_0_to_7cm", "mean"),
                    "sm_l2": ("soil_moisture_7_to_28cm", "mean"),
                }
            )
            df_d = df_h.groupby("date", as_index=False).agg(**agg_spec).sort_values("date").reset_index(drop=True)
        else:
            agg_spec.update(
                {
                    "_sm_0_1": ("soil_moisture_0_to_1cm", "mean"),
                    "_sm_1_3": ("soil_moisture_1_to_3cm", "mean"),
                    "_sm_3_9": ("soil_moisture_3_to_9cm", "mean"),
                    "_sm_9_27": ("soil_moisture_9_to_27cm", "mean"),
                }
            )
            df_d = df_h.groupby("date", as_index=False).agg(**agg_spec).sort_values("date").reset_index(drop=True)
            df_d["sm_l1"] = _weighted_mean([df_d["_sm_0_1"], df_d["_sm_1_3"], df_d["_sm_3_9"]], [1.0, 2.0, 4.0])
            df_d["sm_l2"] = _weighted_mean([df_d["_sm_3_9"], df_d["_sm_9_27"]], [2.0, 15.0])

        df_d["precip_72h_mm"] = (
            df_d["precip_sum_mm"].iloc[::-1].rolling(3, min_periods=1).sum().iloc[::-1]
        )
        df_d.insert(0, "lon", req_lon)
        df_d.insert(0, "lat", req_lat)
        daily_frames.append(df_d[DAILY_OUTPUT_COLS])

    if not daily_frames:
        return pd.DataFrame(columns=DAILY_OUTPUT_COLS)

    out = pd.concat(daily_frames, ignore_index=True)
    num_cols = [c for c in DAILY_OUTPUT_COLS if c not in ("lat", "lon", "date")]
    out[num_cols] = out[num_cols].round(3)
    return out


def fetch_poland_weather_daily(
    output_parquet: str | Path | None = None,
    output_dir: str | Path = "weather_cache",
    coords: list[tuple[float, float]] | None = None,
    past_days: int = 14,
    forecast_days: int = 7,
    start_date: str | date | datetime | None = None,
    end_date: str | date | datetime | None = None,
    batch_size: int = 50,
    pause_sec: float = 6.5,
    force_refresh: bool = False,
    today: str | date | datetime | None = None,
) -> pd.DataFrame:
    """
    Pobiera dzienną pogodę z Open-Meteo dla trybu bieżącego (past_days + forecast_days)
    lub trybu historycznego (start_date..end_date z automatycznym Archive/Forecast API)
    i zapisuje wynik w jednym pliku Parquet z datą w nazwie (cache na dysku).
    """
    today_d = _parse_date(today) if today is not None else date.today()
    use_range = start_date is not None or end_date is not None
    if use_range:
        if start_date is None or end_date is None:
            raise ValueError("Podaj oba parametry: start_date oraz end_date.")
        start_d = _parse_date(start_date)
        end_d = _parse_date(end_date)
        default_name = f"open_meteo_poland_daily_{start_d.isoformat()}_to_{end_d.isoformat()}.parquet"
    else:
        default_name = f"open_meteo_poland_daily_{today_d.isoformat()}.parquet"

    out_path = Path(output_parquet) if output_parquet is not None else Path(output_dir) / default_name
    out_path.parent.mkdir(parents=True, exist_ok=True)

    expected_cols = set(DAILY_OUTPUT_COLS)
    if out_path.exists() and not force_refresh:
        cached_df = pd.read_parquet(out_path)
        if not cached_df.empty and expected_cols.issubset(cached_df.columns):
            print(f"[CACHE] Wczytano dane pogodowe z {out_path} ({len(cached_df)} wierszy).")
            return cached_df[DAILY_OUTPUT_COLS]

    grid_coords = coords if coords is not None else generate_poland_grid()
    all_batches: list[pd.DataFrame] = []

    with requests.Session() as session:
        if use_range:
            segments = _plan_segments(start_d, end_d, today=today_d)
            plan: list[tuple[Literal["archive", "forecast"], date, date, list[tuple[float, float]], float]] = []
            for src, seg_start, seg_end in segments:
                seg_days = (seg_end - seg_start).days + 1
                eff_bs, w_per_loc = _compute_batch_pacing(len(grid_coords), seg_days, batch_size, pause_sec)
                for idx in range(0, len(grid_coords), eff_bs):
                    batch = grid_coords[idx : idx + eff_bs]
                    plan.append((src, seg_start, seg_end, batch, len(batch) * w_per_loc))

            print(f"[START] Pobieranie historycznej pogody ({start_d}..{end_d}) dla {len(grid_coords)} pkt ({len(plan)} paczek)...")
            for b_no, (src, s_d, e_d, batch, weight) in enumerate(plan, start=1):
                print(f"  -> Paczka {b_no}/{len(plan)} [{src} {s_d}..{e_d}] ({len(batch)} pkt)...")
                all_batches.append(
                    fetch_batch_daily(batch, start_date=s_d, end_date=e_d, source=src, session=session)
                )
                if b_no < len(plan):
                    time.sleep(max(pause_sec, weight / 8.0))
        else:
            n_days = max(1, past_days + forecast_days)
            total_batches = (len(grid_coords) + batch_size - 1) // batch_size
            print(f"[START] Pobieranie pogody dla {len(grid_coords)} punktów ({total_batches} paczek po <= {batch_size})...")
            for idx in range(0, len(grid_coords), batch_size):
                batch = grid_coords[idx : idx + batch_size]
                batch_no = idx // batch_size + 1
                print(f"  -> Paczka {batch_no}/{total_batches} ({len(batch)} pkt)...")
                all_batches.append(
                    fetch_batch_daily(batch, past_days=past_days, forecast_days=forecast_days, session=session)
                )
                if batch_no < total_batches:
                    batch_weight = len(batch) * max(1.0, n_days / 14.0)
                    time.sleep(max(pause_sec, batch_weight / 8.0))

    full_df = pd.concat(all_batches, ignore_index=True) if all_batches else pd.DataFrame(columns=DAILY_OUTPUT_COLS)
    if use_range and not full_df.empty:
        full_df = _add_precip_72h(full_df)[DAILY_OUTPUT_COLS]

    tmp_path = out_path.with_suffix(".tmp.parquet")
    full_df.to_parquet(tmp_path, index=False)
    os.replace(tmp_path, out_path)
    print(f"[GOTOWE] Zapisano {len(full_df)} wierszy dziennych do {out_path}.")
    return full_df


def fetch_weather_hourly(
    coords: list[tuple[float, float]] | None = None,
    output_parquet: str | Path | None = None,
    output_dir: str | Path = "weather_cache",
    past_days: int = 2,
    forecast_days: int = 7,
    start_date: str | date | datetime | None = None,
    end_date: str | date | datetime | None = None,
    batch_size: int = 50,
    pause_sec: float = 6.5,
    force_refresh: bool = False,
    today: str | date | datetime | None = None,
) -> pd.DataFrame:
    """
    Pobiera pogodę godzinową (temp, wilgotność, punkt rosy, opad, wiatr)
    dla Modułu 2 (zwilżenie liści, ryzyko chorób, godziny okna oprysku).
    """
    today_d = _parse_date(today) if today is not None else date.today()
    use_range = start_date is not None or end_date is not None
    if use_range:
        if start_date is None or end_date is None:
            raise ValueError("Podaj oba parametry: start_date oraz end_date.")
        start_d = _parse_date(start_date)
        end_d = _parse_date(end_date)
        default_name = f"open_meteo_hourly_{start_d.isoformat()}_to_{end_d.isoformat()}.parquet"
    else:
        default_name = f"open_meteo_hourly_{today_d.isoformat()}.parquet"

    out_path = Path(output_parquet) if output_parquet is not None else Path(output_dir) / default_name
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if out_path.exists() and not force_refresh:
        cached = pd.read_parquet(out_path)
        if not cached.empty and set(HOURLY_OUTPUT_COLS).issubset(cached.columns):
            print(f"[CACHE] Wczytano pogodę godzinową z {out_path} ({len(cached)} wierszy).")
            return cached[HOURLY_OUTPUT_COLS]

    grid_coords = coords if coords is not None else generate_poland_grid()

    def _fetch_hourly_batch(batch_pts, params_base, url) -> pd.DataFrame:
        params = {
            **params_base,
            "latitude": ",".join(str(lat) for lat, _ in batch_pts),
            "longitude": ",".join(str(lon) for _, lon in batch_pts),
            "hourly": ",".join(HOURLY_CORE_VARS),
            "timezone": "Europe/Warsaw",
        }
        payload = _request_open_meteo(url, params, session=session)
        items = [payload] if isinstance(payload, dict) else payload
        frames = []
        for (r_lat, r_lon), item in zip(batch_pts, items):
            h_data = item.get("hourly")
            if not h_data or "time" not in h_data:
                continue
            df_h = pd.DataFrame(h_data)
            ts = pd.to_datetime(df_h["time"])
            frames.append(
                pd.DataFrame(
                    {
                        "lat": r_lat,
                        "lon": r_lon,
                        "time": ts.dt.strftime("%Y-%m-%dT%H:%M"),
                        "date": ts.dt.strftime("%Y-%m-%d"),
                        "hour": ts.dt.hour.astype(int),
                        "temp_c": pd.to_numeric(df_h["temperature_2m"], errors="coerce").round(2),
                        "rh_pct": pd.to_numeric(df_h["relative_humidity_2m"], errors="coerce").round(1),
                        "dew_point_c": pd.to_numeric(df_h["dew_point_2m"], errors="coerce").round(2),
                        "precip_mm": pd.to_numeric(df_h["precipitation"], errors="coerce").round(2),
                        "wind_kmh": pd.to_numeric(df_h["wind_speed_10m"], errors="coerce").round(1),
                    }
                )
            )
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=HOURLY_OUTPUT_COLS)

    all_frames: list[pd.DataFrame] = []
    with requests.Session() as session:
        if use_range:
            segments = _plan_segments(start_d, end_d, today=today_d)
            plan = []
            for src, seg_start, seg_end in segments:
                seg_days = (seg_end - seg_start).days + 1
                eff_bs, w_per_loc = _compute_batch_pacing(len(grid_coords), seg_days, batch_size, pause_sec)
                url = OPEN_METEO_ARCHIVE_URL if src == "archive" else OPEN_METEO_FORECAST_URL
                for idx in range(0, len(grid_coords), eff_bs):
                    batch = grid_coords[idx : idx + eff_bs]
                    plan.append((url, {"start_date": seg_start.isoformat(), "end_date": seg_end.isoformat()}, batch, len(batch) * w_per_loc))
            for b_no, (url, p_base, batch, weight) in enumerate(plan, start=1):
                all_frames.append(_fetch_hourly_batch(batch, p_base, url))
                if b_no < len(plan):
                    time.sleep(max(pause_sec, weight / 8.0))
        else:
            n_days = max(1, past_days + forecast_days)
            total_b = (len(grid_coords) + batch_size - 1) // batch_size
            for idx in range(0, len(grid_coords), batch_size):
                batch = grid_coords[idx : idx + batch_size]
                b_no = idx // batch_size + 1
                all_frames.append(
                    _fetch_hourly_batch(batch, {"past_days": past_days, "forecast_days": forecast_days}, OPEN_METEO_FORECAST_URL)
                )
                if b_no < total_b:
                    time.sleep(max(pause_sec, len(batch) * max(1.0, n_days / 14.0) / 8.0))

    out = pd.concat(all_frames, ignore_index=True) if all_frames else pd.DataFrame(columns=HOURLY_OUTPUT_COLS)
    if not out.empty:
        out = out.drop_duplicates(subset=["lat", "lon", "time"], keep="last").sort_values(["lat", "lon", "time"]).reset_index(drop=True)

    tmp_path = out_path.with_suffix(".tmp.parquet")
    out.to_parquet(tmp_path, index=False)
    os.replace(tmp_path, out_path)
    print(f"[GOTOWE] Zapisano {len(out)} wierszy godzinowych do {out_path}.")
    return out


def load_bayer_weather_hourly(
    bayer_hourly_parquets: str | Path | list[str | Path],
    weather_grids_parquet: str | Path,
    fields_df: pd.DataFrame,
    imerg_hourly_parquet: str | Path | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    """
    Wczytuje godzinową pogodę historyczną Bayera (2020-2025) dla pól i opcjonalnie
    dołącza godzinowe opady satelitarne IMERG (gdy w plikach Bayera brakuje opadów).
    """
    if isinstance(bayer_hourly_parquets, (str, Path)):
        p = Path(bayer_hourly_parquets)
        parquet_list = [str(f) for f in sorted(p.rglob("*.parquet"))] if p.is_dir() else [str(p)]
    else:
        parquet_list = [str(Path(f)) for f in bayer_hourly_parquets]
    if not parquet_list:
        raise FileNotFoundError("Brak plików Parquet z godzinową pogodą Bayera.")

    grids_df = pd.read_parquet(weather_grids_parquet)[["grid_id", "lat", "lon"]].drop_duplicates().reset_index(drop=True)
    g_lats = grids_df["lat"].to_numpy(dtype=np.float64)
    g_lons = grids_df["lon"].to_numpy(dtype=np.float64)

    mapped = []
    for row in fields_df.itertuples():
        cos_lat = float(np.cos(np.radians(row.centroid_lat)))
        dist2 = (g_lats - row.centroid_lat) ** 2 + ((g_lons - row.centroid_lon) * cos_lat) ** 2
        best = grids_df.iloc[int(np.argmin(dist2))]
        mapped.append({"field_id": str(row.field_id), "grid_id": str(best["grid_id"])})
    map_df = pd.DataFrame(mapped)

    con = duckdb.connect()
    con.register("field_grid_map", map_df)
    bayer_cols = set(
        con.execute("DESCRIBE SELECT * FROM read_parquet($1)", [parquet_list[0]])
        .df()["column_name"]
        .tolist()
    )
    has_precip = "precipitation" in bayer_cols

    imerg_join = ""
    if imerg_hourly_parquet is not None:
        imerg_p = Path(imerg_hourly_parquet).as_posix()
        imerg_join = (
            f"LEFT JOIN read_parquet('{imerg_p}') AS i "
            "ON b.grid_id = i.grid_id AND CAST(b.local_time AS TIMESTAMP) = CAST(i.local_time AS TIMESTAMP)"
        )
        precip_expr = (
            "COALESCE(CAST(b.precipitation AS DOUBLE), CAST(i.precipitation AS DOUBLE), 0.0)"
            if has_precip
            else "COALESCE(CAST(i.precipitation AS DOUBLE), 0.0)"
        )
    else:
        if has_precip:
            precip_expr = "COALESCE(CAST(b.precipitation AS DOUBLE), 0.0)"
        else:
            print("[UWAGA] Brak precipitation w plikach godzinowych Bayera i brak imerg_hourly_parquet — wstawiam 0.0.")
            precip_expr = "0.0"

    where_parts = []
    params: list = [parquet_list]
    if start_date is not None:
        where_parts.append("CAST(b.date AS DATE) >= CAST($2 AS DATE)")
        params.append(start_date)
    if end_date is not None:
        idx = len(params) + 1
        where_parts.append(f"CAST(b.date AS DATE) <= CAST(${idx} AS DATE)")
        params.append(end_date)
    where_sql = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""

    sql = f"""
        SELECT
            m.field_id,
            strftime(CAST(b.local_time AS TIMESTAMP), '%Y-%m-%dT%H:%M') AS time,
            strftime(CAST(b.date AS DATE), '%Y-%m-%d') AS date,
            CAST(EXTRACT(HOUR FROM CAST(b.local_time AS TIMESTAMP)) AS INTEGER) AS hour,
            ROUND(CAST(b.temperature AS DOUBLE), 2) AS temp_c,
            ROUND(CAST(b.relative_humidity AS DOUBLE), 1) AS rh_pct,
            ROUND(CAST(b.dew_point_temperature AS DOUBLE), 2) AS dew_point_c,
            ROUND({precip_expr}, 2) AS precip_mm,
            ROUND(CAST(b.wind_speed AS DOUBLE), 1) AS wind_kmh
        FROM field_grid_map AS m
        JOIN read_parquet($1) AS b
          ON m.grid_id = b.grid_id
        {imerg_join}
        {where_sql}
        ORDER BY m.field_id, time
    """
    return con.execute(sql, params).df()


def get_weather_for_field(
    field_lat: float,
    field_lon: float,
    weather_df: pd.DataFrame,
    forecast_only: bool = False,
    start_date: str | date | datetime | None = None,
    end_date: str | date | datetime | None = None,
) -> pd.DataFrame:
    """
    Zwraca tabelę dzienną lub godzinową pogody z najbliższego punktu siatki
    dla wybranego pola. Obsługuje filtrowanie zakresu dat oraz forecast_only=True.
    """
    if weather_df.empty:
        return weather_df.copy()

    pts = weather_df[["lat", "lon"]].drop_duplicates().reset_index(drop=True)
    cos_lat = float(np.cos(np.radians(field_lat)))
    dist2 = (pts["lat"] - field_lat) ** 2 + ((pts["lon"] - field_lon) * cos_lat) ** 2
    nearest = pts.iloc[dist2.idxmin()]

    sub = weather_df[(weather_df["lat"] == nearest["lat"]) & (weather_df["lon"] == nearest["lon"])]
    if forecast_only:
        sub = sub[sub["date"] >= date.today().isoformat()]
    if start_date is not None:
        sub = sub[sub["date"] >= _parse_date(start_date).isoformat()]
    if end_date is not None:
        sub = sub[sub["date"] <= _parse_date(end_date).isoformat()]

    sort_cols = ["date", "hour"] if "hour" in sub.columns else ["date"]
    return sub.sort_values(sort_cols).reset_index(drop=True)


if __name__ == "__main__":
    df_poland = fetch_poland_weather_daily()

    # Przykład: prognoza 7-dniowa dla pola w rejonie kw/fields.geojson (Lubuskie)
    df_field = get_weather_for_field(52.635, 15.765, df_poland, forecast_only=True)
    print(df_field[["date", "temp_mean_c", "precip_sum_mm", "precip_72h_mm", "sm_l1", "sm_l2"]])
