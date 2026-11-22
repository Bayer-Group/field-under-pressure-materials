# PostGIS database (layers `raw`, `curated`, `app`)

The database behind the backend (FastAPI) for weather data, fields and crops. PostgreSQL 15 + PostGIS 3.3 in Docker.
Source of truth for the structure: [`initdb/02_schema.sql`](initdb/02_schema.sql). Module rules: [`AGENTS.md`](AGENTS.md).
All organizer layers (weather, soil, crop map) and the `raw` / `curated` / `app` layering are described in [`RAW_SCHEMA.md`](RAW_SCHEMA.md).

## Start

From the repo root:

```bash
cp example.env .env        # set your own values, in particular the password (.env is in .gitignore)
docker compose --env-file .env -f docker/docker-compose.yml up -d postgis
```

The schema is created automatically **only on the first start with an empty volume**. After changing files in `initdb/`
the database has to be recreated (`down -v`, see below). The first start takes a few seconds; check readiness with:

```bash
set -a; source .env; set +a
docker exec spatial_postgis psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c '\dt raw.*'   # 8 tables
```

## Connection

| Parameter | Value |
| --- | --- |
| host | `localhost` (or the server address) |
| port | `POSTGRES_PORT` from `.env` (default 5432) |
| database | `POSTGRES_DB` from `.env` |
| user / password | `POSTGRES_USER` / `POSTGRES_PASSWORD` from `.env` |
| schema | `raw` (organizer data), `app` (farmer data) |

- psql: `docker exec -it spatial_postgis psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"`
- QGIS: Layer → Add PostGIS layer, schemas `raw` and `app` (e.g. `raw.grid_cell`, `app.field`).
- On a shared server do not expose the database port to the internet (SSH tunnel / VPN) and set your own password.

## Existing database from before the layering

A database created before the `raw` / `curated` / `app` layering (schema `fup`) is brought up to date once with
[`migrations/001_raw_layers.sql`](migrations/001_raw_layers.sql); it renames `fup` to `raw`, moves the farmer tables to `app`
and adds the new tables, without deleting data. A fresh database already has the new structure.

## Rules adopted in the schema

- MVP scope: Mazowieckie, weather for 2024-05-01 … 2024-06-30, **4 km** grid, soil and the crop map for the whole voivodeship.
- Coordinates in **EPSG:4326**.
- No interpolation: a field gets the value of the cell its centroid falls into (view `v_field_grid`).
- Missing source values stay `NULL` (never 0). The source sets `null` for out-of-range values.
- Data is loaded with its original dates. The time shift is done **after loading** (a separate task) and recorded in
  `ingest_log.time_shift`.

## Tables

The raw tables for daily weather (`raw.weather_daily`), IMERG (`raw.imerg_daily`), soil (`raw.soil_h3`) and the crop raster
(`raw.cropland_cty`) are described in [`RAW_SCHEMA.md`](RAW_SCHEMA.md); the DDL is in [`initdb/03_raw_layers.sql`](initdb/03_raw_layers.sql).

### `raw.grid_cell`: 4 km weather grid
Source: `grid_table` from `weather_grids.zip`. The source has points only (cell centres), no polygons.

| Column | Type | Notes |
| --- | --- | --- |
| `grid_id` | text, **PK** | cell identifier |
| `lat`, `lon` | double precision | WGS84 |
| `geom` | geometry(Point, 4326) | built from `lon`/`lat`: `ST_SetSRID(ST_MakePoint(lon, lat), 4326)` |
| `geohash4` | text | helper, optional |
| `time_zone` | text | not in the source (always NULL) |
| `l1_name` | text | voivodeship name (from the grid file) |
| `elevation` | real | metres, constant per cell (from the weather files) |

### `raw.weather_hourly`: hourly weather
Source: `hourly_table` (parquet per voivodeship and year). Columns **1:1 with [`data/weather.md`](../data/weather.md)**, metric
units, `real` values. Key `(grid_id, utc_time)`, plus an index on `utc_time` alone.

