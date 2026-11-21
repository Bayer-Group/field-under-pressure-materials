# Moduł `kw/` — Dane glebowe, pogoda Open-Meteo i ocena zabiegów

Cześć odpowiedzialna za **profilowanie glebowe pól**, **pobieranie aktualnej pogody oraz 7-dniowej prognozy z Open-Meteo** i **silnik oceny warunków nawożenia oraz nawadniania** dla aplikacji MVP *Field Under Pressure* (pola `>= 3 ha`, 3 uprawy, 4 nawozy, kalendarz 7-dniowy).

---

## 1. Zawartość folderu `kw/`

| Plik | Rola |
|---|---|
| `soil_bonification.py` | **Główny moduł glebowy i agronomiczny** (Etap 1: agregacja SoilGrids dla wszystkich pól z GeoJSON -> `fields_soil_profiles.parquet/.json`; Etap 2: ocena nawożenia, ryzyka nawadniania i 7-dniowego kalendarza). |
| `meteo.py` | **Pobieranie pogody z Open-Meteo** dla siatki Polski (14 dni historii + 7 dni prognozy), mapowanie głębokości wilgotności gleby na warstwy Bayera (`sm_l1..sm_l3`), suma opadów 72 h, ochrona przed limitem 429 oraz cache Parquet z datą w nazwie. |
| `test_meteo.py` | Testy jednostkowe (`unittest`, z mockami HTTP — bez zużywania limitów API) dla `meteo.py` oraz `soil_bonification.py`. |
| `fields.geojson` | Przykładowy zbiór granic pól używany podczas budowy i testów pipeline'u glebowego (66 poligonów w woj. lubuskim). |
| `soil.py`, `test.py` | Wcześniejsze prototypy robocze (dla pojedynczego pola / pojedynczego województwa Mazowieckiego), zastąpione przez kompletny `soil_bonification.py`. |

---

## 2. Gleba, bonitacja proxy i ocena zabiegów (`soil_bonification.py`)

Moduł działa w dwóch rozdzielonych etapach: najpierw jednorazowo wylicza statyczne profile glebowe pól (Etap 1), a następnie na ich bazie oraz bieżącej/prognozowanej pogody ocenia konkretne dni zabiegów (Etap 2).

### Etap 1 — Profilowanie pól (`ensure_parquets_unpacked`, `prepare_all_soil_profiles`)

1. **Automatyczne rozpakowanie danych SoilGrids**:
   `ensure_parquets_unpacked(soil_dir)` sprawdza folder `soil_data/`, rozpakowuje wszystkie archiwa `soil_*_isric_250_v2.zip` (jeśli nie zostały jeszcze wypakowane) i zbiera listę plików `.parquet` ze wszystkich województw.
2. **Geometria, powierzchnia i centroidy pól**:
   - Auto-detekcja układu współrzędnych (`EPSG:2180` przy współrzędnych metrowych, `EPSG:4326` przy stopniach).
   - Wyliczenie powierzchni w hektarach w polskim układzie metrycznym `EPSG:2180` i odfiltrowanie działek mniejszych niż `min_area_ha = 3.0 ha` (założenie MVP).
   - Wyznaczenie centroidu każdego pola w WGS84 (`centroid_lat`, `centroid_lon`) — wykorzystywane później m.in. do dopasowania najbliższego punktu pogodowego.
3. **Przestrzenny `JOIN` przez indeks H3 (poziom 10) w DuckDB**:
   - Każdy poligon jest zamieniany na zbiór komórek `h3` poziomu 10 (`h3.geo_to_cells`, z awaryjnym użyciem centroidu dla bardzo wąskich działek).
   - Pojedyncze zapytanie SQL w **DuckDB** łączy wszystkie komórki pól ze wszystkimi plikami wojewódzkimi naraz i liczy średnie parametry (`sand`, `silt`, `clay`, `ph`, `om`, `cec`, `bulk_density`) oraz dominującą klasę tekstury USDA (`MODE(soilTexture)`).
   - **Normalizacja frakcji `0–1` -> `0–100%`**: w źródłowych plikach ISRIC SoilGrids zawartość piasku, pyłu i iłu jest zapisana jako ułamek (`0.0–1.0`, np. `0.695`), dlatego zapytanie automatycznie przelicza je na procenty (`69.5%`).
