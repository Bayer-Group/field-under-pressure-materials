from __future__ import annotations

from pathlib import Path
import sys

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from kw.disease_risk import build_fields_protection_tables, export_protection_to_sql
from kw.meteo import fetch_poland_weather_daily, fetch_weather_hourly, get_weather_for_field
from kw.soil import (
    evaluate_field_calendar,
    load_field_profile,
    prepare_all_soil_profiles,
    prepare_zone_soil_profiles,
)

DATA_DIR = ROOT / "data"
SOIL_DIR = DATA_DIR / "soil"
SOIL_RAW_DIR = SOIL_DIR / "raw"
ZONES_GEOJSON = DATA_DIR / "zones/field_zones.geojson"
METEO_DIR = DATA_DIR / "meteo"
PROTECTION_DIR = DATA_DIR / "protection"


def _resolve_soil_raw_dir() -> Path:
    has_new_raw = SOIL_RAW_DIR.exists() and (
        any(SOIL_RAW_DIR.rglob("*.parquet")) or any(SOIL_RAW_DIR.glob("*.zip"))
    )
    if has_new_raw:
        return SOIL_RAW_DIR
    legacy_dir = ROOT / "soil_data"
    if legacy_dir.exists():
        print(
            "[INFO] Brak plików w data/soil/raw/ — tymczasowo wczytuję surowe dane gleby z soil_data/ "
            "(docelowo przenieś do data/soil/raw/)."
        )
        return legacy_dir
    return SOIL_RAW_DIR


def _offline_hourly_fallback(lat: float, lon: float, start_date: str, end_date: str) -> pd.DataFrame:
    hours = pd.date_range(f"{start_date} 00:00", f"{end_date} 23:00", freq="h")
    hr = hours.hour
    temp_c = 13.5 + 5.5 * np.sin(2.0 * np.pi * (hr - 9) / 24.0)
    rh_pct = np.where((hr >= 21) | (hr <= 6), 93.0, 66.0)
    dew_point_c = temp_c - np.where((hr >= 21) | (hr <= 6), 1.0, 6.2)
    precip_mm = np.where((hours.day % 3 == 0) & (hr >= 2) & (hr <= 5), 1.1, 0.0)
    wind_kmh = np.where((hr >= 9) & (hr <= 17), 10.5, 6.0)
    return pd.DataFrame(
        {
            "lat": round(lat, 4),
            "lon": round(lon, 4),
            "time": hours.strftime("%Y-%m-%dT%H:%M"),
            "date": hours.strftime("%Y-%m-%d"),
            "hour": hr.astype(int),
            "temp_c": np.round(temp_c, 2),
            "rh_pct": rh_pct,
            "dew_point_c": np.round(dew_point_c, 2),
            "precip_mm": precip_mm,
            "wind_kmh": wind_kmh,
        }
    )


