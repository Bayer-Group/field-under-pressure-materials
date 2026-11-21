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
├── docker-compose.yml       # Service definitions: postgis (5432), minio (9000/9001), titiler (8080)
├── README.md                # Database description: start, connection, tables, source mapping, loading
├── VM.md                    # GCP machine with the database: access, start/SSH/stop, tunnel, permissions
└── initdb/                  # SQL scripts run on the first PostGIS start (empty volume)
    ├── 01_extensions.sql    # PostGIS + the fup schema
    └── 02_schema.sql        # MVP tables: grid_cell, weather_hourly, crop_class, field, field_crop_share, ingest_log
```

The `fup` schema (4 km hourly weather, fields, crops) is created only on an empty volume. After changing files in
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
