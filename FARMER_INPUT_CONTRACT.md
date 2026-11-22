# Farmer input API contract — issue #11

This document records the agreed input direction and an example contract. It is not an implemented API. No example represents a real parcel or person.

## Intended flow

1. The farmer can centre the map on device location. This is a client action; it does not select a parcel or prove ownership.
2. The client obtains parcel lookup results from the backend by parcel identifier or map coordinates and displays their geometry. The farmer can select multiple results as their working plots.
3. The backend supplies crop choices. The farmer draws one or more crop-area polygons over selected GUGiK parcels and enters the crop, sowing date, and past spray date and protection duration in days for each crop area. Each plot may have multiple crop areas. If a drawn area extends substantially outside selected parcels, the app allows the farmer to select nearby parcels as additional working plots; selection does not prove ownership. All required input must be supplied before saving; the spray list can be empty when no sprays have been carried out. Saved data remains until updated.
4. MapLibre saves the data via the backend. QGIS reads the same backend representation for spatial inspection. The crop reported by a farmer is distinguishable from any crop-map value.
5. The switchable frontend mock supplies five example plots, some with saved data and some empty, and accepts and returns submitted data. The frontend will switch to the real backend once endpoints are ready. QGIS can use the same mock examples; frontend-local changes are not shared with QGIS without an agreed exchange. Clearly identify mock data and document its storage lifetime.

The farmer-approved multi-parcel geometry validation and group-save extension is described in
[GEOMETRY_VALIDATION_CONTRACT.md](GEOMETRY_VALIDATION_CONTRACT.md). The one-parcel examples
below describe the existing implementation, not the completed multi-parcel workflow.

## Spray input interaction

The farmer explicitly selects whether a spray was carried out; neither answer is selected
by default. If yes, each spray requires the application date and a positive protection
duration in days. If no, the saved `past_sprays` list is empty. An unanswered question
cannot be saved. The UI shows the duration field after a date is selected.

## Proposed field representation

The example uses GeoJSON geometry in longitude/latitude and ISO calendar dates. The examples show values in a saved record and an unfilled example. All required inputs must be supplied before a record is saved. An empty spray list is allowed when no sprays have been carried out. Dates describe calendar days, not timestamps.

```json
{
  "field_id": "field-demo-1",
  "parcel": {
    "parcel_id": "parcel-demo-1",
    "parcel_number": "DEMO-123",
    "geometry": {
      "type": "Polygon",
      "coordinates": [[[20.750, 52.180], [20.760, 52.180], [20.760, 52.170], [20.750, 52.170], [20.750, 52.180]]]
    }
  },
  "crop_areas": [
    {
      "crop_area_id": "area-demo-1",
      "geometry": {
        "type": "Polygon",
        "coordinates": [[[20.750, 52.180], [20.755, 52.180], [20.755, 52.170], [20.750, 52.170], [20.750, 52.180]]]
      },
      "crop": {"farmer_crop_id": "wheat", "map_crop_id": "maize"},
      "sowing_date": "2024-09-15",
      "past_sprays": [{"date": "2024-10-10", "protection_duration_days": 14}]
    },
    {
      "crop_area_id": "area-demo-2",
      "geometry": {
        "type": "Polygon",
        "coordinates": [[[20.755, 52.180], [20.760, 52.180], [20.760, 52.170], [20.755, 52.170], [20.755, 52.180]]]
      },
      "crop": {"farmer_crop_id": "soy", "map_crop_id": null},
      "sowing_date": null,
      "past_sprays": []
    }
  ],
  "data_status": "mock"
}
```

The second crop area illustrates an unfilled form, not a valid saved record. The example protection duration is illustrative and expressed in days. The identifiers and crop codes above are illustrative; the backend must provide actual available choices. The farmer-selected crop is used for the crop area; the farmer value and map value are kept separate so the map value is not erased. A parcel selection denotes a working association, not legal ownership.

## Contract operation overview

| Need | Proposed behaviour | Example result |
| --- | --- | --- |
| Parcel by number | Client sends a parcel identifier; backend returns matching parcels and geometries. | A list; show no match, allow the farmer to choose among multiple matches, or report service unavailability and allow retry. |
| Parcel by click | Client sends map coordinates; backend returns matching parcels and geometries. | A list; show no match, allow the farmer to choose among multiple matches, or report service unavailability and allow retry. |
| Crop choices | Client requests current backend-provided choices. | IDs and display labels for selection. |
| Save field | Client sends selected parcel, crop areas and entered data. | Saved field and stable identifiers, or field-level validation errors. |
| Read field | QGIS or MapLibre requests the saved field. | The same field and crop-area geometries and attributes. |

The agreed operations and examples are specified below. Mock persistence and production identity and access details remain implementation work. The frontend mock is local to the frontend and is not a shared backend; its storage lifetime must be disclosed. QGIS and MapLibre can use the same example contract, but sharing saved data between them requires a backend or a separately agreed exchange.

