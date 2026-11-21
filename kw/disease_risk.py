from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
import re
import sys

import numpy as np
import pandas as pd

if __package__ in (None, ""):
    _repo_root = str(Path(__file__).resolve().parent.parent)
    if _repo_root not in sys.path:
        sys.path.insert(0, _repo_root)

from kw.meteo import get_weather_for_field


@dataclass(frozen=True)
class DiseaseRule:
    code: str
    name_pl: str
    temp_min_c: float
    temp_max_c: float
    medium_hours_48h: int
    high_hours_48h: int
    source: str
    notes: str = ""


# Reguły opracowane na bazie arkusza metodyki/ryzyka_zebrane.xlsx (IOR-PIB / GIORiN).
# Progi godzin zwilżenia (48h) mają charakter demonstracyjny.
DISEASE_RULES: dict[str, list[DiseaseRule]] = {
    "pszenica": [
        DiseaseRule(
            code="septorioza_paskowana_lisci",
            name_pl="Septorioza paskowana liści pszenicy",
            temp_min_c=4.0,
            temp_max_c=18.0,
            medium_hours_48h=6,
            high_hours_48h=12,
            source="ryzyka_zebrane.xlsx (pszenica)",
            notes="Wymaga opadów deszczu i wysokiej wilgotności / zwilżenia liści (4–18°C).",
        ),
        DiseaseRule(
            code="rdza_brunatna",
            name_pl="Rdza brunatna pszenicy",
            temp_min_c=15.0,
            temp_max_c=18.0,
            medium_hours_48h=5,
            high_hours_48h=10,
            source="ryzyka_zebrane.xlsx (pszenica)",
            notes="Sprzyja okresowy dobowy wzrost wilgotności przy 15–18°C.",
        ),
        DiseaseRule(
            code="fuzarioza_klosow",
            name_pl="Fuzarioza kłosów",
            temp_min_c=15.0,
            temp_max_c=25.0,
            medium_hours_48h=6,
            high_hours_48h=12,
            source="ryzyka_zebrane.xlsx (pszenica)",
            notes="Ciepło i wysoka wilgotność powietrza w okresie kwitnienia (15–25°C).",
        ),
        DiseaseRule(
            code="maczniak_prawdziwy",
            name_pl="Mączniak prawdziwy zbóż i traw",
            temp_min_c=5.0,
            temp_max_c=30.0,
            medium_hours_48h=8,
            high_hours_48h=18,
            source="ryzyka_zebrane.xlsx (pszenica)",
            notes="Szeroki zakres temperatur (5–30°C) i podwyższona wilgotność w łanie.",
        ),
        DiseaseRule(
            code="brunatna_plamistosc_lisci",
            name_pl="Brunatna plamistość liści (DTR)",
            temp_min_c=18.0,
            temp_max_c=28.0,
            medium_hours_48h=6,
            high_hours_48h=12,
            source="ryzyka_zebrane.xlsx (pszenica)",
            notes="Wymaga długotrwałego zwilżenia liści przy 18–28°C.",
        ),
    ],
    "kukurydza": [
        DiseaseRule(
            code="zgorzel_siewek",
            name_pl="Zgorzel siewek kukurydzy",
            temp_min_c=5.0,
            temp_max_c=15.0,
            medium_hours_48h=6,
            high_hours_48h=14,
            source="ryzyka_zebrane.xlsx (kukurydza)",
            notes="Chłodna i wilgotna pogoda podczas kiełkowania oraz wschodów.",
        ),
        DiseaseRule(
            code="drobna_plamistosc_lisci",
            name_pl="Drobna plamistość liści kukurydzy",
            temp_min_c=10.0,
            temp_max_c=20.0,
            medium_hours_48h=6,
            high_hours_48h=12,
            source="ryzyka_zebrane.xlsx (kukurydza)",
            notes="Chłód, deszcz lub długo utrzymująca się rosa.",
        ),
        DiseaseRule(
            code="fuzarioza_lodyg_i_kolb",
            name_pl="Fuzarioza łodyg i kolb",
            temp_min_c=18.0,
            temp_max_c=30.0,
            medium_hours_48h=6,
            high_hours_48h=12,
            source="ryzyka_zebrane.xlsx (kukurydza)",
            notes="Ciepłe i wilgotne okresy zwiększające ryzyko mikotoksyn.",
        ),
        DiseaseRule(
            code="rdza_kukurydzy",
            name_pl="Rdza kukurydzy",
            temp_min_c=16.0,
            temp_max_c=26.0,
            medium_hours_48h=6,
            high_hours_48h=12,
            source="ryzyka_zebrane.xlsx (kukurydza)",
            notes="Ciepłe i wilgotne warunki w trakcie wegetacji.",
        ),
    ],
    "rzepak": [
        DiseaseRule(
            code="zgnilizna_twardzikowa",
            name_pl="Zgnilizna twardzikowa rzepaku",
            temp_min_c=15.0,
            temp_max_c=25.0,
            medium_hours_48h=6,
            high_hours_48h=12,
            source="Metodyka integrowanej ochrony rzepaku (IOR-PIB)",
            notes="Wysoka wilgotność i zwilżenie płatków w fazie kwitnienia (15–25°C).",
        ),
        DiseaseRule(
            code="sucha_zgnilizna_kapustnych",
            name_pl="Sucha zgnilizna kapustnych",
            temp_min_c=8.0,
            temp_max_c=20.0,
            medium_hours_48h=6,
            high_hours_48h=12,
            source="Metodyka integrowanej ochrony rzepaku (IOR-PIB)",
            notes="Opady i długie zwilżenie liści sprzyjają infekcjom askosporowym.",
        ),
        DiseaseRule(
            code="czern_krzyzowych",
            name_pl="Czerń krzyżowych",
            temp_min_c=15.0,
            temp_max_c=26.0,
            medium_hours_48h=6,
            high_hours_48h=12,
            source="Metodyka integrowanej ochrony rzepaku (IOR-PIB)",
            notes="Ciepła i wilgotna pogoda od kwitnienia do dojrzewania łuszczyn.",
        ),
    ],
    "burak_cukrowy": [
        DiseaseRule(
            code="chwoscik_buraka",
            name_pl="Chwościk buraka",
            temp_min_c=15.0,
            temp_max_c=30.0,
            medium_hours_48h=6,
            high_hours_48h=12,
            source="ryzyka_zebrane.xlsx (burak cukrowy)",
            notes="Wysoka wilgotność po opadach przy ciepłej pogodzie (noc > 15°C).",
        ),
        DiseaseRule(
            code="brunatna_plamistosc_lisci",
            name_pl="Brunatna plamistość liści buraka",
            temp_min_c=17.0,
            temp_max_c=20.0,
            medium_hours_48h=5,
            high_hours_48h=10,
            source="ryzyka_zebrane.xlsx (burak cukrowy)",
            notes="Wysoka wilgotność w przedziale 17–20°C.",
        ),
        DiseaseRule(
            code="maczniak_rzekomy",
            name_pl="Mączniak rzekomy buraka",
            temp_min_c=4.0,
            temp_max_c=15.0,
            medium_hours_48h=6,
            high_hours_48h=12,
            source="ryzyka_zebrane.xlsx (burak cukrowy)",
            notes="Chłodne i pochmurne okresy o wysokiej wilgotności (<= 15°C).",
        ),
    ],
    "ziemniak": [
        DiseaseRule(
            code="zaraza_ziemniaka",
            name_pl="Zaraza ziemniaka",
            temp_min_c=10.0,
            temp_max_c=20.0,
            medium_hours_48h=5,
            high_hours_48h=10,
            source="ryzyka_zebrane.xlsx (ziemniak)",
            notes="Chłodna i wilgotna pogoda sprzyjająca zarodnikowaniu.",
        ),
    ],
    "slonecznik": [
        DiseaseRule(
            code="zgnilizna_twardzikowa",
            name_pl="Zgnilizna twardzikowa słonecznika",
            temp_min_c=15.0,
            temp_max_c=25.0,
            medium_hours_48h=6,
            high_hours_48h=12,
            source="ryzyka_zebrane.xlsx (słonecznik)",
            notes="Wysoka wilgotność przy 15–25°C (optimum 19–20°C).",
        ),
        DiseaseRule(
            code="szara_plesn",
            name_pl="Szara pleśń słonecznika",
            temp_min_c=10.0,
            temp_max_c=18.0,
            medium_hours_48h=6,
            high_hours_48h=12,
            source="ryzyka_zebrane.xlsx (słonecznik)",
            notes="Chłodna i wilgotna pogoda (10–18°C).",
        ),
        DiseaseRule(
            code="septorioza_slonecznika",
            name_pl="Septorioza słonecznika",
            temp_min_c=10.0,
            temp_max_c=18.0,
            medium_hours_48h=6,
            high_hours_48h=12,
            source="ryzyka_zebrane.xlsx (słonecznik)",
            notes="Wysoka wilgotność w przedziale 10–18°C.",
        ),
    ],
}