| Column | Type | Notes |
| --- | --- | --- |
| `grid_id` | text, **PK**, FK → `grid_cell` | the cell must exist beforehand |
| `date` | date | local calendar date |
| `utc_time` | timestamptz, **PK** | load as UTC |
| `local_time` | timestamp | local time, no time zone |
| `temperature`, `dew_point_temperature` | real | °C, 2 m |
| `precipitation` | real | mm per hour |
| `wind_speed`, `wind_gust`, `wind_speed_2m` | real | km/h |
| `wind_direction` | real | degrees azimuth |
| `relative_humidity` | real | % |
| `downward_solar_radiation`, `net_solar_radiation` | real | MJ/m²/h |
| `atmospheric_pressure` | real | mbar |
| `total_cloud_cover` | real | fraction 0–1 |
| `snow_depth` | real | mm water equivalent |
| `snow_density` | real | kg/m³ |
| `soil_temperature_level_1`…`_4` | real | °C; layers 0–7, 7–28, 28–100, 100–289 cm |
| `soil_moisture_level_1`…`_4` | real | m³/m³ |
| `eto`, `etr` | real | mm/h |

### `raw.crop_class`: CLMS CTY crop class legend
Filled in by the schema (`code` → `name`, e.g. `1110` = Wheat). Source: [`data/cropland.md`](../data/cropland.md).

### `app.field`: fields (e.g. one farmer's fields)

| Column | Type | Notes |
| --- | --- | --- |
| `field_id` | text, **PK** | |
| `name` | text | |
| `source` | text | where the geometry comes from (e.g. `geojson`, `uldk`) |
| `geom` | geometry(Geometry, 4326) | POLYGON or MULTIPOLYGON only (constraint in the database) |

**View `app.v_field_grid`** `(field_id, grid_id)`: the rule "field centroid → nearest cell", computed in metres.

### `app.field_crop_share`: share of crop classes in a field
Computed from the 10 m CTY raster (e.g. zonal statistics) at load time.

| Column | Type | Notes |
| --- | --- | --- |
| `field_id` | text, **PK**, FK → `field` | |
| `year` | integer, **PK** | CTY raster year |
| `class_code` | integer, **PK**, FK → `crop_class` | |
| `pixel_count` | bigint | |
| `share` | real | 0–1 (constraint in the database) |

### Farmer input (schema `app`)
From [`FARMER_INPUT_CONTRACT.md`](../FARMER_INPUT_CONTRACT.md); DDL in [`initdb/04_app_farmer_input.sql`](initdb/04_app_farmer_input.sql)
(migration [`migrations/002_app_farmer_input.sql`](migrations/002_app_farmer_input.sql)).

| Table | One row = | Key | Notes |
| --- | --- | --- | --- |
| `app.field` | a working plot | `field_id` | `owner_id` (isolation: open), `data_status` (`mock` / `replay` / `live`), `created_at`, `updated_at`; `geom` is an optional outline |
| `app.parcel` | a cadastral parcel from the lookup | `parcel_id` | `parcel_number`, `source`, `geom` (polygon, EPSG:4326) |
| `app.field_parcel` | a parcel selected for a field | `(field_id, parcel_id)` | a working association, not proof of ownership |
| `app.crop_area` | an area drawn over the parcels | `crop_area_id` | `farmer_crop_id` and `sowing_date` are required; `geom` is a polygon; optional `bbch_override` (31, 37, 39, 51, 59; not in the farmer contract yet) |
| `app.spray` | a past spray of a crop area | `spray_id` | `spray_date` and `protection_duration_days` (> 0); no rows = no sprays |

The crop reported by the crop map is **not** stored here: it is derived into the curated layer, so the farmer's value is never
overwritten. `app.field_crop_share` (one polygon per field) is the older table used by the loader's `--fields` demo option.

