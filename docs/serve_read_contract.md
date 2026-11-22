# Read contract for the front end and QGIS (PROPOSAL)

Status: **proposal of the database owner**, to be accepted or corrected by the front end (#15) and QGIS (#14, #12) owners in the issues.
**All endpoints below are implemented** (`backend/app/api/v1/endpoints/farm.py` and `farm_write.py`, under `/api/v1`; interactive
documentation at `/docs`). Base URL of the demo: `https://34-118-11-71.nip.io/api/v1` (HTTPS; the address follows the external IP of
the VM, see `docker/VM.md`). CORS allows any origin and no cookies are used, so a front end on any host (also `http://localhost`) can
call it with the `Authorization: Bearer` header.

**Start here: the sandbox.** `POST /sandbox` `{"mode": "mock" | "empty"}` needs no password and returns a token for 8 hours. `mock`
copies **the next example farm in turn** (the example farms are handed out one after another, so a room gets different farms; the
answer has `template`, the example farm that was copied, and `display_name`): a farm of mostly 3 fields, some of them split into 2 or 3
crop areas, with sprays, parcels (`parcel_ids`) and risk. `empty` starts from scratch. Whatever the visitor saves belongs to that
sandbox and is kept for the 8 hours (keep the token, for example in `localStorage`, and the data is there after a reload);
`DELETE /sandbox` starts over. The copy has short ids (`p1`, `p1a`, `p1b`) and is edited in place by `PUT /fields/{id}`.

**The example farmers** can also be read directly: login `farmer001` ... `farmer100` with the password `demo001` ... `demo100` (the same
word and the number of the login). They are **read-only** (`403` on writes: "start a sandbox"), because the copies for the visitors are
made from them and the passwords are easy to guess. The analyst has a separate password. The views of schema `serve` (`docker/README.md`, "Serving layer") are the single source: the API is a thin `SELECT`
over them, so the farmer front end and QGIS see the same data and no business logic lives in the API or in the readers.

## 1. Rules

- **Dates are already shifted for the demo.** A reader sees "today" and never converts a date. Stored data keeps the time of the data
  (2024); `serve.demo_time` decides the shift (pinned day or constant offset). Dates written by a farmer (sowing, spray) are in the
  shown time; the API translates them back before saving. No label about the shift is shown.
- **The class is a statement about conditions**, never an instruction to spray. `conditions_met = true` means class `high`, growth stage
  zone B or C and no protection (`docs/curated_layer_contract.md`, section 3).
- **Isolation.** A farmer sees only own crop areas (the server filters by `owner_id`); the `analyst` role sees all crop areas. The grid layer and the risk surface are public weather data (nothing of a farmer), so every signed-in user may read them; only `method=smooth` of the surface is for the analyst.
- Geometry is GeoJSON, EPSG:4326, `[lon, lat]`. Dates are `YYYY-MM-DD` (local day). Times are ISO 8601 with offset.
- **Colour is the reader's job.** Suggested: `low` green, `medium` amber, `high` red, any `status` other than `ok` grey
  (`protected`, `out_of_window`, `insufficient_data`, `stage_unknown`); `uncertain` is shown as the class with a hatch or an outline.

## 2. Endpoints (PROPOSAL)

| Endpoint | Source | Answer |
| --- | --- | --- |
| `POST /sandbox` `{mode}` | `app.field` (copy) | `{token, owner_id, role, expires_in, crop_areas}`; no password (see above) |
| `DELETE /sandbox` | `app.field` | deletes everything of the sandbox, 204 |
| `POST /login` `{login, password}` | `app.demo_user` | `{token, owner_id, role}`; development logins only; the token goes in `Authorization: Bearer` |
| `GET /crops` | `curated.crop_mapping` | `{crops: [{id, label}], data_status}` (the shape of `FARMER_INPUT_CONTRACT.md`) |
| `GET /places?q=` | GUGiK UUG + names of the parcels we know | `{places: [{name, label, lon, lat, zoom, source}], data_status: "live"}` for the map search box |
| `GET /parcels?lon=&lat=` or `?number=` | GUGiK ULDK (cached in `app.parcel`) | `{parcels: [{parcel_id, parcel_number, geometry}], data_status: "live"}` |
| `GET /fields`, `GET /fields/{id}` | `app.field`, `app.parcel`, `app.crop_area` | the field model of the front end, see section 5 |
| `POST /fields/validate` | PostGIS | findings of the geometry validation, see section 5 |
| `PUT /fields/{id}` | `app.field`, `app.field_parcel`, `app.crop_area`, `app.spray` | atomic group save, see section 5 |
| `GET /clock` | `serve.clock` | `{today, mode}` (the shown "today") |
| `GET /me/crop-areas` | `serve.crop_area_today` | FeatureCollection of the farmer's crop areas with today's class |
| `GET /crop-areas/{id}` | `serve.crop_area` | one crop area with soil and crop-map context |
| `GET /crop-areas/{id}/risk?from=&to=` | `serve.risk_daily` | one row per day (the date slider), with `reasons` for the "Why?" screen |
| `GET /crop-areas/{id}/changes` | `serve.risk_change_log` | when and why the class, status or `conditions_met` changed |
| `GET /grid/risk?date=` | `serve.grid_risk_daily` | FeatureCollection of the grid cells (rectangles of 0.044°, about 3.0 x 4.9 km, tiling the plane) for the whole voivodeship (any signed-in user), default today |
| `GET /grid/risk/surface?date=&format=json\|png\|asc&value=index\|hours&method=&resolution=&sigma_km=` | `serve.grid_risk_daily` | the cells as a continuous surface (a heatmap, any signed-in user), see section 3 |
| `POST /crop-areas` | `app.crop_area` | saves a crop area (`geometry`, `farmer_crop_id`, `sowing_date`, optional `bbch_override`), recomputes, returns it with today's class |
| `POST /crop-areas/{id}/sprays` | `app.spray` | `{spray_date, protection_duration_days}`, may be in the past; recomputes, returns `{spray, crop_area, changed_days}` (the spray has its `spray_id`) |
| `GET /crop-areas/{id}/sprays` | `app.spray` | `{crop_area_id, sprays_confirmed, sprays: [{spray_id, date, protection_duration_days}]}` |
| `PATCH /crop-areas/{id}/sprays/{spray_id}` | `app.spray` | changes `date` and/or `protection_duration_days`; recomputes; returns `{spray, past_sprays, crop_area, changed_days}` |
| `DELETE /crop-areas/{id}/sprays/{spray_id}` | `app.spray` | deletes one spray; recomputes; 200 with `{spray: null, past_sprays, crop_area, changed_days}` |
| `PATCH /crop-areas/{id}` | `app.crop_area` | changes `sowing_date`, `farmer_crop_id`, `bbch_override` (null clears it) and sets `sprays_confirmed`; returns the crop area as an element of `crop_areas` |
| `DELETE /crop-areas/{id}` | `app.field` | deletes a crop area, 204 |

Writing follows `FARMER_INPUT_CONTRACT.md`. After every write the API recomputes that one crop area (a new area in about 0.2 s; a
spray only the assessment); the response is the crop area as a Feature with today's class (`POST /crop-areas`) or `{crop_area,
changed_days}` (a spray). Dates are in the shown time and cannot be in the future. Limits of the demo: at most 10 crop areas per
sandbox, 150 ha per crop area, a valid polygon of at most 500 points, only around the weather data (Mazowieckie; otherwise 422),
`farmer_crop_id` from `GET /crops`. Answers: 401 (no or bad token), 404 (also somebody else's crop area), 422 (validation, with a
`detail` text), 429 (too many requests), 503 (busy or read-only; `DEMO_READONLY` makes the whole demo read-only).

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

`GET /grid/risk`: features with `grid_id`, `date`, `risk_class`, `uncertain`, `h_low`, `h_high`, `coverage`, `risk_index`,
`index_low`, `index_high`.

**`risk_index` (PROPOSAL, #49).** H on a continuous 0-1 scale aligned with the classes (`septoria.risk_index`, thresholds from
`config/septoria.toml`): 0 at 0 h, 0.5 at the medium threshold, 1 at the high threshold and above, linear in between. So `< 0.5`
is `low`, `0.5` to `< 1` is `medium`, `1` is `high`, the same as `risk_class`; it adds no rule, it keeps what the three classes
round away. `index_low` / `index_high` come from `h_low` / `h_high` (missing hours counted dry / wet). NULL wherever `risk_class`
is NULL (e.g. `out_of_window`). Added to `GET /me/crop-areas` (`risk_index`), `GET /crop-areas/{id}/risk` (all three) and
`GET /grid/risk` (all three).

**`GET /grid/risk/surface` (#49).** A heatmap of the voivodeship for one day (any signed-in user), the cells shown as a continuous surface
(`backend/app/services/risk_surface.py`, standard library only). It is built from the **hours** `h_low` of the cells, and the
`risk_index` is applied to each pixel afterwards. (Building it from the index lost the peaks: the index is capped at 20 h, so
averaging it lowered every value next to a peak, and the first version showed no pixel of class high while 13 % of the cells were
high on the check day.)

| Parameter | Values | Meaning |
| --- | --- | --- |
| `date` | a date | the shown day, default today |
| `format` | `json` (default), `png`, `asc` | `json`: the grid; `png`: an RGBA image on the fixed ramp (green 0, amber 0.5, red 1), the bounds in the header `X-Bounds` (`west,south,east,north`), for an image source in MapLibre; `asc`: an ESRI ASCII Grid (QGIS opens it directly, choose EPSG:4326) |
| `value` | `index` (default), `hours` | what `json` and `asc` carry; `png` is always the index. `hours` shows how far above the threshold the cells are (the index stops at 20 h) |
| `method` | `interpolate` (default), `smooth` | `interpolate`: bilinear on the regular lattice of the weather grid, exact at the cell centres (mean error 0.09 h, 33 / 55 / 12 % of low / medium / high pixels against 31 / 55 / 13 % of the cells); `smooth`: Gaussian mean (mean error 0.9 h, blurs the peaks), the fallback when the cells are not a lattice |
| `resolution` | 0.01 to 0.1 degrees, default 0.02 | pixel size; `smooth` needs 0.02 or more |
| `sigma_km` | 1 to 10, default 5 | smoothing radius of `method=smooth` |

`json`: `{date, crs, bounds: [west, south, east, north], resolution_deg, width, height, method, value, values: [[...]] (row 0 is the
north, null outside the data), max_distance_km, class_thresholds, index_scale, class_note, model_version}`. Pixels farther than 4 km
from every cell centre are empty. A day computed once is kept in memory (the default surface takes about 0.3 s the first time).
`method=smooth` costs seconds of CPU, so only one runs at a time per process (another one gets 503 at once; `interpolate` is instant and
more accurate); about 90 grid or surface requests per minute per user in total (429; the limit is 30 a minute in each of the 3 worker
processes). Measured on the VM: a user asking for the surface every second does not change the p95 of 100 people on the
platform (0.42 s, as without it); eight parallel clients hammering it do (the limit exists for that).

**How to mark the classes on it.** The classes belong to the cells (`GET /grid/risk`, `septoria.classify`); a pixel is a continuous
estimate between two cell centres, not a cell. `class_thresholds` gives the landmarks: `{hours: {medium: 10, high: 20}, index:
{medium: 0.5, high: 1.0}}` (from `config/septoria.toml`). In QGIS colour the raster by value with the stops at the thresholds
(green below, amber at the medium one, red at the high one), draw the contour lines at them if the classes must be marked, and put
the cell layer with its three classes over it for the decisions. The surface is a view for the analyst; `conditions_met` and every
decision stay with the cells and the fields. Legend: "hours of continuous leaf wetness in the last 72 h".

## 4. Open points

- The database driver of the backend is `psycopg` (the one the scripts use), chosen so that the front end and QGIS can test now; it is
  one dependency and can be replaced behind `backend/app/core/db.py` if the team decides otherwise (#21).
- Fix what does not fit: shapes, names, missing fields. The API is easy to change; say so in #48 (front end) or #49 (QGIS).
- Authentication is a demonstration only (sandbox token signed with HMAC, scrypt hashed development logins, isolation on the server);
  a production system would use OIDC.
- Paging of `GET /grid/risk` (about 2,400 cells per day is small enough for one answer).
- Whether QGIS needs more layers (soil, weather, crop map): ask in #12; they can become more views.

## 5. Parcels, fields and geometry validation (the farmer front end)

Implements `FARMER_INPUT_CONTRACT.md` and `GEOMETRY_VALIDATION_CONTRACT.md` (the front end's own files; the second one is in PR #24).
Everything needs the sandbox token. Dates are in the shown time (`GET /clock`: "today"), never fixed dates of 2024.

**Parcels.** `GET /parcels?lon=&lat=` is the parcel under a click, `GET /parcels?number=` an identifier (for example
`142009_2.0016.31`) or a number; several matches are possible. A parcel comes from GUGiK ULDK and is cached, so the second request
for the same place is fast and an outage of GUGiK does not matter for parcels already seen (502 only when the service is needed and
does not answer). The `parcel_id` is the identifier of the cadastre. Mock parcels such as `parcel-demo-1` do not exist here.
Each parcel also has the names of its place from GUGiK: `region` (the cadastral precinct: a village, or a number in a town),
`commune`, `county`, `voivodeship` and a ready `location` for display ("Krępica, gm. Płońsk"; "Warszawa"; "Śródmieście 2, Radom").
The same fields are in the `parcels` of `GET /fields`.

**Search box.** `GET /places?q=<text>` (at least 2 characters) returns places of Mazowieckie with the position to fly to:
`{name, label, lon, lat, zoom, source}`; `zoom` is 16, the zoom from which the parcel boundaries (the WMS below) are visible, so flying
there shows the parcels at once. Two sources: the geocoder of GUGiK (whole names only, from 3 characters; towns with the rights of a
county first, then the villages of the same name) and the names of the parcels we know (prefix matching, so it can suggest while the
user types; villages only). Same-named places are told apart by `label` ("Ostrołęka", "Ostrołęka, gm. Warka, pow. grójecki"). No match is
an empty list. Answers are cached for a day and limited to 120 per minute per owner; send the request after a pause in typing (about 250 ms).

**Parcel boundaries on the map (GUGiK WMS, no backend needed).** GUGiK publishes the parcels as a map service only (there is no WFS and
no bulk download of vector parcels): the layers `dzialki` (boundaries), `numery_dzialek` (numbers), `uzytki` (land-use contours),
`kontury`, `obreby`, `budynki` of `https://integracja.gugik.gov.pl/cgi-bin/KrajowaIntegracjaEwidencjiGruntow`, WMS 1.3.0, EPSG:3857, PNG,
CORS open. It draws **thin outlines without fill, and only at scale 1:5000 or larger** (street level, about zoom 16 and up); from afar the
image is empty. Template for MapLibre (raster source, `tileSize` 256, `minzoom` about 16):
`https://integracja.gugik.gov.pl/cgi-bin/KrajowaIntegracjaEwidencjiGruntow?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap&LAYERS=dzialki,numery_dzialek&STYLES=&CRS=EPSG:3857&BBOX={bbox-epsg-3857}&WIDTH=256&HEIGHT=256&FORMAT=image/png&TRANSPARENT=TRUE`.
The land use (`Oznaczenie użytku`, `Oznaczenie konturu`) can only be read for one point (`GetFeatureInfo`), it cannot filter the layer, so
"agricultural or not" is not something this service can draw.