DISEASE_OUTPUT_COLS = ["field_id", "day", "disease", "risk", "wet_hours", "reason"]
SPRAY_OUTPUT_COLS = [
    "field_id",
    "day",
    "spray_status",
    "best_window",
    "all_windows",
    "good_hours_count",
    "conditional_hours_count",
    "reason",
]

DEFAULT_PROTECTION_DIR = Path("data/protection")
DEFAULT_DISEASE_SQL = DEFAULT_PROTECTION_DIR / "field_disease_dump.sql"


def _filter_by_date(df: pd.DataFrame, col: str, start_date, end_date) -> pd.DataFrame:
    out = df
    if start_date is not None:
        sd = start_date.isoformat() if isinstance(start_date, (date, datetime)) else str(start_date)[:10]
        out = out[out[col] >= sd]
    if end_date is not None:
        ed = end_date.isoformat() if isinstance(end_date, (date, datetime)) else str(end_date)[:10]
        out = out[out[col] <= ed]
    return out


def compute_leaf_wetness(hourly_df: pd.DataFrame) -> pd.DataFrame:
    """
    Krok 2: Przybliżenie godziny zwilżenia liści.
    Godzina jest uznana za mokrą, gdy:
      - wilgotność względna > 90%, LUB
      - różnica (temp_c - dew_point_c) < 2.0°C (blisko punktu rosy), LUB
      - występuje opad (precip_mm > 0).
    """
    out = hourly_df.copy()
    if "time" not in out.columns:
        out["time"] = out["date"].astype(str) + "T" + out["hour"].astype(int).map(lambda h: f"{h:02d}:00")
    if "date" not in out.columns:
        out["date"] = pd.to_datetime(out["time"]).dt.strftime("%Y-%m-%d")
    if "hour" not in out.columns:
        out["hour"] = pd.to_datetime(out["time"]).dt.hour.astype(int)

    out["dew_spread_c"] = pd.to_numeric(out["temp_c"], errors="coerce") - pd.to_numeric(
        out["dew_point_c"], errors="coerce"
    )
    out["is_wet_hour"] = (
        (pd.to_numeric(out["rh_pct"], errors="coerce") > 90.0)
        | (out["dew_spread_c"] < 2.0)
        | (pd.to_numeric(out["precip_mm"], errors="coerce") > 0.0)
    )
    return out.sort_values("time").reset_index(drop=True)


