from datetime import date
import os
from pathlib import Path
import time

import numpy as np
import pandas as pd
import requests


OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

# Zgodnie z koncepcją MVP: opady, temperatura oraz wilgotność gleby (bez ET0, wiatru i RH)
HOURLY_VARS = [
    "temperature_2m",
    "precipitation",
    "soil_moisture_0_to_1cm",
    "soil_moisture_1_to_3cm",
    "soil_moisture_3_to_9cm",
    "soil_moisture_9_to_27cm",
    "soil_moisture_27_to_81cm",
]

OUTPUT_COLS = [
    "lat",
    "lon",
    "date",
    "temp_mean_c",
    "temp_min_c",
    "temp_max_c",
    "precip_sum_mm",
    "precip_72h_mm",
    "sm_l1",
    "sm_l2",
    "sm_l3",
]


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


def fetch_batch_daily(
    coords: list[tuple[float, float]],
    past_days: int = 14,
    forecast_days: int = 7,
    max_retries: int = 6,
    session: requests.Session | None = None,
) -> pd.DataFrame:
    """
    Pobiera paczkę lokalizacji (do ~50 naraz) z Open-Meteo (hourly),
    agreguje ją do danych dziennych, wylicza precip_72h_mm oraz mapuje
    głębokości Open-Meteo na warstwy Bayer Poziom 1-3 (sm_l1, sm_l2, sm_l3).
    """
    if not coords:
        return pd.DataFrame(columns=OUTPUT_COLS)

    params = {
        "latitude": ",".join(str(lat) for lat, _ in coords),
        "longitude": ",".join(str(lon) for _, lon in coords),
        "hourly": ",".join(HOURLY_VARS),
        "past_days": past_days,
        "forecast_days": forecast_days,
        "timezone": "Europe/Warsaw",
    }
    http = session if session is not None else requests

    for attempt in range(max_retries):
        resp = http.get(OPEN_METEO_URL, params=params, timeout=60)
        if resp.status_code == 200:
            break
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
            # Okno minutowe Open-Meteo resetuje się po 60s -> pierwsza próba czeka >= 65s
            wait_s = 65 + 30 * attempt
            print(f"[RATE LIMIT 429] {reason or 'limit minutowy'} — czekam {wait_s}s przed ponowieniem...")
            time.sleep(wait_s)
        else:
            resp.raise_for_status()
    else:
        raise RuntimeError("Przekroczono liczbę prób pobrania danych z Open-Meteo (429).")

    payload = resp.json()
    # Dla 1 lokalizacji API zwraca dict, dla >1 zwraca listę dictów
    items = [payload] if isinstance(payload, dict) else payload

    daily_frames = []
    for (req_lat, req_lon), item in zip(coords, items):
        hourly = item.get("hourly")
        if not hourly or "time" not in hourly:
            continue

        df_h = pd.DataFrame(hourly)
        for col in HOURLY_VARS:
            if col not in df_h.columns:
                df_h[col] = np.nan
            df_h[col] = pd.to_numeric(df_h[col], errors="coerce")

        df_h["date"] = pd.to_datetime(df_h["time"]).dt.strftime("%Y-%m-%d")

        df_d = (
            df_h.groupby("date", as_index=False)
            .agg(
                temp_mean_c=("temperature_2m", "mean"),
                temp_min_c=("temperature_2m", "min"),
                temp_max_c=("temperature_2m", "max"),
                precip_sum_mm=("precipitation", lambda s: s.sum(min_count=1)),
                _sm_0_1=("soil_moisture_0_to_1cm", "mean"),
                _sm_1_3=("soil_moisture_1_to_3cm", "mean"),
                _sm_3_9=("soil_moisture_3_to_9cm", "mean"),
                _sm_9_27=("soil_moisture_9_to_27cm", "mean"),
                _sm_27_81=("soil_moisture_27_to_81cm", "mean"),
            )
            .sort_values("date")
            .reset_index(drop=True)
        )

        # Suma opadów w kolejnych 72h (t, t+1, t+2; dla ostatnich 2 dni z dostępnych dni prognozy)
        df_d["precip_72h_mm"] = (
            df_d["precip_sum_mm"].iloc[::-1].rolling(3, min_periods=1).sum().iloc[::-1]
        )

        # Mapowanie głębokości Open-Meteo (0-1, 1-3, 3-9, 9-27, 27-81 cm) na warstwy Bayer L1-L3:
        # - sm_l1 (0-7 cm): ważona po miąższości 0-1 (1), 1-3 (2), 3-9 (4 cm)
        # - sm_l2 (7-28 cm): ważona po miąższości 3-9 (2), 9-27 (18), 27-81 (1 cm)
        # - sm_l3 (28-81 cm): przybliżenie warstwy Bayer Poziom 3 (28-100 cm)
        df_d["sm_l1"] = _weighted_mean([df_d["_sm_0_1"], df_d["_sm_1_3"], df_d["_sm_3_9"]], [1.0, 2.0, 4.0])
        df_d["sm_l2"] = _weighted_mean([df_d["_sm_3_9"], df_d["_sm_9_27"], df_d["_sm_27_81"]], [2.0, 18.0, 1.0])
        df_d["sm_l3"] = df_d["_sm_27_81"]

        df_d.insert(0, "lon", req_lon)
        df_d.insert(0, "lat", req_lat)
        daily_frames.append(df_d[OUTPUT_COLS])

    if not daily_frames:
        return pd.DataFrame(columns=OUTPUT_COLS)

    out = pd.concat(daily_frames, ignore_index=True)
    num_cols = [c for c in OUTPUT_COLS if c not in ("lat", "lon", "date")]
    out[num_cols] = out[num_cols].round(3)
    return out