**Field model.** `GET /fields` returns `{fields: [field], data_status: "mock"}`; `GET /fields/{id}` one field:

```json
{
  "field_id": "field-demo-1", "name": "My field",
  "parcel": {"parcel_id": "142009_2.0016.31", "parcel_number": "31", "geometry": {}},
  "parcel_ids": ["142009_2.0016.31", "142009_2.0016.32"],
  "parcels": [{"parcel_id": "142009_2.0016.31", "parcel_number": "31", "geometry": {}}],
  "crop_areas": [{
    "crop_area_id": "area-demo-1", "geometry": {},
    "crop": {"farmer_crop_id": "wheat", "map_crop_id": "wheat"},
    "sowing_date": "2026-10-10",
    "past_sprays": [{"date": "2026-11-10", "protection_duration_days": 14}],
    "area_ha": 1.27,
    "risk": {"date": "2026-11-21", "risk_class": "medium", "status": "ok", "conditions_met": false, "h_hours": 14,
             "growth_stage_zone": "B", "protected_until": null}
  }]
}
```

`parcel` is the first parcel (the earlier one-parcel shape); `parcels` and `parcel_ids` carry the whole group. `map_crop_id` is what
the crop map says (computed by the server, ignored when sent); `farmer_crop_id` stays separate. `past_sprays` is `[]` for a confirmed
"no sprays" and `null` when the question was not answered. `risk` is today's assessment (extra to the contract, to save a request).

