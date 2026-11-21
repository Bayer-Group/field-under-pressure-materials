# 🤖 AI Agent Instructions: Containers Module (`docker/`)

> Before editing files in this folder, read the parent [`/AGENTS.md`](../AGENTS.md) and [`/CONTRIBUTING.md`](../CONTRIBUTING.md).

---

## 🎯 Module Scope and Role (`Scope`)
The `docker/` folder contains an optional container setup for teams that want to run databases and helper servers with `docker compose`. It covers:
1. The **PostGIS** spatial database (`postgis/postgis:15-3.3`).
2. A local **MinIO** S3 object store for Cloud Optimized GeoTIFF (COG) raster files.
3. The **TiTiler** dynamic raster tile server (`ghcr.io/developmentseed/titiler`).

---

## 📂 Directory Structure
```text
docker/
├── docker-compose.yml       # Service definitions: postgis (5432), backend (8000), minio (9000/9001), titiler (8080)
├── backend.Dockerfile       # Image of the backend API (build context: the repo root, see ../.dockerignore)
├── README.md                # Database description: start, connection, tables, source mapping, loading
├── RAW_SCHEMA.md            # Raw layer: all organizer data (Mazowieckie MVP), keys, columns, source issues
├── VM.md                    # GCP machine with the database: access, start/SSH/stop, tunnel, permissions
├── migrations/              # One-off scripts that bring an older database up to date
│   ├── 001_raw_layers.sql   # fup -> raw, farmer tables -> app, new raw tables (idempotent, deletes no data)
│   ├── 002_app_farmer_input.sql  # farmer input tables in app (idempotent)
│   ├── 003_curated.sql      # curated layer tables (idempotent)
│   ├── 004_serve.sql        # serving layer: change log, cell-day table, demo shift, views (idempotent)
│   ├── 005_demo_users.sql   # app.demo_user for the API login (idempotent)
│   ├── 006_sprays_confirmed.sql  # app.crop_area.sprays_confirmed (idempotent)
│   └── 007_grid_cells.sql   # the cells of serve.grid_risk_daily tile the plane (idempotent)
└── initdb/                  # SQL scripts run on the first PostGIS start (empty volume)
    ├── 01_extensions.sql    # PostGIS, PostGIS raster, schemas raw / curated / app
    ├── 02_schema.sql        # raw: grid_cell, weather_hourly, crop_class, ingest_log; app: field, field_crop_share
    ├── 03_raw_layers.sql    # raw: weather_daily, imerg_daily, soil_h3, cropland_cty
    ├── 04_app_farmer_input.sql  # app: parcel, field_parcel, crop_area, spray (field extended)
    ├── 05_curated.sql       # curated: weather features, resumption, crop map, field context, risk assessment
    ├── 06_serve.sql         # serve: views with the demo shift; curated.risk_change and septoria_cell_day
    └── 07_demo_users.sql    # app.demo_user: demo logins of the API
```

The `raw`, `curated` and `app` schemas are created only on an empty volume. After changing files in
`initdb/` the database has to be recreated: `docker compose down -v` and `up` again (this deletes the data in the database).

Configuration (user, password, database, port) is shared by the whole application: template in [`/example.env`](../example.env),
your own copy in `/.env` (ignored by git). Start from the repo root:
`docker compose --env-file .env -f docker/docker-compose.yml up -d postgis`.

---

## 🛑 Docker-Specific Rules (`Hard Rules`)

1. **Optional status:**
   * The Docker tooling is **entirely optional**. The QGIS plugin and the FastAPI server (`run_backend.py`) must also work correctly without a running Docker.
   * Do not create hard dependencies in Python code on a running PostGIS container for basic analysis operations.
2. **Neutral naming and security:**
   * Container and database names must stay neutral (`spatial_postgis`, `spatial_db`, `spatial_minio`).
   * Configuration variables should be easy to override with a `.env` file.
