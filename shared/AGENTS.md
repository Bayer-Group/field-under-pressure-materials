# 🤖 Instrukcje dla Agenta AI: Moduł Współdzielony (`shared/`)

> Przed edycją plików w tym folderze zapoznaj się z nadrzędnym plikiem [`/AGENTS.md`](../AGENTS.md) oraz [`/CONTRIBUTING.md`](../CONTRIBUTING.md).

---

## 🎯 Zakres i Rola Modułu (`Scope`)
Katalog `shared/` to **Single Source of Truth (Pojedyncze Źródło Prawdy)** dla całego repozytorium. Zawiera:
1. Wspólne modele danych **Pydantic** (`schemas/geo_models.py`) używane jednocześnie przez:
   * Backend FastAPI (jako walidatory zapytań i schematy odpowiedzi `response_model`),
   * Wtyczkę QGIS (jako typy zwracane przez klienta API),
   * Frontend Webowy (jako definicje struktur JSON).
2. Stałe układów współrzędnych i definicje przestrzenne (`constants/poland_crs.py`).

---

## 📂 Struktura Katalogu
```text
shared/
├── constants/
│   ├── poland_crs.py       # Kody EPSG (2180, 4326, 3857) i BBOX Polski
│   └── __init__.py
└── schemas/
    ├── geo_models.py       # Modele: GeoFeatureRequest, SpatialMetric, GeoAnalysisResponse
    └── __init__.py
```

---

## 🛑 Zasady Specyficzne dla Shared (`Twarde Reguły`)

1. **BEZWZGLĘDNY ZAKAZ SAMOWOLNEJ ZMIANY KONTRAKTÓW:**
   * Modyfikacja pól w `geo_models.py` natychmiast wpływa na backend, wtyczkę QGIS i frontend.
   * **Nie wolno Ci dodać, usunąć ani zmienić nazwy żadnego pola** w modelach Pydantic bez jednoznacznego polecenia człowieka.
2. **Czystość zależności:**
   * Moduł `shared/` musi być całkowicie niezależny od środowiska QGIS (`qgis.core`) oraz od frameworka FastAPI.
   * Może korzystać wyłącznie ze standardowych bibliotek Pythona oraz `pydantic`.
3. **Kompatybilność wsteczna:**
   * Wszystkie nowe pola opcjonalne w modelach Pydantic muszą posiadać wartości domyślne (`= None`, `= {}`, `= []`), aby nie powodować błędów deserializacji w innych komponentach.
