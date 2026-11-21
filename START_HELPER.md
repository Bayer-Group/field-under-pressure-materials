# START HELPER — ściągawka uruchamiania projektu

Gotowe komendy w poprawnej kolejności (od konfiguracji środowiska, przez główny pipeline `main.py`, strefy VRA i ML, aż po bazę PostGIS i cron Telegrama).

> **Uwaga dot. ścieżki Pythona:**
>
> - **macOS / Linux:** używaj `.venv/bin/python` oraz `.venv/bin/pip`
> - **Windows (PowerShell):** zamień `.venv/bin/python` na `.venv\Scripts\python.exe` (i analogicznie `.venv\Scripts\pip.exe`).

---

## 0. Jednorazowa konfiguracja środowiska

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
```

### Windows (PowerShell)

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\pip.exe install -r requirements.txt
```

### Plik `.env` i szybki test konfiguracji

W katalogu głównym repozytorium utwórz lub uzupełnij `.env` o wymagane zmienne:

- Linki danych: `CROPLAND_URL_*`, `SOIL_URL_*` (np. `SOIL_URL_LODZKIE`, `SOIL_URL_MAZOWIECKIE`), `BAYER_GRIDS_URL`
- Opcjonalnie dla alertów Telegrama: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `HC_LIZMAP_URL`

Sprawdź konfigurację bez pobierania i bez zapisu plików:

```bash
.venv/bin/python main.py --dry-run
```

---

## 1. Mapa zależności (kolejność kroków)

```text
1) main.py  (pola -> uprawy CLMS -> gleba SoilGrids + H3 -> fields_master -> satelita S2)
     ├─ opcjonalnie --run-zones:       ndvi_kmeans (1D NDVI) -> vra_export -> gleba per strefa + SQL
     ├─ następnie:                     pogoda dzienna (weather_daily.parquet)
     └─ opcjonalnie --run-protection:  Moduł 2 (choroby + okna oprysku + field_disease_dump.sql)

2) [Opcjonalnie, dla stref 2D z AWC]
   ndvi_kmeans (2D: NDVI + awc_mm_per_m) lub firtilization_cluster_learning.ipynb
     └─ potem: vra_export.py (dawki VRA, PLN, 8 scenariuszy, Shapefile/RX .zip, PostGIS SQL + gleba stref)

3) [Opcjonalnie, ML 7-dniowy]
   python -m ml.train (lub gotowy checkpoint ml/checkpoints/vegetation_lstm_pixel.pt)
     └─ python -m ml.predict

4) PostGIS / Lizmap (psql -f ...)  -->  main.py --telegram-cron
```

---

## 2. Główny pipeline danych (`main.py`)

### A. Najczęstsze uruchomienie — użycie lokalnego cache (`--skip-download`)

Aktualizuje warstwy pośrednie na podstawie zapisanych lokalnie plików i uruchamia Moduł 1 (`--run-zones`):

```bash
.venv/bin/python main.py --powiat lowicki --skip-download --run-zones
```

### B. Pełne pobranie z sieci i wymuszenie przeliczenia (`--force`)

```bash
.venv/bin/python main.py --powiat lowicki --run-zones --force
```

### C. Pełny zestaw: strefy VRA + piksele 10 m pod ML + Moduł 2 (choroby/opryski)

```bash
.venv/bin/python main.py --powiat lowicki --skip-download --run-zones --prepare-pixels --run-protection
```

### Najważniejsze flagi `main.py`

| Flaga                                    | Znaczenie                                                                                   |
| ---------------------------------------- | ------------------------------------------------------------------------------------------- |
| `--powiat <nazwa>`                       | Gotowy powiat z bazy bounding boxów (domyślnie `lowicki`)                                   |
| `--bbox MIN_LON MIN_LAT MAX_LON MAX_LAT` | Własny bbox WGS84 (nadpisuje `--powiat`)                                                    |
| `--start-date` / `--end-date`            | Zakres dat `YYYY-MM-DD` (domyślnie `2024-03-01` .. `2024-06-30`)                            |
| `--skip-download`                        | Tryb offline — nie pobiera z sieci, korzysta tylko z lokalnego cache                        |
| `--force`                                | Wymusza nadpisanie istniejących plików pośrednich / cache                                   |
| `--run-zones`                            | Uruchamia klasteryzację K-Means 1D (`NDVI`) -> `vra_export` -> SoilGrids per strefa + SQL   |
| `--prepare-pixels`                       | Buduje próbki 10 m (`data/ml/pixel_master.parquet`, `pixel_satellite_indices.parquet`)      |
| `--run-protection`                       | Uruchamia Moduł 2 (ryzyko chorób i okna oprysku + `data/protection/field_disease_dump.sql`) |
| `--dry-run`                              | Pokazuje plan wykonania i status `.env` bez uruchamiania obliczeń                           |

