# 🤖 Instrukcje dla Agenta AI: Moduł Backend (`backend/`)

> Przed edycją plików w tym folderze zapoznaj się z nadrzędnym plikiem [`/AGENTS.md`](../AGENTS.md) oraz [`/CONTRIBUTING.md`](../CONTRIBUTING.md).

---

## 🎯 Zakres i Rola Modułu (`Scope`)
Folder `backend/` stanowi rdzeń obliczeniowy i komunikacyjny systemu (FastAPI). Odpowiada za:
1. Udostępnianie asynchronicznych endpointów REST API pod prefixem `/api/v1`.
2. Pobieranie surowych danych przestrzennych i środowiskowych przez moduły konektorów (`app/ingestion/`).
3. Wykonywanie obliczeń geometrycznych i analitycznych na żądanie (`app/domain/`).
4. Zapewnienie pełnej dokumentacji interaktywnej Swagger UI pod adresem `/docs`.

---

## 📂 Struktura Katalogu
```text
backend/
├── app/
│   ├── main.py                 # Inicjalizacja FastAPI, middleware CORS, routery
│   ├── core/
│   │   └── config.py           # Zmienne środowiskowe, stałe adresy API
│   ├── ingestion/              # KONEKTORY DANYCH (ULDK GUGiK, IMGW itp.)
│   │   ├── uldk_connector.py   # Klient API ULDK GUGiK
│   │   └── imgw_connector.py   # Klient danych IMGW-PIB
│   ├── domain/                 # FUNKCJE ANALITYCZNE I OBLICZENIOWE
│   │   └── geometry_metrics.py # Obliczenia obwiedni, pola, metryk
│   └── api/v1/
│       ├── router.py           # Rejestracja routerów pod /api/v1
│       └── endpoints/          # Pliki endpointów (cadastre.py, analysis.py)
├── requirements.txt            # Minimalne zależności (FastAPI, uvicorn, pydantic)
└── run_backend.py              # Jednoklikowy skrypt startowy serwera
```

---

## 🛑 Zasady Specyficzne dla Backend (`Twarde Reguły`)

1. **Zależności pod kontrolą człowieka:**
   * Nie instaluj dodatkowych bibliotek (`requests`, `httpx`, `aiohttp`, `geopandas`, `shapely`) bez wyraźnego polecenia człowieka w danym zadaniu.
   * Używaj bibliotek już zadeklarowanych w `requirements.txt` lub wskaż człowiekowi potrzebę dodania nowej biblioteki.
2. **Spójność z modelami Pydantic:**
   * Wszystkie endpointy w `api/v1/endpoints/` **muszą** używać modeli z `shared/schemas/geo_models.py` jako `response_model`.
   * Nie twórz lokalnych, zduplikowanych modeli Pydantic w backendzie – schematy są współdzielone z wtyczką QGIS i frontendem.
3. **Obsługa błędów:**
   * Każde zapytanie do zewnętrznych serwisów (ULDK, IMGW) musi być opakowane w blok `try-except` z obsługą timeoutów (`timeout=5`) i zwróceniem czytelnego statusu HTTP (`HTTPException`).
4. **Czystość kodu:**
   * Zachowaj asynchroniczność (`async def`) w funkcjach endpointów FastAPI.
   * Nie umieszczaj w `app/domain/` żadnej logiki biznesowej, o którą człowiek nie poprosił.
