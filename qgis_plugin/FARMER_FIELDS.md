# Farmer fields in QGIS (issue #14)

The plugin panel can show the saved farmer fields and crop areas defined in
[FARMER_INPUT_CONTRACT.md](../FARMER_INPUT_CONTRACT.md). QGIS only reads; it never writes.

## What is loaded

| Layer | Geometry | Source |
| --- | --- | --- |
| `Farmer parcels` | parcel outline (dashed, no fill) | `parcel` of each field |
| `Farmer crop areas` | crop-area polygons, categorized | `crop_areas` of each field |

When the response says `data_status: "mock"`, both layer names get `(MOCK)` and QGIS shows a warning bar.
Layers are memory layers in EPSG:4326 (GeoJSON lon/lat from the contract). Reloading replaces them.

Crop-area attributes: `field_id`, `crop_area_id`, `parcel_id`, `parcel_number`, `farmer_crop_id`,
`map_crop_id` (kept separate, never merged), `crop_differs`, `sowing_date`, `spray_count`,
`last_spray_date`, `past_sprays` (JSON text), `data_issues`, `data_status`.

Style categories: farmer crop differs from crop map / farmer crop with no map value / matches / incomplete or invalid data.
Label: farmer crop and sowing date.

## How to load

1. Open the panel and use the **Farmer input** section.
2. **Load farmer fields (backend)** calls `GET {base URL}/fields`. Default base URL: `http://127.0.0.1:8000/api/v1`.
3. Without a backend, use **Load farmer fields from JSON file...** with
   [`sample_project/farmer_fields_mock.json`](../sample_project/farmer_fields_mock.json), a copy of the
   frontend mock's `listFields()` (see `web/FARMER_DATA.md`). It has three fields and four crop areas,
   one field with two crop areas and one farmer/map crop mismatch.

## What the panel reports

The status line under the buttons shows the result of the last load. Details (log lines) are collapsed under **Details**
and are also written to the QGIS Log Messages panel under the tag `Field Under Pressure`.

- **Backend unreachable** (`SERVICE_UNAVAILABLE`), HTTP error bodies in the contract's `{error: {code, message, fields}}` shape,
  and invalid JSON are errors (red bar plus log). Existing layers stay.
- **Empty `fields`** is not an error: the log says nothing was returned and no layers are added.
- Parcels or crop areas without a valid closed polygon are skipped and listed as warnings.
- Missing or invalid values (crop, sowing date, spray date or duration) stay empty and are written to `data_issues`.
- A response without `data_status` is flagged as unlabelled.

## Limits

- Only `GET /fields` is used. The backend must return full field objects (with `crop_areas`) in that list.
- The frontend mock keeps edits in browser memory, so QGIS only sees the initial fixtures until a real backend exists.
- Coordinate order, CRS checks and overlap/containment validation are not done in QGIS; they are open contract questions.
