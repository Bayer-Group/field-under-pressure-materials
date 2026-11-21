from dataclasses import dataclass, asdict
from datetime import date, datetime
from pathlib import Path
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
Crop = Literal["pszenica", "kukurydza", "rzepak"]

TEXTURE_BASE_SCORE = {
    "Silt Loam": 92, "Loam": 88, "Silty Clay Loam": 84, "Clay Loam": 78,
    "Silt": 78, "Sandy Clay Loam": 70, "Silty Clay": 62, "Sandy Loam": 56,
    "Clay": 54, "Sandy Clay": 52, "Loamy Sand": 38, "Sand": 20,
}


@dataclass
class FieldSoilProfile:
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
    bonitation_score: float
    klasa_bonitacyjna: str
    bonitation_source: str
    permeability: Literal["wysoka", "srednia", "niska"]
    water_retention: Literal["niska", "srednia", "wysoka"]
    wilting_point: float
    field_capacity: float


# ==============================================================================
# ETAP 1: AUTOMATYCZNE ROZPAKOWANIE WOJEWÓDZTW + PROFILOWANIE PÓL Z GEOJSON
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


def prepare_all_soil_profiles(
    geojson_path: str | Path,
    soil_dir: str | Path,
    output_parquet: str | Path = "fields_soil_profiles.parquet",
    output_json: str | Path = "fields_soil_profiles.json",
    id_col: str | None = "id",
    min_area_ha: float = 3.0,
) -> pd.DataFrame:
    """
    Łączy wszystkie pola >= 3 ha z GeoJSON ze wszystkimi województwami z soil_data/
    i zapisuje gotową tabelę profili glebowych do Parquet i JSON.
    """
    parquet_files = ensure_parquets_unpacked(soil_dir)

    gdf = gpd.read_file(geojson_path)
    gdf["geometry"] = force_2d(gdf.geometry)

    # Auto-detekcja CRS (metry PUWG 1992 vs stopnie WGS84)
    minx, miny, maxx, maxy = gdf.total_bounds
    if max(abs(minx), abs(maxx)) > 180 or max(abs(miny), abs(maxy)) > 90:
        gdf = gdf.set_crs("EPSG:2180", allow_override=True)
    elif gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")

    if id_col and id_col in gdf.columns:
        gdf["field_id"] = gdf[id_col].astype(str)
    else:
        gdf["field_id"] = [f"field_{i}" for i in range(len(gdf))]

    # Dokładna powierzchnia w ha i centroidy pól w układzie metrycznym EPSG:2180
    gdf_2180 = gdf.to_crs("EPSG:2180")
    gdf["area_ha"] = (gdf_2180.geometry.area / 10_000.0).round(2)
    centroids_4326 = gdf_2180.geometry.centroid.to_crs("EPSG:4326")
    gdf["centroid_lon"] = centroids_4326.x.round(6)
    gdf["centroid_lat"] = centroids_4326.y.round(6)

    gdf_valid = gdf[gdf["area_ha"] >= min_area_ha].to_crs("EPSG:4326").copy()
    if gdf_valid.empty:
        raise ValueError(f"Brak pól spełniających warunek powierzchni >= {min_area_ha} ha.")

    # Polyfill H3 poziom 10
    rows = []
    for row in gdf_valid.itertuples():
        geom = row.geometry
        try:
            cells = list(h3.geo_to_cells(geom.__geo_interface__, res=10))
        except Exception:
            cells = []
        if not cells:
            c = geom.centroid
            cells = [h3.latlng_to_cell(c.y, c.x, 10)]
        for cell in cells:
            rows.append({"field_id": row.field_id, "h3_index_10": str(cell).strip().lower()})

    mapping_df = pd.DataFrame(rows).drop_duplicates()

    # Jeden JOIN w DuckDB po WSZYSTKICH plikach wojewódzkich naraz (sand/silt/clay z 0-1 -> 0-100%)
    con = duckdb.connect()
    con.register("field_h3", mapping_df)

    agg_df = con.execute("""
        SELECT
            m.field_id,
            COUNT(s.h3_index_10) AS h3_cells_count,
            ROUND(CASE WHEN AVG(s.sand) <= 1.0 THEN AVG(s.sand) * 100.0 ELSE AVG(s.sand) END, 1) AS sand_pct,
            ROUND(CASE WHEN AVG(s.silt) <= 1.0 THEN AVG(s.silt) * 100.0 ELSE AVG(s.silt) END, 1) AS silt_pct,
            ROUND(CASE WHEN AVG(s.clay) <= 1.0 THEN AVG(s.clay) * 100.0 ELSE AVG(s.clay) END, 1) AS clay_pct,
            ROUND(AVG(s.ph), 2) AS ph,
            ROUND(AVG(s.om), 2) AS om,
            ROUND(AVG(s.cec), 2) AS cec,
            ROUND(AVG(s.bulk_density), 2) AS bulk_density,
            MODE(s.soilTexture) AS soilTexture
        FROM field_h3 m
        JOIN read_parquet($1) s
          ON m.h3_index_10 = LOWER(TRIM(CAST(s.h3_index_10 AS VARCHAR)))
        GROUP BY m.field_id
    """, [parquet_files]).df()

    out = gdf_valid[["field_id", "area_ha", "centroid_lat", "centroid_lon"]].merge(
        agg_df, on="field_id", how="inner"
    )
    if out.empty:
        raise LookupError("JOIN zwrócił 0 pól – sprawdź czy GeoJSON ma poprawne współrzędne.")

    # Bonitacja (skalibrowane proxy 0-100 -> polskie klasy I-VI)
    tex_score = out["soilTexture"].map(TEXTURE_BASE_SCORE).fillna(60.0)
    ph = out["ph"].fillna(5.8)
    ph_score = np.select(
        [
            (ph >= 6.0) & (ph <= 7.2),
            (ph >= 5.5) & (ph < 6.0),
            (ph > 7.2) & (ph <= 7.8),
            (ph >= 5.0) & (ph < 5.5),
        ],
        [100.0, 82.0, 82.0, 60.0],
        default=35.0,
    )
    om_score = np.clip((out["om"].fillna(2.5) / 5.0) * 100.0, 20.0, 100.0)
    cec_score = np.clip((out["cec"].fillna(12.0) / 22.0) * 100.0, 15.0, 100.0)
    bd_score = np.clip(100.0 - np.maximum(0.0, (out["bulk_density"].fillna(1.4) - 1.40) * 180.0), 20.0, 100.0)

    out["bonitation_score"] = np.clip(
        0.55 * tex_score + 0.20 * ph_score + 0.10 * om_score + 0.10 * cec_score + 0.05 * bd_score,
        5.0,
        100.0,
    ).round(1)

    bins = [0, 25, 38, 50, 62, 72, 82, 91, 101]
    labels = ["VI", "V", "IVb", "IVa", "IIIb", "IIIa", "II", "I"]
    out["klasa_bonitacyjna"] = pd.cut(
        out["bonitation_score"], bins=bins, labels=labels, right=False
    ).astype(str)
    out["bonitation_source"] = "Estymacja ISRIC SoilGrids (brak oficjalnej warstwy I-VI)"

    # Przepuszczalność, retencja i progi wilgotności (m3/m3)
    conds = [out["sand_pct"] >= 65, out["clay_pct"] >= 30]
    out["permeability"] = np.select(conds, ["wysoka", "niska"], default="srednia")
    out["water_retention"] = np.select(conds, ["niska", "wysoka"], default="srednia")
    out["wilting_point"] = np.select(conds, [0.08, 0.18], default=0.13)
    out["field_capacity"] = np.select(conds, [0.18, 0.36], default=0.28)

    # Zapis wyniku Etapu 1
    out.to_parquet(output_parquet, index=False)
    out.to_json(output_json, orient="records", force_ascii=False)
    print(f"[ETAP 1] Zapisano {len(out)} pól do {output_parquet} oraz {output_json}.")
    return out


