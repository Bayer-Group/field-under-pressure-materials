# PyQGIS FastAPI Bridge — imported starting point

> This bridge was merged into GeoEarth Junction's Field Under Pressure repository. See [PROJECT.md](PROJECT.md) for the product requirements, first iteration and current open decisions. The notes below describe the imported starter, not a completed crop-risk application. The data ingestion, nationwide risk map, treatment windows, and shared presentation of selected datasets in both clients remain to be built and verified.

> Setup has not yet been validated end to end in the merged repository. The organizer's `requirements.txt` and the bridge's `backend/requirements.txt` / `requirements2.txt` are separate dependency lists. The commands below describe the imported starter; document an integrated, tested setup during the first iteration.

# 🌉 PyQGIS FastAPI Bridge

> **An asynchronous technology boilerplate (Developer Boilerplate)** connecting a **QGIS (PyQGIS)** workstation, a **FastAPI** server and a **MapLibre GL JS** map viewer.

Designed as a universal toolkit for any geospatial project (e.g. urban analysis, spatial planning, transport, hydrology, environmental protection). It contains ready-made multithreaded communication infrastructure, integrations with public APIs in Poland (**GUGiK ULDK, IMGW**) and support for the Polish national coordinate system **EPSG:2180 (PUWG 1992)**.

---

## 🏗️ Architecture and Data Flow

```text
                   ┌──────────────────────────────────────────────┐
                   │             BACKEND (FASTAPI)                │
                   │   Asynchronous API + ULDK GUGiK + IMGW       │
                   └──────────────────────┬───────────────────────┘
                                          │  REST API (Pydantic / GeoJSON)
                  ┌───────────────────────┴───────────────────────┐
                  ▼                                               ▼
     🖥️ QGIS PLUGIN                                  🌐 WEB VIEWER
     (PyQGIS + QgsTask in the background)            (MapLibre GL JS)
     No interface freezing during                    Lightweight map in the browser
     network requests and computations               with GeoJSON layers
```

---

## ⚡ Key Infrastructure Components

1. **Multithreading in QGIS (`QgsTask`):**
   * API requests are executed in the background through the `QgsTask` class.
   * The QGIS interface should stay responsive: the user can freely pan the map, zoom and click objects while the tasks are processed in the background.

2. **Integrations with Polish National Registers (`backend/app/ingestion/`):**
   * **ULDK GUGiK (`uldk_connector.py`):** Fetching cadastral parcel geometries in EPSG:2180 based on a TERYT number or a clicked XY point.
   * **IMGW-PIB (`imgw_connector.py`):** Fetching current measurement data from synoptic stations in Poland.
   * **Open Spatial Data Register:** A collection of over 40 official services (WMS, WFS, WCS, STAC) documented in [`docs/polskie_rejestry_publiczne_gis.md`](docs/polskie_rejestry_publiczne_gis.md).

3. **Coordinate System Converters (`shared/constants/poland_crs.py`):**
   * Definitions and transformations between the metric **EPSG:2180** system and the global **EPSG:4326 (WGS84)** and **EPSG:3857 (Web Mercator)**.

4. **Shared Pydantic Schemas (`shared/schemas/geo_models.py`):**
   * `GeoFeatureRequest`, `SpatialMetric`, `GeoAnalysisResponse` as a universal data contract for the API and the plugin.

---

## 🚀 Quick Start

### 1. QGIS Plugin
The plugin has to be installed or linked into the QGIS profile. The scripts `link_plugin.sh` and `link_plugin.bat` are available; check how they work before running them (the shell script removes an existing target in the default profile). Then:
1. Open the test project: **[`sample_project/sample_project.qgs`](sample_project/sample_project.qgs)**.
2. Go to the menu **Plugins $\rightarrow$ Manage and Install Plugins...** $\rightarrow$ the **Installed** tab and tick:  
   ☑️ **`PyQGIS FastAPI Bridge`**.
3. Click the plugin icon on the toolbar to open the side panel.
4. Click **`▶ Run Analysis (FastAPI)`**: the tasks are handed off in the background to the QGIS task manager (`QgsTask`) and the results appear in the panel without making the map stutter.

### 2. FastAPI Backend
After preparing an environment with the backend dependencies (see `backend/requirements.txt`), run from the repository directory:
```bash
python backend/run_backend.py
```
* **API endpoint:** `http://127.0.0.1:8000`
* **Swagger UI documentation:** `http://127.0.0.1:8000/docs`
* **Health Check:** `http://127.0.0.1:8000/health`

### 3. Unit Tests (Automated Testing)
Running the starter's tests (their result in the merged repository has to be verified):
* **Windows (1 click):** Double-click `run_tests.bat`
* **Linux / macOS:** `./run_tests.sh`
* **Standard command:** `python -m unittest discover -s tests -p "test_*.py" -v`
* **GitHub Actions:** The workflow `.github/workflows/test.yml` is configured for pushes and PRs to `master` and `main`; do not assume it checks every push to the team branch.

### 4. Web Viewer
Open this file in a browser:  
👉 **[`web/index.html`](web/index.html)**. It is the starter's demonstration client; how to run it and the data flow in the merged project have to be verified.

---

## 🎨 Editing the Panel in Qt Designer
1. Run **`open_designer.bat`** (starts Qt Designer with the QGIS widgets).
2. View file: `qgis_plugin/pyqgis_fastapi_bridge/gui/dockwidget.ui`.
3. Thanks to dynamic loading (`uic.loadUiType`), interface changes are visible in QGIS right after the plugin is reloaded.

---

## 📜 Licence and Open Data

### 1. Open Source Licence
The project is released under the open **MIT** licence (see the `LICENSE` file). The code may be freely used, modified and developed for commercial and research purposes.

### 2. List of Open Data Sources Used
The project is based on legal, public and open spatial data sources:
* **GUGiK ULDK / PRG / NMT / BDOT10k:** Cadastral services, the national register of boundaries, digital terrain models and topographic object databases.
* **IMGW-PIB:** Public telemetry data, synoptic and hydrological stations.
* **Copernicus Data Space Ecosystem (ESA/EU):** Open Sentinel satellite imagery.
* The full register of 46 services with links to the official WMS/WFS/REST endpoints is in [`docs/polskie_rejestry_publiczne_gis.md`](docs/polskie_rejestry_publiczne_gis.md).
