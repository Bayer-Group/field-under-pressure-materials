import json
from pathlib import Path
from typing import Optional
import pandas as pd

DATA_DIR = Path(__file__).parent / "data"
FARM_PROFILE_PATH = DATA_DIR / "moje_gospodarstwo.json"

SOWING_ALIASES = {"ZASIEJ", "SIEJ", "ZASADŹ"}
FALLOW_LABEL = "Brak uprawy / Pod zasiew"

KNOWN_CROPS = [
    "Pszenica ozima",
    "Pszenica jara",
    "Jęczmień",
    "Jęczmień jary",
    "Żyto",
    "Owies",
    "Kukurydza",
    "Rzepak ozimy",
    "Ziemniaki",
    "Buraki cukrowe",
    "Rośliny strączkowe",
    "Użytki zielone",
    FALLOW_LABEL,
]

ECO_FERTILIZER_KEYWORDS = (
    "eko",
    "wapno",
    "dolomit",
    "obornik",
    "kompost",
    "biohumus",
    "patentkali",
    "siarczan potasu",
    "mączka",
    "fosforyt",
    "biolog",
)


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
    df = pd.read_parquet(DATA_DIR / "fields_static_33uxr.parquet").copy()
    if "field_uid" not in df.columns:
        df["field_uid"] = [f"P-{i+1:03d}" for i in range(len(df))]
    return df


def load_weather_timeseries() -> pd.DataFrame:
    w_path = DATA_DIR / "weather_timeseries_33uxr.parquet"
    f_path = DATA_DIR / "fields_static_33uxr.parquet"
    df = pd.read_parquet(w_path)
    df["timestamp"] = pd.to_datetime(df["timestamp"])

    # Automatyczne odświeżenie pogody LIVE z Open-Meteo, jeśli dane nie obejmują bieżącej godziny
    now_pl = pd.Timestamp.now(tz="Europe/Warsaw").tz_localize(None)
    if df.empty or df["timestamp"].max() < now_pl + pd.Timedelta(hours=12) or df["timestamp"].min() > now_pl:
        try:
            import json
            import ssl
            import urllib.request
            import numpy as np

            fields_df = pd.read_parquet(f_path)
            c_lat, c_lon = float(fields_df["lat"].mean()), float(fields_df["lon"].mean())
            url = (
                f"https://api.open-meteo.com/v1/forecast?latitude={c_lat:.4f}&longitude={c_lon:.4f}"
                "&past_days=5&forecast_days=5"
                "&hourly=temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m,soil_moisture_0_to_7cm"
                "&wind_speed_unit=ms&timezone=Europe%2FWarsaw"
            )
            ctx = ssl._create_unverified_context()
            with urllib.request.urlopen(url, context=ctx, timeout=12) as resp:
                h = json.loads(resp.read().decode("utf-8"))["hourly"]
            w_base = pd.DataFrame({
                "timestamp": pd.to_datetime(h["time"]),
                "temp_c": pd.Series(h["temperature_2m"]).ffill().bfill().round(1).astype("float32"),
                "humidity_pct": pd.Series(h["relative_humidity_2m"]).ffill().bfill().round(1).astype("float32"),
                "wind_ms": pd.Series(h["wind_speed_10m"]).ffill().bfill().round(1).astype("float32"),
                "precip_1h": pd.Series(h["precipitation"]).fillna(0.0).clip(lower=0.0),
                "soil_moisture": pd.Series(h["soil_moisture_0_to_7cm"]).ffill().bfill().fillna(0.25).round(3).astype("float32"),
            })
            w_base["precip_24h_mm"] = w_base["precip_1h"].rolling(24, min_periods=1).sum().round(1).astype("float32")
            w_base = w_base[w_base["timestamp"] >= w_base["timestamp"].min() + pd.Timedelta(hours=24)].copy()
            out = []
            for gid in fields_df["grid_id"].unique():
                sub = w_base[["timestamp", "temp_c", "humidity_pct", "wind_ms", "precip_24h_mm", "soil_moisture"]].copy()
                sub.insert(0, "grid_id", np.int32(gid))
                out.append(sub)
            df = pd.concat(out, ignore_index=True)
            df.to_parquet(w_path, index=False)
        except Exception:
            pass
    return df