### Curated layer (schema `curated`)
Defined by [`../docs/curated_layer_contract.md`](../docs/curated_layer_contract.md); DDL in [`initdb/05_curated.sql`](initdb/05_curated.sql)
(migration [`migrations/003_curated.sql`](migrations/003_curated.sql)); rules and thresholds in [`../config/septoria.toml`](../config/septoria.toml).
Raw tables stay read-only; these tables are derived from them.

| Table | One row = | Built by |
| --- | --- | --- |
| `curated.weather_hourly_features` | grid cell × hour (`is_wet`, flags) | `scripts/build_curated.py weather` |
| `curated.weather_daily_features` | grid cell × local day (`t_mean`, `gdd3`, wet hours, coverage, `gdd_since_resumption`) | `scripts/build_curated.py weather` |
| `curated.vegetation_resumption` | grid cell × year | `scripts/build_curated.py weather` |
| `curated.crop_mapping` | farmer crop → CTY class code (filled by hand) | the DDL |
| `curated.crop_area_crop_map`, `curated.field_context`, `curated.risk_assessment` | per crop area (and day) | `scripts/refresh_crop_area.py` (the backend calls it when a farmer saves a crop area) |

`python scripts/build_curated.py weather` (connection string in `LOAD_DB_DSN`, like the loader) is repeatable: each run rewrites
its range or year in one transaction. `t_mean` comes from `raw.weather_daily.avg_temperature`, which equals the mean of the hourly values.

### Serving layer (schema `serve`)
The only place the API, the farmer front end and QGIS read from ([`initdb/06_serve.sql`](initdb/06_serve.sql), migration
[`migrations/004_serve.sql`](migrations/004_serve.sql)). Stored data keeps the time of the data (2024); the views add one demo shift
to every date, so a reader sees "today" and needs no knowledge of it. Dates a farmer writes (sowing, spray) are translated back by the API.

| View | One row = |
| --- | --- |
| `serve.crop_area` | crop area: geometry, owner, farmer crop, soil and crop-map context |
| `serve.risk_daily` | crop area × day: class, status, `conditions_met`, growth stage, reasons |
| `serve.crop_area_today` | crop area with the assessment of today (the map layer of a farmer) |
| `serve.risk_change_log` | a change of class, status or `conditions_met` (from `curated.risk_change`) |
| `serve.grid_risk_daily` | grid cell × day: the cell (a rectangle of 0.044°, tiling the plane) and its class for the whole voivodeship (analysts) |
| `serve.spray_weather_hourly` | grid cell × hour: temperature, precipitation, wind and gusts in m/s, for the spray window (migration 011) |
| `serve.clock` | the current shift |

The shift is one row, `serve.demo_time`: `pinned` (today shows the data day `pinned_data_date`; stable demo, default 2024-05-20) or
`offset` (a constant `offset_days`; the data moves one day per day). Example, before a demo:
`UPDATE serve.demo_time SET mode = 'pinned', pinned_data_date = '2024-05-20', updated_at = now();`
`python scripts/build_curated.py cells` fills `curated.septoria_cell_day` after `weather`.

### `raw.ingest_log`: data provenance
One row per loaded dataset/file: `dataset`, `source_file`, `source_year`, `row_count`, `time_shift`, `note`
(`id` and `loaded_at` are filled automatically).

## Loading data (the loader)

`scripts/load_db.py` loads the organizer data into the raw tables (it never creates or alters tables). Settings are in
[`../config/load_db.toml`](../config/load_db.toml); the connection string comes from the environment, never from a file:

```bash
pip install pyarrow numpy rasterio "psycopg[binary]"         # loader dependencies (also in requirements.txt)
export LOAD_DB_DSN="postgresql://<user>:<password>@localhost:5433/<database>"     # through the SSH tunnel, see VM.md
python scripts/load_db.py --raw <folder with raw data> --dry-run                    # the plan, no database access
python scripts/load_db.py --raw <raw> --voiv mazowieckie --months 5-6 --tiles 0,7,13,14,22,23,24,28,33,35,36,42,43,44,46
```

