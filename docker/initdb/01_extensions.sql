-- Uruchamiane automatycznie przy pierwszym starcie kontenera (pusty wolumen).
CREATE EXTENSION IF NOT EXISTS postgis;

CREATE SCHEMA IF NOT EXISTS fup;
COMMENT ON SCHEMA fup IS 'Field Under Pressure: dane pogodowe, pola i uprawy (MVP)';
