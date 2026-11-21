# Data layers (catalog) in the QGIS plugin

The **Data layers** group in the *Field Under Pressure* panel lets you choose which
layers to load instead of loading everything.

1. **Load catalog from backend** (`GET {Base URL}/catalog`) or **Open catalog file…** (JSON).
2. Tick the layers you want in the list (tooltips show source, format and known gaps).
3. **Add selected layers**. Files are checked in a background task first; failures go to Details / Log Messages.
4. **Add local files…** adds any .tif/.tiff, .geojson/.json/.gpkg/.shp or .csv without a catalog.

## Catalog shape (PROPOSAL, not yet agreed with the backend team)

```json
{"layers": [{"id": "soil_ph", "title": "Soil pH 0-15 cm", "kind": "raster|vector|table",
             "format": "cog|geojson|gpkg|csv", "href": "data/soil_ph.tif",
             "legend_qml": "legend/x.qml", "temporal": {"time_field": "sim_date"},
             "known_gaps": "...", "note": "...", "source": "..."}],
 "simulation": {"simulated": true, "shift_days": 0}}
```

- Relative `href` / `legend_qml` are resolved against the catalog location.
- Remote rasters use `/vsicurl/` and need HTTP Range support (server should answer 206).
- Vector via OGR, CSV via delimited text; `temporal.time_field` enables the QGIS temporal controller.
- Invalid entries are skipped with a warning; errors use codes such as `SERVICE_UNAVAILABLE`,
  `FILE_ERROR`, `UNSUPPORTED_FILE`, `INVALID_RESPONSE`, `LAYER_INVALID`.

Sample catalog and data: see `sample_project/` notes; a Range-capable test server is outside the repo.
The backend does not implement `/catalog` yet.
