# Farmer data provider

For the team workflow and backend integration checklist, see [Mock API guide](../MOCK_API_GUIDE.md). For the deployed sandbox and its differences from this mock, see [Live sandbox integration](../LIVE_SANDBOX_INTEGRATION.md).

`farmer-data.js` exposes `FarmerData.createProvider(options)` to browser scripts. It implements the frontend mock for the contract in [`../FARMER_INPUT_CONTRACT.md`](../FARMER_INPUT_CONTRACT.md). No backend server or extra package is required for mock mode. The farmer-facing map viewer loads the provider.

```js
const data = FarmerData.createProvider({ mode: 'mock' });
const { parcels } = await data.findParcels({ number: 'Krzewie 123/4' });
const matches = await data.findParcels({ lon: 20.76, lat: 52.175 });
const { crops } = await data.getCrops();
const { fields } = await data.listFields();
const field = await data.getField('field-demo-1');
field.crop_areas[0].sowing_date = '2024-09-16';
await data.saveField(field.field_id, field);
```

All methods return promises. `findParcels` accepts `{number}`, `{number, locality}`, or `{lon, lat}`. `getField` and `saveField` accept a field ID; save accepts the complete contract field object as its second argument. To create a field on one of the two empty example plots, construct a valid field with a new ID, the selected parcel, and at least one complete crop area, then call `saveField(id, field)`. `past_sprays: []` means no sprays yet. Crop options and geometries come from the provider. Responses contain `data_status: 'mock'`.

The crop editor uses `getCrops()`, `listFields()` and `getCropSuggestions(parcelId)`
to display existing or proposed areas. A crop-map value is preselected when it matches an available crop; farmers can change it. If no available crop is provided, the crop remains unselected. Existing saved farmer choices take precedence.
Drawn areas can span the selected parcels. The old `saveField()` operation remains
available for the original single-parcel mock, but the crop editor now requires a valid
geometry validation response and atomic group save. Neither is available in the mock,
so the editor intentionally cannot save yet. The separately served QGIS fixture is still
read-only and does not receive edits.

`importGeometry(file, {context, parcelIds})` uses a sample polygon in mock mode and does
not read the file. The interface labels the sample clearly. Backend mode sends the file
as multipart form data. The adapter's optional `geometryImportPath`,
`geometryValidationPath`, `geometryGroupLoadPath` and `geometryGroupSavePath` must be
configured once the backend team agrees and implements the operations. Group save is
available only when both save and load paths are configured. No endpoint paths or backend
capabilities are implied by these options. See the proposed
[geometry contract](../GEOMETRY_VALIDATION_CONTRACT.md) for request and response details,
confirmation rules and current limitations.

The editor uses Turf.js 7.1.0 (loaded from unpkg, alongside MapLibre) for a local,
non-authoritative preview of invalid boundaries, polygon intersections, uncovered
parcel areas, and portions outside the selected parcels. The red map highlights come
from the current drawing. Geometry edits invalidate the preview; calculation errors or
an unavailable Turf.js are shown as unavailable rather than as a clean result. The
preview does not alter the drawing by itself or authorize saving. Its map cards offer
farmer-chosen draft changes: clip an area to selected parcels, assign a gap to a chosen
crop area, or remove an overlap from a chosen area. Multi-part results can be displayed
but not edited with vertex handles. The
backend must validate, repair, and return the authoritative findings and confirmation
identifiers. The six synthetic examples remain available through the provider for development and do not validate the drawing.
Saving requires a non-example backend validation result and explicit confirmations.

There are five fictional adjacent parcels with numbers `123/4`, `124/1`, `123/4`, `77/2` and `18/3`; two deliberately share a number across different localities. The first three have saved fields `field-demo-1` through `field-demo-3`; the last two have no saved fields. The first field has two crop areas and a farmer crop/map crop disagreement. A point on the boundary between adjacent plots can return multiple parcel matches. These are synthetic examples, not GUGiK records or proof of ownership.