---

## 3. Moduł 1 — Strefy 2D K-Means (`NDVI + awc_mm_per_m`) + `vra_export.py`

> **Ważna różnica:** `main.py --run-zones` wywołuje `process_fields_ndvi_kmeans(...)` w wariancie **1D (samo NDVI)**.
> Jeśli chcesz wyznaczyć strefy **2D (`NDVI z-score + awc_mm_per_m` z komórek H3)**, uruchom najpierw notebook `firtilization_cluster_learning.ipynb` albo komendę poniżej, a potem przepuść wynik przez `vra_export.py`.

### Krok 3A: Klasteryzacja 2D (`NDVI + awc_mm_per_m`) z terminala

_(Wymaga zainstalowanego `scikit-learn` i `joblib`)_

```bash
.venv/bin/python -c "from ndvi_kmeans import process_fields_ndvi_kmeans; process_fields_ndvi_kmeans('data/fields/lowicki_fields_crops.geojson', 'data/satellite/lowicki_2024-03-01_to_2024-06-30', 'data/zones', model_path='data/zones/ndvi_awc_kmeans_model.joblib', soil_source='data/soil/field_soil_h3_cells.parquet', awc_weight=0.75)"
```

### Krok 3B: Eksport VRA, oszczędności PLN, Shapefile/RX `.zip`, PostGIS SQL i gleba per strefa

Uruchamiaj zawsze po zmianie stref albo kiedy chcesz przeliczyć dawki dla innych parametrów bez ponownej klasteryzacji:

```bash
.venv/bin/python vra_export.py \
  --zones-input data/zones/field_zones.geojson \
  --out-dir data/zones \
  --fields-geojson data/fields/lowicki_fields_crops.geojson \
  --update-zones-geojson \
  --run-zone-soil
```

_(Jeśli notebook zapisał strefy np. do `data/zones/test_2025/field_zones.geojson`, wskaż ten plik w `--zones-input`.)_

### Krok 3C: Własny nawóz, strategia, cena i paczki RX dla wszystkich pól

```bash
.venv/bin/python vra_export.py \
  --zones-input data/zones/field_zones.geojson \
  --out-dir data/zones \
  --fields-geojson data/fields/lowicki_fields_crops.geojson \
  --fertilizer mocznik_inhibitor \
  --strategy wyrownawcza \
  --base-n 100 \
  --delta 0.20 \
  --price-pln-t 2150 \
  --rx-fields ALL \
  --update-zones-geojson \
  --run-zone-soil
```

- Dostępne `--fertilizer`: `saletra_amonowa` (34% N), `mocznik_inhibitor` (46% N), `rsm_32` (32% N), `saletrosan_26` (26% N)
- Dostępne `--strategy`: `potencjal` (więcej N dla mocnej strefy), `wyrownawcza` (więcej N dla słabej strefy)
- Opcja `--rx-fields`: `ALL` (wszystkie pola), konkretna lista ID po spacji (np. `--rx-fields field_0 field_12`), albo pomiń flagę (domyślnie top 3 największe pola)

### Pliki wynikowe Modułu 1

- `data/zones/field_zones_vra.geojson` i `data/zones/field_zones_vra.parquet` (oraz zaktualizowany `data/zones/field_zones.geojson` przy `--update-zones-geojson`)
- `data/zones/field_zones_summary.parquet` i `data/zones/field_zones_summary.json` (podsumowanie kosztów i oszczędności PLN per pole)
- `data/zones/field_zones_scenarios.json` (porównanie 4 nawozy × 2 strategie = 8 scenariuszy)
- `data/zones/shapefiles/all_fields_vra_zones.shp` (ESRI Shapefile `EPSG:2180`, kolumny DBF ≤ 10 znaków)
- `data/zones/rx_packages/rx_*.zip` (paczki RX na terminale rozsiewaczy)
- `data/zones/field_zones_dump.sql` (zrzut PostGIS dla `public.field_zones` i `public.field_zone_summary`)
- `data/soil/field_zone_soil_profiles.{parquet,json,sql}` (profile SoilGrids per strefa przy `--run-zone-soil`)

---

## 4. Moduł ML — Prognoza NDVI/NDMI na 7 dni (`ml.train` / `ml.predict`)

