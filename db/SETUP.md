# MongoDB — S.A.G.E. (Smart Agricultural Guidance Engine)

Reprodukowalny obraz Docker z bazą danych MongoDB odtwarzaną automatycznie z najnowszego dumpa (`.archive.gz`) — wraz ze wszystkimi kolekcjami, dokumentami, indeksami i walidatorami `$jsonSchema` (`_id: ObjectId`).

## Lokalna baza i API pogody

Po pobraniu gałęzi `backend` uruchom panel z katalogu głównego repozytorium. Potrzebujesz Pythona 3.10+, MongoDB 8.0 z MongoDB Database Tools oraz Node.js z npm lub pnpm.

```powershell
python -m pip install -r backend/requirements.txt
python db/scripts/start_weather.py --with-ui
```

Panel otworzysz pod `http://127.0.0.1:5173`. Skrypt przy pierwszym starcie pobiera zależności UI z lockfile i ustawia adres API oraz tryb danych z MongoDB. Opcja `--with-ui --check` sprawdza start wszystkich usług i zamyka je po teście. Przy zajętych portach użyj `--mongo-port`, `--api-port` i `--ui-port`.

### Sam backend

Potrzebujesz Pythona 3.10+, MongoDB 8.0 i MongoDB Database Tools. Z katalogu głównego repozytorium uruchom:

```powershell
python -m pip install -r backend/requirements.txt
python db/scripts/start_weather.py
```

Przy pierwszym starcie skrypt odtwarza zrzut `db/backups/field_under_pressure_20261121_230119.archive.gz` dołączony do gałęzi. Uruchamia MongoDB na `127.0.0.1:27018`, importuje 14 dni pogody z punktów `Orchard.centroid`, uruchamia harmonogram i wyświetla adres działającego wykresu. API nasłuchuje domyślnie na `127.0.0.1:8000`. Kolejne starty używają tej samej bazy z `data/weather-mongodb` i uzupełniają ostatnie dni. `Ctrl+C` zamyka procesy uruchomione przez skrypt.

- Jeśli narzędzia MongoDB są poza `PATH`, podaj `--mongo-bin` z katalogiem `mongod` i `--tools-bin` z katalogiem `mongorestore`. Jeśli oba pliki są w jednym katalogu, wystarczy `--mongo-bin`.
- Opcja `--archive ścieżka/do/zrzutu.archive.gz` wybiera lokalny zrzut przy odtwarzaniu pustej bazy. `--data-dir`, `--mongo-port` i `--api-port` pozwalają uruchomić drugą instancję obok istniejącej.
- Opcja `--check` sprawdza wszystkie pięć zakresów wykresu i CORS dla UI, a następnie zamyka procesy. Dane zostają w katalogu wybranej instancji.

W Compass otwórz `mongodb://127.0.0.1:27018/field_under_pressure`. Bieżąca pogoda, prognoza i historia znajdują się w `Orchard.environmentalData`.

## Kolekcje w bazie `field_under_pressure`

- `User`
- `Orchard`
- `Tree`
- `CropPref`
- `Geofence`
- `JobSchedule`
- `JobLog`
- `ManualControl`

## Uruchomienie samej bazy przez Docker Compose

Z katalogu głównego repozytorium:

```bash
docker compose up -d --build mongodb
```

Przy pierwszym uruchomieniu (pusty wolumen `mongodb_data`) skrypt `/docker-entrypoint-initdb.d/01-restore-latest.sh` automatycznie odtworzy bazę z najnowszego archiwum z katalogu `db/backups/`.

Po uruchomieniu bazy ustaw `MONGO_URI` zgodnie z konfiguracją poniżej i uruchom `python -m backend.main migrate`, `python -m backend.main backfill` oraz `python -m backend.main run`.

Domyślne dane połączenia (można nadpisać zmiennymi środowiskowymi lub plikiem `.env`):