def evaluate_disease_pressure(
    hourly_df: pd.DataFrame,
    crop: str = "pszenica",
    field_id: str = "field_0",
    start_date: str | date | None = None,
    end_date: str | date | None = None,
) -> pd.DataFrame:
    """
    Krok 3–4: Dla każdej głównej choroby uprawy liczy godziny mokre w jej zakresie
    temperatur w oknie kroczącym 48h i klasyfikuje ryzyko (NISKI / SREDNI / WYSOKI).
    Progi mają charakter demonstracyjny.
    """
    if hourly_df.empty:
        return pd.DataFrame(columns=DISEASE_OUTPUT_COLS)

    crop_key = str(crop).strip().lower()
    rules = DISEASE_RULES.get(crop_key, DISEASE_RULES["pszenica"])

    df = compute_leaf_wetness(hourly_df)
    temp = pd.to_numeric(df["temp_c"], errors="coerce")

    rows: list[dict] = []
    for rule in rules:
        fav = (df["is_wet_hour"] & (temp >= rule.temp_min_c) & (temp <= rule.temp_max_c)).astype(int)
        wet_48h = fav.rolling(48, min_periods=1).sum().astype(int)
        daily_max = (
            pd.DataFrame({"day": df["date"], "wet_48h": wet_48h})
            .groupby("day", as_index=False)["wet_48h"]
            .max()
            .sort_values("day")
        )
        daily_max = _filter_by_date(daily_max, "day", start_date, end_date)

        for _, r in daily_max.iterrows():
            wh = int(r["wet_48h"])
            if wh >= rule.high_hours_48h:
                risk = "WYSOKI"
            elif wh >= rule.medium_hours_48h:
                risk = "SREDNI"
            else:
                risk = "NISKI"

            reason = (
                f"{wh} godz. zwilżenia liści w oknie 48h przy temp. "
                f"{rule.temp_min_c:.0f}–{rule.temp_max_c:.0f}°C "
                f"(progi demonstracyjne: średnie >= {rule.medium_hours_48h}h, wysokie >= {rule.high_hours_48h}h; "
                f"źródło: {rule.source})."
            )
            rows.append(
                {
                    "field_id": str(field_id),
                    "day": str(r["day"]),
                    "disease": rule.name_pl,
                    "risk": risk,
                    "wet_hours": wh,
                    "reason": reason,
                }
            )

    return pd.DataFrame(rows, columns=DISEASE_OUTPUT_COLS)


