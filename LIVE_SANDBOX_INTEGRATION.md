# Live sandbox integration and contract gaps

This is a comparison made on 2026-11-21 between the live OpenAPI document at
`https://34-118-11-71.nip.io/api/v1/openapi.json`, the contract in backend PR #52,
and the farmer-input and geometry contracts in this branch. The deployed API is
available. At the time of checking, GitHub reported PR #52 as open; the copy of
`docs/serve_read_contract.md` on the default branch was older than the deployed API.

## Implemented in the frontend

- The startup screen starts a `mock` or `empty` backend sandbox, or resumes a saved
  session. The bearer token is stored in this browser's localStorage and used on
  authenticated requests. Creating a replacement farm warns that the old token will
  no longer be held by this browser. A failed request does not erase the token.
- `GET /me/crop-areas` supplies the selectable crop-area layer, not cadastral parcels.
  Colors use `risk_class` when `status` is `ok` and gray otherwise. The crop labels
  come from the live `GET /crops` array (`farmer_crop_id`, `label`).
- Selecting an area loads `GET /crop-areas/{id}`. The date slider requests the selected
  day from `GET /crop-areas/{id}/risk`; it uses the API's `/clock` date without applying
  the historical time shift again.
- `web/sandbox-client.js` also exposes the documented change-history and write calls,
  but the farmer editor is **not connected** to those writes. Selecting the local parcel
  design preview uses the previous local mock and is clearly separate from the sandbox.

## Gaps requiring coordination

1. `GET /me/crop-areas` returns crop areas, not the selected GUGiK parcel IDs,
   parcel numbers, parcel boundaries, or a parcel group. The API has ULDK cadastre
   routes, but does not expose the frontend's agreed search/autocomplete and parcel
   association contract. Do not treat crop-area polygons as owned cadastral parcels.
2. The live write accepts one `geometry`, `farmer_crop_id`, and `sowing_date` per
   `POST /crop-areas`, then individual `POST /crop-areas/{id}/sprays` requests with
   `spray_date` and `protection_duration_days`. It has no documented atomic group save,
   selected parcel list, grouped read, update operation, or explicit no-spray assertion.
   Separate requests cannot safely implement the agreed all-or-nothing form. The crop
   detail response observed on the VM did not include a list of previous sprays.
3. The live OpenAPI does not document the agreed geometry-validation request/response,
   gap/overlap/outside findings, validation IDs and confirmation tokens, or geometry
   import. The local Turf preview is not a substitute for backend validation. The API's
   own shape/size validation does not establish the parcel-union rules in
   `GEOMETRY_VALIDATION_CONTRACT.md`.
4. The live crop list is a bare array with `farmer_crop_id`; the older frontend mock
   returns `{crops: [{id, label}], data_status}`. Existing feature and detail responses
   use GeoJSON properties instead of the older `field` shape. Agree an adapter or a
   shared executable schema; do not assume these shapes are interchangeable.
5. PR #52 describes demo limits: 10 crop areas per sandbox, 150 ha per area, at most
   500 vertices and Mazowieckie weather coverage. Live OpenAPI limits spray protection to
   1–60 days and gives it a default of 10, while the farmer-input flow requires the user
   to enter a whole number of days. These constraints and the maximum need agreement;
   do not silently default a farmer's duration. The API also disallows future sowing
   and spray dates according to the PR contract.
6. OpenAPI lists empty generic response schemas for several endpoints; versioned, typed
   response/error examples for sandbox, crops, crop areas, risk, changes and writes would
   make client integration verifiable. Align this contract with #53, #54, #39 and #51.

The demo data is time-shifted by the backend. The client displays API dates as supplied,
without a second shift. Sandbox tokens and crop data must never be printed in logs or
checked into Git. Sandbox expiry and browser storage loss can make that session
inaccessible; no account recovery mechanism has been established.