# ==============================================================================
# ETAP 2: WCZYTANIE DANYCH Z ETAPU 1 I OCENA NAWOŻENIA / NAWADNIANIA
# ==============================================================================

def load_field_profile(
    field_id: str,
    profiles_parquet: str | Path = "fields_soil_profiles.parquet",
) -> FieldSoilProfile:
    """Wczytuje profil pojedynczego pola z pliku wygenerowanego w Etapie 1."""
    df = pd.read_parquet(profiles_parquet)
    row = df[df["field_id"] == str(field_id)]
    if row.empty:
        raise KeyError(f"Nie znaleziono pola '{field_id}' w {profiles_parquet}.")
    r = row.iloc[0]
    return FieldSoilProfile(
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
        bonitation_score=float(r["bonitation_score"]),
        klasa_bonitacyjna=str(r["klasa_bonitacyjna"]),
        bonitation_source=str(r["bonitation_source"]),
        permeability=r["permeability"],
        water_retention=r["water_retention"],
        wilting_point=float(r["wilting_point"]),
        field_capacity=float(r["field_capacity"]),
    )


def evaluate_fertilization_day(
    soil: FieldSoilProfile,
    fertilizer: Fertilizer,
    crop: Crop,
    precip_24h_mm: float,
    precip_72h_mm: float,
    temp_c: float,
    sm_l1: float,
    sm_l2: float,
    sm_l3: float,
    day_date: str | date | datetime | None = None,
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
        escalate("CZERWONY", f"Prognozowany silny opad ({precip_24h_mm:.1f} mm/24h > 10 mm) – ryzyko spływu i strat nawozu.")
    elif precip_72h_mm > 20.0:
        escalate("ZOLTY", f"Wysoka suma opadów w 72h ({precip_72h_mm:.1f} mm > 20 mm) – podwyższone ryzyko przemieszczania składników.")

    if l1_saturated and l2_saturated:
        escalate("CZERWONY", "Gleba nasycona wodą w warstwach 1–2 – ryzyko podmakania, koleinowania i strat azotu.")

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
        escalate("ZOLTY", "Ocena RSM 32 jest częściowa (brak danych o wietrze i wilgotności powietrza – sprawdź instrukcję aplikacji).")
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
        reasons.append(
            f"Korzystne warunki glebowe (tekstura: {soil.soilTexture}, pH: {soil.ph}) i umiarkowana wilgotność dla {crop}."
        )

    return {"fertilizer": fertilizer, "crop": crop, "status": status, "reasons": reasons}


def evaluate_irrigation_risk(
    soil: FieldSoilProfile,
    crop: Crop,
    sm_l1: float,
    sm_l2: float,
    sm_l3: float,
    precip_72h_mm: float,
    ndmi_forecast: float | None = None,
) -> dict:
    paw_l2 = float(np.clip((sm_l2 - soil.wilting_point) / (soil.field_capacity - soil.wilting_point), 0.0, 1.0))
    paw_l3 = float(np.clip((sm_l3 - soil.wilting_point) / (soil.field_capacity - soil.wilting_point), 0.0, 1.0))

    crop_threshold = 0.35 if crop in ("kukurydza", "rzepak") else 0.30
    reasons = []

    if paw_l2 < crop_threshold and paw_l3 < 0.40 and precip_72h_mm < 5.0:
        risk = "WYSOKIE"
        reasons.append(f"Niski zapas wody w warstwach 2–3 (retencja gleby: {soil.water_retention}) przy braku opadów.")
    elif paw_l2 < crop_threshold + 0.15 and precip_72h_mm < 5.0:
        risk = "UMIARKOWANE"
        reasons.append("Spadek wilgotności w płytszej strefie korzeniowej (Poziom 2) – zalecana kontrola nawadniania.")
    else:
        risk = "NISKIE"
        reasons.append("Wystarczający zapas wody w profilu glebowym.")

    if ndmi_forecast is not None and ndmi_forecast < 0.15:
        risk = "UMIARKOWANE" if risk == "NISKIE" else "WYSOKIE"
        reasons.append(f"Prognozowany niski wskaźnik NDMI ({ndmi_forecast:.2f}) wskazuje na możliwy stres wodny roślin.")

    return {
        "irrigation_risk": risk,
        "paw_layer2_pct": round(paw_l2 * 100, 1),
        "paw_layer3_pct": round(paw_l3 * 100, 1),
        "reasons": reasons,
    }


def evaluate_field_calendar(
    soil: FieldSoilProfile,
    field_weather_df: pd.DataFrame,
    fertilizer: Fertilizer,
    crop: Crop,
    ndmi_by_date: dict[str, float] | None = None,
    ndvi_by_date: dict[str, float] | None = None,
) -> list[dict]:
    """
    Łączy profil glebowy pola z tabelą dziennej pogody (z Open-Meteo lub historii Bayer)
    i zwraca gotową listę ocen dla widoku kalendarza oraz panelu szczegółowego dnia.
    """
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
        )
        irrig = evaluate_irrigation_risk(
            soil=soil,
            crop=crop,
            sm_l1=sm_l1,
            sm_l2=sm_l2,
            sm_l3=sm_l3,
            precip_72h_mm=precip_72h,
            ndmi_forecast=ndmi,
        )
        calendar_days.append(
            {
                "date": day_str,
                "field_id": soil.field_id,
                "crop": crop,
                "fertilizer": fertilizer,
                "status": fert["status"],
                "fertilization_reasons": fert["reasons"],
                "irrigation_risk": irrig["irrigation_risk"],
                "paw_layer2_pct": irrig["paw_layer2_pct"],
                "paw_layer3_pct": irrig["paw_layer3_pct"],
                "irrigation_reasons": irrig["reasons"],
                "weather": {
                    "temp_mean_c": round(temp_c, 2),
                    "precip_24h_mm": round(precip_24h, 2),
                    "precip_72h_mm": round(precip_72h, 2),
                    "sm_l1": round(sm_l1, 3),
                    "sm_l2": round(sm_l2, 3),
                    "sm_l3": round(sm_l3, 3),
                },
                "ndvi_forecast": ndvi,
                "ndmi_forecast": ndmi,
            }
        )
    return calendar_days


