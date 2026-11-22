# Raw layer: organizer data in the database (Mazowieckie MVP)

**Status: for review by the whole team.** This is the input for the curated-layer contract and for the wheat/septoria
business logic (see the epic "Wheat/septoria risk pipeline: raw → curated → served"). Everything here was measured on the
prepared data on the external disk (`HACKATHON/raw`) and on the database on the VM, where the whole scope is now loaded. Items marked **PROPOSAL** are not
decided yet. The current database structure is in [`README.md`](README.md); this file extends it to all organizer layers.

## Scope

- **Region:** Mazowieckie only (2,428 grid cells, `l1_name = 'Mazowieckie'`).
- **Time-varying data:** hourly weather for local dates **2024-04-01 … 2024-06-30** (91 days = 2,184 hours); daily weather and
  IMERG daily for the **whole of 2024** (366 days, needed for the growth stage from 1 February); source year 2024.
- **Static data** (soil, crop map): the whole of Mazowieckie.
- **MVP crop and disease:** wheat / septoria. Other crops (e.g. maize) are optional and later.
- **Dates are the original source dates.** Any demo time shift is applied later (#20 / API) and is NOT part of this layer.

## Layers (decided)

| Schema | Content | Written by |
| --- | --- | --- |
| `raw` | organizer data as delivered (typed, deduplicated, no business logic) | loader |
| `curated` | derived tables defined by the curated-layer contract | transformations |
| `app` | farmer input (parcels, fields, crop areas, sprays) and computed results | backend |

The tables that exist today live in schema `fup`. It will be renamed to `raw` (`ALTER SCHEMA fup RENAME TO raw`) and the
farmer tables (`field`, `field_crop_share`) will move to `app`. **Table and column names below do not change.** The
contract must use `raw.<table>`; until the rename is applied, `fup.<table>` is the same table.

## Table catalogue

| Table | Source | Key | Rows (Mazowieckie scope) | Status |
| --- | --- | --- | --- | --- |
| `raw.grid_cell` | `weather_grids/weather_grids.parquet` | `grid_id` | 21,196 (2,428 in scope) | **loaded** (with `l1_name` and `elevation`) |
| `raw.weather_hourly` | `weather_hourly/year=2024/voivodeship=mazowieckie/*.parquet` + IMERG hourly | `(grid_id, utc_time)` | 5,302,752 | **loaded** |
| `raw.weather_daily` | `weather_daily/year=2024/voivodeship=mazowieckie/*.parquet` | `(grid_id, date)` | 888,648 | **loaded** |
| `raw.imerg_daily` | `imerg_daily/daily/2024/precip_daily_2024_Mazowieckie.parquet` | `(grid_id, date)` | 888,648 | **loaded** |
| `raw.soil_h3` | `soil/voivodeship=mazowieckie/Mazowieckie_isric_250_v2.parquet` | `h3_index_10` | 2,491,086 | **loaded** |
| `raw.cropland_cty` (raster) | `cropland/year=2024/CLMS_HRLVLCC_CTY_PL_*.tif` (15 tiles) | `rid` (tile file in `tile`) | 15 files, 29,334 raster tiles of 256×256 (181 MB in the database) | **loaded** |
| `raw.crop_class` | CTY legend | `code` | 21 | loaded |
| `raw.ingest_log` | loader | `id` | one row per loaded file | loaded |

**Not available for Mazowieckie: Sentinel-2.** The 10 delivered scenes (May–September 2024) are all tile 33UXR
(lon 16.4–18.0, lat 49.5–50.5), which does not intersect Mazowieckie (lon 19.3–23.1, lat 51.1–53.5). Nothing is loaded.
**Decision: Sentinel-2 is out of scope for the MVP** (it would only serve verification, and it is available from public APIs if needed).

### `raw.grid_cell`: weather grid (4 km)
`grid_id` text PK · `lat`, `lon` double · `geom` Point 4326 (centre of the cell) · `geohash4` text · `time_zone` text (always NULL: not in the source).
**To add:** `l1_name` text (voivodeship name, in the source) and `elevation` double (in the weather files, one value per cell).
The grid has cell centres only, no polygons. Step ≈ 0.044° in both axes (a regular lattice in degrees).

### `raw.weather_hourly`: hourly weather (loaded)
Columns as in [`README.md`](README.md) and [`bayer/data/weather.md`](../bayer/data/weather.md); `date` is the local calendar date,
`utc_time` timestamptz, `local_time` timestamp (no zone). Measured for the scope: **no NULLs**, temperature 0.3…35.5 °C,
relative humidity 18…100 %, hourly precipitation 0…23.6 mm.
- `precipitation` comes from **IMERG hourly**, joined on `(grid_id, utc_time)` at load time (the weather files have no precipitation column).
- Not stored: `elevation` (moves to `grid_cell`) and the wind components `u_component_of_wind_10m`, `v_component_of_wind_10m`.

### `raw.weather_daily`: daily weather (loaded)
Key `(grid_id, date)`; `date` is the local calendar date. The file has 50 columns: the key, `elevation` (constant per
cell, stored in `grid_cell` instead) and 47 measured columns (units as in `bayer/data/weather.md`):
`min/max/avg/midpoint_temperature` · `min/max/avg_dew_point_temperature` · `min/max/avg_atmospheric_pressure` ·
`total/max_downward_solar_radiation` · `total/max_net_solar_radiation` · `avg_total_cloud_cover` · `avg_snow_depth` · `avg_snow_density` ·
`min/max/avg_wind_speed` · `avg_wind_direction` · `max_wind_gust` · `min/max/avg_wind_speed_2m` · `min/max/avg_relative_humidity` ·
`min/max/avg_soil_temperature_level_1…4` · `avg_soil_moisture_level_1…4` · `eto` · `etr` · `day_length`.
`total_precipitation` is **not** in the daily weather file; daily precipitation is `raw.imerg_daily`.
Daily values are aggregates of the hourly series, so they can be recomputed from `raw.weather_hourly` (the curated layer may do that instead).

### `raw.imerg_daily`
`grid_id` text · `date` date · `total_precipitation` double (mm per day, NASA IMERG). Key `(grid_id, date)`.

### `raw.soil_h3`: ISRIC SoilGrids (static, 250 m, H3 level 10)
One row per H3 cell: `h3_index_10` text PK (15 characters), `hid` bigint (partition key), plus:
- **layered properties** at six depths `0_5cm, 5_15cm, 15_30cm, 30_60cm, 60_100cm, 100_200cm`:
  `bdod`, `cec`, `cfvo`, `clay`, `nitrogen`, `ocd`, `phh2o`, `sand`, `silt`, `soc` (`…_<depth>_mean`), and `ocs_0_30cm_mean`;
- **root-zone aggregates:** `cec`, `om`, `ph`, `sand`, `silt`, `clay`, `bulk_density`;
- **classes:** `BAND_om`, `BAND_cec`, `BAND_pH` (low / moderate / high) and `soilTexture` (USDA class);
- **geometry:** `geom_point` (Point 4326) and `geom` (hexagon, Polygon 4326), both supplied in the source as WKB.

Measured: about 0.6 % of cells have NULL values (no soil data); textures are mostly Sandy Loam and Loamy Sand.
**Units to verify:** `bayer/data/soil.md` says sand/silt/clay are in `g/100g (%)`, but the root-zone `clay`, `sand`, `silt`
values are **fractions 0.04…0.92**. `bayer/data/soil.md` also lists `band_*` as floats while the data has text, and names the
texture column `soil_texture` while the file has `soilTexture`. The table keeps the **file's values**; column names are
lower-cased (`band_om`, `band_cec`, `band_ph`) and `soilTexture` is stored as `soil_texture`.

### `raw.cropland_cty`: CLMS crop types 2024 (raster, 10 m, EPSG:4326, uint16)
15 tiles cover Mazowieckie (`…_PL_0, 7, 13, 14, 22, 23, 24, 28, 33, 35, 36, 42, 43, 44, 46`); 3.6 GB in total,
**uncompressed, not tiled, no overviews**. Pixel value = crop class (`raw.crop_class`; 1110 = wheat, 1130 = maize).
**Caution (measured):** the tiles come from a metric tile grid reprojected to degrees, so their bounding boxes
**overlap**, and the padding is filled with **0**, the same value as "No cropland", and there is no nodata tag.
Counting pixels over all tiles that touch a polygon therefore adds padding zeros. Any use of this raster must mosaic with
"non-zero wins" before counting. The raw table keeps tiles unchanged; the mosaic belongs to the curated layer.
**Storage (decided, raster spike): PostGIS raster tiles in the database.** GeoTIFF is supported (read by GDAL inside PostGIS).
The loader compresses each tile losslessly (DEFLATE) in memory, sends the bytes to the database and the server converts
them with `ST_FromGDALRaster` + `ST_Tile(…, 256, 256)`; no files on the VM and no `raster2pgsql` are needed (the tool is not in
the database image, the `postgis_raster` extension is). Measured on one tile: 153 MB → 1.7 MB compressed upload, 4.9 MB in the
database, 1,247 raster tiles, and the class counts inside a polygon equal an independent `rasterio` read (35 ms per field;
the out-of-database alternative needed 1.6 s). Table:
`raw.cropland_cty(rid serial PK, tile text, year int, rast raster)`, one row per 256×256 raster tile, GiST index on
`ST_ConvexHull(rast)`. The loading session needs `SET postgis.gdal_enabled_drivers = 'GTiff'`. The raw table keeps the tiles
unchanged (source file name in `tile`). The tiles are not aligned to each other (each has its own grid), so the mosaic with
"non-zero wins" is built in the curated layer by resampling with nearest neighbour onto one grid.

### `raw.crop_class`
`code` integer PK, `name` text; the 21 CTY classes (0, 1110 Wheat, 1120 Barley, 1130 Maize, …, 65535 Outside area).

## Joins the curated layer can rely on

| From | To | How |
| --- | --- | --- |
| field / crop area | weather cell | nearest cell to the geometry centroid (`app.field` → `raw.grid_cell`), no interpolation |
| weather cell | hourly / daily weather | `grid_id` |
| field / crop area | soil | spatial intersection with `raw.soil_h3.geom`, or nearest `geom_point` |
| field / crop area | crop map | raster mosaic (non-zero wins) clipped to the geometry, class codes from `raw.crop_class` |

## Known data issues (source)

1. **Duplicate rows** in hourly weather for Kujawsko-Pomorskie, Lubelskie and Lubuskie (Oct / Dec 2024), identical values; **not in the Mazowieckie window**.
2. `wind_speed_2m` has negative values (min −1.4 km/h); in the Mazowieckie window use as is, flag in curated if used.
3. Some file names lost Polish letters (`odzkie`, `Maopolskie`); partition folders are correct.
4. Crop tiles: overlapping bounding boxes with 0 padding (see above).
5. Soil: unit and column-name differences from the documentation (see above).
6. `time_zone` is not in the source grid. Local time is already in the weather files (`local_time`, `date`).

## Rules for anything built on this layer

- Raw tables are **read-only for transformations**; results go to `curated` / `app`.
- `NULL` means missing in the source; never replace it with 0. Report coverage (valid vs expected hours) wherever a value is aggregated.
- Time keys: `utc_time` (timestamptz) for hourly data and the local `date` for daily data. State which one a derived table uses.
- Spatial keys: EPSG:4326, longitude/latitude order.
- Every loaded file has a row in `raw.ingest_log` (dataset, file, rows, load time).

## Loading (measured)

All tables above are loaded in the VM database for the Mazowieckie scope (2026-11-21), with `scripts/load_db.py`
(see [`README.md`](README.md)). The whole load took about 10 minutes through an SSH tunnel with compression (`-C`):
grid, hourly and daily weather and IMERG 3.5 min, soil 3 min, the 15 crop tiles 3 min (each tile is compressed
losslessly before sending: 150–250 MB become 2–7 MB). The database is 2.3 GB (soil 1.4 GB, hourly weather 0.8 GB,
crop raster 0.2 GB). Checks after the load: row counts equal the source; hourly weather has 1,464 hours for each of the
2,428 cells and no NULLs; the soil geometries are valid (SRID 4326); the class counts inside a polygon from the loaded raster
equal an independent `rasterio` read. The data on the external disk (34 GB) is mostly not loaded: only this scope is.

**Later extension (2026-11-21):** hourly weather was widened from May–June to April–June (5,302,752 rows, 5 minutes) and the daily weather and IMERG daily
were loaded for the whole year (888,648 rows each, 1.5 minutes). Checked: the daily mean, maximum and minimum temperature equal the aggregates of the
hourly values for every cell and day (difference 0.000 °C), and IMERG daily equals the sum of the hourly values (up to rounding, at most 0.05 mm).
