-- Migration 008: the cells of serve.grid_risk_daily tile the plane (docker/initdb/06_serve.sql).
-- The view is replaced (same columns): the cells are the rectangles of half a grid step (0.022 degrees) around the nodes of the nominal
-- lattice instead of 4 x 4 km squares around the points, which overlapped east-west and left gaps north-south. A fresh database (docker/initdb/) already has this view.
--
-- Run once, from the repo root:
--   PGPASSWORD=... psql -h localhost -p 5433 -U <user> <database> -v ON_ERROR_STOP=1 -f docker/migrations/008_grid_cells.sql
-- It deletes no data, and running it again changes nothing.

BEGIN;
\ir ../initdb/06_serve.sql
COMMIT;
