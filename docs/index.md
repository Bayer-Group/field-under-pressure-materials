---
title: Home
layout: home
---

# Field Under Pressure

GeoEarth Junction's project for the Field Under Pressure hackathon (20–22 November 2026). It helps a farmer see when the
weather has favoured a crop disease on their fields, and when the next hours may be a suitable window to **consider** a
treatment. The farmer or agronomist makes the decision: the tool does not diagnose disease and never tells anyone to spray.

The first crop and disease is **winter wheat and septoria** in Mazowieckie. The same data reaches two clients: a web map for
the farmer and a QGIS plugin for the analyst, both reading one FastAPI backend over a PostGIS database.

## What is in the prototype

| Feature | Status |
| --- | --- |
| Septoria risk per crop area and day (wet hours, growth stage, spray protection) | working, demo data 2024 |
| Risk heatmap of the voivodeship (grid cells) | working |
| Spray window: up to three weather windows in the next 72 hours | backend and API client working, no UI yet |
| Farmer input: parcels from GUGiK ULDK, crop areas, sowing dates, sprays | working in the sandbox |
| QGIS plugin reading the same API | working |

The demo replays the real weather of 2024, shifted so that the data looks current ("replay"). See
[Risk models](risk-models.md) for what each value means and what it cannot say.

## Documentation

| Page | For whom |
| --- | --- |
| [Getting started](getting-started.md) | run the backend, the web map, the tests and the QGIS plugin locally |
| [Architecture](architecture.md) | how data flows from the organizer files to the map, and where the code lives |
| [Risk models](risk-models.md) | the septoria rules and the spray window rules, with the origin of every threshold |
| [API](api.md) | the endpoints, authentication and the sandbox |
| [Deployment](deployment.md) | the VM, database migrations and deploying the backend |
| [Data sources](data-sources.md) | the organizer datasets and the public Polish registers |
| [Team](team.md) | who works on what |

## Contracts and specifications

The detailed, agreed specifications stay as separate documents:

- [Project requirements](PROJECT.md): goals, first iteration and open decisions
- [Read contract of the API (serve)](serve_read_contract.md)
- [Curated layer contract](curated_layer_contract.md): the database tables behind the risk
- [Farmer input contract](FARMER_INPUT_CONTRACT.md) and [geometry validation contract](GEOMETRY_VALIDATION_CONTRACT.md)
- [Live sandbox integration](LIVE_SANDBOX_INTEGRATION.md) and [mock API guide](MOCK_API_GUIDE.md)
- [Data pipeline notes](DATA_PIPELINE_NOTES.md)

Source code: [github.com/geoearth-junction/field-under-pressure-materials](https://github.com/geoearth-junction/field-under-pressure-materials).
