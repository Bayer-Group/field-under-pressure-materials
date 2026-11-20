# Data pipeline notes: download → prepare → DuckDB

Summary of the working session on getting the hackathon data onto disk and ready for DuckDB.
No credentials are stored here. Presigned links live only in `data/download_links.txt` (gitignored).

## Goal

Load the data from `data/*.md` (weather, soil, cropland, satellite, risk docs) into a DuckDB database.

## Chosen approach

1. **Download** the ZIPs from the organizers' presigned S3 links into `data/zips/`.
2. **Prepare**: unzip into a clean, partitioned layout in `data/raw/` that DuckDB reads with one glob.
3. **Build the DB** (not written yet): a `.duckdb` file that mixes copied tables and views over Parquet.

## Scripts (in `scripts/`)

| Script | What it does |
|---|---|
| `download_data.py` | Reads `data/download_links.txt` (any format, URLs are regex-extracted), sorts files into `data/zips/<category>/`. Parallel, resumable (`.part` + HTTP Range), retries, live status lines (`--status-every`), filters `--only/--exclude/--years/--voiv`, `--dry-run`. |
| `prepare_data.py` | Unzips `data/zips/` → `data/raw/` with Hive partitions (`year=…/voivodeship=…`), normalises voivodeship names, skips identical duplicates, blocks zip-slip, fixes cp437 file names, writes `prepare_manifest.json`, validates Parquet with DuckDB. Options: `--only`, `--force`, `--delete-zips`. |
| `download_sentinel2.py` | Stdlib-only CLI version of the Sentinel-2 notebook (Element 84 Earth Search, no account). Saves to `data/raw/satellite/sentinel2_l2a/<scene>/<band>.tif`. |

Target layout produced by `prepare_data.py`:

```
data/raw/
├── weather_grids/   weather_daily/year=2024/voivodeship=…/   weather_hourly/year=2024/voivodeship=…/
├── imerg_daily/     imerg_hourly/
├── soil/voivodeship=…/
├── cropland/year=2024/*.tif   cropland/legend/
└── satellite/sentinel2_l2a/<scene>/{red,nir,scl}.tif
```

```sql
SELECT * FROM read_parquet('data/raw/weather_daily/**/*.parquet', hive_partitioning = true)
WHERE voivodeship = 'mazowieckie' AND year = 2024;
```

## Key findings

### Source data and links
- The organizers' CSV (dated 17 Nov) was unusable: every link returned `ExpiredToken`. The signed URL says 7 days, but the underlying STS session token expires earlier. Fresh links dated 20 Nov worked (`dhub-pl-hackathon-2026_presigned_urls.txt`, tab-separated: key, URL).
- **Bug fixed:** the URL regex swallowed the CSV's trailing `,<size>` column and corrupted the signature (HTTP 400). Commas are now excluded from URLs.
- **Spelling inconsistencies in file names** (source side): `Maopolskie` vs `Malopolskie`, `odzkie` vs `Łódzkie`/`Lodzkie`, `Kujawsko_Pomorskie` vs `Kujawsko-Pomorskie`. In 2025 hourly, Małopolskie is uploaded twice. `prepare_data.py` maps all of them to 16 canonical names.
- The satellite zip from the organizers (`S2A_33UXR_2025_L2A.zip`, 51 GB) is 2025 only. 2024 imagery has to come from `download_sentinel2.py`.
- Full package is about 147 GB: hourly weather ≈ 80 GB, Sentinel-2 zip 51 GB, the rest ≈ 15 GB.

### What is inside the files (read from real downloads)
- **weather_daily**: one Parquet per voivodeship, 50 columns, key `(grid_id, date)` unique (Opolskie 2024: 226,188 rows). `grid_id` is a string like `'44823195'`. **No lat/lon in the file.**
- **weather_hourly**: several parts per voivodeship (`part000…`, ≈ 1.7 GB for Mazowieckie 2024), 30 columns, key `(grid_id, utc_time)`, also `local_time`, `date`, wind u/v components.
- **soil**: one Parquet per voivodeship, 76 columns, key `h3_index_10` unique (Opolskie: 638,068 rows). Layered properties at 6 depths plus root-zone aggregates. About 0.7% of rows are fully empty. `geom` (polygon) and `geom_point` (centre) are geometry columns.
- **soil column names differ from the docs**: actual `ph`, `soilTexture`, `BAND_om/BAND_cec/BAND_pH` (docs say `pH`, `soil_texture`, `band_*`).
- **cropland**: 48 GeoTIFF tiles per year, EPSG:4326, ~10 m pixels, `uint16` class codes. About 97% of pixels in a sampled tile are 0 (no cropland).
- Grid cells do not repeat across neighbouring voivodeship files (checked Opolskie vs Śląskie).
- **`weather_grids.zip` is required** to put weather on a map and to join it with soil/cropland. It is tiny (0.25 MB) and is **not** in the current `download_links.txt`.

