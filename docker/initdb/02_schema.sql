-- MVP schema: hourly weather (4 km grid) + fields + crops.
-- Weather columns map 1:1 to data/weather.md (metric units). NULL from the source stays NULL (not 0).
-- Data is loaded with its original dates. The time shift is applied AFTER loading,
-- inside the database (UPDATE), and the applied shift is recorded in fup.ingest_log.time_shift
-- so it is clear that the dates are not the original ones.

SET search_path = fup, public;

-- 1. 4 km weather grid (grid_table from weather_grids.zip: points / cell centres only).
CREATE TABLE grid_cell (
    grid_id   text PRIMARY KEY,
    lat       double precision NOT NULL,
    lon       double precision NOT NULL,
    geom      geometry(Point, 4326) NOT NULL,
    geohash4  text,
    time_zone text
);
-- Geography index: nearest-cell lookup in metres (not degrees).
CREATE INDEX grid_cell_geog_gix ON grid_cell USING gist ((geom::geography));

-- 2. Hourly weather (hourly_table). The key (grid_id, utc_time) serves "series for a cell" queries.
CREATE TABLE weather_hourly (
    grid_id                   text        NOT NULL REFERENCES grid_cell (grid_id),
    date                      date        NOT NULL,           -- local calendar date
    utc_time                  timestamptz NOT NULL,
    local_time                timestamp   NOT NULL,           -- local time (no time zone)
    temperature               real,   -- °C, 2 m
    dew_point_temperature     real,   -- °C, 2 m
    precipitation             real,   -- mm per hour
    wind_speed                real,   -- km/h, 10 m
    wind_direction            real,   -- degrees azimuth, 10 m
    wind_gust                 real,   -- km/h, 10 m
    wind_speed_2m             real,   -- km/h, 2 m
    relative_humidity         real,   -- %
    downward_solar_radiation  real,   -- MJ/m2/h
    net_solar_radiation       real,   -- MJ/m2/h
    atmospheric_pressure      real,   -- mbar
    total_cloud_cover         real,   -- fraction 0-1
    snow_depth                real,   -- mm water equivalent
    snow_density              real,   -- kg/m3
    soil_temperature_level_1  real,   -- °C, 0-7 cm
    soil_temperature_level_2  real,   -- °C, 7-28 cm
    soil_temperature_level_3  real,   -- °C, 28-100 cm
    soil_temperature_level_4  real,   -- °C, 100-289 cm
    soil_moisture_level_1     real,   -- m3/m3
    soil_moisture_level_2     real,
    soil_moisture_level_3     real,
    soil_moisture_level_4     real,
    eto                       real,   -- mm/h, reference evapotranspiration (grass)
    etr                       real,   -- mm/h, reference evapotranspiration (alfalfa)
    PRIMARY KEY (grid_id, utc_time)
);
-- Snapshot of the whole country at a given moment (queries by time without grid_id).
CREATE INDEX weather_hourly_utc_time_idx ON weather_hourly (utc_time);

-- 3. CLMS CTY crop class legend (data/cropland.md).
CREATE TABLE crop_class (
    code integer PRIMARY KEY,
    name text    NOT NULL
);
INSERT INTO crop_class (code, name) VALUES
    (0,     'No cropland'),
    (1110,  'Wheat'),
    (1120,  'Barley'),
    (1130,  'Maize'),
    (1140,  'Rice'),
    (1150,  'Other cereals'),
    (1210,  'Fresh vegetables'),
    (1220,  'Dry pulses'),
    (1310,  'Potatoes'),
    (1320,  'Sugar beet'),
    (1410,  'Sunflower'),
    (1420,  'Soybeans'),
    (1430,  'Rapeseed'),
    (1440,  'Flax, cotton and hemp'),
    (2100,  'Grapes'),
    (2200,  'Olives'),
    (2310,  'Fruits'),
    (2320,  'Nuts'),
    (3100,  'Unclassified arable crop'),
    (3200,  'Unclassified permanent crop'),
    (65535, 'Outside area');

-- 4. Fields (e.g. one farmer's fields). Any source (GeoJSON, ULDK...), recorded in the source column.
CREATE TABLE field (
    field_id text PRIMARY KEY,
    name     text,
    source   text,
    geom     geometry(Geometry, 4326) NOT NULL,
    CONSTRAINT field_geom_polygonal CHECK (GeometryType(geom) IN ('POLYGON', 'MULTIPOLYGON'))
);
CREATE INDEX field_geom_gix ON field USING gist (geom);

-- Rule assigning a field to a weather cell: field centroid -> nearest 4 km cell, no interpolation.
CREATE VIEW v_field_grid AS
SELECT f.field_id, g.grid_id
FROM field f
CROSS JOIN LATERAL (
    SELECT c.grid_id
    FROM grid_cell c
    ORDER BY c.geom::geography <-> ST_Centroid(f.geom)::geography
    LIMIT 1
) g;

-- 5. Share of crop classes in a field (from the 10 m CTY raster, computed at load time).
CREATE TABLE field_crop_share (
    field_id    text    NOT NULL REFERENCES field (field_id) ON DELETE CASCADE,
    year        integer NOT NULL,
    class_code  integer NOT NULL REFERENCES crop_class (code),
    pixel_count bigint  NOT NULL,
    share       real    NOT NULL CHECK (share >= 0 AND share <= 1),
    PRIMARY KEY (field_id, year, class_code)
);

-- 6. Data provenance: what, from where, how many rows and which time shift was applied.
CREATE TABLE ingest_log (
    id          bigserial PRIMARY KEY,
    dataset     text        NOT NULL,   -- e.g. 'weather_hourly', 'grid_cell', 'cropland'
    source_file text,                   -- e.g. weather_hourly_2025_Mazowieckie.zip
    source_year integer,
    row_count   bigint,
    time_shift  interval,               -- shift applied after loading; NULL = no shift
    loaded_at   timestamptz NOT NULL DEFAULT now(),
    note        text
);