**Ids.** The ids chosen by the client (`field_id`, `crop_area_id`) are kept per owner: two visitors may both use `field-demo-1`.
An id is 1 to 80 characters of letters, digits and `_ . : -`.

**Validation.** `POST /fields/validate` with `{parcel_ids, crop_areas: [{crop_area_id, geometry}]}` answers as the validation
contract: `validation_id`, `crop_areas` (the proposed repaired and clipped geometry and `repair`), `overlaps`, `gaps`, `outside`,
`errors`, `data_status: "live"`. The server uses its own parcel geometries and validates against the union of the selected parcels.
A repair is silent only when the boundary moved at most 0.25 m, the area changed at most 0.5 % and no part disappeared; otherwise
`requires_review` is true (also when the measurement is impossible, then the numbers are `null`). Findings thinner than 5 cm are
treated as noise. Overlaps block saving; every gap, every clipped outside part and every repair needing review needs a confirmation.
Error codes: `unknown_parcel`, `parcel_service_unavailable`, `invalid_geometry`, `unrepairable_geometry`, `empty_area`.
The ids of the findings are derived from the geometry, so they are stable. `validation_id` is valid for an hour and for exactly this
selection and geometry.

**Group save.** `PUT /fields/{id}` with `{field_id, name?, parcel_ids (or parcel: {parcel_id}), validation_id, confirmations,
crop_areas: [{crop_area_id, geometry, crop: {farmer_crop_id}, sowing_date, past_sprays}]}`; `confirmations` are strings
`gap:<gap_id>`, `outside:<outside_id>`, `repair:<repair_id>`. One transaction: the server validates again, checks the validation id
and the confirmations, stores the approved geometry (repaired and clipped) as one crop area with the same id (no splitting per
parcel is needed), links the field to all its parcels, replaces the crop areas and sprays and recomputes the risk. The answer is the
saved field (as in `GET`). Answers: 422 (spray question unanswered, missing confirmations with the list `missing`, overlaps,
errors, validation rules of section 2), 409 (stale `validation_id`: validate again), 404 and 401 as before. The earlier one-parcel
shape (`parcel` instead of `parcel_ids`) works too; the validation id is required in both.