def ensure_base_reference_data() -> dict[str, bool]:
    """Gwarantuje obecność plików bazowych (gminy Polski + reguły) nawet bez folderu data_local."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    gminy_path = DATA_DIR / "gminy_polska.parquet"
    rules_path = DATA_DIR / "reguly_agronomiczne.csv"

    if not gminy_path.exists():
        try:
            import json
            import ssl
            import urllib.request
            from shapely.geometry import shape

            ctx = ssl._create_unverified_context()
            url = "https://github.com/wmgeolab/geoBoundaries/raw/main/releaseData/gbOpen/POL/ADM2/geoBoundaries-POL-ADM2_simplified.geojson"
            with urllib.request.urlopen(url, context=ctx, timeout=25) as resp:
                geo = json.loads(resp.read().decode("utf-8"))
            rows = []
            for feat in geo.get("features", []):
                props = feat.get("properties", {})
                geom = shape(feat["geometry"])
                minx, miny, maxx, maxy = geom.bounds
                c = geom.centroid
                name = str(props.get("shapeName", "Gmina")).strip()
                rows.append({
                    "wojewodztwo": "Polska",
                    "powiat": name,
                    "gmina": name,
                    "typ_gminy": "Jednostka ADM2",
                    "min_lon": round(minx, 5),
                    "min_lat": round(miny, 5),
                    "max_lon": round(maxx, 5),
                    "max_lat": round(maxy, 5),
                    "center_lat": round(c.y, 5),
                    "center_lon": round(c.x, 5),
                })
            if rows:
                pd.DataFrame(rows).to_parquet(gminy_path, index=False)
        except Exception:
            pass

    if not rules_path.exists():
        default_rules = pd.DataFrame([
            {
                "rule_id": "R-001", "uprawa": "WSZYSTKIE", "zagrozenie": "Zbyt silny wiatr do oprysku",
                "temp_min_c": "", "temp_max_c": "", "wilgotnosc_min_pct": "", "opad_24h_min_mm": "",
                "wiatr_max_ms": 4.0, "ndvi_prog": "", "decyzja": "CZEKAJ", "poziom_ryzyka": "WYSOKI",
                "komunikat": "Wstrzymaj oprysk: wiatr przekracza 4 m/s", "ph_min": "", "ph_max": "",
                "soc_max_g_kg": "", "zalecany_nawoz": "", "nawozy_eko": "TAK",
            },
            {
                "rule_id": "R-002", "uprawa": "WSZYSTKIE", "zagrozenie": "Zakwaszenie gleby (pH < 5.6)",
                "temp_min_c": 2.0, "temp_max_c": 26.0, "wilgotnosc_min_pct": "", "opad_24h_min_mm": "",
                "wiatr_max_ms": 4.5, "ndvi_prog": "", "decyzja": "NAWOŹ", "poziom_ryzyka": "ŚREDNI",
                "komunikat": "Zalecane wapnowanie EKO w celu podniesienia pH gleby", "ph_min": "", "ph_max": 5.6,
                "soc_max_g_kg": "", "zalecany_nawoz": "Wapno kredowe / Dolomit (EKO)", "nawozy_eko": "TAK (wykaz IUNG)",
            },
            {
                "rule_id": "R-003", "uprawa": "Pszenica ozima", "zagrozenie": "Presja chorób grzybowych / dokarmianie",
                "temp_min_c": 8.0, "temp_max_c": 24.0, "wilgotnosc_min_pct": 55.0, "opad_24h_min_mm": 0.0,
                "wiatr_max_ms": 4.0, "ndvi_prog": 0.45, "decyzja": "PRYSKAJ TERAZ", "poziom_ryzyka": "ŚREDNI",
                "komunikat": "Optymalne okno pogodowe na zabieg biologiczny EKO", "ph_min": "", "ph_max": "",
                "soc_max_g_kg": "", "zalecany_nawoz": "Preparat biologiczny / Siarka (EKO)", "nawozy_eko": "TAK (rozp. UE 2018/848)",
            },
        ])
        default_rules.to_csv(rules_path, sep=";", index=False, encoding="utf-8-sig")

    return {
        "gminy_ok": gminy_path.exists(),
        "rules_ok": rules_path.exists(),
        "has_data_local": (Path(__file__).resolve().parents[1] / "data_local").exists(),
    }


def load_admin_hierarchy() -> dict[str, dict[str, list[dict]]]:
    ensure_base_reference_data()
    base_dir = Path(__file__).parent
    candidates = [
        DATA_DIR / "gminy_polska.parquet",
        base_dir / "data_app" / "gminy_polska.parquet",
        base_dir / "data" / "gminy_polska.parquet",
    ]
    gminy_path = next((p for p in candidates if p.exists()), None)
    hierarchy: dict[str, dict[str, list[dict]]] = {}
    if gminy_path is not None:
        gdf = pd.read_parquet(gminy_path)
        for r in gdf.itertuples(index=False):
            woj = str(getattr(r, "wojewodztwo", "")).strip()
            powiat = str(getattr(r, "powiat", "")).strip()
            gmina = str(getattr(r, "gmina", "")).strip()
            if not (woj and powiat and gmina):
                continue
            bbox = [
                float(getattr(r, "min_lon", 19.0)),
                float(getattr(r, "min_lat", 50.0)),
                float(getattr(r, "max_lon", 20.0)),
                float(getattr(r, "max_lat", 51.0)),
            ]
            hierarchy.setdefault(woj, {}).setdefault(powiat, []).append(
                {"gmina": gmina, "bbox": bbox}
            )
    return hierarchy


def load_farm_profile() -> dict:
    if FARM_PROFILE_PATH.exists():
        try:
            with open(FARM_PROFILE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                data.setdefault("farm_name", "Moje Gospodarstwo")
                data.setdefault("wojewodztwo", "Małopolskie")
                data.setdefault("powiat", "proszowicki")
                data.setdefault("gmina", "Wszystkie gminy (33UXR)")
                data.setdefault("only_my_farm", False)
                data.setdefault("eco_mode", False)
                data.setdefault("fields", {})
                return data
        except Exception:
            pass
    return {
        "farm_name": "Moje Gospodarstwo",
        "wojewodztwo": "Małopolskie",
        "powiat": "proszowicki",
        "gmina": "Wszystkie gminy (33UXR)",
        "only_my_farm": False,
        "eco_mode": False,
        "fields": {},
    }


def save_farm_profile(profile: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(FARM_PROFILE_PATH, "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)


def apply_farm_profile(
    fields_df: pd.DataFrame,
    farm_profile: dict,
    crop_dict_df: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    df = fields_df.copy()
    selected_map: dict = farm_profile.get("fields", {})
    global_eco = bool(farm_profile.get("eco_mode", False))

    df["is_my_field"] = df["field_uid"].isin(selected_map.keys())
    df["is_fallow"] = False
    df["is_eco_field"] = global_eco

    if selected_map:
        new_crops = []
        new_ndvi = []
        is_fallow_list = []
        is_eco_list = []
        for r in df.itertuples(index=False):
            cfg = selected_map.get(r.field_uid)
            if cfg is not None:
                declared = str(cfg.get("crop_name", r.crop_name)).strip()
                is_eco_list.append(bool(cfg.get("is_eco", global_eco)))
                if declared == FALLOW_LABEL:
                    rec_crop, _ = recommend_crop_by_soil(
                        r.soil_ph, r.soil_soc, r.soil_texture, crop_dict_df=crop_dict_df
                    )
                    new_crops.append(f"Pod zasiew ({rec_crop})")
                    new_ndvi.append(min(float(r.ndvi), 0.18))
                    is_fallow_list.append(True)
                else:
                    new_crops.append(declared)
                    new_ndvi.append(float(r.ndvi))
                    is_fallow_list.append(False)
            else:
                new_crops.append(r.crop_name)
                new_ndvi.append(float(r.ndvi))
                is_fallow_list.append(False)
                is_eco_list.append(global_eco)

        df["crop_name"] = new_crops
        df["ndvi"] = pd.Series(new_ndvi, index=df.index, dtype="float32")
        df["is_fallow"] = is_fallow_list
        df["is_eco_field"] = is_eco_list

    if farm_profile.get("only_my_farm", False) and df["is_my_field"].any():
        df = df[df["is_my_field"]].copy().reset_index(drop=True)

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
                "nawozy_eko",
                "dawka_nawozu_kg_ha",
                "preparat_eko",
                "metoda_oprysku",
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
    if "nawozy_eko" not in df.columns:
        df["nawozy_eko"] = ""
    if "preparat_eko" not in df.columns:
        df["preparat_eko"] = ""
    if "metoda_oprysku" not in df.columns:
        df["metoda_oprysku"] = ""

    df["decyzja_norm"] = df["decyzja"].apply(normalize_decision)

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
        "dawka_nawozu_kg_ha",
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

    if pd.isna(soil_ph) or pd.isna(soil_soc):
        return "Jęczmień jary", "Uniwersalny wybór przy niepełnych danych glebowych"

    if soil_ph >= 6.6 and soil_soc >= 19.0 and ("clay" in texture or "silt" in texture or texture == "loam"):
        return (
            "Burak cukrowy",
            f"Bardzo żyzne stanowisko (pH {soil_ph:.1f}, próchnica {soil_soc:.1f} g/kg, {soil_texture}) — wysoki potencjał okopowych",
        )

    if soil_ph >= 6.3 and soil_soc >= 16.5 and "sand" not in texture:
        return (
            "Rzepak ozimy",
            f"Wysokie pH ({soil_ph:.1f}) i zasobność organiczna ({soil_soc:.1f} g/kg) na zwięzłej glebie ({soil_texture})",
        )

    if soil_ph >= 6.0 and soil_soc >= 14.0 and texture in {"loam", "silt loam", "clay loam", "silty clay loam", "silt"}:
        return (
            "Pszenica ozima",
            f"Uregulowany odczyn (pH {soil_ph:.1f}) i dobra zawartość próchnicy ({soil_soc:.1f} g/kg) sprzyjają pszenicy",
        )

    if soil_ph >= 6.0 and soil_soc < 14.0 and "sand" not in texture:
        return (
            "Soja / Bobik (strączkowe)",
            f"Dobre pH ({soil_ph:.1f}) przy niższym SOC ({soil_soc:.1f} g/kg) — rośliny motylkowe wzbogacą glebę w azot",
        )

    if 5.6 <= soil_ph < 6.4 and ("sandy loam" in texture or "loam" in texture) and soil_soc >= 12.5:
        return (
            "Kukurydza na ziarno",
            f"Dobra tolerancja dla odczynu pH {soil_ph:.1f} i przepuszczalnej struktury ({soil_texture})",
        )

    if 5.2 <= soil_ph < 5.9 and ("sandy" in texture or "loam" in texture) and soil_soc >= 12.5:
        return (
            "Ziemniak jadalny",
            f"Lekko kwaśny odczyn (pH {soil_ph:.1f}) i lżejsze uziarnienie ({soil_texture}) ułatwiają zbiór i ograniczają parcha",
        )

    if 5.8 <= soil_ph < 6.3 and soil_soc >= 11.5:
        return (
            "Jęczmień jary",
            f"Stabilne plonowanie przy pH {soil_ph:.1f} i zasobności SOC {soil_soc:.1f} g/kg ({soil_texture})",
        )

    if 5.4 <= soil_ph < 6.0 and soil_soc < 12.5:
        return (
            "Pszenżyto ozime",
            f"Mniejsze wymagania glebowe niż pszenica — optymalne dla pH {soil_ph:.1f} i SOC {soil_soc:.1f} g/kg",
        )

    if 5.0 <= soil_ph < 5.6 and soil_soc >= 11.0:
        return (
            "Owies zwyczajny",
            f"Wysoka odporność na zakwaszenie (pH {soil_ph:.1f}) i efektywne wykorzystanie wilgoci ({soil_texture})",
        )

    if soil_ph < 5.3 and ("sand" in texture or soil_soc < 11.0):
        return (
            "Łubin wąskolistny (EKO)",
            f"Stanowisko kwaśne i lekkie (pH {soil_ph:.1f}, {soil_texture}) — łubin poprawi strukturę i zwiąże azot",
        )

    return (
        "Żyto ozime",
        f"Niezawodny gatunek na słabsze i kwaśniejsze stanowiska (pH {soil_ph:.1f}, {soil_texture})",
    )


def recommend_fertilization(
    soil_ph: float,
    soil_soc: float,
    soil_texture: str,
    crop_name: str,
    area_ha: float,
    temp_c: Optional[float] = None,
    precip_24h_mm: Optional[float] = None,
    rule_fertilizer: str = "",
    rule_eco_fertilizer: str = "",
    rule_dose_kg_ha: Optional[float] = None,
    eco_mode: bool = False,
) -> dict:
    area = float(area_ha) if pd.notna(area_ha) and float(area_ha) > 0 else 1.5
    ph = float(soil_ph) if pd.notna(soil_ph) else 6.2
    soc = float(soil_soc) if pd.notna(soil_soc) else 15.0
    crop_l = str(crop_name).strip().lower()

    weather_blocked = (
        (pd.notna(precip_24h_mm) and float(precip_24h_mm) >= 5.0)
        or (pd.notna(temp_c) and (float(temp_c) < 2.0 or float(temp_c) > 32.0))
    )

    clean_rule_fert = str(rule_fertilizer).strip() if pd.notna(rule_fertilizer) else ""
    clean_rule_eco = str(rule_eco_fertilizer).strip() if pd.notna(rule_eco_fertilizer) else ""

    if ph < 5.5:
        eco_name = clean_rule_eco or "Wapno kredowe / dolomitowe (EKO)"
        conv_name = clean_rule_fert or "Wapno węglanowe granulowane"
        dose_ha = float(rule_dose_kg_ha) if (rule_dose_kg_ha is not None and pd.notna(rule_dose_kg_ha) and rule_dose_kg_ha > 0) else 650.0
        reason = f"Niskie pH ({ph:.1f} < 5,5) — zalecane wapnowanie korygujące odczyn gleby."
    elif soc < 13.5:
        eco_name = clean_rule_eco or "Obornik granulowany / kompost (EKO)"
        conv_name = clean_rule_fert or "Obornik / nawóz organiczno-mineralny"
        dose_ha = float(rule_dose_kg_ha) if (rule_dose_kg_ha is not None and pd.notna(rule_dose_kg_ha) and rule_dose_kg_ha > 0) else 400.0
        reason = f"Niska zawartość próchnicy/SOC ({soc:.1f} g/kg < 13,5) — uzupełnienie materii organicznej."
    elif "rzepak" in crop_l:
        eco_name = clean_rule_eco or "Patentkali + siarka i bor (EKO)"
        conv_name = clean_rule_fert or "NPK pod rzepak + siarczan magnezu"
        dose_ha = float(rule_dose_kg_ha) if (rule_dose_kg_ha is not None and pd.notna(rule_dose_kg_ha) and rule_dose_kg_ha > 0) else 220.0
        reason = f"Zapotrzebowanie rzepaku na siarkę, potas i magnez przy pH {ph:.1f}."
    elif "kukurydz" in crop_l:
        eco_name = clean_rule_eco or "Obornik / biohumus pod kukurydzę (EKO)"
        conv_name = clean_rule_fert or "NPK startowy pod kukurydzę"
        dose_ha = float(rule_dose_kg_ha) if (rule_dose_kg_ha is not None and pd.notna(rule_dose_kg_ha) and rule_dose_kg_ha > 0) else 250.0
        reason = f"Zapotrzebowanie kukurydzy przy SOC {soc:.1f} g/kg i pH {ph:.1f}."
    else:
        eco_name = clean_rule_eco or "Biohumus / mączka mineralna (EKO)"
        conv_name = clean_rule_fert or "Nawóz wieloskładnikowy pogłówny"
        dose_ha = float(rule_dose_kg_ha) if (rule_dose_kg_ha is not None and pd.notna(rule_dose_kg_ha) and rule_dose_kg_ha > 0) else 180.0
        reason = f"Utrzymanie zasobności stanowiska ({soil_texture}, pH {ph:.1f}, SOC {soc:.1f} g/kg)."

    if eco_mode:
        chosen_fert = eco_name
        eco_status = "TAK (EKO)"
    else:
        chosen_fert = conv_name if conv_name else eco_name
        check_str = f"{chosen_fert} {clean_rule_eco}".lower()
        is_eco_compatible = any(k in check_str for k in ECO_FERTILIZER_KEYWORDS)
        eco_status = "TAK (EKO)" if is_eco_compatible else "NIE"

    if weather_blocked:
        reason = f"Warunki pogodowe ograniczają aplikację (sprawdź opady/temperaturę) — {reason}"

    total_kg = round(dose_ha * area, 1)
    return {
        "zalecany_nawoz": chosen_fert,
        "nawozy_eko": eco_status,
        "dawka_nawozu_kg_ha": round(dose_ha, 1),
        "ilosc_nawozu_kg": total_kg,
        "uzasadnienie_nawozenia": reason,
    }


def _rule_matches_row(rule, row) -> bool:
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

    if pd.notna(rule.ndvi_prog) and pd.notna(row.ndvi):
        if rule.decyzja_norm in {"ZASIEJ", "ZBIERAJ"}:
            if row.ndvi > rule.ndvi_prog:
                return False
        else:
            if row.ndvi < rule.ndvi_prog:
                return False

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
    eco_mode: bool = False,
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
    eco_statuses = []
    dose_kg_ha_list = []
    total_kg_list = []
    fert_reasons = []
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
        rule_fert = ""
        rule_eco = ""
        rule_dose = None
        is_fallow = bool(getattr(row, "is_fallow", False))

        if pd.notna(row.precip_24h_mm) and row.precip_24h_mm >= 5.0:
            decision = "CZEKAJ"
            message = f"CZEKAJ: Wysoki opad 24h ({row.precip_24h_mm:.1f} mm) — ryzyko zmycia środka / grząska gleba"
            hazard = "Nadmierny opad 24h"
            rule_id = "BLK-RAIN"
            risk_level = "KRYTYCZNY"
        elif pd.notna(row.wind_ms) and row.wind_ms > 4.0 and not is_fallow:
            decision = "CZEKAJ"
            message = f"CZEKAJ: Zbyt silny wiatr > 4 m/s ({row.wind_ms:.1f} m/s)"
            hazard = "Znoszenie cieczy roboczej"
            rule_id = "BLK-WIND"
            risk_level = "WYSOKI"
        elif is_fallow:
            if pd.notna(row.soil_ph) and row.soil_ph < 5.5:
                decision = "NAWOŹ"
                rule_fert = "Wapno węglanowe granulowane"
                rule_eco = "Wapno kredowe / dolomitowe (EKO)"
                hazard = "Zbyt kwaśny odczyn gleby przed siewem"
                rule_id = "FALLOW-LIME"
                risk_level = "WYSOKI"
                message = f"NAWOŹ przed siewem: pH {row.soil_ph:.1f} wymaga wapnowania | Docelowo: {rec_crop}"
            else:
                decision = "ZASIEJ"
                hazard = "Pole nieobsiane — gotowe do siewu"
                rule_id = "FALLOW-SOW"
                risk_level = "OPTYMALNY"
                message = f"ZASIEJ: Pole pod zasiew — zalecany gatunek: {rec_crop} ({soil_reason})"
        else:
            crop_rules = rules_df[
                (rules_df["uprawa"].str.strip().str.lower() == str(row.crop_name).strip().lower())
                | (rules_df["uprawa"].str.strip().str.upper() == "WSZYSTKIE")
            ]

            blocking_rules = crop_rules[crop_rules["decyzja_norm"] == "CZEKAJ"]
            action_rules = crop_rules[crop_rules["decyzja_norm"] != "CZEKAJ"]

            matched_rule = None
            for r in blocking_rules.itertuples(index=False):
                if _rule_matches_row(r, row):
                    matched_rule = r
                    break

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
                raw_eco = getattr(matched_rule, "nawozy_eko", "")
                raw_dose = getattr(matched_rule, "dawka_nawozu_kg_ha", None)
                if pd.notna(raw_fert) and str(raw_fert).strip():
                    rule_fert = str(raw_fert).strip()
                if pd.notna(raw_eco) and str(raw_eco).strip():
                    rule_eco = str(raw_eco).strip()
                if pd.notna(raw_dose):
                    rule_dose = float(raw_dose)

        row_eco_mode = bool(getattr(row, "is_eco_field", eco_mode)) or bool(eco_mode)
        fert_info = recommend_fertilization(
            soil_ph=row.soil_ph,
            soil_soc=row.soil_soc,
            soil_texture=row.soil_texture,
            crop_name=row.crop_name,
            area_ha=getattr(row, "area_ha", 1.5),
            temp_c=row.temp_c,
            precip_24h_mm=row.precip_24h_mm,
            rule_fertilizer=rule_fert,
            rule_eco_fertilizer=rule_eco,
            rule_dose_kg_ha=rule_dose,
            eco_mode=row_eco_mode,
        )

        if decision == "ZASIEJ":
            message = f"{message} | Rekomendowany siew: {rec_crop}"
        elif decision == "NAWOŹ":
            message = (
                f"{message} | Nawóz: {fert_info['zalecany_nawoz']} "
                f"({fert_info['dawka_nawozu_kg_ha']:.0f} kg/ha, {fert_info['ilosc_nawozu_kg']:.0f} kg łącznie) "
                f"[{fert_info['nawozy_eko']}]"
            )

        decisions.append(decision)
        messages.append(message)
        hazards.append(hazard)
        rule_ids.append(rule_id)
        risk_levels.append(risk_level)
        fertilizers.append(fert_info["zalecany_nawoz"])
        eco_statuses.append(fert_info["nawozy_eko"])
        dose_kg_ha_list.append(fert_info["dawka_nawozu_kg_ha"])
        total_kg_list.append(fert_info["ilosc_nawozu_kg"])
        fert_reasons.append(fert_info["uzasadnienie_nawozenia"])

    merged["decyzja"] = decisions
    merged["komunikat"] = messages
    merged["zagrozenie"] = hazards
    merged["rule_id"] = rule_ids
    merged["poziom_ryzyka"] = risk_levels
    merged["zalecany_nawoz"] = fertilizers
    merged["nawozy_eko"] = eco_statuses
    merged["dawka_nawozu_kg_ha"] = dose_kg_ha_list
    merged["ilosc_nawozu_kg"] = total_kg_list
    merged["uzasadnienie_nawozenia"] = fert_reasons
    merged["rekomendowana_uprawa"] = recommended_crops
    merged["uzasadnienie_glebowe"] = soil_reasons
    return merged
