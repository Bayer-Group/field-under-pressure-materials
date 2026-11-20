# Baza PostGIS (schemat `fup`)

Baza obsługująca backend (FastAPI) dla danych pogodowych, pól i upraw. PostgreSQL 15 + PostGIS 3.3 w Dockerze.
Źródło prawdy dla struktury: [`initdb/02_schema.sql`](initdb/02_schema.sql). Zasady modułu: [`AGENTS.md`](AGENTS.md).

## Uruchomienie

Z rootu repo:

```bash
cp example.env .env        # ustaw własne wartości, w szczególności hasło (.env jest w .gitignore)
docker compose --env-file .env -f docker/docker-compose.yml up -d postgis
```

Schemat tworzy się sam **tylko przy pierwszym starcie na pustym wolumenie**. Po zmianie plików w `initdb/` trzeba
odtworzyć bazę (`down -v`, patrz niżej). Pierwszy start trwa kilka sekund; gotowość sprawdzisz tak:

```bash
set -a; source .env; set +a
docker exec spatial_postgis psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c '\dt fup.*'   # 6 tabel
```

## Połączenie

| Parametr | Wartość |
| --- | --- |
| host | `localhost` (lub adres serwera) |
| port | `POSTGRES_PORT` z `.env` (domyślnie 5432) |
| baza | `POSTGRES_DB` z `.env` |
| użytkownik / hasło | `POSTGRES_USER` / `POSTGRES_PASSWORD` z `.env` |
| schemat | `fup` |

- psql: `docker exec -it spatial_postgis psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"`
- QGIS: Warstwa → Dodaj warstwę PostGIS, schemat `fup` (np. `grid_cell`, `field`).
- Na współdzielonym serwerze nie wystawiaj portu bazy do internetu (tunel SSH / VPN) i ustaw własne hasło.

## Zasady przyjęte w schemacie

- Zakres MVP: pogoda **godzinowa**, siatka **4 km**, okno 1–2 miesięcy, rok źródłowy 2024.
- Współrzędne w **EPSG:4326**.
- Brak interpolacji: pole dostaje wartość komórki, w której leży jego centroid (widok `v_field_grid`).
- Brakujące wartości ze źródła zostają `NULL` (nigdy 0). Źródło ustawia `null` dla wartości poza zakresem.
- Dane ładujemy z oryginalnymi datami. Przesunięcie czasu robimy **po załadowaniu** (osobne zadanie) i zapisujemy
  w `ingest_log.time_shift`.

## Tabele

### `fup.grid_cell`: siatka pogodowa 4 km
Źródło: `grid_table` z `weather_grids.zip`. Źródło ma tylko punkty (środki komórek), bez wielokątów.

| Kolumna | Typ | Uwagi |
| --- | --- | --- |
| `grid_id` | text, **PK** | identyfikator komórki |
| `lat`, `lon` | double precision | WGS84 |
| `geom` | geometry(Point, 4326) | budowana z `lon`/`lat`: `ST_SetSRID(ST_MakePoint(lon, lat), 4326)` |
| `geohash4` | text | pomocnicze, opcjonalne |
| `time_zone` | text | w dokumentacji źródła „STRING / FLOAT”: sprawdzić faktyczny typ |

### `fup.weather_hourly`: pogoda godzinowa
Źródło: `hourly_table` (parquet per województwo i rok). Kolumny **1:1 z [`data/weather.md`](../data/weather.md)**, jednostki
metryczne, wartości `real`. Klucz `(grid_id, utc_time)`, plus indeks po samym `utc_time`.

| Kolumna | Typ | Uwagi |
| --- | --- | --- |
| `grid_id` | text, **PK**, FK → `grid_cell` | komórka musi istnieć wcześniej |
| `date` | date | lokalna data kalendarzowa |
| `utc_time` | timestamptz, **PK** | wczytywać jako UTC |
| `local_time` | timestamp | czas lokalny, bez strefy |
| `temperature`, `dew_point_temperature` | real | °C, 2 m |
| `precipitation` | real | mm w godzinie |
| `wind_speed`, `wind_gust`, `wind_speed_2m` | real | km/h |
| `wind_direction` | real | ° azymut |
| `relative_humidity` | real | % |
| `downward_solar_radiation`, `net_solar_radiation` | real | MJ/m²/h |
| `atmospheric_pressure` | real | mbar |
| `total_cloud_cover` | real | ułamek 0–1 |
| `snow_depth` | real | mm ekwiwalentu wodnego |
| `snow_density` | real | kg/m³ |
| `soil_temperature_level_1`…`_4` | real | °C; warstwy 0–7, 7–28, 28–100, 100–289 cm |
| `soil_moisture_level_1`…`_4` | real | m³/m³ |
| `eto`, `etr` | real | mm/h |