> Gotowy wytrenowany checkpoint pikselowy znajduje się w `ml/checkpoints/vegetation_lstm_pixel.pt`. Do treningu GPU użyj notatnika `notebooks/colab_train_vegetation_lstm.ipynb`.

### Trening lokalny (opcjonalny)

```bash
# Tryb pikselowy 10 m (wymaga wcześniejszego --prepare-pixels w main.py)
.venv/bin/python -m ml.train --data-dir data/ml --mode pixel

# Tryb per pole (średnia dla całego pola)
.venv/bin/python -m ml.train --data-dir data/ml --mode field
```

### Predykcja 7-dniowa

```bash
# Prognoza per pole (domyślnie dla pierwszego pola lub podanego --field-id)
.venv/bin/python -m ml.predict --mode field --data-dir data/ml --field-id field_0

# Prognoza pikselowa 10 m (rastry GeoTIFF + tabela)
.venv/bin/python -m ml.predict \
  --mode pixel \
  --data-dir data/ml \
  --field-id field_0 \
  --fields-geojson data/fields/lowicki_fields_crops.geojson \
  --tiff-dir data/satellite/lowicki_2024-03-01_to_2024-06-30 \
  --soil-h3-parquet data/soil/field_soil_h3_cells.parquet
```

---

## 5. Moduł 4 — Alerty Telegram (`telegram_alerts.py` + cron w `main.py`)

Wymaga działającego PostGIS z tabelą `public.field_calendar` (domyślne DSN w `telegram_alerts.py`: `host=localhost port=8093 dbname=geoai user=postgres password=postgres`) oraz ustawionego `TELEGRAM_BOT_TOKEN` (i `TELEGRAM_CHAT_ID` do wysyłki).

```bash
# 1) Napisz wiadomość do bota na Telegramie, potem odczytaj swoje CHAT_ID:
.venv/bin/python -c "from telegram_alerts import sendTelegramAlert; sendTelegramAlert(get_chat_id=True)"

# 2) Test treści wiadomości bez wysyłania (dry-run):
.venv/bin/python -c "from telegram_alerts import sendTelegramAlert; sendTelegramAlert(top=3, dry_run=True)"

# 3) Jednorazowa wysyłka alertów dla 3 pól o największym ryzyku:
.venv/bin/python -c "from telegram_alerts import sendTelegramAlert; sendTelegramAlert(top=3)"

# 4) Ciągły CRON — wysyła codziennie o 00:00 (Europe/Warsaw):
.venv/bin/python main.py --telegram-cron
```

---

## 6. Ładowanie dumpów SQL do PostGIS

Przykładowe wgranie wygenerowanych plików `.sql` do lokalnej bazy PostGIS (`localhost:8093`, baza `geoai`, użytkownik `postgres`):

```bash
psql "host=localhost port=8093 dbname=geoai user=postgres" -f data/zones/field_zones_dump.sql
psql "host=localhost port=8093 dbname=geoai user=postgres" -f data/soil/field_zone_soil_profiles.sql
psql "host=localhost port=8093 dbname=geoai user=postgres" -f data/protection/field_disease_dump.sql
```

_(Jeśli korzystasz ze zmiennych środowiskowych PGPASSWORD lub innego hosta/portu, podmień parametry połączenia w `psql`.)_

---

## 7. Najczęstsze problemy (Troubleshooting)

1. **`ModuleNotFoundError: No module named 'sklearn'` lub `'joblib'`**Zainstaluj brakujące zależności do `.venv`:

   ```bash
   .venv/bin/pip install scikit-learn joblib
   ```

   _(Sam skrypt `vra_export.py` nie wymaga `scikit-learn` ani `joblib` — są potrzebne dopiero do klasteryzacji K-Means w `ndvi_kmeans.py`.)_

2. **Błąd PROJ / GDAL (`proj.db` version mismatch / CRS error)**`ndvi_kmeans.py` i `vra_export.py` same czyszczą zewnętrzne zmienne `PROJ_LIB`/`PROJ_DATA`, żeby koła `.venv` korzystały z własnego `proj.db`. Jeśli uruchamiasz inny skrypt lub `main.py` i widzisz błąd PROJ, wyczyść je w bieżącym shellu przed komendą:

   ```bash
   unset PROJ_LIB PROJ_DATA
   ```

3. **Komendy na Windows zamiast macOS/Linux**
   Wszystkie wywołania `.venv/bin/python ...` w tym pliku odpalasz na Windowsie jako `.venv\Scripts\python.exe ...` (np. `.venv\Scripts\python.exe vra_export.py --update-zones-geojson --run-zone-soil`).
