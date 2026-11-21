# MongoDB — Field Under Pressure (Hackathon GEO · Crop Science)

Reprodukowalny obraz Docker z bazą danych MongoDB odtwarzaną automatycznie z najnowszego dumpa (`.archive.gz`) — wraz ze wszystkimi kolekcjami, dokumentami, indeksami i walidatorami `$jsonSchema` (`_id: ObjectId`).

## Kolekcje w bazie `field_under_pressure`

- `User`
- `Orchard`
- `Tree`
- `CropPref`
- `Geofence`
- `JobSchedule`
- `JobLog`
- `ManualControl`

Analiza pikseli tworzy kolekcję `TreePixelAnalysis` przy pierwszym zapisie.

## Uruchomienie MongoDB

Z katalogu głównego repozytorium:

```bash
docker compose up -d mongodb
```

Przy pierwszym uruchomieniu (pusty wolumen `mongodb_data`) skrypt `/docker-entrypoint-initdb.d/01-restore-latest.sh` automatycznie odtworzy bazę z najnowszego archiwum z katalogu `db/backups/`.

Domyślne dane połączenia (można nadpisać zmiennymi środowiskowymi lub plikiem `.env`):

| Zmienna | Wartość domyślna |
|---|---|
| `MONGO_PORT` | `27017` |
| `MONGO_ROOT_USER` | `admin` |
| `MONGO_ROOT_PASSWORD` | `admin123` |
| `MONGO_DB` | `field_under_pressure` |

Adres do MongoDB Compass i lokalnych skryptów:

```text
mongodb://admin:admin123@localhost:27017/field_under_pressure?authSource=admin
```

Lokalne skrypty mogą używać tego adresu w `MONGO_URI`. Backend w Dockerze domyślnie łączy się z usługą `mongodb`. Aby skierować go do innej bazy, ustaw `BACKEND_MONGO_URI` na adres osiągalny z kontenera.

### Seed danych demonstracyjnych

Z głównego katalogu repozytorium uruchom:

```powershell
docker compose run --rm seed
```

Seed dodaje dwa pola `DEMO`, sześć drzew, profil gatunkowy oraz syntetyczne wartości do panelu **Analityka**. Pola pokazują przykład wysokiego i niskiego ryzyka. Przy kolejnym uruchomieniu skrypt pomija istniejące rekordy. Dane demonstracyjne obejmują granice, punkty i wskaźniki liczbowe. Warstwy GeoTIFF pochodzą z osobnych eksportów.

### Import przykładowej geometrii pól

Zainstaluj [zależności ML](../ML/soil_moisture/README.md) i uruchom w PowerShellu z katalogu repozytorium.

```powershell
$env:MONGO_URI = "mongodb://admin:admin123@localhost:27017/field_under_pressure?authSource=admin"
python -m ML.soil_moisture.import_fields
```

Skrypt wczytuje `ML/soil_moisture/data/fields.geojson` i dodaje pola do `Orchard`. Ponowne uruchomienie pomija wcześniejszy import.

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

Wyniki drzew znajdziesz w `TreePixelAnalysis`. Dokument łączy drzewo i jego gatunek z pikselem, sceną, estymacją wilgotności, prognozą (jeśli uruchomiona) oraz pogodą i nasłonecznieniem dla pola. Te dwie ostatnie wartości pochodzą z reprezentatywnego punktu w polu i mają własne pola w `context`. Gdy danych zabraknie, skrypt zapisze status i poda podsumowanie.

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

## Weryfikacja kolekcji

```bash
docker compose exec mongodb mongosh \
  -u admin -p admin123 --authenticationDatabase admin field_under_pressure \
  --eval "db.getCollectionNames().forEach(c => print(c, '-> docs:', db.getCollection(c).countDocuments()))"
```

## Reset bazy do stanu z najnowszego dumpa

```bash
docker compose down -v
docker compose up -d --build
```
