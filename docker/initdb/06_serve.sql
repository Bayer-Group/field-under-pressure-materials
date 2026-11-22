-- Serving layer (schema serve): the only place the API, the farmer front end and QGIS read from. Safe to run more than once;
-- also applied to an existing database by docker/migrations/004_serve.sql.
-- Stored data keeps the time of the data (2024). The views add one demo shift to every date, so readers see "today" without
-- knowing anything about it (serve.demo_time, serve.shift_days()). Dates written by a farmer are translated back by the API.

CREATE SCHEMA IF NOT EXISTS serve;
COMMENT ON SCHEMA serve IS 'Read-only views for the API, front end and QGIS: dates already shifted for the demo; no business logic';

-- 1. Change log of the risk assessment (not SCD2: the day is already part of the key of curated.risk_assessment, so the date
--    slider needs no history; this table records what was recomputed and why).
CREATE TABLE IF NOT EXISTS curated.risk_change (
    change_id         bigserial PRIMARY KEY,
    crop_area_id      text NOT NULL REFERENCES app.crop_area (crop_area_id) ON DELETE CASCADE,
    disease           text NOT NULL,
    date              date NOT NULL,                     -- the day the assessment is about (data time)
    computed_at       timestamptz NOT NULL DEFAULT now(),
    reason            text NOT NULL,                     -- created, recompute, spray, sowing, weather, rules
    old_class         text,                              -- NULL on the first calculation
    new_class         text,
    old_status        text,
    new_status        text,
    old_conditions_met boolean,
    new_conditions_met boolean,
    new_input_hash    text NOT NULL
);
CREATE INDEX IF NOT EXISTS risk_change_area_idx ON curated.risk_change (crop_area_id, date, computed_at);

-- 2. Septoria per grid cell and local day (before growth stage and protection): shared by all fields in the cell.
CREATE TABLE IF NOT EXISTS curated.septoria_cell_day (
    grid_id       text NOT NULL REFERENCES raw.grid_cell (grid_id),
    date          date NOT NULL,
    h_low         integer NOT NULL,
    h_high        integer NOT NULL,
    coverage      real    NOT NULL,
    risk_class    text    NOT NULL CHECK (risk_class IN ('low', 'medium', 'high')),   -- class of h_low
    uncertain     boolean NOT NULL,                      -- the class of h_high differs
    model_version text    NOT NULL,
    computed_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (grid_id, date)
);