### `fup.crop_class`: legenda klas upraw CLMS CTY
Wypełniona w schemacie (`code` → `name`, np. `1110` = Wheat). Źródło: [`data/cropland.md`](../data/cropland.md).

### `fup.field`: pola (np. pola jednego rolnika)

| Kolumna | Typ | Uwagi |
| --- | --- | --- |
| `field_id` | text, **PK** | |
| `name` | text | |
| `source` | text | skąd pochodzi geometria (np. `geojson`, `uldk`) |
| `geom` | geometry(Geometry, 4326) | tylko POLYGON lub MULTIPOLYGON (ograniczenie w bazie) |

**Widok `fup.v_field_grid`** `(field_id, grid_id)`: reguła „centroid pola → najbliższa komórka”, liczona w metrach.

### `fup.field_crop_share`: udział klas upraw w polu
Liczone z rastra CTY 10 m (np. statystyki strefowe) przy ładowaniu.

| Kolumna | Typ | Uwagi |
| --- | --- | --- |
| `field_id` | text, **PK**, FK → `field` | |
| `year` | integer, **PK** | rok rastra CTY |
| `class_code` | integer, **PK**, FK → `crop_class` | |
| `pixel_count` | bigint | |
| `share` | real | 0–1 (ograniczenie w bazie) |

### `fup.ingest_log`: pochodzenie danych
Jeden wpis na załadowany zbiór/plik: `dataset`, `source_file`, `source_year`, `row_count`, `time_shift`, `note`
(`id` i `loaded_at` wypełniają się same).

## Ładowanie danych (dla loadera)

Kolejność (klucze obce): `grid_cell` → `weather_hourly` → `field` → `field_crop_share` → wpis w `ingest_log`.
`crop_class` jest już wypełniona.

- Nazwy kolumn w `weather_hourly` i `grid_cell` są takie jak w parquet, poza `geom` (budowana z `lat`/`lon`).
- Czas wczytywać w UTC (`SET TIME ZONE 'UTC'` w sesji, jeśli narzędzie tego nie robi).
- Nie zamieniać `NULL` na 0 i nie wypełniać braków; braki mają zostać widoczne.
- Do ładowania dużych plików nadaje się dowolne narzędzie (np. DuckDB czytające parquet i zapisujące do Postgresa, `COPY`).
  Wybór narzędzia należy do osoby piszącej loader.
- Po każdym załadowanym zbiorze dopisać wiersz do `ingest_log`.
- Dane i dumpy nie trafiają do Gita (`data/**` jest ignorowane).

## Kontrole po załadowaniu

```sql
SELECT count(*) FROM fup.grid_cell;
SELECT count(*) FROM fup.weather_hourly;
SELECT min(utc_time), max(utc_time) FROM fup.weather_hourly;
SELECT * FROM fup.v_field_grid;                -- pole -> komórka
SELECT utc_time, temperature FROM fup.weather_hourly
 WHERE grid_id = '<id>' AND utc_time BETWEEN '<od>' AND '<do>' ORDER BY 1;   -- szereg dla komórki
```

## Serwer (VM na GCP)

Maszynę z bazą stawia i obsługuje [`../scripts/provision_vm.sh`](../scripts/provision_vm.sh) (wymaga `gcloud`
i konfiguracji z kontem oraz projektem, domyślnie `geoearth`):

```bash
scripts/provision_vm.sh create     # utworzenie VM (płatne, pyta o potwierdzenie; DRY_RUN=1 tylko wypisuje komendy)
scripts/provision_vm.sh setup      # Docker, klon repo, .env z losowym hasłem, start PostGIS
scripts/provision_vm.sh tunnel     # tunel SSH: localhost:5433 -> baza na VM
scripts/provision_vm.sh status|start|stop
```

- Port bazy (5432) **nie jest** otwarty w zaporze GCP; dostęp tylko tunelem SSH.
- Hasło bazy jest losowane na VM i zostaje w `.env` na VM (nie trafia do repo ani na ekran).
- `setup` klonuje gałąź `BRANCH` (domyślnie `team/geoearth-junction`), więc `docker/initdb/` musi już w niej być.
- Dane przenosimy dumpem (patrz niżej) zamiast ładować od zera.

## Reset i kopia

```bash
# Reset (KASUJE dane w bazie); wymagany po zmianie initdb/
docker compose --env-file .env -f docker/docker-compose.yml down -v

# Kopia i odtworzenie (np. przeniesienie na serwer zamiast ponownego ładowania)
docker exec spatial_postgis pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB" > fup.dump
docker exec -i spatial_postgis pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists < fup.dump
```
