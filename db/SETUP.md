# MongoDB — Field Under Pressure (Hackathon GEO · Crop Science)

Reprodukowalny obraz Docker z bazą danych MongoDB oraz idempotentnym skryptem seedującym puste kolekcje wyłącznie z identyfikatorem `_id` typu `ObjectId` (bez sztucznych dokumentów i dodatkowych pól).

## Kolekcje

Skrypt [`scripts/seed.js`](scripts/seed.js) tworzy w bazie `field_under_pressure` następujące 9 pustych kolekcji:

- `User`
- `Orchard`
- `Tree`
- `CropPref`
- `Preferences`
- `Geofence`
- `JobSchedule`
- `JobLog`
- `ManualControl`

Każda kolekcja posiada walidator `$jsonSchema` wymuszający wyłącznie pole `_id` typu `objectId` (bez definiowania dodatkowych parametrów ani wstawiania rekordów startowych).

## Uruchomienie przez Docker Compose (zalecane)

Z katalogu głównego repozytorium:

```bash
docker compose up -d --build
```

Przy pierwszym uruchomieniu (pusty wolumen `mongodb_data`) skrypt `/docker-entrypoint-initdb.d/01-seed-collections.js` wykona się automatycznie i utworzy wszystkie kolekcje.

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

## Ręczne uruchomienie skryptu seedującego

Skrypt jest idempotentny — tworzy brakujące kolekcje i nie modyfikuje istniejących:

```bash
# Dla kontenera uruchomionego przez docker compose:
./db/scripts/seed.sh

# Dla dowolnej zewnętrznej instancji MongoDB (wymaga lokalnego mongosh):
MONGO_URI="mongodb://admin:admin123@localhost:27017/field_under_pressure?authSource=admin" ./db/scripts/seed.sh
```

## Udostępnianie bazy między deweloperami (Backup & Restore)

Cała baza `field_under_pressure` (wszystkie kolekcje, dokumenty, indeksy i walidatory) jest eksportowana do jednego współdzielonego pliku archiwum: `db/backups/field_under_pressure.archive.gz`.

### 1. Eksport bazy do archiwum (`backup.sh`)

```bash
# Zrzut całej bazy field_under_pressure do db/backups/field_under_pressure.archive.gz
./db/scripts/backup.sh

# Opcjonalnie: zapis do własnej ścieżki
./db/scripts/backup.sh path/to/custom.archive.gz
```

Wygenerowany plik `db/backups/field_under_pressure.archive.gz` można scommitować do repozytorium lub przekazać bezpośrednio innemu deweloperowi.

### 2. Odtworzenie bazy z archiwum (`restore.sh`)

```bash
# Odtworzenie całej bazy 1:1 z db/backups/field_under_pressure.archive.gz
# (domyślnie czyści lokalną bazę przed importem, aby stan był identyczny z archiwum)
./db/scripts/restore.sh

# Opcjonalnie: odtworzenie z innej ścieżki lub bez czyszczenia lokalnej bazy (--no-drop)
./db/scripts/restore.sh path/to/custom.archive.gz
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

## Reset bazy do stanu początkowego

```bash
docker compose down -v
docker compose up -d --build
```