-- 3. The demo shift: one row. 'pinned' = today shows the data day pinned_data_date (stable demo, no drift);
--    'offset' = a constant shift of offset_days (the data moves one day per day until it runs out).
CREATE TABLE IF NOT EXISTS serve.demo_time (
    id               smallint PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    mode             text    NOT NULL DEFAULT 'pinned' CHECK (mode IN ('pinned', 'offset')),
    pinned_data_date date    DEFAULT DATE '2024-05-20',
    offset_days      integer NOT NULL DEFAULT 0,
    updated_at       timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT demo_time_pinned_needs_date CHECK (mode <> 'pinned' OR pinned_data_date IS NOT NULL)
);
INSERT INTO serve.demo_time (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

-- Days to add to a data date to get the date shown to the reader.
CREATE OR REPLACE FUNCTION serve.shift_days() RETURNS integer
LANGUAGE sql STABLE AS $$
    SELECT CASE mode WHEN 'pinned' THEN (current_date - pinned_data_date) ELSE offset_days END
    FROM serve.demo_time WHERE id = 1
$$;

-- 4. Views. Dates are shifted; computed_at stays real time.
CREATE OR REPLACE VIEW serve.clock AS
SELECT mode, current_date AS today, serve.shift_days() AS shift_days, current_date - serve.shift_days() AS data_date
FROM serve.demo_time WHERE id = 1;

CREATE OR REPLACE VIEW serve.crop_area AS
SELECT a.crop_area_id, a.field_id, f.owner_id, f.name AS field_name, f.data_status, a.farmer_crop_id,
       a.sowing_date + serve.shift_days() AS sowing_date, a.bbch_override, a.geom,
       c.soil_texture, c.soil_ph, c.soil_clay, c.soil_sand, c.soil_silt, c.soil_om, c.soil_cec, c.soil_bulk_density,
       c.soil_coverage, c.map_crop_class_code, c.farmer_class_code, c.crop_differs
FROM app.crop_area a
JOIN app.field f ON f.field_id = a.field_id
LEFT JOIN curated.field_context c ON c.crop_area_id = a.crop_area_id;

CREATE OR REPLACE VIEW serve.risk_daily AS
SELECT r.crop_area_id, r.disease, r.date + serve.shift_days() AS date, r.grid_id, r.h_hours, r.h_low, r.h_high,
       r.risk_class, r.status, r.conditions_met, r.coverage, r.protected_until + serve.shift_days() AS protected_until,
       r.growth_stage_zone, r.growth_stage_source, r.gdd_since_resumption, r.reasons, r.computed_at, r.model_version
FROM curated.risk_assessment r;

-- Every crop area with its geometry and the assessment of today (as shown to the reader).
CREATE OR REPLACE VIEW serve.crop_area_today AS
SELECT a.crop_area_id, a.field_id, a.owner_id, a.field_name, a.farmer_crop_id, a.geom,
       r.date, r.risk_class, r.status, r.conditions_met, r.h_hours, r.growth_stage_zone, r.protected_until
FROM serve.crop_area a
LEFT JOIN serve.risk_daily r ON r.crop_area_id = a.crop_area_id AND r.disease = 'septoria' AND r.date = current_date;

CREATE OR REPLACE VIEW serve.risk_change_log AS
SELECT c.change_id, c.crop_area_id, c.disease, c.date + serve.shift_days() AS date, c.computed_at, c.reason,
       c.old_class, c.new_class, c.old_status, c.new_status, c.old_conditions_met, c.new_conditions_met
FROM curated.risk_change c;

-- The whole voivodeship, per cell and day. The weather grid is regular, 0.044 degrees in both directions (about 3.0 km east-west and
-- 4.9 km north-south at 52 N); the source coordinates are rounded (the step is sometimes 0.043), so each point is put on the nominal
-- lattice (anchor and step 0.044) and a cell is the rectangle of half a step around its node, with vertices snapped to 1e-5 degrees:
-- neighbouring cells share their edges exactly, with no overlaps and no gaps. (Squares of 4 x 4 km around the points overlapped
-- east-west by 1 km and left gaps north-south.)
CREATE OR REPLACE VIEW serve.grid_risk_daily AS
WITH o AS (SELECT min(lon) AS lon0, min(lat) AS lat0 FROM raw.grid_cell)
SELECT d.grid_id, d.date + serve.shift_days() AS date, d.h_low, d.h_high, d.risk_class, d.uncertain, d.coverage,
       ST_SnapToGrid(ST_MakeEnvelope(n.x - 0.022, n.y - 0.022, n.x + 0.022, n.y + 0.022, 4326), 0.00001)::geometry(Polygon, 4326) AS geom,
       d.date AS data_date       -- the day in the time of the data: filter on this one (a filter on the shifted date calls shift_days() for every row)
FROM curated.septoria_cell_day d
JOIN raw.grid_cell g ON g.grid_id = d.grid_id
CROSS JOIN o
CROSS JOIN LATERAL (SELECT o.lon0 + round((g.lon - o.lon0) / 0.044) * 0.044 AS x, o.lat0 + round((g.lat - o.lat0) / 0.044) * 0.044 AS y) n;

-- Hourly weather for the spray window (docs/serve_read_contract.md, "Spray window"; rules in config/spray_window.toml): wind and
-- gusts in m/s (the source stores km/h), times shifted for the demo. In the demo this is the "forecast" (replay of the actual
-- weather of the next hours). No business logic: the API applies the limits.
CREATE OR REPLACE VIEW serve.spray_weather_hourly AS
SELECT w.grid_id,
       w.utc_time + make_interval(days => sh.s)   AS utc_time,
       w.local_time + make_interval(days => sh.s) AS local_time,
       w.temperature,                                           -- degrees C, 2 m
       w.precipitation,                                         -- mm per hour (IMERG)
       w.wind_speed / 3.6                         AS wind_speed_ms,   -- m/s, 10 m
       w.wind_gust / 3.6                          AS wind_gust_ms     -- m/s, 10 m
FROM raw.weather_hourly w
CROSS JOIN (SELECT serve.shift_days() AS s) sh;
