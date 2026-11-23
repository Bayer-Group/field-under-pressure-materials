-- Raw layers beyond hourly weather (see docker/RAW_SCHEMA.md): daily weather, IMERG daily, soil (H3), crop raster.
-- Safe to run more than once (IF NOT EXISTS); also applied to an existing database by docker/migrations/001_raw_layers.sql.

SET search_path = raw, public;

-- 1. Daily weather (daily_table). The source also has `elevation`; it is constant per cell and lives in grid_cell.
--    Units as in bayer/data/weather.md. The daily file has no precipitation: daily precipitation is imerg_daily.
CREATE TABLE IF NOT EXISTS weather_daily (
    grid_id                          text NOT NULL REFERENCES grid_cell (grid_id),
    date                             date NOT NULL,          -- local calendar date
    min_temperature                  real,
    max_temperature                  real,
    avg_temperature                  real,
    midpoint_temperature             real,
    min_dew_point_temperature        real,
    max_dew_point_temperature        real,
    avg_dew_point_temperature        real,
    min_atmospheric_pressure         real,
    max_atmospheric_pressure         real,
    avg_atmospheric_pressure         real,
    total_downward_solar_radiation   real,
    max_downward_solar_radiation     real,
    total_net_solar_radiation        real,
    max_net_solar_radiation          real,
    avg_total_cloud_cover            real,
    avg_snow_depth                   real,
    avg_snow_density                 real,
    min_wind_speed                   real,
    max_wind_speed                   real,
    avg_wind_speed                   real,
    avg_wind_direction               real,
    max_wind_gust                    real,
    min_wind_speed_2m                real,
    max_wind_speed_2m                real,
    avg_wind_speed_2m                real,
    min_relative_humidity            real,
    max_relative_humidity            real,
    avg_relative_humidity            real,
    min_soil_temperature_level_1     real,
    min_soil_temperature_level_2     real,
    min_soil_temperature_level_3     real,
    min_soil_temperature_level_4     real,
    max_soil_temperature_level_1     real,
    max_soil_temperature_level_2     real,
    max_soil_temperature_level_3     real,
    max_soil_temperature_level_4     real,
    avg_soil_temperature_level_1     real,
    avg_soil_temperature_level_2     real,
    avg_soil_temperature_level_3     real,
    avg_soil_temperature_level_4     real,
    avg_soil_moisture_level_1        real,
    avg_soil_moisture_level_2        real,
    avg_soil_moisture_level_3        real,
    avg_soil_moisture_level_4        real,
    eto                              real,
    etr                              real,
    day_length                       real,
    PRIMARY KEY (grid_id, date)
);
CREATE INDEX IF NOT EXISTS weather_daily_date_idx ON weather_daily (date);

-- 2. NASA IMERG daily precipitation.
CREATE TABLE IF NOT EXISTS imerg_daily (
    grid_id             text NOT NULL REFERENCES grid_cell (grid_id),
    date                date NOT NULL,                       -- local calendar date
    total_precipitation real,                                -- mm per day
    PRIMARY KEY (grid_id, date)
);

-- 3. ISRIC SoilGrids (static, 250 m, H3 level 10). Names as in the file, lower-cased; soilTexture -> soil_texture.
--    Layered columns are <property>_<depth>_mean with depths 0_5cm, 5_15cm, 15_30cm, 30_60cm, 60_100cm, 100_200cm.
--    Values are kept as in the file (root-zone clay/sand/silt are fractions 0-1, not percent as bayer/data/soil.md says).
CREATE TABLE IF NOT EXISTS soil_h3 (
    h3_index_10            text PRIMARY KEY,
    hid                    bigint,
    bdod_0_5cm_mean        real,
    bdod_5_15cm_mean       real,
    bdod_15_30cm_mean      real,
    bdod_30_60cm_mean      real,
    bdod_60_100cm_mean     real,
    bdod_100_200cm_mean    real,
    cec_0_5cm_mean         real,
    cec_5_15cm_mean        real,
    cec_15_30cm_mean       real,
    cec_30_60cm_mean       real,
    cec_60_100cm_mean      real,
    cec_100_200cm_mean     real,
    cfvo_0_5cm_mean        real,
    cfvo_5_15cm_mean       real,
    cfvo_15_30cm_mean      real,
    cfvo_30_60cm_mean      real,
    cfvo_60_100cm_mean     real,
    cfvo_100_200cm_mean    real,
    clay_0_5cm_mean        real,
    clay_5_15cm_mean       real,
    clay_15_30cm_mean      real,
    clay_30_60cm_mean      real,
    clay_60_100cm_mean     real,
    clay_100_200cm_mean    real,
    nitrogen_0_5cm_mean    real,
    nitrogen_5_15cm_mean   real,
    nitrogen_15_30cm_mean  real,
    nitrogen_30_60cm_mean  real,
    nitrogen_60_100cm_mean real,
    nitrogen_100_200cm_mean real,
    ocd_0_5cm_mean         real,
    ocd_5_15cm_mean        real,
    ocd_15_30cm_mean       real,
    ocd_30_60cm_mean       real,
    ocd_60_100cm_mean      real,
    ocd_100_200cm_mean     real,
    ocs_0_30cm_mean        real,
    phh2o_0_5cm_mean       real,
    phh2o_5_15cm_mean      real,
    phh2o_15_30cm_mean     real,
    phh2o_30_60cm_mean     real,
    phh2o_60_100cm_mean    real,
    phh2o_100_200cm_mean   real,
    sand_0_5cm_mean        real,
    sand_5_15cm_mean       real,
    sand_15_30cm_mean      real,
    sand_30_60cm_mean      real,
    sand_60_100cm_mean     real,
    sand_100_200cm_mean    real,
    silt_0_5cm_mean        real,
    silt_5_15cm_mean       real,
    silt_15_30cm_mean      real,
    silt_30_60cm_mean      real,
    silt_60_100cm_mean     real,
    silt_100_200cm_mean    real,
    soc_0_5cm_mean         real,
    soc_5_15cm_mean        real,
    soc_15_30cm_mean       real,
    soc_30_60cm_mean       real,
    soc_60_100cm_mean      real,
    soc_100_200cm_mean     real,
    cec                    real,
    om                     real,
    ph                     real,
    sand                   real,
    silt                   real,
    clay                   real,
    bulk_density           real,
    band_om                text,
    band_cec               text,
    band_ph                text,
    soil_texture           text,
    geom                   geometry(Polygon, 4326),
    geom_point             geometry(Point, 4326)
);
-- Spatial indexes: for a bulk load of a whole voivodeship create them after loading (see docker/README.md).
CREATE INDEX IF NOT EXISTS soil_h3_geom_point_gix ON soil_h3 USING gist (geom_point);
CREATE INDEX IF NOT EXISTS soil_h3_geom_gix ON soil_h3 USING gist (geom);

-- 4. CLMS crop types (CTY), PostGIS raster tiles of 256x256 pixels loaded from the GeoTIFF tiles (one row per raster tile).
--    `tile` is the source file name. The tiles overlap and the padding is 0: the mosaic is built in the curated layer.
CREATE TABLE IF NOT EXISTS cropland_cty (
    rid   serial PRIMARY KEY,
    tile  text    NOT NULL,
    year  integer NOT NULL,
    rast  raster  NOT NULL
);
CREATE INDEX IF NOT EXISTS cropland_cty_rast_gix ON cropland_cty USING gist (ST_ConvexHull(rast));
CREATE INDEX IF NOT EXISTS cropland_cty_tile_idx ON cropland_cty (tile);