def _format_hour_intervals(hours: list[int]) -> list[str]:
    if not hours:
        return []
    hrs = sorted(set(hours))
    blocks: list[tuple[int, int]] = []
    start = prev = hrs[0]
    for h in hrs[1:]:
        if h == prev + 1:
            prev = h
        else:
            blocks.append((start, prev))
            start = prev = h
    blocks.append((start, prev))
    return [f"{s:02d}:00–{e + 1:02d}:00" for s, e in blocks]


def evaluate_spray_windows(
    hourly_df: pd.DataFrame,
    field_id: str = "field_0",
    start_date: str | date | None = None,
    end_date: str | date | None = None,
    dry_after_hours: int = 3,
    max_wind_good_kmh: float = 14.4,   # 4 m/s — standardowy limit prawny PIORiN/GIORiN
    max_wind_toz_kmh: float = 18.0,    # 5 m/s — dopuszczalne przy technikach TOZ
    min_temp_c: float = 8.0,
    max_temp_c: float = 22.0,
    min_rh_pct: float = 50.0,
    max_rh_pct: float = 90.0,
) -> pd.DataFrame:
    """
    Krok 5: Wyznacza dzienne okna godzinowe bezpiecznego oprysku:
      - brak opadu w godzinie oprysku oraz przez kolejne dry_after_hours (domyślnie 3h),
      - brak zwilżenia liści i wilgotność względna 50–90%,
      - temperatura w bezpiecznym zakresie aplikacji (8–22°C),
      - wiatr <= 14.4 km/h (DOBRE) lub <= 18.0 km/h przy rozpylaczach TOZ (WARUNKOWE).
    """
    if hourly_df.empty:
        return pd.DataFrame(columns=SPRAY_OUTPUT_COLS)

    df = compute_leaf_wetness(hourly_df)
    precip = pd.to_numeric(df["precip_mm"], errors="coerce").fillna(0.0)
    temp = pd.to_numeric(df["temp_c"], errors="coerce")
    rh = pd.to_numeric(df["rh_pct"], errors="coerce")
    wind = pd.to_numeric(df["wind_kmh"], errors="coerce")

    # Suma opadów w oknie [h .. h + dry_after_hours]
    future_rain = precip.iloc[::-1].rolling(dry_after_hours + 1, min_periods=1).sum().iloc[::-1]
    dry_ok = future_rain <= 0.0
    temp_ok = (temp >= min_temp_c) & (temp <= max_temp_c)
    rh_ok = (rh >= min_rh_pct) & (rh <= max_rh_pct) & (~df["is_wet_hour"])

    df["dry_ok"] = dry_ok
    df["temp_ok"] = temp_ok
    df["rh_ok"] = rh_ok
    df["wind_good_ok"] = wind <= max_wind_good_kmh
    df["wind_toz_ok"] = wind <= max_wind_toz_kmh

    df["hour_status"] = np.select(
        [
            dry_ok & temp_ok & rh_ok & df["wind_good_ok"],
            dry_ok & temp_ok & rh_ok & df["wind_toz_ok"],
        ],
        ["DOBRE", "WARUNKOWE"],
        default="NIEODPOWIEDNIE",
    )

    df_filtered = _filter_by_date(df, "date", start_date, end_date)
    rows: list[dict] = []

    for day_str, grp in df_filtered.groupby("date", sort=True):
        good_hrs = grp.loc[grp["hour_status"] == "DOBRE", "hour"].tolist()
        cond_hrs = grp.loc[grp["hour_status"] == "WARUNKOWE", "hour"].tolist()
        usable_hrs = sorted(set(good_hrs + cond_hrs))

        intervals = _format_hour_intervals(usable_hrs)
        if intervals:
            best_window = max(
                intervals,
                key=lambda iv: int(iv.split("–")[1][:2]) - int(iv.split("–")[0][:2]),
            )
            all_windows = ", ".join(intervals)
        else:
            best_window = ""
            all_windows = ""

        if good_hrs:
            spray_status = "DOBRE"
            reason = (
                f"Dostępne bezpieczne okno oprysku ({all_windows}) — brak opadów przez min. "
                f"{dry_after_hours}h po zabiegu, wiatr <= {max_wind_good_kmh:.1f} km/h, temp. {min_temp_c:.0f}–{max_temp_c:.0f}°C."
            )
        elif cond_hrs:
            spray_status = "WARUNKOWE"
            reason = (
                f"Okno warunkowe ({all_windows}) — wiatr w przedziale "
                f"{max_wind_good_kmh:.1f}–{max_wind_toz_kmh:.1f} km/h (wymagane rozpylacze antyznoszeniowe TOZ)."
            )
        else:
            spray_status = "BRAK_OKNA"
            blockers = []
            if not bool(grp["dry_ok"].any()):
                blockers.append(f"opady lub brak {dry_after_hours}h przerwy po zabiegu")
            if not bool(grp["wind_toz_ok"].any()):
                blockers.append(f"zbyt silny wiatr (> {max_wind_toz_kmh:.0f} km/h)")
            if not bool(grp["temp_ok"].any()):
                blockers.append(f"temperatura poza zakresem {min_temp_c:.0f}–{max_temp_c:.0f}°C")
            if not bool(grp["rh_ok"].any()):
                blockers.append("zbyt wysoka wilgotność / mokry liść lub za sucho (< 50%)")
            reason = "Brak bezpiecznego okna oprysku: " + (", ".join(blockers) or "niespełnione kryteria meteo") + "."

        rows.append(
            {
                "field_id": str(field_id),
                "day": str(day_str),
                "spray_status": spray_status,
                "best_window": best_window,
                "all_windows": all_windows,
                "good_hours_count": len(good_hrs),
                "conditional_hours_count": len(cond_hrs),
                "reason": reason,
            }
        )

    return pd.DataFrame(rows, columns=SPRAY_OUTPUT_COLS)