| Zmienna | Wartość domyślna |
|---|---|
| `MONGO_PORT` | `27017` |
| `MONGO_ROOT_USER` | `admin` |
| `MONGO_ROOT_PASSWORD` | `admin123` |
| `MONGO_DB` | `field_under_pressure` |

Przykładowy connection string:

```text
mongodb://admin:admin123@localhost:27017/field_under_pressure?authSource=admin
```

## Uruchomienie samego obrazu Docker (bez Docker Compose)

```bash
docker build -t field-under-pressure-mongodb ./db
docker run -d --name fup-mongodb -p 27017:27017 field-under-pressure-mongodb
```

## Udostępnianie bazy między deweloperami (Backup & Restore)

Cała baza `field_under_pressure` (wszystkie kolekcje, dokumenty, indeksy i walidatory) jest eksportowana do archiwum z timestampem: `db/backups/field_under_pressure_YYYYMMDD_HHMMSS.archive.gz`.

### 1. Eksport bazy do archiwum (`backup.sh`)

```bash
# Zrzut całej bazy field_under_pressure do db/backups/field_under_pressure_YYYYMMDD_HHMMSS.archive.gz
./db/scripts/backup.sh

# Opcjonalnie: zapis do własnej ścieżki
./db/scripts/backup.sh path/to/custom.archive.gz
```

Wygenerowane archiwum można scommitować do repozytorium lub przekazać bezpośrednio innemu deweloperowi.

### 2. Odtworzenie bazy z archiwum (`restore.sh`)

```bash
# Odtworzenie całej bazy 1:1 z najnowszego archiwum field_under_pressure_*.archive.gz w db/backups/
# (domyślnie czyści lokalną bazę przed importem, aby stan był identyczny z archiwum)
./db/scripts/restore.sh

# Opcjonalnie: odtworzenie ze wskazanego archiwum lub bez czyszczenia lokalnej bazy (--no-drop)
./db/scripts/restore.sh db/backups/field_under_pressure_20261120_235500.archive.gz
./db/scripts/restore.sh --no-drop
```

Oba skrypty działają również z zewnętrzną instancją MongoDB po ustawieniu `MONGO_URI` (wymagają wtedy lokalnego `mongodump`/`mongorestore`):

```bash
MONGO_URI="mongodb://admin:admin123@localhost:27017/?authSource=admin" ./db/scripts/backup.sh
MONGO_URI="mongodb://admin:admin123@localhost:27017/?authSource=admin" ./db/scripts/restore.sh
```

## Weryfikacja kolekcji

```bash
docker compose exec mongodb mongosh \
  -u admin -p admin123 --authenticationDatabase admin field_under_pressure \
  --eval "db.getCollectionNames().forEach(c => print(c, '-> docs:', db.getCollection(c).countDocuments()))"
```

## Reset bazy do stanu z najnowszego dumpa

```bash
docker compose down -v
docker compose up -d --build mongodb
```


## Obserwacje satelitarne drzew

W Compass otwórz kolekcję `Tree` i dodaj dokument z `orchardId` wskazującym rzeczywiste `Orchard._id`, gatunkiem oraz położeniem. Poniższy dokument w formacie Extended JSON pokazuje format używany przez bazę. Zastąp przykładowy identyfikator i współrzędne danymi swojego drzewa. Skrypt obsługuje również starsze rekordy z `geo` lub `geometry` typu GeoJSON `Point`.

```json
{
  "orchardId": {"$oid": "000000000000000000000001"},
  "species": "jabłoń domowa",
  "coordinates": {"lat": 52.23, "lng": 21.01}
}
```

Z katalogu repozytorium w aktywnym środowisku Python ustaw `MONGO_URI` jak w Compass. Ustaw `MONGO_ORCHARD_ID`, żeby eksport GEE objął tylko wybrane pole. Daty treningu i testu dopasuj do sceny, którą chcesz analizować.