def fetch_poland_weather_daily(
    output_parquet: str | Path | None = None,
    output_dir: str | Path = "weather_cache",
    coords: list[tuple[float, float]] | None = None,
    past_days: int = 14,
    forecast_days: int = 7,
    batch_size: int = 50,
    pause_sec: float = 6.5,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """
    Pobiera dzienną pogodę z Open-Meteo dla Polski (domyślnie 14 dni wstecz + 7 dni prognozy)
    i zapisuje wynik do pojedynczego pliku Parquet z datą w nazwie (cache na dysku).
    """
    out_path = (
        Path(output_parquet)
        if output_parquet is not None
        else Path(output_dir) / f"open_meteo_poland_daily_{date.today().isoformat()}.parquet"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)

    expected_cols = set(OUTPUT_COLS)
    if out_path.exists() and not force_refresh:
        cached_df = pd.read_parquet(out_path)
        if not cached_df.empty and expected_cols.issubset(cached_df.columns):
            print(f"[CACHE] Wczytano dane pogodowe z {out_path} ({len(cached_df)} wierszy).")
            return cached_df[OUTPUT_COLS]

    grid_coords = coords if coords is not None else generate_poland_grid()
    n_days = max(1, past_days + forecast_days)
    total_batches = (len(grid_coords) + batch_size - 1) // batch_size
    print(f"[START] Pobieranie pogody dla {len(grid_coords)} punktów ({total_batches} paczek po <= {batch_size})...")

    all_batches = []
    with requests.Session() as session:
        for idx in range(0, len(grid_coords), batch_size):
            batch = grid_coords[idx : idx + batch_size]
            batch_no = idx // batch_size + 1
            print(f"  -> Paczka {batch_no}/{total_batches} ({len(batch)} pkt)...")
            df_batch = fetch_batch_daily(
                batch,
                past_days=past_days,
                forecast_days=forecast_days,
                session=session,
            )
            all_batches.append(df_batch)
            if batch_no < total_batches:
                # Waga zapytania Open-Meteo: nLocations * max(1, nDays / 14); celujemy <= 480/min (8/s)
                batch_weight = len(batch) * max(1.0, n_days / 14.0)
                time.sleep(max(pause_sec, batch_weight / 8.0))

    full_df = pd.concat(all_batches, ignore_index=True) if all_batches else pd.DataFrame(columns=OUTPUT_COLS)
    tmp_path = out_path.with_suffix(".tmp.parquet")
    full_df.to_parquet(tmp_path, index=False)
    os.replace(tmp_path, out_path)
    print(f"[GOTOWE] Zapisano {len(full_df)} wierszy dziennych do {out_path}.")
    return full_df


def get_weather_for_field(
    field_lat: float,
    field_lon: float,
    weather_df: pd.DataFrame,
    forecast_only: bool = False,
) -> pd.DataFrame:
    """
    Zwraca tabelę dzienną pogody z najbliższego punktu siatki dla wybranego pola.
    Gdy forecast_only=True, zwraca tylko dni od dzisiaj w przód (kalendarz 7-dniowy).
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

    return sub.sort_values("date").reset_index(drop=True)


if __name__ == "__main__":
    df_poland = fetch_poland_weather_daily()

    # Przykład: prognoza 7-dniowa dla pola w rejonie kw/fields.geojson (Lubuskie)
    df_field = get_weather_for_field(52.635, 15.765, df_poland, forecast_only=True)
    print(df_field[["date", "temp_mean_c", "precip_sum_mm", "precip_72h_mm", "sm_l1", "sm_l2", "sm_l3"]])
