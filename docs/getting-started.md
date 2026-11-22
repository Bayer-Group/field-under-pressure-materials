# Getting started

How to run the parts of the project on your own computer. All commands run from the repository root unless stated otherwise.

## Requirements

| What | Version | Needed for |
| --- | --- | --- |
| Python | 3.10 or newer | backend, scripts, tests |
| Backend packages | [`backend/requirements.txt`](https://github.com/geoearth-junction/field-under-pressure-materials/blob/team/geoearth-junction/backend/requirements.txt) (FastAPI, uvicorn, pydantic, psycopg) | backend and its tests |
| Google Cloud CLI (`gcloud`) | any recent | the SSH tunnel to the database on the VM |
| QGIS | 3.x | the QGIS plugin |
| A web browser | any recent | the web map |

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r backend/requirements.txt
```

The root `requirements.txt` lists the packages of the data scripts and the organizer notebook (parquet, rasters, Sentinel-2).

## 1. The web map (no installation)

The web map is static HTML and JavaScript in `web/`; there is no build step.

```bash
cd web
python -m http.server 5500
```

Open <http://localhost:5500> and choose **Explore an example farm**. By default the page talks to the deployed demo API
(`BASE_URL` in `web/sandbox-client.js`), so it works without a local backend. MapLibre GL JS and Turf.js are loaded from a CDN,
so the page needs internet access.

## 2. The backend (FastAPI)

The backend reads the PostGIS database on the project VM. The database port is closed to the internet, so open an SSH tunnel
first (see [Deployment](deployment.md) for access to the VM):

```bash
gcloud compute ssh fup-vm --zone europe-central2-a --project geo-earth-junction -- -N -L 5433:localhost:5432
```

Leave that terminal open (it prints nothing). In a second terminal:

```bash
export DATABASE_URL="postgresql://gis_user:<password>@localhost:5433/spatial_db"   # PowerShell: $env:DATABASE_URL = "..."
python -m uvicorn backend.app.main:app --reload --port 8000
```

The password comes from the owner of the VM; it is not in the repository. Then:

- interactive API documentation: <http://localhost:8000/docs>
- health check: <http://localhost:8000/health>

Without `DATABASE_URL` the server starts, but every endpoint that reads data answers `503`. Optional settings
(`AUTH_SECRET`, sandbox limits, `DEMO_READONLY`) are read from the environment in `backend/app/core/config.py`.

To point the web map at your local backend, create a client in the browser console:

```js
const local = SandboxClient.create({ baseUrl: 'http://localhost:8000/api/v1', storageKey: 'local-test' });
await local.start('mock');
await local.sprayWindows();
```

## 3. Tests

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

or `scripts/run_tests.sh` (Linux, macOS) and `scripts/run_tests.bat` (Windows). The tests need no database and no network:
external services and the database are replaced by stubs. A few API tests use the FastAPI test client and need its HTTP
dependency installed; without it they report an import error. CI runs the same command (`.github/workflows/test.yml`).

## 4. The QGIS plugin

The plugin is in `qgis_plugin/pyqgis_fastapi_bridge`. Link it into your QGIS profile instead of copying it:

| System | Command |
| --- | --- |
| any | `python scripts/deploy.py` |
| Windows | `scripts\link_plugin.bat` (a directory junction) |
| Linux, macOS | `scripts/link_plugin.sh` (a symlink; it removes an existing plugin folder of the same name first) |

Then in QGIS: **Plugins → Manage and Install Plugins → Installed**, tick **PyQGIS FastAPI Bridge** and open its panel from the
toolbar. Requests run in the background (`QgsTask`), so the map stays responsive. A test project is in
`sample_project/sample_project.qgs`.

To build an installable ZIP: `python scripts/package_plugin.py` (the release workflow does the same for tags).

### Editing the panel

The panel is `qgis_plugin/pyqgis_fastapi_bridge/gui/dockwidget.ui`. On Windows, `scripts/open_designer.bat` opens it in Qt
Designer with the QGIS widgets (it expects QGIS 3.44.6 in the default path). The plugin loads the `.ui` file at run time, so a
change shows after the plugin is reloaded.

## 5. Data scripts

Downloading and loading the organizer data into PostGIS is described in
[`docker/README.md`](https://github.com/geoearth-junction/field-under-pressure-materials/blob/team/geoearth-junction/docker/README.md)
and in the [data pipeline notes](DATA_PIPELINE_NOTES.md). The data files themselves are not committed (`data/` is ignored
except for documentation).
