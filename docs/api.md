# API

The FastAPI backend serves everything under `/api/v1`, mostly as GeoJSON with WGS 84 coordinates (EPSG:4326). A running server
documents itself at `/docs` (Swagger UI) and `/api/v1/openapi.json`. The full specification, with shapes and error codes, is the
[read contract](serve_read_contract.md); this page is an overview.

## Authentication

Every data endpoint needs a bearer token: `Authorization: Bearer <token>`.

- **Sandbox (for visitors).** `POST /api/v1/sandbox` with `{"mode": "mock"}` (a copy of an example farm) or `{"mode": "empty"}`
  returns a token valid for 8 hours, with no password. Everything a visitor saves stays in their own sandbox.
- **Accounts.** `POST /api/v1/login` with a login and a password, or `POST /api/v1/register` to add one. This is a demonstration
  mock (signed tokens, hashed passwords, isolation on the server), not production authentication.

A farmer sees only their own crop areas; the analyst role sees all of them. Errors: `401` no or bad token, `404` also for
somebody else's crop area, `422` validation, `429` too many requests, `503` database busy, not configured or read-only.

## Endpoints

### Session and catalogues

| Method | Path | Returns |
| --- | --- | --- |
| POST | `/sandbox` | a sandbox token; `DELETE /sandbox` clears the sandbox |
| POST | `/login`, `/register` | a token for an account |
| GET | `/me` | who is logged in and whether they can write |
| GET | `/clock` | the demo "today" |
| GET | `/crops` | the crops a farmer can choose |
| GET | `/places?q=` | towns and villages for the map search |
| GET | `/parcels?number=` or `?lon=&lat=` | cadastral parcels from GUGiK ULDK |

### Fields and crop areas

| Method | Path | Returns |
| --- | --- | --- |
| GET | `/fields`, `/fields/{field_id}` | the farmer's fields with parcels, crop areas and today's risk |
| POST | `/fields/validate` | validation of drawn crop areas against the selected parcels |
| PUT | `/fields/{field_id}` | saves a field with its crop areas in one transaction |
| POST | `/crop-areas` | saves one crop area and computes its risk |
| PATCH, DELETE | `/crop-areas/{id}` | edits (sowing date, crop, growth stage) or deletes a crop area |
| GET, POST | `/crop-areas/{id}/sprays` | lists or records sprays; `PATCH` and `DELETE` on `/sprays/{spray_id}` |

Every write recomputes the risk of the crop area it touches.

### Risk

| Method | Path | Returns |
| --- | --- | --- |
| GET | `/me/crop-areas` | the farmer's crop areas with today's class (the map layer) |
| GET | `/crop-areas/{id}` | one crop area with soil and crop-map context |
| GET | `/crop-areas/{id}/risk?from=&to=` | the assessment per day (the date slider) |
| GET | `/crop-areas/{id}/changes` | when and why the class, status or signal changed |
| GET | `/grid/risk?date=` | the grid cells of the voivodeship with their class for one day |
| GET | `/grid/risk/surface?date=&format=` | the same as a continuous surface (heatmap) in JSON, PNG or ASCII grid |

### Spray window

| Method | Path | Returns |
| --- | --- | --- |
| GET | `/me/spray-window` | every crop area with its spray window status and best window (a GeoJSON layer) |
| GET | `/crop-areas/{id}/spray-window` | the signal, up to three ranked windows in the next 72 hours and the check of every hour |

Both accept `at` (local time to assess, default now), `work_from` and `work_to` (the farmer's working hours). Every answer
carries `notes`: the disclaimer, the data source (`replay`), the limits and their origin. The rules are in
[Risk models](risk-models.md#spray-window).

### Starter endpoints

`GET /cadastre/uldk/{teryt_id}`, `GET /cadastre/uldk/by-xy/{x}/{y}` and `GET /analysis/{feature_id}` come from the bridge the
project started from, and `GET /health` reports the server status.

## Clients

- **Web:** `web/sandbox-client.js` wraps the endpoints (`areas()`, `risk()`, `gridRisk()`, `sprayWindows()`, `sprayWindow()`, the
  writes) with error messages for the user.
- **QGIS:** `qgis_plugin/pyqgis_fastapi_bridge/core/serve_api.py` reads the same endpoints in background tasks.
