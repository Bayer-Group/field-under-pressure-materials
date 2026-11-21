# Read contract for the front end and QGIS (PROPOSAL)

Status: **proposal of the database owner**, to be accepted or corrected by the front end (#15) and QGIS (#14, #12) owners in the issues.
**The read endpoints below are implemented** (`backend/app/api/v1/endpoints/farm.py`, under `/api/v1`; interactive documentation at
`/docs`), except the two `POST` writes (#51). Demo logins: `analyst` and `farmer001` … `farmer050`, all with the password `demo`
(`scripts/generate_mock_farmers.py`). Where to reach the API: `docker/VM.md`. The views of schema `serve` (`docker/README.md`,
"Serving layer") are the single source: the API is a thin `SELECT` over them, so the farmer front end and QGIS see the same data and
no business logic lives in the API or in the readers.

## 1. Rules

- **Dates are already shifted for the demo.** A reader sees "today" and never converts a date. Stored data keeps the time of the data
  (2024); `serve.demo_time` decides the shift (pinned day or constant offset). Dates written by a farmer (sowing, spray) are in the
  shown time; the API translates them back before saving. No label about the shift is shown.
- **The class is a statement about conditions**, never an instruction to spray. `conditions_met = true` means class `high`, growth stage
  zone B or C and no protection (`docs/curated_layer_contract.md`, section 3).
- **Isolation.** A farmer sees only own crop areas (the server filters by `owner_id`); the `analyst` role sees all and the grid layer.
- Geometry is GeoJSON, EPSG:4326, `[lon, lat]`. Dates are `YYYY-MM-DD` (local day). Times are ISO 8601 with offset.
- **Colour is the reader's job.** Suggested: `low` green, `medium` amber, `high` red, any `status` other than `ok` grey
  (`protected`, `out_of_window`, `insufficient_data`, `stage_unknown`); `uncertain` is shown as the class with a hatch or an outline.

## 2. Endpoints (PROPOSAL)

| Endpoint | Source | Answer |
| --- | --- | --- |
| `POST /login` `{login, password}` | `app.demo_user` | `{token, owner_id, role}`; the token goes in `Authorization: Bearer` |
| `GET /clock` | `serve.clock` | `{today, mode}` (the shown "today") |
| `GET /me/crop-areas` | `serve.crop_area_today` | FeatureCollection of the farmer's crop areas with today's class |
| `GET /crop-areas/{id}` | `serve.crop_area` | one crop area with soil and crop-map context |
| `GET /crop-areas/{id}/risk?from=&to=` | `serve.risk_daily` | one row per day (the date slider), with `reasons` for the "Why?" screen |
| `GET /crop-areas/{id}/changes` | `serve.risk_change_log` | when and why the class, status or `conditions_met` changed |
| `GET /grid/risk?date=` | `serve.grid_risk_daily` | FeatureCollection of 4 km cells for the whole voivodeship (analyst), default today |
| `POST /crop-areas` | `app.crop_area` | saves a crop area (`geometry`, `farmer_crop_id`, `sowing_date`, optional `bbch_override`), recomputes, returns it with today's class |
| `POST /crop-areas/{id}/sprays` | `app.spray` | `{spray_date, protection_duration_days}`, may be in the past; recomputes, returns the new class |

Writing follows `FARMER_INPUT_CONTRACT.md`. After every write the API calls `refresh()` for that one crop area; the response contains
the new assessment of today and the list of days that changed.

## 3. Shapes (PROPOSAL)

`GET /me/crop-areas` (one feature):

```json
{
  "type": "Feature",
  "geometry": { "type": "Polygon", "coordinates": [[[20.497, 52.597], [20.503, 52.597], [20.503, 52.603], [20.497, 52.597]]] },
  "properties": {
    "crop_area_id": "area-demo-1", "field_name": "Demo field", "farmer_crop_id": "wheat",
    "date": "2026-11-21", "risk_class": "medium", "status": "ok", "conditions_met": false,
    "h_hours": 14, "growth_stage_zone": "B", "protected_until": null
  }
}
```

`GET /crop-areas/{id}/risk` (one day): `date`, `risk_class`, `status`, `conditions_met`, `h_hours`, `h_low`, `h_high`, `coverage`,
`protected_until`, `growth_stage_zone`, `growth_stage_source`, `gdd_since_resumption`, `reasons` (object), `model_version`.
Fields can be `null` (for example `risk_class` when `status` is `out_of_window`); the reader must handle that.

`GET /grid/risk`: features with `grid_id`, `date`, `risk_class`, `uncertain`, `h_low`, `h_high`, `coverage`.

## 4. Open points

- The database driver of the backend is `psycopg` (the one the scripts use), chosen so that the front end and QGIS can test now; it is
  one dependency and can be replaced behind `backend/app/core/db.py` if the team decides otherwise (#21).
- Fix what does not fit: shapes, names, missing fields. The API is easy to change; say so in #48 (front end) or #49 (QGIS).
- Authentication is a demonstration only (login page, hashed passwords, signed token, isolation on the server); a production system
  would use OIDC.
- Paging of `GET /grid/risk` (about 2,400 cells per day is small enough for one answer).
- Whether QGIS needs more layers (soil, weather, crop map): ask in #12; they can become more views.
