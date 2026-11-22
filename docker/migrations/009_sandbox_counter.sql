-- Migration 009: the counter that hands out the example farms to the sandboxes (docker/initdb/07_demo_users.sql).
-- Requires migration 005. A fresh database (docker/initdb/) already has this table.
--
-- Run once, from the repo root:
--   PGPASSWORD=... psql -h localhost -p 5433 -U <user> <database> -v ON_ERROR_STOP=1 -f docker/migrations/009_sandbox_counter.sql
-- It deletes no data, and running it again changes nothing.

BEGIN;
\ir ../initdb/07_demo_users.sql
COMMIT;
