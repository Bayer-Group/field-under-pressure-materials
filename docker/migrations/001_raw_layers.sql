-- Migration 001: bring a database created before the raw / curated / app layering up to date.
-- A fresh database (docker/initdb/) already has this structure and does not need it.
--
-- Run once, from the repo root, against the database (e.g. through the SSH tunnel):
--   PGPASSWORD=... psql -h localhost -p 5433 -U <user> <database> -v ON_ERROR_STOP=1 -f docker/migrations/001_raw_layers.sql
--
-- It renames schema fup to raw, moves the farmer tables to app, adds the new grid columns and creates the new raw tables
-- (docker/initdb/03_raw_layers.sql). It deletes no data, and running it again changes nothing.

BEGIN;

CREATE EXTENSION IF NOT EXISTS postgis_raster;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'fup')
       AND NOT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'raw') THEN
        ALTER SCHEMA fup RENAME TO raw;
    END IF;
END $$;

CREATE SCHEMA IF NOT EXISTS raw;
COMMENT ON SCHEMA raw IS 'Organizer data as delivered (typed, deduplicated, no business logic); written by the loader';
CREATE SCHEMA IF NOT EXISTS curated;
COMMENT ON SCHEMA curated IS 'Derived tables defined by the curated layer contract; written by the transformations';
CREATE SCHEMA IF NOT EXISTS app;
COMMENT ON SCHEMA app IS 'Farmer input (parcels, fields, crop areas, sprays) and computed results; written by the backend';

DO $$
BEGIN
    IF to_regclass('raw.v_field_grid') IS NOT NULL THEN ALTER VIEW raw.v_field_grid SET SCHEMA app; END IF;
    IF to_regclass('raw.field_crop_share') IS NOT NULL THEN ALTER TABLE raw.field_crop_share SET SCHEMA app; END IF;
    IF to_regclass('raw.field') IS NOT NULL THEN ALTER TABLE raw.field SET SCHEMA app; END IF;
END $$;

ALTER TABLE raw.grid_cell ADD COLUMN IF NOT EXISTS l1_name text;
ALTER TABLE raw.grid_cell ADD COLUMN IF NOT EXISTS elevation real;

\ir ../initdb/03_raw_layers.sql

COMMIT;
