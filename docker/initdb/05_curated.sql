-- Curated layer (schema curated), from docs/curated_layer_contract.md. Safe to run more than once;
-- also applied to an existing database by docker/migrations/003_curated.sql.
-- Written by scripts/build_curated.py (weather features) and the backend (per crop area); raw tables stay read-only.
-- The conclusion field is `conditions_met` (renamed from `spray_signal` in the draft): conditions favourable to the disease
-- in a susceptible stage, never an instruction to spray.

SET search_path = curated, public;

-- 1. Crop mapping: the farmer's crop choice -> CLMS CTY class code (static, filled by hand). Re-check when GET /crops is real.
CREATE TABLE IF NOT EXISTS crop_mapping (
    farmer_crop_id text PRIMARY KEY,
    label          text    NOT NULL,
    class_code     integer NOT NULL REFERENCES raw.crop_class (code)
);
INSERT INTO crop_mapping (farmer_crop_id, label, class_code) VALUES
    ('wheat', 'Wheat', 1110), ('maize', 'Maize', 1130), ('soy', 'Soybeans', 1420)
ON CONFLICT (farmer_crop_id) DO NOTHING;

-- 2. Hourly wetness features per grid cell (utc_time key; the local date is kept for joins).
CREATE TABLE IF NOT EXISTS weather_hourly_features (
    grid_id            text        NOT NULL REFERENCES raw.grid_cell (grid_id),
    utc_time           timestamptz NOT NULL,
    date               date        NOT NULL,            -- local calendar day
    local_time         timestamp   NOT NULL,
    relative_humidity  real,                            -- %
    precipitation      real,                            -- mm per hour (IMERG)
    temperature        real,                            -- degrees C, 2 m
    is_wet             boolean,                         -- NULL = unknown (a missing input), never "dry"
    wind_speed_2m_flag boolean     NOT NULL,            -- true when the source value is negative
    PRIMARY KEY (grid_id, utc_time)
);
CREATE INDEX IF NOT EXISTS weather_hourly_features_date_idx ON weather_hourly_features (date);

-- 3. Daily features per grid cell (local date key). t_mean comes from raw.weather_daily.avg_temperature, which equals the mean
--    of the 24 hourly values (checked: difference 0.000); the wet-hour columns exist only where hourly data is loaded.
CREATE TABLE IF NOT EXISTS weather_daily_features (
    grid_id              text NOT NULL REFERENCES raw.grid_cell (grid_id),
    date                 date NOT NULL,
    t_mean               real,                          -- degrees C
    gdd3                 real,                          -- degree-days: max(t_mean - base, 0)
    wet_hours            integer,                       -- hours with is_wet = true
    valid_hours          integer,                       -- hours with is_wet not NULL
    expected_hours       integer,                       -- 24, or 23 / 25 on clock-change days
    coverage             real,                          -- valid_hours / expected_hours
    gdd_since_resumption real,                          -- sum of gdd3 from the resumption date; NULL before it or if none
    PRIMARY KEY (grid_id, date)
);

-- 4. Vegetation resumption per cell and year (first day after 1 Feb from which t_mean >= 3 holds for 5 consecutive days).
CREATE TABLE IF NOT EXISTS vegetation_resumption (
    grid_id         text    NOT NULL REFERENCES raw.grid_cell (grid_id),
    year            integer NOT NULL,
    resumption_date date,                               -- NULL if not found
    PRIMARY KEY (grid_id, year)
);

-- 5. What the crop map says grows inside a crop area (kept separately from the farmer's crop, never overwriting it).
CREATE TABLE IF NOT EXISTS crop_area_crop_map (
    crop_area_id text    NOT NULL REFERENCES app.crop_area (crop_area_id) ON DELETE CASCADE,
    year         integer NOT NULL,
    class_code   integer NOT NULL REFERENCES raw.crop_class (code),
    pixel_count  bigint  NOT NULL,
    total_pixels bigint  NOT NULL,
    share        real    NOT NULL CHECK (share >= 0 AND share <= 1),
    is_map_crop  boolean NOT NULL,
    computed_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (crop_area_id, year, class_code)
);

-- 6. Soil and crop-map result per crop area (one row).
CREATE TABLE IF NOT EXISTS field_context (
    crop_area_id       text PRIMARY KEY REFERENCES app.crop_area (crop_area_id) ON DELETE CASCADE,
    soil_ph            real,
    soil_clay          real,                            -- fraction 0-1 (as in the source file)
    soil_sand          real,
    soil_silt          real,
    soil_om            real,
    soil_cec           real,
    soil_bulk_density  real,
    soil_texture       text,                            -- USDA class with the largest area share
    soil_cell_count    integer NOT NULL,                -- H3 cells intersecting the polygon
    soil_coverage      real    NOT NULL,                -- share of the polygon area covered by cells with values
    crop_map_year      integer,
    map_crop_class_code integer,
    farmer_class_code  integer,
    crop_differs       boolean,                         -- NULL if either class is NULL
    computed_at        timestamptz NOT NULL DEFAULT now()
);

-- 7. Septoria condition class per crop area and local day, with the reasons. States conditions favourable to the disease,
--    not its presence, and gives no instruction to spray.
CREATE TABLE IF NOT EXISTS risk_assessment (
    crop_area_id          text NOT NULL REFERENCES app.crop_area (crop_area_id) ON DELETE CASCADE,
    disease               text NOT NULL,                -- 'septoria' in v1
    date                  date NOT NULL,                -- local day
    grid_id               text NOT NULL REFERENCES raw.grid_cell (grid_id),
    h_hours               integer,                      -- longest run of wet hours in the window
    h_low                 integer,                      -- H when missing hours count as dry
    h_high                integer,                      -- H when missing hours count as wet
    risk_class            text CHECK (risk_class IN ('low', 'medium', 'high')),
    status                text NOT NULL CHECK (status IN
                              ('ok', 'uncertain', 'out_of_window', 'protected', 'insufficient_data', 'stage_unknown')),
    threshold_medium      integer NOT NULL,
    threshold_high        integer NOT NULL,
    coverage              real    NOT NULL,             -- valid hours / window hours
    protected_until       date,
    growth_stage_zone     text CHECK (growth_stage_zone IN ('A', 'B', 'C')),
    growth_stage_source   text CHECK (growth_stage_source IN ('calendar', 'estimated', 'override')),
    gdd_since_resumption  real,
    conditions_met        boolean NOT NULL,             -- class high, zone B or C, not protected
    reasons               jsonb   NOT NULL,
    computed_at           timestamptz NOT NULL DEFAULT now(),
    model_version         text    NOT NULL,
    input_hash            text    NOT NULL,
    PRIMARY KEY (crop_area_id, disease, date)
);
CREATE INDEX IF NOT EXISTS risk_assessment_date_idx ON risk_assessment (date);