# ==============================================================================
# URUCHOMIENIE CAŁEGO PIPELINE'U (ETAP 1 -> ETAP 2)
# ==============================================================================

if __name__ == "__main__":
    # 1. ETAP 1: Przelicz wszystkie pola z GeoJSON na bazie wszystkich województw
    df_profiles = prepare_all_soil_profiles(
        geojson_path="fields.geojson",
        soil_dir="soil_data",
        output_parquet="fields_soil_profiles.parquet",
        output_json="fields_soil_profiles.json",
        id_col="id",
    )
    print(
        df_profiles[
            ["field_id", "area_ha", "centroid_lat", "centroid_lon", "sand_pct", "soilTexture", "ph", "klasa_bonitacyjna", "permeability"]
        ].head()
    )

    # 2. ETAP 2: Pobierz pierwsze pole z wyników Etapu 1 i oceń dzień
    first_field_id = df_profiles["field_id"].iloc[0]
    soil_profile = load_field_profile(first_field_id, "fields_soil_profiles.parquet")

    fert_eval = evaluate_fertilization_day(
        soil=soil_profile,
        fertilizer="mocznik_inhibitor",
        crop="kukurydza",
        precip_24h_mm=0.0,
        precip_72h_mm=1.5,
        temp_c=23.0,
        sm_l1=0.09,
        sm_l2=0.12,
        sm_l3=0.14,
    )

    irrig_eval = evaluate_irrigation_risk(
        soil=soil_profile,
        crop="kukurydza",
        sm_l1=0.09,
        sm_l2=0.12,
        sm_l3=0.14,
        precip_72h_mm=1.5,
        ndmi_forecast=0.12,
    )

    print("\n--- WYNIK DLA POLA:", first_field_id, "---")
    print("PROFIL:", asdict(soil_profile))
    print("NAWOŻENIE:", fert_eval)
    print("NAWADNIANIE:", irrig_eval)
