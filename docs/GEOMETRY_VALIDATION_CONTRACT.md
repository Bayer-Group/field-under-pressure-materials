# Proposed geometry validation contract

This is the farmer-approved behaviour for the next iteration. It extends the existing
[FARMER_INPUT_CONTRACT.md](FARMER_INPUT_CONTRACT.md); the real validation and group-save
operations are not implemented yet. Endpoint paths and transport details are to be agreed
by the backend team. The existing one-parcel field representation remains the current
implementation until the group-save and reconstruction operations are available.

## Farmer-facing model

A working selection contains multiple cadastral parcels. A crop area belongs to that
selection, not to one particular parcel: the farmer draws and enters its crop, sowing date
and sprays once. The backend may split that area into per-parcel pieces for storage, but
must persist a shared crop-area identity and data so MapLibre and QGIS can retrieve and
edit the same area as one. Joining pieces must preserve holes and disconnected pieces.
Selecting a parcel expresses a working association, not proof of ownership.

## Validation request

A validation request contains the selected parcel IDs and farmer-drawn crop areas with
stable IDs and GeoJSON geometries. The backend obtains authoritative parcel geometries;
parcel boundaries submitted by a client are not authoritative. Crop-area geometries may
be `Polygon` or `MultiPolygon`, using GeoJSON longitude/latitude in WGS84 (RFC 7946).
Crop details are carried in the group save, not needed to determine geometry conflicts.

```json
{
  "parcel_ids": ["parcel-demo-4"],
  "crop_areas": [
    {
      "crop_area_id": "area-1",
      "geometry": {
        "type": "Polygon",
        "coordinates": [[[20.780, 52.170], [20.785, 52.170], [20.785, 52.180], [20.780, 52.180], [20.780, 52.170]]]
      }
    }
  ]
}
```

The backend must check its inputs even when the frontend has performed preliminary
checks. Validate against the union of selected parcel geometries, rather than validating
each crop independently against one parcel.

## Validation response

The response reports all applicable findings rather than choosing just one: a drawing
can have both gaps and overlap, for example. Empty arrays mean no findings of that kind;
`validation_id` identifies this exact submitted geometry and parcel selection. The
backend must reject a stale validation ID after a change, and re-check at group save.

```json
{
  "validation_id": "validation-example",
  "crop_areas": [
    {
      "crop_area_id": "area-1",
      "geometry": {
        "type": "Polygon",
        "coordinates": [[[20.780, 52.170], [20.785, 52.170], [20.785, 52.180], [20.780, 52.180], [20.780, 52.170]]]
      },
      "repair": {
        "performed": false,
        "max_boundary_displacement_m": 0,
        "area_change_percent": 0,
        "requires_review": false
      }
    }
  ],
  "overlaps": [],
  "gaps": [
    {
      "gap_id": "gap-1",
      "geometry": {
        "type": "Polygon",
        "coordinates": [[[20.785, 52.170], [20.790, 52.170], [20.790, 52.180], [20.785, 52.180], [20.785, 52.170]]]
      }
    }
  ],
  "outside": [],
  "errors": [],
  "data_status": "mock"
}
```

Each `overlaps` entry contains `crop_area_ids` (the conflicting areas) and the GeoJSON
`geometry` of their shared surface. Touching only along an edge or point is allowed.
Each `outside` entry contains `crop_area_id`, a stable `outside_id`, and the GeoJSON
`geometry` outside the selected parcels. The returned crop-area geometry is the proposed
repaired and clipped geometry; it is not committed or substituted for the farmer's draft
until the necessary confirmations are supplied. A removed/empty crop area is reported in
`errors` and cannot be saved. Geometry-bearing findings may be Polygon or MultiPolygon.
A performed repair also includes a stable `repair_id`; a repair requiring review must
be confirmed against that ID. If no valid surface can be proposed, its geometry is `null`
and `errors` blocks saving. `errors` contains machine-readable `code`, optional `crop_area_id`, and a human-readable
`message`; a failure to validate is distinct from an empty findings list. Production
responses must identify their actual data source, not claim to be mock data.

