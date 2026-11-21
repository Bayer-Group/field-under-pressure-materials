# Live sandbox integration and contract gaps

This is a comparison made on 2026-11-21 against the deployed OpenAPI document at
`https://34-118-11-71.nip.io/api/v1/openapi.json` and the farmer-input and geometry
contracts in this branch. Backend PR #52 is merged and the live API is responding.

## Implemented in the frontend

- The startup screen offers Farmer view and New view. New view opens parcel selection
  directly in its own backend sandbox, creating an empty one if needed and reusing
  its session after reload. Farmer
  view has a separate session. The bearer tokens stay in this browser's localStorage.
  A network failure does not erase the token; after expiry the user can explicitly
  start a new sandbox.
- `GET /me/crop-areas` supplies the selectable crop-area layer, not cadastral parcels.
  Colors use `risk_class` when `status` is `ok` and gray otherwise. The crop labels
  come from the live `GET /crops` array (`farmer_crop_id`, `label`).
- Selecting an area loads `GET /crop-areas/{id}`. The date slider requests the selected
  day from `GET /crop-areas/{id}/risk`; it uses the API's `/clock` date without applying
  the historical time shift again.
- **Select parcels** opens the existing farmer editor with the sandbox's backend
  adapter. It calls `GET /parcels`, `GET /fields`, `POST /fields/validate` and
  `PUT /fields/{id}` with the sandbox bearer token. The field ID is retained for later
  updates; grouped areas retain their common IDs. Backend validation and confirmations
  remain mandatory. The local design preview remains separate and uses its local mock.
- The adapter normalizes both observed crop-catalog formats: the earlier array with
  `farmer_crop_id` and the current `{crops: [{id, label}]}` envelope. A validation,
  save and retrieval round trip was exercised in a disposable backend sandbox.

## Remaining gaps and constraints

1. Existing seeded crop areas may have empty `parcel_ids` and `parcels` in `GET /fields`.
   They can be inspected in the sandbox view, but cannot yet be reconstructed as
   selected cadastral parcels in the editor. Never equate crop areas with legal parcels.
2. The deployed parcel response observed for point lookup has `parcel_id`,
   `parcel_number` and geometry but does not include locality, municipality or area.
   Search accepts a number or coordinates, but a dedicated locality autocomplete was
   not observed. The frontend shows only available values and uses the cadastral ID.
3. No crop-map-suggestion or file-import endpoint appears in the deployed OpenAPI. The
   editor starts without a proposed crop where no data is available; file import remains
   unavailable in backend mode. Multipart geometries can be shown but not vertex-edited.
4. Current OpenAPI limits one validation/save request to **20 parcels and 20 crop
   areas**. This differs from the requested unlimited parcel selection. The field spray
   schema requires protection duration from 1 to 60 whole days; the editor does not
   silently choose a default. Backend PR #52 also describes Mazowieckie coverage and
   area/vertex limits for the individual crop-area API; confirm how those apply to the
   grouped field endpoint.
5. Field response and error schemas in OpenAPI are currently generic. Validate the full
   backend behavior for overlap, outside geometry, confirmation IDs, stale validations,
   automatic repair, multipart geometry and owner isolation with #53 and #54. The
   successful round trip alone does not establish that all cases are implemented.
6. `GET /me/crop-areas` remains a crop-area risk view; it does not by itself supply
   the parcel association needed for the parcel editor. Historical dates from the API
   are already in displayed time and must not be shifted a second time.

The demo data is time-shifted by the backend. The client displays API dates as supplied,
without a second shift. Sandbox tokens and crop data must never be printed in logs or
checked into Git. Sandbox expiry and browser storage loss can make that session
inaccessible; no account recovery mechanism has been established.

## Parcel map and metadata handoff

The parcel-selection map needs a backend-served cadastral boundary layer for the current
viewport at an appropriate zoom. The live `/parcels` operation is a lookup by point or
search term; it cannot be used as a complete viewport layer. The backend team should
provide a documented map layer (for example, a tiled WMS/vector-tile proxy or a bounded
viewport response), its URL, zoom/scale limits, CRS, attribution, error behavior and
coverage. The frontend should not call GUGiK directly. At nationwide zoom, show a zoom-in
hint rather than suggest that invisible parcel lines do not exist.

For each returned parcel in point lookup, search and stored parcel associations, the
existing selection UI expects:

```json
{
  "parcel_id": "141201_1.0001.123/4",
  "cadastral_id": "141201_1.0001.123/4",
  "parcel_number": "123/4",
  "locality": "Krzewie",
  "commune": "Wolsztyn",
  "area_ha": 2.35,
  "geometry": { "type": "Polygon", "coordinates": [[[20.75, 52.17], [20.76, 52.17], [20.76, 52.18], [20.75, 52.18], [20.75, 52.17]]] }
}
```

This is a fictional schema example, not a real cadastral record. `parcel_id` is the
stable GUGiK identifier used to validate and save; `cadastral_id` can carry the same
value. Geometry is GeoJSON longitude/latitude (EPSG:4326); `area_ha` is a number in
hectares from an authoritative source or an agreed backend calculation. Unknown
locality, municipality or area must be `null`, not invented or zero. For the original
two-step search, the backend also needs locality-prefix suggestions that distinguish
identically named localities by municipality and a locality-plus-parcel-number lookup.
The current backend lookup returns the identifier, parcel number and geometry, but the
remaining metadata has not been observed in its response.
