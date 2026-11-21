# PostGIS database (schema `fup`)

The database behind the backend (FastAPI) for weather data, fields and crops. PostgreSQL 15 + PostGIS 3.3 in Docker.
Source of truth for the structure: [`initdb/02_schema.sql`](initdb/02_schema.sql). Module rules: [`AGENTS.md`](AGENTS.md).

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
docker exec spatial_postgis psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c '\dt fup.*'   # 6 tables
```

## Connection

| Parameter | Value |
| --- | --- |
| host | `localhost` (or the server address) |
| port | `POSTGRES_PORT` from `.env` (default 5432) |
| database | `POSTGRES_DB` from `.env` |
| user / password | `POSTGRES_USER` / `POSTGRES_PASSWORD` from `.env` |
| schema | `fup` |

- psql: `docker exec -it spatial_postgis psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"`
- QGIS: Layer → Add PostGIS layer, schema `fup` (e.g. `grid_cell`, `field`).
- On a shared server do not expose the database port to the internet (SSH tunnel / VPN) and set your own password.

## Rules adopted in the schema

- MVP scope: **hourly** weather, **4 km** grid, a window of 1–2 months, source year 2024.
- Coordinates in **EPSG:4326**.
- No interpolation: a field gets the value of the cell its centroid falls into (view `v_field_grid`).
- Missing source values stay `NULL` (never 0). The source sets `null` for out-of-range values.
- Data is loaded with its original dates. The time shift is done **after loading** (a separate task) and recorded in
  `ingest_log.time_shift`.

## Tables

### `fup.grid_cell`: 4 km weather grid
Source: `grid_table` from `weather_grids.zip`. The source has points only (cell centres), no polygons.

| Column | Type | Notes |
| --- | --- | --- |
| `grid_id` | text, **PK** | cell identifier |
| `lat`, `lon` | double precision | WGS84 |
| `geom` | geometry(Point, 4326) | built from `lon`/`lat`: `ST_SetSRID(ST_MakePoint(lon, lat), 4326)` |
| `geohash4` | text | helper, optional |
| `time_zone` | text | documented as "STRING / FLOAT" in the source: check the actual type |

### `fup.weather_hourly`: hourly weather
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

### `fup.crop_class`: CLMS CTY crop class legend
Filled in by the schema (`code` → `name`, e.g. `1110` = Wheat). Source: [`data/cropland.md`](../data/cropland.md).

### `fup.field`: fields (e.g. one farmer's fields)

| Column | Type | Notes |
| --- | --- | --- |
| `field_id` | text, **PK** | |
| `name` | text | |
| `source` | text | where the geometry comes from (e.g. `geojson`, `uldk`) |
| `geom` | geometry(Geometry, 4326) | POLYGON or MULTIPOLYGON only (constraint in the database) |

**View `fup.v_field_grid`** `(field_id, grid_id)`: the rule "field centroid → nearest cell", computed in metres.

### `fup.field_crop_share`: share of crop classes in a field
Computed from the 10 m CTY raster (e.g. zonal statistics) at load time.

| Column | Type | Notes |
| --- | --- | --- |
| `field_id` | text, **PK**, FK → `field` | |
| `year` | integer, **PK** | CTY raster year |
| `class_code` | integer, **PK**, FK → `crop_class` | |
| `pixel_count` | bigint | |
| `share` | real | 0–1 (constraint in the database) |

### `fup.ingest_log`: data provenance
One row per loaded dataset/file: `dataset`, `source_file`, `source_year`, `row_count`, `time_shift`, `note`
(`id` and `loaded_at` are filled automatically).

## Loading data (for the loader)

Order (foreign keys): `grid_cell` → `weather_hourly` → `field` → `field_crop_share` → an `ingest_log` row.
`crop_class` is already filled in.

- Column names in `weather_hourly` and `grid_cell` match the parquet files, except `geom` (built from `lat`/`lon`).
- Load time as UTC (`SET TIME ZONE 'UTC'` in the session if the tool does not do it).
- Do not turn `NULL` into 0 and do not fill gaps; missing values must stay visible.
- Any tool is fine for large files (e.g. DuckDB reading parquet and writing to Postgres, `COPY`).
  The choice of tool is up to whoever writes the loader.
- After each loaded dataset add a row to `ingest_log`.
- Data and dumps do not go into Git (`data/**` is ignored).

## Checks after loading

```sql
SELECT count(*) FROM fup.grid_cell;
SELECT count(*) FROM fup.weather_hourly;
SELECT min(utc_time), max(utc_time) FROM fup.weather_hourly;
SELECT * FROM fup.v_field_grid;                -- field -> cell
SELECT utc_time, temperature FROM fup.weather_hourly
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