def build_fields_protection_tables(
    fields_df: pd.DataFrame,
    hourly_weather_df: pd.DataFrame,
    default_crop: str = "pszenica",
    start_date: str | date | None = None,
    end_date: str | date | None = None,
    output_dir: str | Path | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Krok 6: Oblicza tabele public.field_disease oraz field_spray_windows dla wszystkich pól
    (obsługuje pogodę godzinową per field_id z Bayera lub siatkę lat/lon z Open-Meteo).
    Gdy podano output_dir (np. data/protection), zapisuje też pliki Parquet i JSON.
    """
    has_field_id = "field_id" in hourly_weather_df.columns
    disease_frames: list[pd.DataFrame] = []
    spray_frames: list[pd.DataFrame] = []

    for _, f_row in fields_df.iterrows():
        fid = str(f_row["field_id"])
        crop_val = f_row["crop"] if "crop" in f_row.index and pd.notna(f_row["crop"]) else default_crop

        if has_field_id:
            h_sub = hourly_weather_df[hourly_weather_df["field_id"].astype(str) == fid]
        else:
            h_sub = get_weather_for_field(
                float(f_row["centroid_lat"]),
                float(f_row["centroid_lon"]),
                hourly_weather_df,
            )

        if h_sub.empty:
            continue

        disease_frames.append(
            evaluate_disease_pressure(h_sub, crop=str(crop_val), field_id=fid, start_date=start_date, end_date=end_date)
        )
        spray_frames.append(
            evaluate_spray_windows(h_sub, field_id=fid, start_date=start_date, end_date=end_date)
        )

    disease_df = (
        pd.concat(disease_frames, ignore_index=True)
        if disease_frames
        else pd.DataFrame(columns=DISEASE_OUTPUT_COLS)
    )
    spray_df = (
        pd.concat(spray_frames, ignore_index=True)
        if spray_frames
        else pd.DataFrame(columns=SPRAY_OUTPUT_COLS)
    )

    if output_dir is not None:
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        disease_df.to_parquet(out_dir / "field_disease.parquet", index=False)
        disease_df.to_json(out_dir / "field_disease.json", orient="records", force_ascii=False)
        spray_df.to_parquet(out_dir / "field_spray_windows.parquet", index=False)
        spray_df.to_json(out_dir / "field_spray_windows.json", orient="records", force_ascii=False)

    return disease_df, spray_df


def export_protection_to_sql(
    disease_df: pd.DataFrame,
    spray_df: pd.DataFrame | None = None,
    sql_path: str | Path = DEFAULT_DISEASE_SQL,
) -> Path:
    """
    Generuje zrzut SQL dla bazy PostgreSQL/PostGIS zgodny ze schematem:
      public.field_disease (field_id, day, disease, risk, wet_hours, reason)
    oraz opcjonalnie public.field_spray_windows.
    """
    def _esc(val: object) -> str:
        if val is None or (isinstance(val, float) and np.isnan(val)) or pd.isna(val):
            return "NULL"
        return "'" + str(val).replace("'", "''") + "'"

    lines = [
        "CREATE TABLE IF NOT EXISTS public.field_disease (",
        "    field_id TEXT NOT NULL,",
        "    day DATE NOT NULL,",
        "    disease TEXT NOT NULL,",
        "    risk TEXT NOT NULL,",
        "    wet_hours INTEGER NOT NULL,",
        "    reason TEXT NOT NULL,",
        "    PRIMARY KEY (field_id, day, disease)",
        ");",
        "",
    ]

    for _, r in disease_df.iterrows():
        lines.append(
            "INSERT INTO public.field_disease (field_id, day, disease, risk, wet_hours, reason) "
            f"VALUES ({_esc(r['field_id'])}, {_esc(r['day'])}, {_esc(r['disease'])}, "
            f"{_esc(r['risk'])}, {int(r['wet_hours'])}, {_esc(r['reason'])}) "
            "ON CONFLICT (field_id, day, disease) DO UPDATE SET "
            "risk = EXCLUDED.risk, wet_hours = EXCLUDED.wet_hours, reason = EXCLUDED.reason;"
        )

    if spray_df is not None and not spray_df.empty:
        lines.extend(
            [
                "",
                "CREATE TABLE IF NOT EXISTS public.field_spray_windows (",
                "    field_id TEXT NOT NULL,",
                "    day DATE NOT NULL,",
                "    spray_status TEXT NOT NULL,",
                "    best_window TEXT NOT NULL,",
                "    all_windows TEXT NOT NULL,",
                "    good_hours_count INTEGER NOT NULL,",
                "    conditional_hours_count INTEGER NOT NULL,",
                "    reason TEXT NOT NULL,",
                "    PRIMARY KEY (field_id, day)",
                ");",
                "",
            ]
        )
        for _, r in spray_df.iterrows():
            lines.append(
                "INSERT INTO public.field_spray_windows "
                "(field_id, day, spray_status, best_window, all_windows, good_hours_count, conditional_hours_count, reason) "
                f"VALUES ({_esc(r['field_id'])}, {_esc(r['day'])}, {_esc(r['spray_status'])}, "
                f"{_esc(r['best_window'])}, {_esc(r['all_windows'])}, "
                f"{int(r['good_hours_count'])}, {int(r['conditional_hours_count'])}, {_esc(r['reason'])}) "
                "ON CONFLICT (field_id, day) DO UPDATE SET "
                "spray_status = EXCLUDED.spray_status, best_window = EXCLUDED.best_window, "
                "all_windows = EXCLUDED.all_windows, good_hours_count = EXCLUDED.good_hours_count, "
                "conditional_hours_count = EXCLUDED.conditional_hours_count, reason = EXCLUDED.reason;"
            )

    out_path = Path(sql_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[SQL] Zapisano zrzut ochrony roślin ({len(disease_df)} wpisów chorób) -> {out_path}")
    return out_path


if __name__ == "__main__":
    # Lekki offline'owy podgląd działania modułu (bez zapytań sieciowych i zapisu plików)
    hours = pd.date_range("2025-05-10 00:00", periods=72, freq="h")
    hr = hours.hour
    temp_c = 14.0 + 5.0 * np.sin(2.0 * np.pi * (hr - 9) / 24.0)
    rh_pct = np.where((hr >= 21) | (hr <= 6), 93.0, 68.0)
    dew_point_c = temp_c - np.where((hr >= 21) | (hr <= 6), 1.0, 6.0)
    precip_mm = np.where((hours >= "2025-05-11 03:00") & (hours <= "2025-05-11 06:00"), 1.2, 0.0)
    wind_kmh = np.where((hr >= 9) & (hr <= 17), 10.5, 6.5)

    demo_hourly = pd.DataFrame(
        {
            "time": hours.strftime("%Y-%m-%dT%H:%M"),
            "temp_c": np.round(temp_c, 1),
            "rh_pct": rh_pct,
            "dew_point_c": np.round(dew_point_c, 1),
            "precip_mm": precip_mm,
            "wind_kmh": wind_kmh,
        }
    )

    demo_disease = evaluate_disease_pressure(demo_hourly, crop="pszenica", field_id="field_demo")
    demo_spray = evaluate_spray_windows(demo_hourly, field_id="field_demo")

    print("=== DEMO MODUŁ 2: PRESJA CHORÓB (pszenica, 72h offline) ===")
    print(demo_disease[["day", "disease", "risk", "wet_hours"]].to_string(index=False))
    print("\n=== DEMO MODUŁ 2: OKNA OPRYSKU ===")
    print(demo_spray[["day", "spray_status", "best_window", "good_hours_count"]].to_string(index=False))