4. **Szacunkowa klasa bonitacyjna (I–VI) i parametry wodne**:
   - Na podstawie tekstury (`TEXTURE_BASE_SCORE`), pH, materii organicznej (`om`), pojemności sorpcyjnej (`cec`) i gęstości objętościowej (`bulk_density`) wyliczany jest wskaźnik `bonitation_score` (`0–100`):
     `0.55 * tex_score + 0.20 * ph_score + 0.10 * om_score + 0.10 * cec_score + 0.05 * bd_score`,
     mapowany następnie na polskie klasy `VI, V, IVb, IVa, IIIb, IIIa, II, I`.
   - Pole `bonitation_source` jawnie informuje UI/API, że jest to estymacja na bazie ISRIC SoilGrids (brak oficjalnej państwowej warstwy bonitacyjnej).
   - Wyznaczana jest przepuszczalność (`permeability`), zdolność zatrzymywania wody (`water_retention`) oraz progi wilgotności objętościowej (`wilting_point` i `field_capacity` w `m³/m³`):
     - gleby lekkie/piaszczyste (`sand_pct >= 65`): `wysoka` przepuszczalność, `niska` retencja, progi `0.08 / 0.18`,
     - gleby ciężkie/ilaste (`clay_pct >= 30`): `niska` przepuszczalność, `wysoka` retencja, progi `0.18 / 0.36`,
     - gleby średnie: `srednia` przepuszczalność i retencja, progi `0.13 / 0.28`.
5. **Eksport i wczytywanie**:
   Wyniki zapisywane są do `fields_soil_profiles.parquet` oraz `fields_soil_profiles.json`. Pojedyncze pole wczytuje się funkcją `load_field_profile(field_id, profiles_parquet)` jako obiekt dataclass `FieldSoilProfile`.

### Etap 2 — Ocena zabiegów i kalendarza (`evaluate_fertilization_day`, `evaluate_irrigation_risk`, `evaluate_field_calendar`)

Obsługiwane warianty MVP:
- **Uprawy (`Crop`)**: `pszenica`, `kukurydza`, `rzepak`
- **Nawozy (`Fertilizer`)**: `saletra_amonowa`, `mocznik_inhibitor`, `rsm_32`, `saletrosan_26`

#### Ocena dnia nawożenia (`evaluate_fertilization_day`)
Zwraca słownik ze statusem (`ZIELONY`, `ZOLTY`, `CZERWONY`) oraz listą konkretnych uzasadnień (`reasons`):
- **Ograniczenia prawne i termiczne**:
  - jeśli podano `day_date` i wypada w okresie zimowym (miesiące `11, 12, 1, 2`) → `CZERWONY` (zakaz stosowania nawozów azotowych wg Programu Azotanowego),
  - przymrozek / zamarznięta gleba (`temp_c <= 0.0°C`) → `CZERWONY`.
- **Warunki wodne i opadowe (wspólne)**:
  - silny opad `precip_24h_mm > 10.0 mm` → `CZERWONY`,
  - wysoki opad `precip_72h_mm > 20.0 mm` → `ZOLTY`,
  - nasycenie wodą w warstwach 1–2 (`sm_l1 >= 1.05 * field_capacity` i `sm_l2 >= 1.05 * field_capacity`) → `CZERWONY`.
