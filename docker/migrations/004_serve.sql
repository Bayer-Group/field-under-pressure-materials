-- Migration 004: the serving layer (docker/initdb/06_serve.sql): schema serve, the change log, the cell-day table and the demo shift.
-- Requires migrations 001-003 (raw, app and curated tables). A fresh database (docker/initdb/) already has this structure.
--
-- Run once, from the repo root:
--   PGPASSWORD=... psql -h localhost -p 5433 -U <user> <database> -v ON_ERROR_STOP=1 -f docker/migrations/004_serve.sql
-- It deletes no data, and running it again changes nothing.

BEGIN;
\ir ../initdb/06_serve.sql
COMMIT;
