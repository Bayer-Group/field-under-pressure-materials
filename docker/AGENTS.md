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
└── docker-compose.yml       # Definicja serwisów: postgis (5432), minio (9000/9001), titiler (8080)
```

---

## 🛑 Zasady Specyficzne dla Docker (`Twarde Reguły`)

1. **Status opcjonalny:**
   * Narzędzia Docker są **całkowicie opcjonalne**. Wtyczka QGIS oraz serwer FastAPI (`run_backend.py`) muszą działać poprawnie również bez uruchomionego Dockera.
   * Nie twórz twardych zależności w kodzie Pythona wymagających działającego kontenera PostGIS do podstawowych operacji analizy.
2. **Neutralne nazewnictwo i bezpieczeństwo:**
   * Nazwy kontenerów i baz danych muszą pozostać neutralne (`spatial_postgis`, `spatial_db`, `spatial_minio`).
   * Zmienne konfiguracyjne powinny być łatwe do nadpisania za pomocą pliku `.env`.