## Implementation questions

- What parcel identifier and lookup inputs does the real cadastral service accept, and how should multiple matches and service failures be returned?
- How should drawn geometry validity, overlap, coordinate reference systems and substantial out-of-bounds extent be checked, and how should nearby parcels be offered for selection? The threshold and interaction are implementation choices; never silently claim a parcel.
- Can multiple sprays occur on the same day? Each recorded spray requires its date and protection duration in days.
- What metadata should accompany farmer corrections and source-map values beyond retaining both values?
- What access and isolation rules associate saved fields with users? What mock behaviour is appropriate before those rules are agreed?
- Which backend-provided options and errors must the farmer-facing flow show, and what does QGIS need to retrieve?

## Acceptance walkthrough after agreement

Using five frontend mock plots (some saved, some empty), select more than one sample parcel by number and by map click, draw crop-area polygons over them, enter crops and full sowing dates, and record spray dates and protection durations. Exercise a substantially out-of-bounds drawing and the option to select nearby parcels. Retrieve the result in the frontend and compare it with the shared example contract used for QGIS. Verify shared saved data across both clients once the backend is available. Check missing inputs, no parcel match, ambiguous results, invalid dates, and backend unavailability. Record what is mocked and not yet implemented. Locate-me should only centre the map.

## Agreed operations and examples

These operations describe the interface that the frontend mock will implement locally and the eventual backend will provide. Paths below are relative to the API base; the existing backend prefix can be used. The frontend mock contains five fictional plots: three with saved inputs and two empty. The mock must disclose whether its data survives a browser refresh. Switching data providers must not require changing the client-facing contract.

- `GET /parcels?number={parcel_number}` searches by parcel number.
- `GET /parcels?lon={longitude}&lat={latitude}` searches by a clicked position.
- `GET /crops` lists crop choices supplied by the provider.
- `GET /fields` lists the farmer's saved plots.
- `GET /fields/{id}` retrieves one saved plot with its crop areas.
- `PUT /fields/{id}` saves or updates a plot and returns the saved representation.

### Parcel lookup

`GET /parcels?number=DEMO-123` and `GET /parcels?lon=20.755&lat=52.175` use the same response shape. This fictional response contains one match; multiple matches are returned in the same list for the farmer to select.

```json
{
  "parcels": [
    {
      "parcel_id": "parcel-demo-1",
      "parcel_number": "DEMO-123",
      "geometry": {
        "type": "Polygon",
        "coordinates": [[[20.750, 52.180], [20.760, 52.180], [20.760, 52.170], [20.750, 52.170], [20.750, 52.180]]]
      }
    }
  ],
  "data_status": "mock"
}
```

No match is a successful response with `"parcels": []`; the client displays a no-match message and allows retry. Service unavailability is an error, not an empty result. Device location only centres the map and does not select a parcel.

### Choices

`GET /crops` returns identifiers and labels. These values are fictional examples, not a fixed production list.

```json
{
  "crops": [
    {"id": "wheat", "label": "Wheat"},
    {"id": "soy", "label": "Soy"},
    {"id": "maize", "label": "Maize"}
  ],
  "data_status": "mock"
}
```

### Save and retrieve

`PUT /fields/field-demo-1` takes the field representation shown above, with every required input completed. For example, the second crop area in that representation can be completed with `"sowing_date": "2024-09-20"` and `"past_sprays": []`; the empty spray list means no sprays yet. A successful response returns the complete saved representation in the same shape, including `field_id` and `data_status`. `GET /fields/field-demo-1` returns that same representation until updated. `GET /fields` returns `{"fields": [ ... ], "data_status": "mock"}`; each item uses the same field representation. The mock examples are fictional; production data must identify its source appropriately.

Required before saving: a selected parcel, at least one crop area, each crop area's polygon, farmer-selected crop and sowing date. Every spray that is recorded requires its date and a positive protection duration in days. An empty spray list is valid. Crop rotation is not collected. The farmer-selected crop is the value used for the crop area; retain a separate crop-map value when available. Use GeoJSON polygon geometry in longitude/latitude and dates as `YYYY-MM-DD`. Reject malformed polygons and invalid dates.

### Errors

Use a consistent error object with a stable code, a readable message and field details where applicable. For example, an invalid date can return a validation error with HTTP 422:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Check the entered data.",
    "fields": [
      {"path": "crop_areas[0].sowing_date", "message": "Enter a valid date in YYYY-MM-DD format."}
    ]
  }
}
```

A service-unavailable response should use a distinct error code and message so the client can offer retry. A no-match result is distinct from service failure; multiple matches are a list, not an error. Farmer-facing messages should be understandable without exposing implementation details.

A crop area may extend substantially outside the selected parcels. Offer nearby parcels for the farmer to select as additional working plots; never add them silently. The team can determine the out-of-bounds threshold and interaction during implementation. Selecting a parcel records a working association and does not establish legal ownership.
