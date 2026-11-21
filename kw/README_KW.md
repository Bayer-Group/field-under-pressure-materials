# Moduł `kw/` — Gleba per strefa, pogoda (live/historyczna) i presja chorób

Część projektu odpowiedzialna za **profilowanie glebowe (per pole, per strefa i komórki H3)**, **pobieranie pogody z Open-Meteo (tryb bieżący i historyczny, dzienny i godzinowy) + wczytywanie godzinowych danych Bayera**, **diagnostykę stresu wodnego** oraz **Moduł 2: presję chorób roślin i okna oprysku**.

---

## 1. Zawartość folderu `kw/` i struktura katalogu `data/`

| Plik              | Rola                                                                                                                                                                                                                                                                                                                                                                                                                           |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `soil.py`         | **Gleba, stres wodny i nawożenie**: profile SoilGrids per pole, **per strefa (`prepare_zone_soil_profiles`)** i per komórka H3 (`prepare_field_h3_soil_cells`), **parametry retencji Saxtona & Rawlsa (2006)** (`wilting_point`, `field_capacity`, `awc_mm_per_m`) oraz natywne klasy SoilGrids (`band_ph`, `band_om`, `band_cec`), integracja upraw z `bk/assign_crops.py`, ocena nawożenia i diagnostyka **stresu wodnego**. |
| `meteo.py`        | **Pogoda Open-Meteo + loader Bayera**: tryb bieżący (`past_days`/`forecast_days`) oraz **tryb historyczny** (`start_date`/`end_date`, automatyczne przełączanie Forecast vs Archive API), tryb dzienny i **godzinowy** (`temp`, `RH`, `punkt rosy`, `opad`, `wiatr`), loader godzinowy Bayer + IMERG oraz ochrona przed limitem `429`.                                                                                         |
| `disease_risk.py` | **Moduł 2 — ochrona roślin**: przybliżenie godzin zwilżenia liści, presja głównych chorób uprawy w oknie **48 h** wg `metodyki/ryzyka_zebrane.xlsx`, wyznaczanie godzinowych okien oprysku (wg norm PIORiN/GIORiN) oraz eksport do SQL (`public.field_disease`, `public.field_spray_windows`).                                                                                                                                 |
| `use.py`          | **Skrypt spinający cały przepływ (demo / podgląd danych)** od profilowania gleby przez kalendarz 7-dniowy po ochronę roślin.                                                                                                                                                                                                                                                                                                   |
| `fields.geojson`  | Przykładowy zbiór granic pól używany podczas budowy i testów (66 poligonów w woj. lubuskim).                                                                                                                                                                                                                                                                                                                                   |

### Docelowa struktura danych wyjściowych i wejściowych w `data/`

| Katalog            | Przeznaczenie                                                                                                                                                            |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `data/soil/raw/`   | Surowe paczki/pliki `.parquet` i `.zip` ISRIC SoilGrids (wcześniej `soil_data/`).                                                                                        |
| `data/soil/`       | Wygenerowane profile glebowe (`fields_soil_profiles.parquet/.json`, `field_zone_soil_profiles.parquet/.json`, `field_soil_h3_cells.parquet`, `field_soil_profiles.sql`). |
| `data/meteo/`      | Cache pogody Open-Meteo (`open_meteo_poland_daily_*.parquet`, `open_meteo_hourly_*.parquet` — wcześniej `weather_cache/`).                                               |
| `data/protection/` | Tabele ochrony roślin Modułu 2 (`field_disease.parquet/.json`, `field_spray_windows.parquet/.json`, `field_disease_dump.sql`).                                           |
| `data/zones/`      | Warstwa stref 10 m z Modułu 1 (`field_zones.geojson`).                                                                                                                   |
| `data/ml/`         | Tabele dla sieci neuronowej ML (`fields_master.parquet`, `satellite_indices.parquet`, `weather_daily.parquet` oraz `demo/` — wcześniej `ml_data/`).                      |

---

## 2. Gleba per strefa, zmienność wewnętrzna i stres wodny (`soil.py`)

