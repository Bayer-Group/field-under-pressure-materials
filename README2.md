# 🌉 PyQGIS FastAPI Bridge

> **Asynchroniczny szkielet technologiczny (Developer Boilerplate)** łączący stację roboczą **QGIS (PyQGIS)**, serwer **FastAPI** oraz podgląd mapowy **MapLibre GL JS**.

Zaprojektowany jako uniwersalna biblioteka narzędziowa pod dowolne projekty geoprzestrzenne (np. analizy miejskie, gospodarka przestrzenna, transport, hydrologia, ochrona środowiska). Zawiera gotową, wielowątkową infrastrukturę komunikacyjną, integracje z publicznymi API w Polsce (**GUGiK ULDK, IMGW**) oraz obsługę państwowego układu współrzędnych **EPSG:2180 (PUWG 1992)**.

---

## 🏗️ Architektura i Przepływ Danych

```text
                   ┌──────────────────────────────────────────────┐
                   │             BACKEND (FASTAPI)                │
                   │   Asynchroniczne API + ULDK GUGiK + IMGW     │
                   └──────────────────────┬───────────────────────┘
                                          │  REST API (Pydantic / GeoJSON)
                  ┌───────────────────────┴───────────────────────┐
                  ▼                                               ▼
     🖥️ WTYCZKA QGIS                                 🌐 PODGLĄD WEBOWY
     (PyQGIS + QgsTask w tle)                        (MapLibre GL JS)
     Zero zawieszania interfejsu podczas             Lekka mapa w przeglądarce
     zapytań sieciowych i obliczeń                   z warstwami GeoJSON
```

---

## ⚡ Kluczowe Komponenty Infrastruktury

1. **Wielowątkowość w QGIS (`QgsTask`):**
   * Zapytania do API wykonywane są w tle za pośrednictwem klasy `QgsTask`.
   * Interfejs QGIS **nigdy się nie zawiesza** – użytkownik może swobodnie przesuwać mapę, przybliżać i klikać obiekty, podczas gdy zadania przetwarzają się w tle.

2. **Integracje z Polskimi Rejestrami Państwowymi (`backend/app/ingestion/`):**
   * **ULDK GUGiK (`uldk_connector.py`):** Pobieranie geometrii działek ewidencyjnych w układzie EPSG:2180 na podstawie numeru TERYT lub klikniętego punktu XY.
   * **IMGW-PIB (`imgw_connector.py`):** Pobieranie bieżących danych pomiarowych ze stacji synoptycznych w Polsce.
   * **Rejestr Otwartych Danych Przestrzennych:** Zbiór ponad 40 oficjalnych usług (WMS, WFS, WCS, STAC) udokumentowany w [`docs/polskie_rejestry_publiczne_gis.md`](docs/polskie_rejestry_publiczne_gis.md).

3. **Przeliczniki Układów Współrzędnych (`shared/constants/poland_crs.py`):**
   * Definicje i transformacje pomiędzy metrycznym układem **EPSG:2180** a globalnym **EPSG:4326 (WGS84)** oraz **EPSG:3857 (Web Mercator)**.

4. **Wspólne Schematy Pydantic (`shared/schemas/geo_models.py`):**
   * `GeoFeatureRequest`, `SpatialMetric`, `GeoAnalysisResponse` jako uniwersalny kontrakt danych dla API i wtyczki.

---

## 🚀 Szybki Start

### 1. Wtyczka QGIS
Wtyczka została podlinkowana bezpośrednio do profilu QGIS:
1. Otwórz projekt testowy: **[`sample_project/sample_project.qgs`](file:///C:/Users/wiktor/PycharmProjects/pyqgis-fastapi-bridge/sample_project/sample_project.qgs)**.
2. Wejdź w menu **Wtyczki $\rightarrow$ Zarządzaj wtyczkami...** $\rightarrow$ zakładka **Zainstalowane** i zaznacz:  
   ☑️ **`PyQGIS FastAPI Bridge`**.
3. Na pasku narzędzi kliknij ikonkę wtyczki, aby otworzyć boczny panel.
4. Kliknij **`▶ Run Analysis (FastAPI)`** – zadania zostaną zlecone w tle do menedżera zadań QGIS (`QgsTask`), a wyniki pojawią się w panelu bez zacinania mapy.

### 2. Backend FastAPI
Uruchomienie serwera jednym poleceniem:
```bash
python backend/run_backend.py
```
* **Endpoint API:** `http://127.0.0.1:8000`
* **Dokumentacja Swagger UI:** `http://127.0.0.1:8000/docs`
* **Health Check:** `http://127.0.0.1:8000/health`

### 3. Testy Jednostkowe (Automated Testing)
Uruchomienie całego pakietu testów (16 testów: API, schematy Pydantic, CRS, konektory ULDK/IMGW, walidacja wtyczki QGIS):
* **Windows (1 kliknięcie):** Uruchom dwuklikiem `run_tests.bat`
* **Linux / macOS:** `./run_tests.sh`
* **Standardowe polecenie:** `python -m unittest discover -s tests -p "test_*.py" -v`
* **GitHub Actions:** Każdy push i PR jest automatycznie testowany w chmurze (`.github/workflows/test.yml`).

### 4. Podgląd Webowy
Otwórz w przeglądarce plik:  
👉 **[`web/index.html`](file:///C:/Users/wiktor/PycharmProjects/pyqgis-fastapi-bridge/web/index.html)**

---

## 🎨 Edycja Panelu w Qt Designerze
1. Uruchom plik **`open_designer.bat`** (uruchamia Qt Designera z kontrolkami QGIS).
2. Plik widoku: `qgis_plugin/pyqgis_fastapi_bridge/gui/dockwidget.ui`.
3. Dzięki dynamicznemu ładowaniu (`uic.loadUiType`) zmiany w interfejsie są widoczne w QGIS od razu po przeładowaniu wtyczki.

---

## 📜 Licencja i Otwarte Dane

### 1. Licencja Open Source
Projekt udostępniany jest na zasadach otwartej licencji **MIT** (patrz plik `LICENSE`). Kod może być swobodnie używany, modyfikowany i rozwijany w celach komercyjnych oraz badawczych.

### 2. Wykaz Wykorzystywanych Otwartych Źródeł Danych
Projekt bazuje na legalnych, publicznych i otwartych źródłach danych przestrzennych:
* **GUGiK ULDK / PRG / NMT / BDOT10k:** Usługi katastralne, państwowy rejestr granic, numeryczne modele terenu i bazy danych obiektów topograficznych.
* **IMGW-PIB:** Publiczne dane telemetryczne, stacje synoptyczne i hydrologiczne.
* **Copernicus Data Space Ecosystem (ESA/EU):** Otwarte zobrazowania satelitarne Sentinel.
* Pełny rejestr 46 usług z odnośnikami do oficjalnych endpointów WMS/WFS/REST znajduje się w pliku [`docs/polskie_rejestry_publiczne_gis.md`](docs/polskie_rejestry_publiczne_gis.md).
