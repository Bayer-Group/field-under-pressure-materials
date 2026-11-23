-- Migration 007: names of the place of a parcel (docker/initdb/04_app_farmer_input.sql): region (cadastral precinct), commune, county,
-- voivodeship, from GUGiK ULDK. Parcels stored before this migration get their names from scripts/backfill_parcel_names.py.
-- A fresh database (docker/initdb/) already has these columns.
--
-- Run once, from the repo root:
--   PGPASSWORD=... psql -h localhost -p 5433 -U <user> <database> -v ON_ERROR_STOP=1 -f docker/migrations/007_parcel_locations.sql
-- It deletes no data, and running it again changes nothing.

BEGIN;
ALTER TABLE app.parcel ADD COLUMN IF NOT EXISTS region      text;
ALTER TABLE app.parcel ADD COLUMN IF NOT EXISTS commune     text;
ALTER TABLE app.parcel ADD COLUMN IF NOT EXISTS county      text;
ALTER TABLE app.parcel ADD COLUMN IF NOT EXISTS voivodeship text;
COMMIT;