- **Reguły specyficzne dla nawozów**:
  - `saletra_amonowa` / `saletrosan_26`: na glebach o wysokiej przepuszczalności przy `precip_72h_mm > 15.0 mm` → `CZERWONY` (ryzyko wymywania); przy przesuszonej warstwie powierzchniowej (`sm_l1 <= 1.15 * wilting_point`) → `ZOLTY`.
  - `mocznik_inhibitor`: przy `pH > 7.2` i `temp_c > 20°C` → `CZERWONY` (straty amoniaku); przy `pH > 7.0` lub przesuszeniu warstwy 1 bez lekkiego opadu (`precip_72h_mm < 3.0 mm`) → `ZOLTY`.
  - `rsm_32`: z założenia eskaluje co najmniej do `ZOLTY` (ocena częściowa — w MVP brakuje wiatru i wilgotności powietrza do pełnej oceny oprysku/aplikacji); przy `temp_c > 22°C` lub `< 2°C` → `CZERWONY` (ryzyko poparzenia).

#### Ocena ryzyka nawadniania (`evaluate_irrigation_risk`)
Nie wylicza dawki wody (brak pełnego bilansu wodnego w MVP), lecz wskazuje ryzyko niedoboru (`NISKIE` / `UMIARKOWANE` / `WYSOKIE`) oraz procent dostępnej wody dla roślin (`paw_layer2_pct`, `paw_layer3_pct`):
- Liczy znormalizowaną wodę dostępną `PAW = (sm - wilting_point) / (field_capacity - wilting_point)` w warstwach L2 i L3.
- Uwzględnia większą wrażliwość kukurydzy i rzepaku (próg `0.35`) względem pszenicy (`0.30`) przy braku opadów (`precip_72h_mm < 5.0 mm`).
- Jeśli przekazano prognozę satelitarnego wskaźnika uwilgotnienia `ndmi_forecast < 0.15` (np. z modelu LSTM), podnosi ocenę ryzyka o jeden stopień w górę i dopisuje uzasadnienie.

#### Gotowy generator kalendarza (`evaluate_field_calendar`)
Łączy obiekt `FieldSoilProfile` z tabelą dziennej pogody (z `meteo.py` lub archiwum Bayera) oraz opcjonalnymi słownikami `ndmi_by_date` / `ndvi_by_date`, zwracając listę gotowych obiektów dziennych (status, ryzyko nawadniania, PAW L2/L3, parametry pogody, uzasadnienia) pod interfejs kalendarza i panel szczegółów dnia.

---

## 3. Pobieranie pogody Open-Meteo (`meteo.py`)

Skrypt pobiera aktualną i prognozowaną pogodę z darmowego API `https://api.open-meteo.com/v1/forecast` (strefa czasowa `Europe/Warsaw`), w formacie spójnym z resztą aplikacji i danymi historycznymi Bayera.

### Co jest pobierane i jak jest agregowane (`HOURLY_VARS`, `fetch_batch_daily`)

Zgodnie z założeniami MVP pobierane są wyłącznie:
- `temperature_2m` → agregacja dzienna do `temp_mean_c`, `temp_min_c`, `temp_max_c` (°C),
- `precipitation` → dzienna suma `precip_sum_mm` (mm) oraz wyliczona w przód 3-dniowa suma `precip_72h_mm` (`t + t+1 + t+2`, mm) wymagana bezpośrednio przez reguły nawożenia i nawadniania,
- 5 warstw wilgotności gleby Open-Meteo (`0_to_1cm`, `1_to_3cm`, `3_to_9cm`, `9_to_27cm`, `27_to_81cm`) → mapowane za pomocą średniej ważonej miąższością (`_weighted_mean`) na warstwy kompatybilne z Bayer Poziom 1–3:
  - `sm_l1` (**0–7 cm**, powierzchnia): wagi `1 : 2 : 4` z warstw `0–1`, `1–3`, `3–9 cm`,
  - `sm_l2` (**7–28 cm**, płytsza strefa korzeniowa): wagi `2 : 18 : 1` z warstw `3–9`, `9–27`, `27–81 cm`,
  - `sm_l3` (**28–81 cm**, głębszy zapas): warstwa `27–81 cm` jako przybliżenie Poziomu 3 Bayera (`28–100 cm`).