### Sentinel-2, tile 33UXR, 2024
- 146 scenes in total. Cloud filters: 141 (<100%), 38 (<40%), 20 (<20%). Growing season Apr–Sep with cloud <20%: **14 scenes**.
- Measured band sizes per scene: `red`/`nir`/`green`/`blue` ≈ 200 MB (10 m); `scl` ≈ 2 MB; `swir16` and `rededge1-3` ≈ 55 MB (20 m).
- `red nir scl` ≈ 0.4 GB per scene → 14 scenes ≈ 5.6 GB; all 146 scenes ≈ 58 GB.
- Native resolution is 10 m; any coarser grid (e.g. 200 m) can be derived later. Compute NDVI at 10 m first, mask clouds with `scl` before aggregating, and never average `scl` (it holds classes).

Command for the growing season:

```
python scripts/download_sentinel2.py --tile 33UXR --start 2024-04-01 --end 2024-09-30 --max-cloud 20 --max-scenes 14 --bands red nir scl
```

## Loading into the database

The target is an existing PostGIS schema `fup` (tables `grid_cell`, `weather_hourly`, `field`, `field_crop_share`, `crop_class`, `ingest_log`). `scripts/load_db.py` only inserts rows into those tables; see `python scripts/load_db.py --help`, code in `scripts/dbload/`, tests in `tests/`. Soil, daily weather and Sentinel-2 are not loaded (no tables for them).

## Environment notes

- Python 3.15: `earthengine-api`/`geemap` dependencies (`pyyaml`, `lz4`) fail to build without Visual C++ Build Tools. The Sentinel-2 notebook does not need them. Installed instead: `pystac-client`, `pyproj`, `tqdm`, `duckdb` 2.0.1.
- DuckDB 2.0 API change: relations no longer have `fetchone()`. Use `con.execute(sql).fetchall()`.
- GitHub CLI 2.105.0 installed with winget. A terminal opened before the install needs restarting to see `gh`.

## Chronology of the session

1. Read `data/*.md`; recommended a hybrid DuckDB layout (Parquet views for big tables, copied tables for small ones, rasters aggregated to H3 first).
2. Wrote `download_data.py`, `extract_data.py`, `download_sentinel2.py`; tested routing and unzip with synthetic zips.
3. First real run failed (HTTP 400): CSV comma bug, then `ExpiredToken` on the 17 Nov links.
4. Fresh links arrived; added download progress/status output.
5. Download stopped and wiped twice while narrowing scope: first only 2025 links, then 2024 + soil (48 files, ≈ 18.8 GB).
6. Sentinel-2 scope narrowed from all 146 scenes to the 14 growing-season scenes.
7. Replaced `extract_data.py` with `prepare_data.py`; tested end to end with realistic fixtures (duplicates, legacy encoding, zip-slip).
8. Inspected real Parquet/GeoTIFF files to define the table layout above.

## State when these notes were written

- `data/download_links.txt`: 48 links (2024 weather daily/hourly, cropland 2024, soil ×15). Links expire; ask the organizers for new ones if downloads return 400/403.
- `data/zips/` held about 19 GB of downloaded archives; a Sentinel-2 download had started under `data/raw/satellite/`.
- `prepare_data.py` has only been tested on synthetic zips, not on the real downloads.

## Next steps

1. Create the schema from the team DDL in PostGIS.
2. `python scripts/load_db.py --dry-run`, then `--limit-files 1`, then the full load (needs `LOAD_DB_DSN`).
3. Provide a fields GeoJSON (`--fields`) to fill `field` and `field_crop_share`.
