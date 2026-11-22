-- Migration 010: user accounts with a login and a password (docker/initdb/08_user_accounts.sql).
-- Requires migration 002 (schema app). A fresh database (docker/initdb/) already has this table.
--
-- Run once, from the repo root:
--   PGPASSWORD=... psql -h localhost -p 5433 -U <user> <database> -v ON_ERROR_STOP=1 -f docker/migrations/010_user_accounts.sql
-- It deletes no data, and running it again changes nothing.

BEGIN;
\ir ../initdb/08_user_accounts.sql
COMMIT;