**Editing one crop area and its sprays (no full-field save).** Every `/crop-areas/{id}/...` endpoint accepts **the id of `GET /fields`** (the
id the client chose) as well as the stored one, and is limited to the owner (404 for somebody else's). The sprays of `GET /fields`
(`past_sprays`) have a `spray_id`; `PUT /fields/{id}` keeps the ids of the sprays it is given (a spray without `spray_id` is new, one
that is missing is deleted). `PATCH /crop-areas/{id}` sends only what changes: `sowing_date` (not in the future, in the shown time),
`farmer_crop_id` (see `GET /crops`), `bbch_override` (31, 37, 39, 51 or 59; `null` clears it, the risk then uses the estimated stage) and
`sprays_confirmed: true` (the answer "no sprays" or "the list is complete"; `false` is refused). Body errors are 422, before anything is
looked up. The spray endpoints answer the whole list of sprays, so after a lost connection the client reads the state back (the list)
instead of sending the spray again.

**The geometry of a saved crop area.** A crop area is clipped to its parcels only when something sticks out of them (the part outside
needs the confirmation `outside:<id>`); otherwise the repaired geometry is stored as it is, so saving the same area again does not change
it (a crop area equal to a parcel used to gain vertices with every save). After a clipping the geometry follows the parcel boundary and
the next saves leave it unchanged.