### Główne zmiany względem pierwszej wersji

1. **Obsługa zmienności gleby wewnątrz pola i integracja upraw (`bk/assign_crops.py`)**:
   - `prepare_all_soil_profiles(...)` poza średnimi parametrami wyznacza rozpiętość w obrębie pola (`sand_min_pct`, `sand_max_pct`, `ph_min`, `ph_max`) oraz kategorię zmienności wewnętrznej `soil_variability` (`niska` / `umiarkowana` / `wysoka`).
   - Dołączanie upraw (`crop_code`, `crop`) działa przez `_attach_crops(...)` na trzy sposoby: (a) kolumny obecne już w GeoJSON (np. `bk/fields_crops.geojson`), (b) zewnętrzny plik `crops_geojson` dopasowany przestrzennie po geometrii, lub (c) bezpośrednie wywołanie `CropDetector(year=...)` z `bk/assign_crops.py` po podaniu `assign_crops_year`.
   - `prepare_zone_soil_profiles(zones_input, soil_dir, ...)` liczy pełny profil glebowy **osobno dla każdej strefy 10 m z Modułu 1** (`field_id`, `zone`, `ndvi_z`, `dose_kg_n_ha`, `dose_kg_product_ha`). Dzięki temu strefa piaszczysta/słaba nie jest maskowana średnią z całego pola.
   - `prepare_field_h3_soil_cells(...)` zwraca surowe komórki H3 poziomu 10 (`~250 m`) wewnątrz każdego pola do wizualizacji na mapie ryzyka.
   - `export_soil_profiles_to_sql(...)` generuje gotowy plik SQL dla PostgreSQL (`public.field_soil_profiles` / `public.field_zone_soil_profiles`).
2. **Parametry fizyczno-wodne Saxtona & Rawlsa (2006) oraz natywne pasma ISRIC (zamiast sztucznej punktacji)**:
   - Zrezygnowano z heurystycznego słownika `TEXTURE_BASE_SCORE` oraz sztucznych wag oceny gleby i fikcyjnych klas I–VI.
   - Zamiast nich wyliczamy:
     - `wilting_point` (WP, 1500 kPa), `field_capacity` (FC, 33 kPa) i użyteczną pojemność wodną `awc_mm_per_m` z recenzowanych równań pedotransferowych **Saxtona & Rawlsa (2006)** (na podstawie `sand_pct`, `clay_pct`, `om`), z której wynika klasa `water_retention` (`niska` `< 110`, `srednia` `110–150`, `wysoka` `>= 150 mm/m`),
     - natywne klasy kategoryczne bezpośrednio z plików ISRIC SoilGrids: `band_ph` (`BAND_pH`), `band_om` (`BAND_om`), `band_cec` (`BAND_cec`),
     - `soil_method_note` (jawna adnotacja o pochodzeniu z SoilGrids 250 m i braku urzędowej klasy I–VI — w produkcji docelowo z usług WFS/EGiB GUGiK oraz IUNG-PIB).
3. **Moduł stresu wodnego (`evaluate_water_stress`) zamiast nawadniania**:
   - Uprawy polowe w Polsce rzadko są nawadniane, więc zamiast rekomendacji podlewania moduł diagnozuje:
     - `water_status`: `DEFICYT` / `OPTYMALNY` / `NADMIAR` (nadmiar wykrywany przy nasyceniu warstw 1–2 powyżej pojemności polowej),
     - `water_stress_level`: `NISKI` / `UMIARKOWANY` / `WYSOKI` (z uwzględnieniem zapasu wody dostępnej `PAW` w warstwach L2–L3 oraz opcjonalnego `ndmi_value < 0.15`).
4. **Ocena nawożenia (`evaluate_fertilization_day`)**:
   - Uwzględnia zakaz zimowy Programu Azotanowego (XI–II), przymrozki (`<= 0°C`), opad 24 h / 72 h, nasycenie gleby, pH i temperaturę (mocznik) oraz — jeśli podano `wind_max_kmh` i `rh_mean_pct` — pełne kryteria wiatrowe/wilgotnościowe dla **RSM 32** (`> 18 km/h` → `CZERWONY`, `14.4–18 km/h` → `ZOLTY`).