```powershell
$env:MONGO_ORCHARD_ID = "ID_Z_ORCHARD"
python -m ML.soil_moisture.earth_engine --start 2025-04-01 --test-start 2025-07-01 --end 2025-08-01 --export-tree-raster
```

Pobierz z Dysku Google wyeksportowany `tree_pixels_*.tif`. Z komunikatu `Tree raster` skopiuj identyfikator sceny (fragment nazwy między `tree_pixels_` a `.tif`) i czas UTC. Trzy pasma TIFF zawierają kolejno VV, VH i estymację wilgotności gleby. Skrypt przyjmuje także jednopasmowy TIFF wilgotności z dotychczasowego eksportu.

```powershell
python -m ML.soil_moisture.tree_pixel_analysis --raster "C:\dane\tree_pixels_SCENA.tif" --scene-id "ID_SCENY" --acquired-at "2025-07-28T16:40:00Z"
```

Dodaj `--forecast-days 3`, żeby dla świeżej sceny wyliczyć trzy kolejne dni prognozy wilgotności od chwili uruchomienia. Domyślną dobą pogody i nasłonecznienia jest dzień przed akwizycją w strefie Europe/Warsaw. Opcja `--date YYYY-MM-DD` ustawia inną zakończoną dobę.

Wyniki drzew znajdziesz w `TreePixelAnalysis`. Dokument łączy drzewo i jego gatunek z pikselem, sceną, estymacją wilgotności, prognozą (jeśli uruchomiona) oraz pogodą i nasłonecznieniem dla pola. Te dwie ostatnie wartości pochodzą z centroidu sadu, z rezerwowym punktem reprezentatywnym przy braku centroidu i mają własne pola w `context`. Gdy danych zabraknie, skrypt zapisze status i poda podsumowanie.

### Podsumowanie pola w Orchard

Pobierz warstwy z [eksportów NDVI i parametrów gleby](../ML/soil_moisture/README.md#ndvi-i-parametry-gleby). Podaj je razem z rastrem wilgotności, aby zapisać komplet danych w `Orchard.analysis`. Użyj plików obejmujących wybrane pole.

```powershell
python -m ML.soil_moisture.tree_pixel_analysis --orchard-id "ID_POLA" --raster "tree_pixels_SCENA.tif" --scene-id "ID_SCENY" --acquired-at "2025-07-28T16:40:00Z" --ndvi-raster "sentinel2_ndvi_20250701_20250801.tif" --soil-ph-raster "openlandmap_soil_ph_0cm.tif" --soil-texture-raster "openlandmap_soil_texture_0cm.tif" --soil-depth-cm 0
```

- `analysis.ndvi`, `analysis.soil_moisture` i `analysis.soil_parameters.ph` zawierają średnią i liczbę ważnych pikseli.
- `analysis.soil_parameters.texture` zawiera najczęstszy kod USDA i rozkład liczby pikseli według klasy. Dla warstw gleby liczą się komórki przecinające pole. Każdy raster zachowuje własną siatkę.
- `analysis.solar_intensity.level` zawiera kategorię nasłonecznienia, a pozostałe pola tego obiektu przechowują dobę, energię i referencję.

Dodatkowe warstwy są opcjonalne. Podanie warstwy zapisuje jej podsumowanie i dodaje do `TreePixelAnalysis.layers` wartość z piksela pod każdym drzewem. Wartość `null` oznacza brak pokrycia lub ważnych danych dla danej warstwy. Analiza pola działa też w sadzie bez zapisanych drzew.

Do analizy drzew grupuj po `tree_id` lub `species`. Przy agregacji wartości satelitarnych wybierz jedną obserwację z każdego `pixel_id` w analizowanej scenie i dobie. Ponowne wykonanie dla tego samego drzewa, sceny i doby aktualizuje jego obserwację. Uruchomienie bez prognozy zachowuje zapisaną wcześniej prognozę.