The parcel-search fixtures demonstrate the farmer-friendly formats: a locality prefix (for example `Krz`), a locality and parcel number (`Krzewie 123/4`), a bare parcel number (`123/4`), a full cadastral-looking identifier, or `{number, locality}` after choosing a locality. Search results include human-readable locality, commune and area details; the identifier is secondary. All fixture identifiers, areas and geometries are synthetic and must not be treated as matching real registers. A bare number may return multiple localities, so the UI asks the farmer to choose the right result. The map-selection UI displays selected parcels, their cadastral identifiers and the sum of their provided areas; the older saved-field contract stores one `parcel` per field; group persistence requires the proposed backend operation.

### ULDK lookup check

The official [ULDK service documentation](https://uldk.gugik.gov.pl/opis.html) describes `GetParcelByIdOrNr` for full parcel identifiers or a locality name plus parcel number. It warns that locality names can match parcels in multiple regions and that these searches may take longer. The documentation also describes `GetAggregateArea` for combining parcel geometries, returning a polygon or multipolygon depending on adjacency. On 2026-11-21, a read-only live request to the official ULDK endpoint using its documented `Krzewina 134` example returned one matching parcel. This confirms the documented lookup is reachable for that example; it does not establish availability, performance or coverage for all farmer queries. The app continues to use frontend mocks and has no ULDK integration yet.

Changes are stored **in memory per provider instance** and disappear on page reload or when a new instance is created. They are not sent to a server, shared with QGIS, or durable. Returned data is copied so clients must call `saveField` to save changes. `data.setAvailable(false)` simulates a service failure; call `data.setAvailable(true)` to restore it. Errors are rejected promises with `status` and `error: {code, message, fields?}`. Empty search results return `{parcels: [], data_status: 'mock'}`. A missing field rejects with status 404; invalid input rejects with 400 or 422; simulated unavailability rejects with 503.

The legacy single-parcel mock validates required values, calendar dates, positive whole-day spray durations, crop choices and basic closed GeoJSON Polygon structure. It does not yet implement the multi-parcel group contract or MultiPolygon group persistence. It does not validate self-intersections, overlapping areas, containment in parcels, or offer nearby parcels; those are separate UI/spatial integration work. No land is silently claimed.

To switch providers when the real API is ready, keep the same method calls and configure:

```js
const data = FarmerData.createProvider({
  mode: 'backend',
  baseUrl: 'http://127.0.0.1:8000/api/v1'
});
```

Backend mode uses `fetch` and the contract's `/parcels`, `/crops`, and `/fields` paths. The viewer creates its provider near the start of the script in `web/index.html`; switch that configuration to `mode: 'backend'` and set `baseUrl` when the endpoints are ready. Both search entry points use the same `findParcels` method. For autocomplete the backend must support partial locality and parcel-number queries, the optional `locality` filter, and return the locality, commune, area and cadastral ID metadata used by the suggestions; these search extensions are not yet agreed or implemented in the real API. It does not fall back to mock data if the backend fails. These legacy `/parcels`, `/fields`, and crop-suggestion paths have not been verified against the deployed API; the live sandbox uses different operations described in the integration notes. Callers must catch rejected promises and present a useful message.

## Read-only QGIS layer

The same initial frontend fixtures can be served as a read-only GeoJSON layer, without changing the real backend. From the repository root, with Node.js installed:

```bash
node web/mock-qgis-server.cjs
```

In QGIS, add a vector layer from the URL `http://127.0.0.1:8765/mock/plots.geojson`. The layer contains six features across five fictional plots: four crop-area features from the three populated plots and two parcel features for the empty plots. `plot_status` distinguishes saved from empty examples. Crop, sowing date and previous sprays are in the attributes; `past_sprays` is JSON text. The geometry uses GeoJSON longitude/latitude (EPSG:4326).

This server binds to `127.0.0.1` (the same computer) and serves a **read-only snapshot** of the initial frontend examples. It does not access GUGiK, prove ownership, or receive edits from a browser provider instance. Use `FARMER_MOCK_PORT` to select a different port if needed. Stop the server with Ctrl+C. A real backend or a separately agreed shared service is required to exchange edits between clients.
