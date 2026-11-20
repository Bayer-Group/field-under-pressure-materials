# 🤖 Instrukcje dla Agenta AI: Moduł Kontenerów (`docker/`)

> Przed edycją plików w tym folderze zapoznaj się z nadrzędnym plikiem [`/AGENTS.md`](../AGENTS.md) oraz [`/CONTRIBUTING.md`](../CONTRIBUTING.md).

---

## 🎯 Zakres i Rola Modułu (`Scope`)
Folder `docker/` zawiera opcjonalną konfigurację środowisk kontenerowych dla zespołów, które chcą uruchamiać bazy danych i serwery pomocnicze za pomocą `docker compose`. Obejmuje:
1. Bazę danych przestrzennych **PostGIS** (`postgis/postgis:15-3.3`).
2. Lokalne repozytorium obiektowe S3 **MinIO** na pliki rastrowe Cloud Optimized GeoTIFF (COG).
3. Serwer dynamicznego kafelkowania rastrów **TiTiler** (`ghcr.io/developmentseed/titiler`).

---

## 📂 Struktura Katalogu
```text
docker/
├── docker-compose.yml       # Definicja serwisów: postgis (5432), minio (9000/9001), titiler (8080)
├── README.md                # Opis bazy: uruchomienie, połączenie, tabele, mapowanie ze źródeł, ładowanie
└── initdb/                  # Skrypty SQL wykonywane przy pierwszym starcie PostGIS (pusty wolumen)
    ├── 01_extensions.sql    # PostGIS + schemat fup
    └── 02_schema.sql        # Tabele MVP: grid_cell, weather_hourly, crop_class, field, field_crop_share, ingest_log
```

Schemat `fup` (pogoda godzinowa 4 km, pola, uprawy) wykonuje się tylko na pustym wolumenie. Po zmianie
plików w `initdb/` trzeba odtworzyć bazę: `docker compose down -v` i ponownie `up` (kasuje dane w bazie).

Konfiguracja (użytkownik, hasło, baza, port) jest wspólna dla całej aplikacji: wzór w [`/example.env`](../example.env),
własna kopia w `/.env` (ignorowana przez git). Uruchomienie z rootu repo:
`docker compose --env-file .env -f docker/docker-compose.yml up -d postgis`.

---

## 🛑 Zasady Specyficzne dla Docker (`Twarde Reguły`)

1. **Status opcjonalny:**
   * Narzędzia Docker są **całkowicie opcjonalne**. Wtyczka QGIS oraz serwer FastAPI (`run_backend.py`) muszą działać poprawnie również bez uruchomionego Dockera.
   * Nie twórz twardych zależności w kodzie Pythona wymagających działającego kontenera PostGIS do podstawowych operacji analizy.
2. **Neutralne nazewnictwo i bezpieczeństwo:**
   * Nazwy kontenerów i baz danych muszą pozostać neutralne (`spatial_postgis`, `spatial_db`, `spatial_minio`).
   * Zmienne konfiguracyjne powinny być łatwe do nadpisania za pomocą pliku `.env`.
