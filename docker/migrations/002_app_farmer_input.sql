-- Migration 002: farmer input tables in schema app (docker/initdb/04_app_farmer_input.sql).
-- Requires migration 001 (the app schema and app.field). A fresh database (docker/initdb/) already has this structure.
--
-- Run once, from the repo root:
--   PGPASSWORD=... psql -h localhost -p 5433 -U <user> <database> -v ON_ERROR_STOP=1 -f docker/migrations/002_app_farmer_input.sql
-- It deletes no data, and running it again changes nothing.

BEGIN;
\ir ../initdb/04_app_farmer_input.sql
COMMIT;
