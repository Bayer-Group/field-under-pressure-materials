-- Schemat MVP: pogoda godzinowa (siatka 4 km) + pola + uprawy.
-- Kolumny pogodowe 1:1 z data/weather.md (jednostki metryczne). NULL ze źródła zostaje NULL (nie 0).
-- Dane są ładowane z oryginalnymi datami. Przesunięcie czasu (time shift) robimy PO załadowaniu,
-- w bazie (UPDATE), a zastosowane przesunięcie zapisujemy w fup.ingest_log.time_shift,
-- żeby wiadomo było, że daty nie są oryginalne.

SET search_path = fup, public;

-- 1. Siatka pogodowa 4 km (tabela grid_table z paczki weather_grids.zip: tylko punkty/środki komórek).
CREATE TABLE grid_cell (
    grid_id   text PRIMARY KEY,
    lat       double precision NOT NULL,
    lon       double precision NOT NULL,
    geom      geometry(Point, 4326) NOT NULL,
    geohash4  text,
    time_zone text
);
-- Indeks geograficzny: wyszukiwanie najbliższej komórki w metrach (a nie w stopniach).
CREATE INDEX grid_cell_geog_gix ON grid_cell USING gist ((geom::geography));

-- 2. Pogoda godzinowa (hourly_table). Klucz (grid_id, utc_time) obsługuje zapytania o szereg dla komórki.
CREATE TABLE weather_hourly (
    grid_id                   text        NOT NULL REFERENCES grid_cell (grid_id),
    date                      date        NOT NULL,           -- lokalna data kalendarzowa
    utc_time                  timestamptz NOT NULL,
    local_time                timestamp   NOT NULL,           -- czas lokalny (bez strefy)
    temperature               real,   -- °C, 2 m
    dew_point_temperature     real,   -- °C, 2 m
    precipitation             real,   -- mm w godzinie
    wind_speed                real,   -- km/h, 10 m
    wind_direction            real,   -- ° azymut, 10 m
    wind_gust                 real,   -- km/h, 10 m
    wind_speed_2m             real,   -- km/h, 2 m
    relative_humidity         real,   -- %
    downward_solar_radiation  real,   -- MJ/m2/h
    net_solar_radiation       real,   -- MJ/m2/h
    atmospheric_pressure      real,   -- mbar
    total_cloud_cover         real,   -- ułamek 0-1
    snow_depth                real,   -- mm ekwiwalentu wodnego
    snow_density              real,   -- kg/m3
    soil_temperature_level_1  real,   -- °C, 0-7 cm
    soil_temperature_level_2  real,   -- °C, 7-28 cm
    soil_temperature_level_3  real,   -- °C, 28-100 cm
    soil_temperature_level_4  real,   -- °C, 100-289 cm
    soil_moisture_level_1     real,   -- m3/m3
    soil_moisture_level_2     real,
    soil_moisture_level_3     real,
    soil_moisture_level_4     real,
    eto                       real,   -- mm/h, ewapotranspiracja referencyjna (trawa)
    etr                       real,   -- mm/h, ewapotranspiracja referencyjna (lucerna)
    PRIMARY KEY (grid_id, utc_time)
);
-- Snapshot dla całej Polski w danej chwili (zapytania po czasie bez grid_id).
CREATE INDEX weather_hourly_utc_time_idx ON weather_hourly (utc_time);

-- 3. Legenda klas upraw CLMS CTY (data/cropland.md).
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

-- 4. Pola (np. pola jednego rolnika). Źródło dowolne (GeoJSON, ULDK...), zapisane w kolumnie source.
CREATE TABLE field (
    field_id text PRIMARY KEY,
    name     text,
    source   text,
    geom     geometry(Geometry, 4326) NOT NULL,
    CONSTRAINT field_geom_polygonal CHECK (GeometryType(geom) IN ('POLYGON', 'MULTIPOLYGON'))
);
CREATE INDEX field_geom_gix ON field USING gist (geom);

-- Reguła przypisania pola do komórki pogodowej: centroid pola -> najbliższa komórka 4 km, bez interpolacji.
CREATE VIEW v_field_grid AS
SELECT f.field_id, g.grid_id
FROM field f
CROSS JOIN LATERAL (
    SELECT c.grid_id
    FROM grid_cell c
    ORDER BY c.geom::geography <-> ST_Centroid(f.geom)::geography
    LIMIT 1
) g;

-- 5. Udział klas upraw w polu (z rastra CTY 10 m, liczony przy ładowaniu).
CREATE TABLE field_crop_share (
    field_id    text    NOT NULL REFERENCES field (field_id) ON DELETE CASCADE,
    year        integer NOT NULL,
    class_code  integer NOT NULL REFERENCES crop_class (code),
    pixel_count bigint  NOT NULL,
    share       real    NOT NULL CHECK (share >= 0 AND share <= 1),
    PRIMARY KEY (field_id, year, class_code)
);

-- 6. Pochodzenie danych: co, skąd, ile wierszy i jakie przesunięcie czasu zastosowano.
CREATE TABLE ingest_log (
    id          bigserial PRIMARY KEY,
    dataset     text        NOT NULL,   -- np. 'weather_hourly', 'grid_cell', 'cropland'
    source_file text,                   -- np. weather_hourly_2025_Mazowieckie.zip
    source_year integer,
    row_count   bigint,
    time_shift  interval,               -- przesunięcie zastosowane po załadowaniu; NULL = bez przesunięcia
    loaded_at   timestamptz NOT NULL DEFAULT now(),
    note        text
);
