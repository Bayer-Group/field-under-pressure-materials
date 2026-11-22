-- Migration 006: app.crop_area.sprays_confirmed (docker/initdb/04_app_farmer_input.sql).
-- NULL means the spray question was not answered; true means it was (an empty list of sprays is an answer). Existing rows stay NULL.
-- A fresh database (docker/initdb/) already has this column.
--
-- Run once, from the repo root:
--   PGPASSWORD=... psql -h localhost -p 5433 -U <user> <database> -v ON_ERROR_STOP=1 -f docker/migrations/006_sprays_confirmed.sql
-- It deletes no data, and running it again changes nothing.

BEGIN;
ALTER TABLE app.crop_area ADD COLUMN IF NOT EXISTS sprays_confirmed boolean;
COMMENT ON COLUMN app.crop_area.sprays_confirmed IS 'NULL: spray question not answered; true: answered (an empty list is an answer)';
COMMIT;
