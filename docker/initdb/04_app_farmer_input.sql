-- Farmer input (schema app), from FARMER_INPUT_CONTRACT.md. Safe to run more than once;
-- also applied to an existing database by docker/migrations/002_app_farmer_input.sql.
--
--   field (a working plot) ──< field_parcel >── parcel   (the parcels the farmer selected; not proof of ownership)
--   field ──< crop_area ──< spray                        (crop areas drawn over the parcels, their sprays)
--
-- The crop reported by the map (CTY) is NOT stored here: it is derived into curated.crop_area_crop_map, so the farmer's
-- value is never overwritten. Open: who may see which fields (owner_id is a placeholder until isolation is decided).

SET search_path = app, public;

-- 1. field: the working plot of the farmer. The table exists since 02_schema.sql (one polygon per field, used by the
--    loader's --fields demo option); here it becomes the plot that groups parcels and crop areas.
ALTER TABLE field ALTER COLUMN geom DROP NOT NULL;            -- optional outline; the crop areas hold the geometry
ALTER TABLE field ADD COLUMN IF NOT EXISTS owner_id    text;  -- placeholder for isolation (open decision)
ALTER TABLE field ADD COLUMN IF NOT EXISTS data_status text NOT NULL DEFAULT 'mock';
ALTER TABLE field ADD COLUMN IF NOT EXISTS created_at  timestamptz NOT NULL DEFAULT now();
ALTER TABLE field ADD COLUMN IF NOT EXISTS updated_at  timestamptz NOT NULL DEFAULT now();
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'field_data_status_check') THEN
        ALTER TABLE field ADD CONSTRAINT field_data_status_check CHECK (data_status IN ('mock', 'replay', 'live'));
    END IF;
END $$;
COMMENT ON COLUMN field.data_status IS 'mock, replay or live; mock data must never be shown as real';

-- 2. parcel: a cadastral parcel (from the parcel lookup). Geometry in EPSG:4326, longitude/latitude.
CREATE TABLE IF NOT EXISTS parcel (
    parcel_id     text PRIMARY KEY,
    parcel_number text,
    source        text,                                      -- e.g. 'uldk' or 'mock'
    geom          geometry(Geometry, 4326) NOT NULL,
    CONSTRAINT parcel_geom_polygonal CHECK (GeometryType(geom) IN ('POLYGON', 'MULTIPOLYGON'))
);
CREATE INDEX IF NOT EXISTS parcel_geom_gix ON parcel USING gist (geom);
CREATE INDEX IF NOT EXISTS parcel_number_idx ON parcel (parcel_number);

-- 3. field_parcel: the parcels the farmer selected as working plots (a working association, not ownership).
CREATE TABLE IF NOT EXISTS field_parcel (
    field_id  text NOT NULL REFERENCES field (field_id) ON DELETE CASCADE,
    parcel_id text NOT NULL REFERENCES parcel (parcel_id),
    PRIMARY KEY (field_id, parcel_id)
);

-- 4. crop_area: an area drawn over the parcels, with the crop and the sowing date entered by the farmer.
--    Required before saving: geometry, farmer crop, sowing date (an unfilled form is not a saved record).
CREATE TABLE IF NOT EXISTS crop_area (
    crop_area_id   text PRIMARY KEY,
    field_id       text NOT NULL REFERENCES field (field_id) ON DELETE CASCADE,
    geom           geometry(Geometry, 4326) NOT NULL,
    farmer_crop_id text NOT NULL,                            -- id from GET /crops (see curated.crop_mapping)
    sowing_date    date NOT NULL,                            -- calendar day, no time
    CONSTRAINT crop_area_geom_polygonal CHECK (GeometryType(geom) IN ('POLYGON', 'MULTIPOLYGON'))
);
CREATE INDEX IF NOT EXISTS crop_area_geom_gix ON crop_area USING gist (geom);
CREATE INDEX IF NOT EXISTS crop_area_field_idx ON crop_area (field_id);

-- 5. spray: a past spray of a crop area. An empty list (no rows) is valid. Several sprays on one day are not
--    forbidden (open question in the contract).
CREATE TABLE IF NOT EXISTS spray (
    spray_id                 bigserial PRIMARY KEY,
    crop_area_id             text    NOT NULL REFERENCES crop_area (crop_area_id) ON DELETE CASCADE,
    spray_date               date    NOT NULL,
    protection_duration_days integer NOT NULL CHECK (protection_duration_days > 0)
);
CREATE INDEX IF NOT EXISTS spray_crop_area_idx ON spray (crop_area_id, spray_date);