def main() -> None:
    # --------------------------------------------------------------------------
    # KROK 1: Profile glebowe pól + rozpoznane uprawy -> data/soil/
    # --------------------------------------------------------------------------
    raw_soil_dir = _resolve_soil_raw_dir()
    soil_parquet = SOIL_DIR / "fields_soil_profiles.parquet"
    if soil_parquet.exists():
        fields_df = pd.read_parquet(soil_parquet)
        print(f"[ETAP 1] Wczytano {len(fields_df)} profili pól z {soil_parquet.relative_to(ROOT)}.")
    else:
        fields_df = prepare_all_soil_profiles(
            geojson_path=ROOT / "bk/fields_crops.geojson",
            soil_dir=raw_soil_dir,
            output_parquet=soil_parquet,
            output_json=SOIL_DIR / "fields_soil_profiles.json",
        )

    preview_cols = [
        "field_id",
        "area_ha",
        "crop",
        "soilTexture",
        "ph",
        "band_ph",
        "awc_mm_per_m",
        "water_retention",
        "soil_variability",
    ]
    print("\n=== PODGLĄD PROFILI GLEBOWYCH (pierwsze 5 pól) ===")
    print(fields_df[[c for c in preview_cols if c in fields_df.columns]].head().to_string(index=False))
    print("Rozkład upraw:", fields_df["crop"].value_counts(dropna=False).to_dict())

    if ZONES_GEOJSON.exists():
        zones_df = prepare_zone_soil_profiles(
            zones_input=ZONES_GEOJSON,
            soil_dir=raw_soil_dir,
            crops_geojson=ROOT / "bk/fields_crops.geojson",
            output_parquet=SOIL_DIR / "field_zone_soil_profiles.parquet",
            output_json=SOIL_DIR / "field_zone_soil_profiles.json",
        )
        print(f"[ETAP 1 - STREFY] Przeliczono {len(zones_df)} profili stref.")
    else:
        print("\n[INFO] Brak pliku data/zones/field_zones.geojson (Moduł 1) — pomijam krok strefowy.")

    # --------------------------------------------------------------------------
    # KROK 2: Pogoda dzienna z data/meteo/ + kalendarz 7-dniowy
    # --------------------------------------------------------------------------
    cached_daily = sorted(METEO_DIR.glob("open_meteo_poland_daily_*.parquet"))
    if cached_daily:
        latest_daily = cached_daily[-1]
        w_daily = pd.read_parquet(latest_daily)
        print(f"\n[ETAP 2] Wczytano dzienną pogodę z {latest_daily.relative_to(ROOT)} ({len(w_daily)} wierszy).")
    else:
        legacy_daily = sorted((ROOT / "weather_cache").glob("open_meteo_poland_daily_*.parquet"))
        if legacy_daily:
            latest_daily = legacy_daily[-1]
            w_daily = pd.read_parquet(latest_daily)
            print(
                f"\n[INFO] Tymczasowo wczytano pogodę z {latest_daily.relative_to(ROOT)} "
                "(docelowo przenieś pliki *.parquet do data/meteo/)."
            )
        else:
            w_daily = fetch_poland_weather_daily(output_dir=METEO_DIR)

    known_crops = fields_df[fields_df["crop"].notna() & (fields_df["crop"] != "inne")]
    sample_row = (known_crops if not known_crops.empty else fields_df).iloc[0]
    soil_profile = load_field_profile(str(sample_row["field_id"]), soil_parquet)

    field_weather_7d = get_weather_for_field(
        soil_profile.centroid_lat, soil_profile.centroid_lon, w_daily, forecast_only=True
    )
    if field_weather_7d.empty:
        field_weather_7d = get_weather_for_field(
            soil_profile.centroid_lat, soil_profile.centroid_lon, w_daily, forecast_only=False
        ).tail(7)

    calendar = evaluate_field_calendar(
        soil=soil_profile,
        field_weather_df=field_weather_7d.head(7),
        fertilizer="saletra_amonowa",
        crop=soil_profile.crop or "pszenica",
    )
    cal_rows = [
        {
            "date": d["date"],
            "status": d["status"],
            "water_stress_level": d["water_stress_level"],
            "water_status": d["water_status"],
            "temp_mean_c": d["weather"]["temp_mean_c"],
            "precip_24h_mm": d["weather"]["precip_24h_mm"],
            "main_reason": d["fertilization_reasons"][0] if d["fertilization_reasons"] else "",
        }
        for d in calendar
    ]
    print(f"\n=== KALENDARZ 7 DNI DLA {soil_profile.field_id} ({soil_profile.crop or 'pszenica'}) ===")
    print(pd.DataFrame(cal_rows).to_string(index=False))

    # --------------------------------------------------------------------------
    # KROK 3: Moduł 2 — Presja chorób (48h) i okna oprysku -> data/protection/
    # --------------------------------------------------------------------------
    sample_fields = (known_crops if not known_crops.empty else fields_df).head(5).copy()
    center_lat = round(float(sample_fields["centroid_lat"].mean()), 4)
    center_lon = round(float(sample_fields["centroid_lon"].mean()), 4)

    used_fallback = False
    try:
        w_hourly = fetch_weather_hourly(
            coords=[(center_lat, center_lon)],
            start_date="2025-04-12",
            end_date="2025-04-20",
            output_dir=METEO_DIR,
        )
    except requests.RequestException as exc:
        used_fallback = True
        print(
            f"\n[OFFLINE FALLBACK] Brak połączenia z Open-Meteo ({exc.__class__.__name__}) — "
            f"używam syntetycznej pogody godzinowej dla ({center_lat}, {center_lon})."
        )
        w_hourly = _offline_hourly_fallback(center_lat, center_lon, "2025-04-12", "2025-04-20")

    disease_df, spray_df = build_fields_protection_tables(
        sample_fields,
        w_hourly,
        start_date="2025-04-14",
        end_date="2025-04-20",
        output_dir=PROTECTION_DIR if not used_fallback else None,
    )
    print("\n=== MODUŁ 2: PRESJA CHORÓB (pierwsze 10 wierszy) ===")
    print(disease_df[["field_id", "day", "disease", "risk", "wet_hours"]].head(10).to_string(index=False))
    print("\n=== MODUŁ 2: OKNA OPRYSKU (pierwsze 10 wierszy) ===")
    print(
        spray_df[["field_id", "day", "spray_status", "best_window", "good_hours_count"]]
        .head(10)
        .to_string(index=False)
    )

    if not used_fallback:
        export_protection_to_sql(disease_df, spray_df, PROTECTION_DIR / "field_disease_dump.sql")
    else:
        print(
            "\n[INFO] Pominięto zapis w data/protection/ w trybie offline fallback — "
            "uruchom z dostępem do sieci lub przenieś cache godzinowy do data/meteo/, aby zapisać Parquet/JSON i zrzut SQL."
        )


if __name__ == "__main__":
    main()
