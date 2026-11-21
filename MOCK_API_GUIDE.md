# Frontend mocks and backend API integration

This guide describes the existing farmer-input mock and how to extend it so the frontend can develop before real endpoints are available. The agreed data shapes, operations and validation requirements are in [FARMER_INPUT_CONTRACT.md](FARMER_INPUT_CONTRACT.md). The implementation and runnable examples are in [web/FARMER_DATA.md](web/FARMER_DATA.md).

## One interface for the UI

Frontend code uses one provider instance and calls its methods; it does not choose mock data or build backend URLs inside individual components. Load `web/farmer-data.js` and create the provider at the application's entry point. Pass that instance to the components that need data, so they see the same in-memory changes.

```js
// Local development: no server or external data needed.
const data = FarmerData.createProvider({ mode: 'mock' });

// When the real endpoints are available and verified, switch configuration:
// const data = FarmerData.createProvider({
//   mode: 'backend', baseUrl: 'http://127.0.0.1:8000/api/v1'
// });

const { parcels } = await data.findParcels({ number: 'DEMO-001' });
const { crops } = await data.getCrops();
const { fields } = await data.listFields();
```

The existing provider interface is asynchronous: `findParcels({number})` or `findParcels({lon, lat})`, `getCrops()`, `listFields()`, `getField(id)` and `saveField(id, field)`. Each returns a promise. The UI must handle rejected promises and show appropriate messages. Do not create a provider per component: mock state is held per instance and resets when the instance is recreated or the page reloads.

To add a new operation, agree its request and response with both teams in the relevant issue, update the contract and provide the same method on the mock and backend adapters. Use fictional fixtures and include useful empty, populated and error cases. Do not put real farmer or restricted data into source control. Do not silently fall back to a mock when a real backend request fails: the UI must be able to distinguish an outage from an empty result and from a simulated response.

## What the backend needs to implement

The real API implements the agreed contract, not the frontend's local storage. The current adapter expects these paths relative to the configured base URL:

| Provider method | HTTP request | Expected success body |
| --- | --- | --- |
| `findParcels({number})` | `GET /parcels?number=...` | `{parcels: [...]}`; empty array means no match |
| `findParcels({lon, lat})` | `GET /parcels?lon=...&lat=...` | Same parcel list; multiple matches are possible |
| `getCrops()` | `GET /crops` | `{crops: [{id, label}, ...]}` |
| `listFields()` | `GET /fields` | `{fields: [...]}` |
| `getField(id)` | `GET /fields/{id}` | Full field representation |
| `saveField(id, field)` | `PUT /fields/{id}` with JSON | The complete saved field representation |

See the contract for GeoJSON polygon geometry, exact date values, crop overrides and past sprays. The real API must describe its actual source and status; `data_status: "mock"` identifies mock responses and must not be presented as real data. The adapter URI-encodes field IDs, sends JSON for saves and expects JSON on both success and error responses. It converts a network failure to a `SERVICE_UNAVAILABLE` error; backend errors should return the agreed `{error: {code, message, fields?}}` shape. Define authentication, authorization, durable storage, concurrency and CORS when implementing the real service; they are not provided by the frontend mock.

Before switching an environment, verify the real endpoint paths, envelopes, geometry/coordinate order, dates, validation and error responses against the contract and run the same user flows against both providers. The current backend adapter is an integration boundary, **not evidence that real endpoints already exist or conform**.

## Mock data and QGIS

The mock starts with five fictional parcels: three populated and two without saved fields. It supports searches, crop choices, field save/read, validation and simulated unavailability. It is not a cadastral service, ownership system or durable database. The provider checks basic polygon structure; self-intersections, overlap, containment and the nearby-parcel selection flow are not implemented here.

For QGIS, `node web/mock-qgis-server.cjs` serves the **initial fixtures** at `http://127.0.0.1:8765/mock/plots.geojson` as a read-only GeoJSON layer. This optional local endpoint is for visualization, not a mock of the real backend's write operations. It uses the same initial data but cannot see browser-memory changes. QGIS and MapLibre can share the contract and example content now; shared edits need the real backend or a separately agreed exchange. See [web/FARMER_DATA.md](web/FARMER_DATA.md) for the commands, attributes and limitations.