## Automatic repair and findings

The backend attempts to repair invalid geometry. A repair may be applied without farmer
review only if all of these conditions are demonstrably true:

- maximum boundary displacement is at most **0.25 m**;
- absolute area change is at most **0.5%** of the original surface;
- no surface component disappears and the result remains a valid crop surface.

When measurements cannot be determined reliably, the result is not eligible for silent
repair; return it for review or report that it cannot be repaired. The backend team must
specify the metric calculation and coordinate transformation, and handle invalid input
whose original surface cannot be meaningfully measured. `requires_review` must be true
for repairs outside these limits. Geometry repair must not silently choose which of two
crops owns an overlapping surface.

All overlap blocks save. Every gap requires explicit confirmation that it is excluded
from analysis. Every clipped outside part requires explicit confirmation before clipping.
A visible-map threshold determines whether to additionally offer nearby parcel selection:
when the projected distance beyond the selected boundary exceeds **24 CSS pixels** in
the current map view, offer nearby parcels or clipping; at or below the threshold ask
for clipping confirmation without the nearby-parcel prompt. This threshold controls UI
behaviour only; backend geometry calculations do not depend on zoom. The comparison is
at the view in which the farmer finishes editing. Backend parcel search supplies nearby
candidates; no candidate is selected or claimed automatically.

## Group save and confirmation

The future group-save request contains the selected parcel IDs, crop areas and their
farmer crop, sowing date and explicit past-spray input, plus the current `validation_id`
and explicit confirmations for all reported gap IDs, outside IDs and review-required
repair IDs. A spray-free record is an explicitly confirmed empty list; an unanswered spray question cannot be saved. The backend
revalidates before saving, rejects stale or incomplete confirmations, and returns the
saved grouped crop areas and stable IDs for MapLibre and QGIS. Confirmation does not
allow an overlap or an empty area. Persist the final, approved geometry as the source of
truth; preserving the submitted geometry and repair details is recommended for audit.
On failure or unavailability, preserve the frontend draft and do not present it as saved.
The save should be atomic across selected parcels; the current mock's sequential
per-parcel writes do not provide this guarantee and are not the new group-save operation.

## Mock boundaries

The frontend mock provider exposes `getGeometryValidationExample(name)` for explicit,
synthetic examples: `valid`, `gap`, `overlap`, `outside`, `minor_repair` and
`review_repair`. Each returns `{request, response}` and is labelled as mock data. It is
not a validation method and cannot certify an arbitrary farmer drawing. The repair
measurements are illustrative rather than measured values. These examples are available to developers through the provider; they cannot approve or save the farmer's drawing. The editor displays actual preview findings as map-anchored messages and shows backend confirmation controls on the map when saving. The frontend uses Turf.js for an immediate, non-authoritative preview of invalid
boundaries, overlaps, uncovered parcel surfaces and areas outside the parcel union. It
does not silently repair or clip geometry. The farmer may explicitly apply a suggested
local clip, assign a gap to a chosen area, or remove an overlap from a chosen area;
these draft changes always require fresh backend validation. The backend must validate the actual input,
produce authoritative findings and repair results, and verify confirmations. Real
backend validation and atomic group persistence are not implemented and are required to
complete a save. Cross-client persistence is
not yet available.

The adapter accepts configured paths for import, validation, group load and group save;
no endpoint names are assumed. Import uses multipart form fields `file`, `context` and
JSON-encoded `parcel_ids`. It returns either `parcels` or `crop_areas`. The mock never
reads file contents and explicitly offers a synthetic sample geometry instead. The crop
editor currently cannot edit multipart geometries, although it can display them.

The 24 CSS pixel calculation samples the projected boundary and is an approximation. The
nearby lookup currently searches one point within each outside piece, so it can miss
candidates; it never adds one without the farmer's selection. These interactions need
real backend integration and review before they can be considered complete.
