from pathlib import Path
from typing import Optional
import pandas as pd

DATA_DIR = Path(__file__).parent / "data_app"

SOWING_ALIASES = {"ZASIEJ", "SIEJ", "ZASADŹ"}


def _to_float_series(series: pd.Series) -> pd.Series:
    return pd.to_numeric(
        series.astype(str).str.strip().str.replace(",", ".", regex=False),
        errors="coerce",
    )


def normalize_decision(value: str) -> str:
    clean = str(value).strip().upper()
    if clean in SOWING_ALIASES:
        return "ZASIEJ"
    return clean


def load_static_fields() -> pd.DataFrame:
    return pd.read_parquet(DATA_DIR / "fields_static_33uxr.parquet")


def load_weather_timeseries() -> pd.DataFrame:
    df = pd.read_parquet(DATA_DIR / "weather_timeseries_33uxr.parquet")
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df


def load_agronomic_rules() -> pd.DataFrame:
    path = DATA_DIR / "reguly_agronomiczne.csv"
    if not path.exists():
        return pd.DataFrame(
            columns=[
                "rule_id",
                "uprawa",
                "zagrozenie",
                "temp_min_c",
                "temp_max_c",
                "wilgotnosc_min_pct",
                "opad_24h_min_mm",
                "wiatr_max_ms",
                "ndvi_prog",
                "decyzja",
                "poziom_ryzyka",
                "komunikat",
                "ph_min",
                "ph_max",
                "soc_max_g_kg",
                "zalecany_nawoz",
                "decyzja_norm",
            ]
        )
    df = pd.read_csv(path, sep=None, engine="python", encoding="utf-8-sig")
    df.columns = [c.strip() for c in df.columns]

    if "rule_id" not in df.columns:
        df["rule_id"] = [f"R-{i+1:03d}" for i in range(len(df))]
    if "poziom_ryzyka" not in df.columns:
        df["poziom_ryzyka"] = "ŚREDNI"
    if "zalecany_nawoz" not in df.columns:
        df["zalecany_nawoz"] = ""

    # Ujednolicenie nazw decyzji (ZASIEJ / SIEJ / ZASADŹ -> ZASIEJ)
    df["decyzja_norm"] = df["decyzja"].apply(normalize_decision)

    # Konwersja kolumn liczbowych (odporna na przecinki z Google Sheets)
    numeric_cols = [
        "temp_min_c",
        "temp_max_c",
        "wilgotnosc_min_pct",
        "opad_24h_min_mm",
        "wiatr_max_ms",
        "ndvi_prog",
        "ph_min",
        "ph_max",
        "soc_max_g_kg",
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = _to_float_series(df[col])
        else:
            df[col] = float("nan")

    return df


def load_optional_crop_recommendations() -> Optional[pd.DataFrame]:
    path = DATA_DIR / "rekomendacje_upraw.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path, sep=None, engine="python", encoding="utf-8-sig")
    df.columns = [c.strip() for c in df.columns]
    for col in ["ph_min", "ph_max", "soc_min_g_kg"]:
        if col in df.columns:
            df[col] = _to_float_series(df[col])
    return df


def recommend_crop_by_soil(
    soil_ph: float,
    soil_soc: float,
    soil_texture: str,
    crop_dict_df: Optional[pd.DataFrame] = None,
) -> tuple[str, str]:
    texture = str(soil_texture).strip().lower()

    # 1. Jeśli Osoba 3 dostarczyła opcjonalny Plik D (rekomendacje_upraw.csv)
    if crop_dict_df is not None and not crop_dict_df.empty and pd.notna(soil_ph) and pd.notna(soil_soc):
        for r in crop_dict_df.itertuples(index=False):
            ph_ok = (pd.isna(r.ph_min) or soil_ph >= r.ph_min) and (pd.isna(r.ph_max) or soil_ph <= r.ph_max)
            soc_ok = pd.isna(r.soc_min_g_kg) or soil_soc >= r.soc_min_g_kg
            pref_tex = str(getattr(r, "preferowana_tekstura", "")).strip().lower()
            tex_ok = (not pref_tex) or (pref_tex in texture) or (texture in pref_tex)
            if ph_ok and soc_ok and tex_ok:
                reason = str(getattr(r, "uzasadnienie", f"Dopasowanie do pH {soil_ph:.1f}, SOC {soil_soc:.1f} g/kg"))
                return str(r.uprawa), reason

    # 2. Wbudowana logika agronomiczna oparta na SoilGrids v2
    if pd.isna(soil_ph) or pd.isna(soil_soc):
        return "Jęczmień jary", "Uniwersalny wybór przy niepełnych danych glebowych"

    if soil_ph >= 6.3 and soil_soc >= 16.0 and texture in {"loam", "silt loam", "clay loam", "silty clay loam"}:
        return "Rzepak ozimy", f"Wysokie pH ({soil_ph:.1f}), wysoki SOC ({soil_soc:.1f} g/kg) i zwięzła gleba ({soil_texture})"

    if soil_ph >= 6.0 and soil_soc >= 13.0 and "sand" not in texture:
        return "Pszenica ozima", f"Dobre pH ({soil_ph:.1f}) i zasobność w węgiel organiczny ({soil_soc:.1f} g/kg)"

    if 5.5 <= soil_ph < 6.2 and ("sandy" in texture or soil_soc >= 11.0):
        return "Kukurydza", f"Dobra tolerancja dla pH {soil_ph:.1f} i uziarnienia {soil_texture}"

    return "Jęczmień jary", f"Bezpieczny wybór dla stanowiska o pH {soil_ph:.1f} ({soil_texture})"


def _rule_matches_row(rule, row) -> bool:
    # Warunki pogodowe (puste progi w CSV nie blokują dopasowania)[cite: 6]
    if pd.notna(rule.temp_min_c) and pd.notna(row.temp_c) and row.temp_c < rule.temp_min_c:
        return False
    if pd.notna(rule.temp_max_c) and pd.notna(row.temp_c) and row.temp_c > rule.temp_max_c:
        return False
    if pd.notna(rule.wilgotnosc_min_pct) and pd.notna(row.humidity_pct) and row.humidity_pct < rule.wilgotnosc_min_pct:
        return False
    if pd.notna(rule.opad_24h_min_mm) and pd.notna(row.precip_24h_mm) and row.precip_24h_mm < rule.opad_24h_min_mm:
        return False
    if pd.notna(rule.wiatr_max_ms) and pd.notna(row.wind_ms) and row.wind_ms > rule.wiatr_max_ms:
        return False

    # Logika ndvi_prog wg v2.0: dla ZASIEJ i ZBIERAJ próg górny (<=), dla reszty próg dolny (>=)[cite: 6]
    if pd.notna(rule.ndvi_prog) and pd.notna(row.ndvi):
        if rule.decyzja_norm in {"ZASIEJ", "ZBIERAJ"}:
            if row.ndvi > rule.ndvi_prog:
                return False
        else:
            if row.ndvi < rule.ndvi_prog:
                return False

    # Opcjonalne warunki glebowe (ph_min, ph_max, soc_max_g_kg)[cite: 6]
    if pd.notna(rule.ph_min) and pd.notna(row.soil_ph) and row.soil_ph < rule.ph_min:
        return False
    if pd.notna(rule.ph_max) and pd.notna(row.soil_ph) and row.soil_ph > rule.ph_max:
        return False
    if pd.notna(rule.soc_max_g_kg) and pd.notna(row.soil_soc) and row.soil_soc > rule.soc_max_g_kg:
        return False

    return True


def evaluate_fields(
    fields_df: pd.DataFrame,
    weather_df: pd.DataFrame,
    rules_df: pd.DataFrame,
    selected_timestamp: pd.Timestamp,
    what_if: bool = False,
    override_temp_c: Optional[float] = None,
    override_wind_ms: Optional[float] = None,
    override_precip_24h_mm: Optional[float] = None,
    crop_dict_df: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    weather_slice = weather_df[weather_df["timestamp"] == pd.to_datetime(selected_timestamp)].copy()
    merged = fields_df.merge(weather_slice, on="grid_id", how="left")

    if what_if:
        if override_temp_c is not None:
            merged["temp_c"] = float(override_temp_c)
        if override_wind_ms is not None:
            merged["wind_ms"] = float(override_wind_ms)
        if override_precip_24h_mm is not None:
            merged["precip_24h_mm"] = float(override_precip_24h_mm)

    decisions = []
    messages = []
    hazards = []
    rule_ids = []
    risk_levels = []
    fertilizers = []
    recommended_crops = []
    soil_reasons = []

    for row in merged.itertuples(index=False):
        rec_crop, soil_reason = recommend_crop_by_soil(
            row.soil_ph, row.soil_soc, row.soil_texture, crop_dict_df=crop_dict_df
        )
        recommended_crops.append(rec_crop)
        soil_reasons.append(soil_reason)

        decision = "MONITORUJ"
        message = "MONITORUJ: Warunki stabilne, brak konieczności interwencji"
        hazard = "Brak krytycznego zagrożenia"
        rule_id = "DEFAULT-00"
        risk_level = "NISKI"
        fertilizer = "-"

        # 1. Nadrzędne blokady bezpieczeństwa (zgodnie ze scenariuszem demo i v2.0)[cite: 6]
        if pd.notna(row.precip_24h_mm) and row.precip_24h_mm >= 5.0:
            decision = "CZEKAJ"
            message = f"CZEKAJ: Wysoki opad 24h ({row.precip_24h_mm:.1f} mm) — ryzyko zmycia środka"
            hazard = "Nadmierny opad 24h"
            rule_id = "BLK-RAIN"
            risk_level = "KRYTYCZNY"
        elif pd.notna(row.wind_ms) and row.wind_ms > 4.0:
            decision = "CZEKAJ"
            message = f"CZEKAJ: Zbyt silny wiatr > 4 m/s ({row.wind_ms:.1f} m/s)"
            hazard = "Znoszenie cieczy roboczej"
            rule_id = "BLK-WIND"
            risk_level = "WYSOKI"
        else:
            crop_rules = rules_df[
                (rules_df["uprawa"].str.strip().str.lower() == str(row.crop_name).strip().lower())
                | (rules_df["uprawa"].str.strip().str.upper() == "WSZYSTKIE")
            ]

            # 2. Najpierw sprawdzamy reguły blokujące CZEKAJ z CSV (np. stres termiczny)[cite: 6]
            blocking_rules = crop_rules[crop_rules["decyzja_norm"] == "CZEKAJ"]
            action_rules = crop_rules[crop_rules["decyzja_norm"] != "CZEKAJ"]

            matched_rule = None
            for r in blocking_rules.itertuples(index=False):
                if _rule_matches_row(r, row):
                    matched_rule = r
                    break

            # 3. Jeśli brak blokady, dopasowujemy reguły zabiegowe (PRYSKAJ TERAZ, NAWOŹ, ZASIEJ, ZBIERAJ)[cite: 6]
            if matched_rule is None:
                for r in action_rules.itertuples(index=False):
                    if _rule_matches_row(r, row):
                        matched_rule = r
                        break

            if matched_rule is not None:
                decision = str(matched_rule.decyzja_norm)
                message = str(matched_rule.komunikat)
                hazard = str(matched_rule.zagrozenie)
                rule_id = str(matched_rule.rule_id)
                risk_level = str(matched_rule.poziom_ryzyka).strip().upper()
                raw_fert = getattr(matched_rule, "zalecany_nawoz", "")
                if pd.notna(raw_fert) and str(raw_fert).strip():
                    fertilizer = str(raw_fert).strip()

                if decision == "ZASIEJ":
                    message = f"{message} | Rekomendowany siew: {rec_crop}"
                elif decision == "NAWOŹ" and fertilizer != "-":
                    message = f"{message} | Zalecany nawóz: {fertilizer}"

        decisions.append(decision)
        messages.append(message)
        hazards.append(hazard)
        rule_ids.append(rule_id)
        risk_levels.append(risk_level)
        fertilizers.append(fertilizer)

    merged["decyzja"] = decisions
    merged["komunikat"] = messages
    merged["zagrozenie"] = hazards
    merged["rule_id"] = rule_ids
    merged["poziom_ryzyka"] = risk_levels
    merged["zalecany_nawoz"] = fertilizers
    merged["rekomendowana_uprawa"] = recommended_crops
    merged["uzasadnienie_glebowe"] = soil_reasons
    return merged


