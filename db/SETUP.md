# MongoDB — Field Under Pressure (Hackathon GEO · Crop Science)

Reprodukowalny obraz Docker z bazą danych MongoDB odtwarzaną automatycznie z najnowszego dumpa (`.archive.gz`) — wraz ze wszystkimi kolekcjami, dokumentami, indeksami i walidatorami `$jsonSchema` (`_id: ObjectId`).

## Lokalna baza i API pogody

Potrzebujesz Pythona 3.10+, MongoDB 8.0 i MongoDB Database Tools. Z katalogu głównego repozytorium uruchom:

```powershell
python -m pip install -r backend/requirements.txt
python db/scripts/start_weather.py
```

Przy pierwszym starcie skrypt pobiera z `origin/ml` najnowszy zrzut do odtworzenia. Uruchamia MongoDB na `127.0.0.1:27018`, importuje 14 dni pogody z punktów `Orchard.centroid`, uruchamia harmonogram i wyświetla adres działającego wykresu. API nasłuchuje domyślnie na `127.0.0.1:8000`. Kolejne starty używają tej samej bazy z `data/weather-mongodb` i uzupełniają ostatnie dni. `Ctrl+C` zamyka procesy uruchomione przez skrypt.

- Jeśli narzędzia MongoDB są poza `PATH`, podaj `--mongo-bin` z katalogiem `mongod` i `--tools-bin` z katalogiem `mongorestore`. Jeśli oba pliki są w jednym katalogu, wystarczy `--mongo-bin`.
- Opcja `--archive ścieżka/do/zrzutu.archive.gz` wybiera lokalny zrzut przy odtwarzaniu pustej bazy. `--data-dir`, `--mongo-port` i `--api-port` pozwalają uruchomić drugą instancję obok istniejącej.
- Opcja `--check` sprawdza wszystkie pięć zakresów wykresu i CORS dla UI, a następnie zamyka oba procesy. Dane zostają w katalogu wybranej instancji.

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
git fetch origin ml:refs/remotes/origin/ml
git restore --source=origin/ml --worktree -- db/backups/field_under_pressure_20261121_154819.archive.gz
docker compose up -d --build
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
docker compose up -d --build
```
