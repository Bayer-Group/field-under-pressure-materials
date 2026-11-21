# Farmer data provider

For the team workflow and backend integration checklist, see [Mock API guide](../MOCK_API_GUIDE.md).

`farmer-data.js` exposes `FarmerData.createProvider(options)` to browser scripts. It implements the frontend mock for the contract in [`../FARMER_INPUT_CONTRACT.md`](../FARMER_INPUT_CONTRACT.md). No backend server or extra package is required for mock mode. The existing map viewer loads the provider, but its farmer-facing UI is separate work in issue #15.

```js
const data = FarmerData.createProvider({ mode: 'mock' });
const { parcels } = await data.findParcels({ number: 'DEMO-001' });
const matches = await data.findParcels({ lon: 20.76, lat: 52.175 });
const { crops } = await data.getCrops();
const { fields } = await data.listFields();
const field = await data.getField('field-demo-1');
field.crop_areas[0].sowing_date = '2024-09-16';
await data.saveField(field.field_id, field);
```

All methods return promises. `findParcels` accepts `{number}`, `{number, locality}`, or `{lon, lat}`. `getField` and `saveField` accept a field ID; save accepts the complete contract field object as its second argument. To create a field on one of the two empty example plots, construct a valid field with a new ID, the selected parcel, and at least one complete crop area, then call `saveField(id, field)`. `past_sprays: []` means no sprays yet. Crop options and geometries come from the provider. Responses contain `data_status: 'mock'`.

There are five fictional adjacent parcels with numbers `123/4`, `124/1`, `123/4`, `77/2` and `18/3`; two deliberately share a number across different localities. The first three have saved fields `field-demo-1` through `field-demo-3`; the last two have no saved fields. The first field has two crop areas and a farmer crop/map crop disagreement. A point on the boundary between adjacent plots can return multiple parcel matches. These are synthetic examples, not GUGiK records or proof of ownership.

The parcel-search fixtures demonstrate the farmer-friendly formats: a locality prefix (for example `Krz`), a locality and parcel number (`Krzewie 123/4`), a bare parcel number (`123/4`), a full cadastral-looking identifier, or `{number, locality}` after choosing a locality. Search results include human-readable locality, commune and area details; the identifier is secondary. All fixture identifiers, areas and geometries are synthetic and must not be treated as matching real registers. A bare number may return multiple localities, so the UI asks the farmer to choose the right result. The map-selection UI can collect multiple parcels under one farmer-facing field name; the current saved-field contract still stores one `parcel` per field, so this screen does not persist a multi-parcel group.

### ULDK lookup check

The official [ULDK service documentation](https://uldk.gugik.gov.pl/opis.html) describes `GetParcelByIdOrNr` for full parcel identifiers or a locality name plus parcel number. It warns that locality names can match parcels in multiple regions and that these searches may take longer. The documentation also describes `GetAggregateArea` for combining parcel geometries, returning a polygon or multipolygon depending on adjacency. On 2026-11-21, a read-only live request to the official ULDK endpoint using its documented `Krzewina 134` example returned one matching parcel. This confirms the documented lookup is reachable for that example; it does not establish availability, performance or coverage for all farmer queries. The app continues to use frontend mocks and has no ULDK integration yet.

Changes are stored **in memory per provider instance** and disappear on page reload or when a new instance is created. They are not sent to a server, shared with QGIS, or durable. Returned data is copied so clients must call `saveField` to save changes. `data.setAvailable(false)` simulates a service failure; call `data.setAvailable(true)` to restore it. Errors are rejected promises with `status` and `error: {code, message, fields?}`. Empty search results return `{parcels: [], data_status: 'mock'}`. A missing field rejects with status 404; invalid input rejects with 400 or 422; simulated unavailability rejects with 503.

The mock validates required values, date format, positive spray durations, crop choices and basic closed GeoJSON polygon structure. It does not validate self-intersections, overlapping areas, containment in parcels, or offer nearby parcels; those are separate UI/spatial integration work. No land is silently claimed.

To switch providers when the real API is ready, keep the same method calls and configure:

```js
const data = FarmerData.createProvider({
  mode: 'backend',
  baseUrl: 'http://127.0.0.1:8000/api/v1'
});
```

Backend mode uses `fetch` and the contract's `/parcels`, `/crops`, and `/fields` paths. It does not fall back to mock data if the backend fails. The real endpoints do not yet exist or have not been verified; integration, CORS, authentication and persistence remain backend work. Callers must catch rejected promises and present a useful message.

## Read-only QGIS layer

The same initial frontend fixtures can be served as a read-only GeoJSON layer, without changing the real backend. From the repository root, with Node.js installed:

```bash
node web/mock-qgis-server.cjs
```

In QGIS, add a vector layer from the URL `http://127.0.0.1:8765/mock/plots.geojson`. The layer contains six features across five fictional plots: four crop-area features from the three populated plots and two parcel features for the empty plots. `plot_status` distinguishes saved from empty examples. Crop, sowing date and previous sprays are in the attributes; `past_sprays` is JSON text. The geometry uses GeoJSON longitude/latitude (EPSG:4326).

This server binds to `127.0.0.1` (the same computer) and serves a **read-only snapshot** of the initial frontend examples. It does not access GUGiK, prove ownership, or receive edits from a browser provider instance. Use `FARMER_MOCK_PORT` to select a different port if needed. Stop the server with Ctrl+C. A real backend or a separately agreed shared service is required to exchange edits between clients.