- Order (foreign keys): `grid_cell` → `weather_hourly`, `weather_daily`, `imerg_daily` → `soil_h3`, `cropland_cty` → `field` → `field_crop_share`.
  `crop_class` is filled in by the schema. A re-run skips the files already in `raw.ingest_log` (`--mode replace` reloads a table).
- Column names match the parquet files by name, case-insensitively. Exceptions: `geom` of `grid_cell` is built from `lat`/`lon`;
  `elevation` and `l1_name` of `grid_cell` come from the weather and grid files; in `soil_h3` the geometries (WKB in the file) are
  stored as PostGIS geometry and `soilTexture` becomes `soil_texture`.
- The crop raster (`cropland_cty`) is sent as a losslessly compressed GeoTIFF (150–250 MB becomes 2–6 MB) and converted to
  256×256 raster tiles by the server (`ST_FromGDALRaster`, `ST_Tile`); no files on the VM and no `raster2pgsql`.
- Duplicate rows `(grid_id, utc_time)` or `(grid_id, date)` inside a file are loaded once and counted in the load report.
- Times are loaded as UTC (the loader sets the session time zone). `NULL` stays `NULL`; gaps are never filled.
- For a whole voivodeship of soil, create the soil spatial indexes after loading: drop `soil_h3_geom_point_gix` and
  `soil_h3_geom_gix` before the load and recreate them afterwards (`CREATE INDEX ... USING gist`).
- Data and dumps do not go into Git (`data/**` is ignored).

## Checks after loading

```sql
SELECT count(*) FROM raw.grid_cell;
SELECT count(*) FROM raw.weather_hourly;
SELECT min(utc_time), max(utc_time) FROM raw.weather_hourly;
SELECT count(*) FROM raw.weather_daily;   SELECT count(*) FROM raw.imerg_daily;
SELECT count(*) FROM raw.soil_h3;         SELECT count(DISTINCT tile), count(*) FROM raw.cropland_cty;
SELECT * FROM app.v_field_grid;                -- field -> cell
SELECT utc_time, temperature FROM raw.weather_hourly
 WHERE grid_id = '<id>' AND utc_time BETWEEN '<from>' AND '<to>' ORDER BY 1;   -- series for a cell
```

## Server (VM on GCP)

The machine with the database is created and operated by [`../scripts/provision_vm.sh`](../scripts/provision_vm.sh)
(requires `gcloud` and a configuration with an account and a project, `geoearth` by default):

```bash
scripts/provision_vm.sh create     # create the VM (billable, asks for confirmation; DRY_RUN=1 only prints the commands)
scripts/provision_vm.sh setup      # Docker, repo clone, .env with a random password, start PostGIS
scripts/provision_vm.sh tunnel     # SSH tunnel: localhost:5433 -> database on the VM
scripts/provision_vm.sh status|start|stop
```

- The database port (5432) is **not** open in the GCP firewall; access only through an SSH tunnel.
- The database password is generated on the VM and stays in `.env` there (it does not go into the repo or onto the screen).
- `setup` clones branch `BRANCH` (default `team/geoearth-junction`), so `docker/initdb/` must already be in it.
- Data is moved with a dump (see below) instead of loading from scratch.
- How to log in, start and stop the machine, SSH in and use the tunnel: [`VM.md`](VM.md).

## Reset and backup

```bash
# Reset (DELETES the data in the database); required after changing initdb/
docker compose --env-file .env -f docker/docker-compose.yml down -v

# Backup and restore (e.g. moving to a server instead of loading again)
docker exec spatial_postgis pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB" > fup.dump
docker exec -i spatial_postgis pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists < fup.dump
```