---

## 3. Pogoda Open-Meteo (bieżąca + historyczna, dzienna + godzinowa) i loader Bayera (`meteo.py`)

### Tryby działania

1. **Tryb bieżący (`past_days=14, forecast_days=7`)** — pobiera ostatnie 14 dni + 7 dni prognozy z `/v1/forecast` do pliku `data/meteo/open_meteo_poland_daily_<YYYY-MM-DD>.parquet`.
2. **Tryb historyczny (`start_date="2024-04-01", end_date="2024-06-30"`)** — automatycznie kieruje zapytania do `/v1/archive` (dla dat starszych niż 6 dni) lub dzieli zakres na `archive + forecast`, dzieląc długie okresy na kawałki `<= 90` dni, do pliku `data/meteo/open_meteo_poland_daily_<start>_to_<end>.parquet`.
3. **Tryb godzinowy (`fetch_weather_hourly`)** — pobiera 5 parametrów potrzebnych w Module 2: `temperature_2m`, `relative_humidity_2m`, `dew_point_2m`, `precipitation`, `wind_speed_10m` (działa zarówno dla prognozy, jak i historii).
4. **Loader godzinowy Bayera (`load_bayer_weather_hourly`)** — łączy pola z najbliższym `grid_id` w DuckDB i wczytuje godzinowe pliki Bayera (`2020–2025`), automatycznie podpinając opady z `imerg_hourly_parquet`, jeśli w tabelach Bayera brakuje opadów.

### Zmienne i ochrona przed `429`

- Dzienne wyjście (`DAILY_OUTPUT_COLS`): `temp_mean_c`, `temp_min_c`, `temp_max_c`, `rh_mean_pct`, `dew_point_mean_c`, `wind_mean_kmh`, `wind_max_kmh`, `precip_sum_mm`, `precip_72h_mm`, oraz warstwy wilgotności gleby (`sm_l1`, `sm_l2` — dla Forecast API ważone miąższością `0–9` i `9–27 cm`, dla Archive API bezpośrednio z `0–7` i `7–28 cm`; opcjonalna warstwa `sm_l3` z danych Bayera jest wspierana, ale nie wymagana przez `evaluate_field_calendar`).
- Zarówno `FORECAST_HOURLY_VARS` (9 zmiennych), jak i `ARCHIVE_HOURLY_VARS` (8 zmiennych) mieszczą się w limicie `<= 10` zmiennych bez dodatkowej kary wagowej Open-Meteo; przerwy między paczkami skalują się poniżej `480 req/min`, a backoff po `429` startuje od `65 s`.

---

## 4. Moduł 2: Presja chorób i okno oprysku (`disease_risk.py`)

Implementuje bez-ML-owy, w pełni wyjaśnialny system oceny ryzyka fitosanitarnego i doboru godzin zabiegu:

1. **Godzina zwilżenia liści (`compute_leaf_wetness`)**:
   Godzina jest uznawana za mokrą, gdy `rh_pct > 90%` **lub** `temp_c - dew_point_c < 2.0°C` **lub** `precip_mm > 0.0`.
2. **Presja chorób w oknie 48 h (`evaluate_disease_pressure`)**:
   - Reguły termiczno-wilgotnościowe z `metodyki/ryzyka_zebrane.xlsx` (dla `pszenica`: septorioza paskowana liści `4–18°C`, rdza brunatna `15–18°C`, fuzarioza kłosów `15–25°C`, mączniak prawdziwy `5–30°C`, DTR `18–28°C`; plus reguły dla `kukurydza`, `rzepak`, `burak_cukrowy`, `ziemniak`, `slonecznik`).
   - Dla każdego dnia i choroby liczymy maksymalną liczbę mokrych godzin sprzyjających infekcji w kroczącym oknie **48 h** i nadajemy poziom `NISKI` / `SREDNI` / `WYSOKI` według **progów demonstracyjnych** (jawnie opisanych w `reason`).
