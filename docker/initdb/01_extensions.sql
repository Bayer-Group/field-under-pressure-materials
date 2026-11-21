-- Runs automatically on the first container start (empty volume).
CREATE EXTENSION IF NOT EXISTS postgis;

CREATE SCHEMA IF NOT EXISTS fup;
COMMENT ON SCHEMA fup IS 'Field Under Pressure: weather data, fields and crops (MVP)';
