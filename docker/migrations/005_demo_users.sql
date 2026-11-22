-- Migration 005: demo users of the API (docker/initdb/07_demo_users.sql).
-- Requires migration 002 (schema app). A fresh database (docker/initdb/) already has this structure.
--
-- Run once, from the repo root:
--   PGPASSWORD=... psql -h localhost -p 5433 -U <user> <database> -v ON_ERROR_STOP=1 -f docker/migrations/005_demo_users.sql
-- It deletes no data, and running it again changes nothing.

BEGIN;
\ir ../initdb/07_demo_users.sql
COMMIT;
