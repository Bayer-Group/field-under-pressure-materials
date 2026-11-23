-- Migration 003: the curated layer tables (docker/initdb/05_curated.sql).
-- Requires migrations 001 and 002 (raw tables and app.crop_area). A fresh database (docker/initdb/) already has this structure.
--
-- Run once, from the repo root:
--   PGPASSWORD=... psql -h localhost -p 5433 -U <user> <database> -v ON_ERROR_STOP=1 -f docker/migrations/003_curated.sql
-- It deletes no data, and running it again changes nothing.

BEGIN;
\ir ../initdb/05_curated.sql
COMMIT;