3. **Godzinowe okna oprysku (`evaluate_spray_windows`)**:
   - Brak opadów w godzinie oprysku oraz przez kolejne `dry_after_hours = 3` h po zabiegu.
   - Liść suchy (`~is_wet_hour`), wilgotność względna `50–90%`, temperatura `8–22°C`.
   - Wiatr: `<= 14.4 km/h` (`4 m/s`, limit standardowy PIORiN) → `DOBRE`; `14.4–18.0 km/h` (`5 m/s` z rozpylaczami antyznoszeniowymi TOZ) → `WARUNKOWE`.
   - Zwraca ciągłe przedziały godzinowe (np. `08:00–16:00`), najlepsze okno oraz wyjaśnienie blokad przy `BRAK_OKNA`.
4. **Eksport do bazy PostgreSQL (`build_fields_protection_tables`, `export_protection_to_sql`)**:
   Zapisuje `data/protection/field_disease.parquet/.json`, `data/protection/field_spray_windows.parquet/.json` oraz zrzut SQL (`data/protection/field_disease_dump.sql`) dla tabel `public.field_disease (field_id, day, disease, risk, wet_hours, reason)` i `public.field_spray_windows`.

---

## 5. Szybkie przykłady użycia

Gotowy skrypt spinający cały przepływ (gleba + uprawy + cache pogody + kalendarz 7 dni + Moduł 2 chorób i oprysków) znajduje się w `kw/use.py`.

```bash
# Uruchomienie pełnego podglądu na realnych plikach w repozytorium:
.venv/bin/python kw/use.py
# albo jako moduł z katalogu głównego projektu:
.venv/bin/python -m kw.use
```

> **Uwaga o imporcie `from kw...`:** Jeśli uruchamiasz własny plik leżący w podkatalogu `kw/` bezpośrednio (`python kw/moj_skrypt.py`) albo z wnętrza `kw/`, Python widzi na początku `sys.path` sam folder `kw/` zamiast katalogu głównego projektu. Dlatego uruchamiaj skrypty z katalogu głównego przez `python -m kw.nazwa_skryptu` albo dodaj katalog nadrzędny do `sys.path` tak jak w `kw/use.py`.

```python
from kw.soil import prepare_all_soil_profiles, prepare_zone_soil_profiles, evaluate_field_calendar, load_field_profile
from kw.meteo import fetch_weather_hourly, fetch_poland_weather_daily, get_weather_for_field
from kw.disease_risk import build_fields_protection_tables, export_protection_to_sql

# 1a. Profile glebowe pól z podpięciem upraw z bk/fields_crops.geojson -> data/soil/
fields_df = prepare_all_soil_profiles("bk/fields_crops.geojson")

# 1b. (Opcjonalnie, po wygenerowaniu data/zones/field_zones.geojson w Module 1) Profile per strefa 10 m
# zones_df = prepare_zone_soil_profiles("data/zones/field_zones.geojson", crops_geojson="bk/fields_crops.geojson")

# 2. Pogoda bieżąca/historyczna (zapisuje do data/meteo/)
w_daily = fetch_poland_weather_daily()
soil = load_field_profile("field_0")
w_7d = get_weather_for_field(soil.centroid_lat, soil.centroid_lon, w_daily, forecast_only=True)
calendar = evaluate_field_calendar(soil, w_7d, fertilizer="saletra_amonowa", crop=soil.crop or "pszenica")

# 3. Presja chorób i okna oprysku -> data/protection/
w_hourly = fetch_weather_hourly(coords=[(52.63, 20.82)], start_date="2025-04-12", end_date="2025-04-20")
disease_df, spray_df = build_fields_protection_tables(fields_df.head(5), w_hourly, output_dir="data/protection")
export_protection_to_sql(disease_df, spray_df)
```

### Uruchomienie samego pipeline'u glebowego

```bash
.venv/bin/python kw/soil.py
```
