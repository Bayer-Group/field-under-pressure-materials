-- Runs automatically on the first container start (empty volume).
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_raster;          -- crop map tiles (raw.cropland_cty)

-- Layers (see docker/RAW_SCHEMA.md)
CREATE SCHEMA IF NOT EXISTS raw;
COMMENT ON SCHEMA raw IS 'Organizer data as delivered (typed, deduplicated, no business logic); written by the loader';
CREATE SCHEMA IF NOT EXISTS curated;
COMMENT ON SCHEMA curated IS 'Derived tables defined by the curated layer contract; written by the transformations';
CREATE SCHEMA IF NOT EXISTS app;
COMMENT ON SCHEMA app IS 'Farmer input (parcels, fields, crop areas, sprays) and computed results; written by the backend';
