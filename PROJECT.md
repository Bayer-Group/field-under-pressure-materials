# Field Under Pressure — GeoEarth Junction

## Purpose

Help a farmer understand when weather conditions may favour crop disease, identify possible disease-risk periods, and see weather windows that may be suitable for treatment. The farmer or agronomist makes the decision; the prototype does not diagnose disease or instruct anyone to spray.

The longer-term goal is a nationwide crop-risk heatmap and a field-level view explaining risk, treatment windows and data confidence. Both QGIS and the MapLibre web map should be able to present data made available by the backend.

## First iteration: data visible end to end

Focus on one crop (selection still open). Download and classify the relevant available data, make it importable to the backend, and show a representative result in both QGIS and MapLibre. The deliverable is a repeatable demonstration that the selected data opens, appears in the correct location, and can be inspected in both environments. Document selected sources, coverage, classifications, quality limitations and how to reproduce the demonstration. Nationwide risk is the product goal; a disease-risk model and treatment recommendation are not prerequisites for this data-validation deliverable.

The team will decide implementation details, data formats, interfaces and acceptance checks within the relevant issues. Iterations should remain limited in scope and end with a demonstrable deliverable.

## Product direction and boundaries

- A farmer selects a field and crop; disease risk should explain the conditions and period that contribute to it, with uncertainty and data provenance visible.
- The team plan identifies wheat/septoria, maize/yellow leaf spot and soy/white mould as candidate crop–disease combinations. The first crop and disease have not yet been selected; the other combinations are future candidates, not first-iteration commitments.
- Treatment windows are a later capability, based on forecast conditions and relevant equipment, product label and applicable rules. Where information is missing, do not claim eligibility or compliance. Agronomic models, thresholds and legal requirements require source and expert verification before use.
- Historical weather is not a current forecast. Satellite vegetation indicators provide context and do not confirm disease. Farmer symptom reports, if added, remain a separate signal.
- No training a new AI model from scratch, photo-based disease diagnosis, or instruction to spray is planned for the hackathon prototype.

## Data direction

Organizer data is available. Candidate inputs in the team plan include hourly and daily historical weather, weather-grid locations, IMERG precipitation, soil and crop maps, and Sentinel-2. Forecasts, product information, farmer inputs and expert validation are potential later inputs. Exact datasets, geographic and temporal coverage, access, quality and licensing must be checked and recorded as work proceeds. Keep large datasets and credentials out of Git; preserve source attribution and original values when documenting corrections.

## Existing starting point

The PyQGIS–FastAPI bridge has been merged into this repository. It supplies a FastAPI backend, QGIS plugin, shared components and a MapLibre viewer as a starting point. Their presence does not mean that the crop-risk product, data ingestion, nationwide coverage or the end-to-end workflow is already implemented or validated. See [README2.md](README2.md) for the imported bridge instructions and [data/README.md](data/README.md) for organizer dataset documentation. The organizer's [README.md](README.md) remains the materials guide. Setup and demo instructions for the integrated product should be recorded once verified.

## Team and collaboration

| Person | GitHub | Focus | Pair |
| --- | --- | --- | --- |
| Michał | @michcio10 | QGIS and spatial analysis | Wiktor |
| Wiktor | @wwwitkowski | UX and project management | Michał |
| Maciek | @terleckimaciej | Backend | Olaf |
| Olaf | @leonkacpereski | Database and SQL | Maciek |

Work is tracked in [Project 1](https://github.com/orgs/geoearth-junction/projects/1). Assignments and implementation decisions belong in the issues.

## Open decisions

- Which crop, disease, representative locations and time period should be used first?
- Which available datasets and subset are needed to prove the first end-to-end flow?
- What classifications and checks establish that the data is correctly located and consistent in both clients?
- How will the team reproduce the integrated demo, and what are the limitations of the result?

These questions are intentionally open for the team to resolve in the corresponding issues.