Świadomie pominięto ET₀, prędkość wiatru oraz wilgotność względną powietrza (zgodnie z podsumowaniem założeń MVP).

### Okno czasowe, siatka, cache i obejście limitów (`429`)

- **Siatka Polski (`generate_poland_grid`)**: regularna siatka co `0.25°` szerokości i `0.35°` długości geograficznej (~25 km, `696` punktów dla `lat 49.0..54.9`, `lon 14.1..24.2`). Można też podać własną zawężoną listę `coords`.
- **Domyślny zakres (`past_days=14`, `forecast_days=7`)**: dostarcza 14 dni bieżącej historii (np. pod okna wilgotności gleby w listopadzie 2026 r., których nie ma w archiwum Bayera 2020–2025) oraz 7 dni prognozy pod kalendarz.
- **Ochrona przed rate limitem Open-Meteo (`429`)**:
  - Open-Meteo na darmowym planie ogranicza ruch do **600 ważonych wywołań/min** (`waga = liczba_punktów * max(1, liczba_dni / 14)`).
  - Między paczkami (`batch_size=50`) skrypt automatycznie utrzymuje bezpieczną pauzę `max(pause_sec, batch_weight / 8.0)` (poniżej 480 wywołań/min — np. `6.5 s` dla 14 dni × 50 pkt lub `9.375 s` dla 21 dni × 50 pkt).
  - Gdy mimo to pojawi się HTTP `429`, backoff dla limitu minutowego startuje od **65 s** (`65 + 30 * attempt`) zamiast krótkich przerw 10 s, a przekroczenie limitu dziennego przerywa od razu z czytelnym `RuntimeError`.
- **Cache na dysku z datą w nazwie**:
  `fetch_poland_weather_daily()` zapisuje atomowo wynik do jednego pliku `weather_cache/open_meteo_poland_daily_<YYYY-MM-DD>.parquet`. Ponowne wywołanie tego samego dnia wczytuje dane z dysku bez odpytywania API (chyba że podano `force_refresh=True`).
- **Dopasowanie do pola (`get_weather_for_field`)**:
  Wybiera najbliższy punkt siatki względem `(field_lat, field_lon)` z korektą długości geograficznej przez `cos(lat)` i przy `forecast_only=True` zwraca tylko dni od dzisiaj w przód.

---

## 4. Przykłady użycia i uruchomienie testów

### Wygenerowanie profili glebowych z katalogu głównego repozytorium
```python
from kw.soil_bonification import prepare_all_soil_profiles, load_field_profile

prepare_all_soil_profiles(
    geojson_path="kw/fields.geojson",   # albo "bk/fields_crops.geojson" dla wspólnego zbioru pól
    soil_dir="soil_data",
    output_parquet="fields_soil_profiles.parquet",
    output_json="fields_soil_profiles.json",
)
soil = load_field_profile("field_0", "fields_soil_profiles.parquet")
```

### Pobranie pogody i wyliczenie 7-dniowego kalendarza dla pola
```python
from kw.meteo import fetch_poland_weather_daily, get_weather_for_field
from kw.soil_bonification import load_field_profile, evaluate_field_calendar

weather_pl = fetch_poland_weather_daily()
soil = load_field_profile("field_0", "fields_soil_profiles.parquet")
weather_7d = get_weather_for_field(soil.centroid_lat, soil.centroid_lon, weather_pl, forecast_only=True)

calendar = evaluate_field_calendar(
    soil=soil,
    field_weather_df=weather_7d,
    fertilizer="mocznik_inhibitor",
    crop="kukurydza",
)
```

### Uruchomienie testów jednostkowych modułu `kw/`
```bash
.venv/bin/python -m unittest discover -s kw -p "test_meteo.py" -v
```
