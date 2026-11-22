# Architecture

## Data flow

```text
 organizer files (parquet, GeoTIFF)          farmer (web map / QGIS)
              │ scripts/load_db.py                     │ POST / PUT / PATCH
              ▼                                        ▼
   ┌────────────────────┐                    ┌──────────────────┐
   │ raw.*              │                    │ app.*            │
   │ weather, grid,     │                    │ fields, crop     │
   │ soil, crop map     │                    │ areas, sprays    │
   └─────────┬──────────┘                    └────────┬─────────┘
             │ scripts/build_curated.py               │ recomputed by the API after every write
             ▼                                        ▼
   ┌────────────────────────────────────────────────────────────┐
   │ curated.*   weather features, septoria assessment per      │
   │             crop area and day, change log, field context   │
   └─────────────────────────────┬──────────────────────────────┘
                                 │ views, dates shifted for the demo
                                 ▼
   ┌────────────────────────────────────────────────────────────┐
   │ serve.*     the only schema the API reads                  │
   └─────────────────────────────┬──────────────────────────────┘
                                 │ FastAPI  /api/v1  (GeoJSON)
                  ┌──────────────┴──────────────┐
                  ▼                             ▼
        web map (MapLibre GL JS)       QGIS plugin (PyQGIS, QgsTask)
        served from Cloud Run
```

All data lives in one PostGIS database with four schemas:

| Schema | Contents | Written by |
| --- | --- | --- |
| `raw` | organizer data as loaded: 4 km weather grid, hourly and daily weather, IMERG precipitation, soil (H3), CLMS crop map | `scripts/load_db.py` (inserts rows only) |
| `app` | farmer input: fields, crop areas, sowing dates, sprays, accounts and sandboxes | the API |
| `curated` | derived data: weather features (wet hours, degree days), septoria assessment per crop area and day, its change log, soil and crop-map context of each crop area | `scripts/build_curated.py` and the API |
| `serve` | read-only views for the API, the web map and QGIS | migrations |

The tables are described in
[`docker/README.md`](https://github.com/geoearth-junction/field-under-pressure-materials/blob/team/geoearth-junction/docker/README.md);
the derived layer is specified in the [curated layer contract](curated_layer_contract.md) and the API in the
[read contract](serve_read_contract.md).

## The demo clock

The weather data is from 2024. Stored data keeps its own dates; the `serve` views add one shift (`serve.shift_days()`, set in
`serve.demo_time`) so that a reader sees "today". In the default `pinned` mode today always shows the same data day, which keeps
the demo stable. The API translates dates written by a farmer back to data time. Everything that answers "what is today"
(`GET /clock`, the crop-area layer, the spray window) uses this one clock from the database.

## Rules live in configuration

The domain logic is written as pure functions with no database access, and its thresholds are read from TOML files:

| Model | Rules (pure functions) | Thresholds | Tests |
| --- | --- | --- | --- |
| Septoria risk | `backend/app/domain/septoria.py` | `config/septoria.toml` | `tests/test_septoria_domain.py` |
| Spray window | `backend/app/domain/spray_window.py` | `config/spray_window.toml` | `tests/test_spray_window_domain.py`, `tests/test_spray_window_service.py` |

Every threshold records its origin (literature, regulation or team assumption) in the TOML file; the spray window API also
returns that origin with its limits (`notes.origin`). See [Risk models](risk-models.md).

## Repository layout

| Path | Contents |
| --- | --- |
| `backend/` | FastAPI application: endpoints (`app/api/v1/endpoints`), services that read the database (`app/services`), domain rules (`app/domain`), connectors to GUGiK ULDK and IMGW (`app/ingestion`) |
| `web/` | the farmer's web map: one static page (`index.html`) with MapLibre GL JS and a small API client (`sandbox-client.js`) |
| `qgis_plugin/` | the PyQGIS plugin for analysts |
| `shared/` | Pydantic schemas and CRS constants shared by the backend and the plugin |
| `config/` | rules and thresholds (TOML) |
| `docker/` | database schema (`initdb/`), migrations (`migrations/`), Docker Compose for PostGIS, the backend and Caddy, VM notes |
| `scripts/` | data download, loading and curation, VM provisioning, plugin packaging and linking, test runners |
| `tests/` | unit tests (`unittest`, no database and no network) |
| `docs/` | this documentation and the contracts |
| `sample_project/` | a QGIS test project and mock responses |
| `bayer/` | the organizer's original hackathon materials, unchanged (dataset descriptions, crop-protection methodologies, starter notebook) |
| `data/` | local data downloads; ignored by git |

Each module has an `AGENTS.md` with its scope and working rules, and the repository-wide rules are in `AGENTS.md` and
`CONTRIBUTING.md` at the root.
