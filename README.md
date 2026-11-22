# Field Under Pressure · GeoEarth Junction

Weather-driven crop disease risk and spray windows for farmers, built at the
[Field Under Pressure](https://geo-hackathon.g.location360.ag/) hackathon (20–22 November 2026).

The prototype shows a farmer when the weather has favoured **septoria in winter wheat** on their fields, and when the next hours
may be a suitable window to **consider** a treatment. It states conditions, not a diagnosis, and never tells anyone to spray:
the decision stays with the farmer or agronomist.

**Documentation:** <https://geoearth-junction.github.io/field-under-pressure-materials/> (source in [`docs/`](docs/index.md))

## What it does

- **Septoria risk** per crop area and day, from wet hours, the estimated growth stage and recorded sprays, with the reason
  behind every level.
- **Risk heatmap** of the voivodeship on the 4 km weather grid.
- **Spray window:** up to three weather windows in the next 72 hours (wind, gusts, temperature, rain), ranked by margin.
- **Farmer input:** parcels from GUGiK ULDK, crop areas drawn on the map, sowing dates and sprays, with a no-login sandbox.
- **Two clients, one API:** a web map (MapLibre GL JS) for farmers and a QGIS plugin for analysts.

Demo data: the real weather of 2024 in Mazowieckie, replayed so that it looks current. See [Risk models](docs/risk-models.md)
for the rules, the origin of every threshold and the limits of the prototype.

## Quick start

```bash
# web map (talks to the deployed demo API)
cd web && python -m http.server 5500          # open http://localhost:5500

# backend (needs DATABASE_URL, see the documentation)
pip install -r backend/requirements.txt
python -m uvicorn backend.app.main:app --reload --port 8000

# tests (no database, no network)
python -m unittest discover -s tests -p "test_*.py" -v
```

Details, including the database tunnel and the QGIS plugin: [Getting started](docs/getting-started.md).

## Repository layout

| Path | Contents |
| --- | --- |
| [`backend/`](backend/) | FastAPI application: endpoints, services, domain rules, connectors to public APIs |
| [`web/`](web/) | the farmer's web map (static HTML and JavaScript, no build step) |
| [`qgis_plugin/`](qgis_plugin/) | the QGIS plugin for analysts |
| [`shared/`](shared/) | Pydantic schemas and CRS constants shared by the backend and the plugin |
| [`config/`](config/) | thresholds of the risk models (TOML) |
| [`docker/`](docker/) | PostGIS schema, migrations, Docker Compose and VM notes |
| [`scripts/`](scripts/) | data loading and curation, VM provisioning, plugin packaging, test runners |
| [`tests/`](tests/) | unit tests |
| [`docs/`](docs/) | documentation (GitHub Pages) and the agreed contracts |
| [`bayer/`](bayer/) | the organizer's original hackathon materials, unchanged |

## Documentation

| | |
| --- | --- |
| [Architecture](docs/architecture.md) | data flow from organizer files to the map, database layers, demo clock |
| [Risk models](docs/risk-models.md) | septoria and spray window rules |
| [API](docs/api.md) | endpoints, authentication, sandbox |
| [Deployment](docs/deployment.md) | the VM, migrations and deploying the backend |
| [Data sources](docs/data-sources.md) | organizer datasets and public registers |
| [Project requirements](docs/PROJECT.md) | goals, first iteration, open decisions |

## Contributing

Work starts from an issue, on a branch, through a pull request to `team/geoearth-junction`. The conventions for branches,
commits and AI assistants are in [`CONTRIBUTING.md`](CONTRIBUTING.md) and [`AGENTS.md`](AGENTS.md).

## Team

Michał (QGIS and spatial analysis), Wiktor (UX and project management), Maciek (backend) and Olaf (database and SQL). See
[Team](docs/team.md).

## Licence and acknowledgements

The code is released under the [MIT licence](LICENSE). The hackathon materials in [`bayer/`](bayer/) (dataset descriptions,
crop-protection methodologies, starter notebook) were provided by the organizers and keep their terms. Public data comes from
GUGiK, IMGW and Copernicus under the terms of each publisher.
