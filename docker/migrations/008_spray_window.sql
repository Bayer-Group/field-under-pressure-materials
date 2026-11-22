-- Migration 008: serve.spray_weather_hourly, the hourly weather of the spray window (docker/initdb/06_serve.sql).
-- Requires migration 004 (schema serve, serve.shift_days()). A fresh database (docker/initdb/) already has this view.
--
-- Run once, from the repo root:
--   PGPASSWORD=... psql -h localhost -p 5433 -U <user> <database> -v ON_ERROR_STOP=1 -f docker/migrations/008_spray_window.sql
-- It deletes no data, and running it again changes nothing.

BEGIN;
CREATE OR REPLACE VIEW serve.spray_weather_hourly AS
SELECT w.grid_id,
       w.utc_time + make_interval(days => sh.s)   AS utc_time,
       w.local_time + make_interval(days => sh.s) AS local_time,
       w.temperature,
       w.precipitation,
       w.wind_speed / 3.6                         AS wind_speed_ms,
       w.wind_gust / 3.6                          AS wind_gust_ms
FROM raw.weather_hourly w
CROSS JOIN (SELECT serve.shift_days() AS s) sh;
COMMENT ON VIEW serve.spray_weather_hourly IS 'Hourly weather of the spray window: wind and gusts in m/s, times shifted for the demo';
COMMIT;
