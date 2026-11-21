# Curated layer contract (wheat / septoria, Mazowieckie)

**Status: DRAFT for review (issues #34, #35, #36, #37).** Items marked **PROPOSAL** are not decided. Items marked **DEPENDS ON #33**
cannot be closed until `docs/wheat_septoria_logic.md` exists. All example rows are **fictional illustrations** and not
measured values. Raw names come only from [`docker/RAW_SCHEMA.md`](../docker/RAW_SCHEMA.md); farmer-side inputs come from
`FARMER_INPUT_CONTRACT.md`.

## Decisions after review (2026-11-21)

Applied after the implementation review in #34 and the data loaded in the database:

1. **Growth stage is estimated from the weather in v1** (`growth_stage_source = 'estimated'`): daily weather for the whole of 2024 is loaded, so the
   vegetation resumption date and the degree-days since it can be computed (1.2). The calendar window (April to June) is only a fallback when
   no estimate exists. Spring wheat stays `stage_unknown`.
2. **Hourly weather now covers 2024-04-01 to 2024-06-30** (5,302,752 rows), so the 72 h look-back and the April part of the window have data.
   Daily weather and IMERG daily cover the whole of 2024.
3. **`spray_signal` is renamed `conditions_met`.** The prototype does not instruct anyone to spray (`PROJECT.md`); the field states that
   conditions are favourable to the disease in a susceptible stage and the UI says so.
4. **`app.crop_area.bbch_override`** (31, 37, 39, 51, 59, nullable) was added for `growth_stage_source = 'override'`. It is not in
   `FARMER_INPUT_CONTRACT.md` yet.
5. **App table names** are fixed (PR #42): `app.field`, `app.parcel`, `app.field_parcel`, `app.crop_area`, `app.spray`.
6. **Configuration is TOML**, in `config/septoria.toml` (YAML would add a dependency).
7. **Time shift (PROPOSAL):** the API applies +2 calendar years to the date, not a fixed number of days: `shift_days: 730` is exact only for
   dates from 1 March 2024 on (2024 is a leap year; 29 February 2024 has no target).

---

## 0. General rules

- Tables are named `curated.<name>`. Raw tables are read-only for transformations.
- **Time keys.** Hourly tables use `utc_time` (timestamptz) and also carry the local `date`; daily tables use the local `date`
  from `raw.weather_hourly.date` (already the local calendar day, so no cut is computed here). Each table states which key it uses.
- **Original source dates.** The demo time shift is applied at the API, not here. A client asks for `as_of` (demo "now"); the API
  subtracts the shift and reads the row for the original date.
- **NULL means missing.** It is never replaced by 0. Every aggregate reports coverage (valid vs. expected rows).
- **Coordinates.** Geometry is EPSG:4326, longitude/latitude order. Area, length and buffers are computed in EPSG:2180
  (`ST_Transform(geom, 2180)`), never in degrees. Responses state `"crs": "EPSG:4326"`.
- **Repeatable.** Every transformation can be rerun for a time range or for a single crop area.
- **Farmer input** lives in schema `app`: `app.crop_area` (`crop_area_id`, `geom`, `farmer_crop_id`, `sowing_date`, optional `bbch_override`) and
  `app.spray` (`spray_date`, `protection_duration_days`); see `docker/README.md`. Field names follow `FARMER_INPUT_CONTRACT.md`.

---

## 1. `curated.weather_hourly_features` (issue #35)

**Purpose.** Hourly wetness indicators per grid cell, the input of the septoria indicator H.

**Grain.** One row = one grid cell × one hour. **Primary key:** `(grid_id, utc_time)`. **Time key:** `utc_time` (local `date` kept for joins).

**Decision.** Hourly is the source of truth for the wet-hour indicators. `raw.weather_daily` (the whole of 2024) is used only for the daily mean
temperature `t_mean`, which equals the mean of the hourly values (checked: difference 0.000 °C), so the growth stage can be estimated from
1 February. `raw.imerg_daily` is not used in v1. Hourly weather is loaded for 2024-04-01 to 2024-06-30.

| Column | Type | Unit | NULL | Description | Source |
| --- | --- | --- | --- | --- | --- |
| `grid_id` | text | | no | weather cell | `raw.weather_hourly.grid_id` |
| `utc_time` | timestamptz | | no | hour | `raw.weather_hourly.utc_time` |
| `date` | date | | no | local calendar day | `raw.weather_hourly.date` |
| `local_time` | timestamp | | no | local time, no zone | `raw.weather_hourly.local_time` |
| `relative_humidity` | real | % | yes | | `raw.weather_hourly.relative_humidity` |
| `precipitation` | real | mm/h | yes | IMERG hourly, joined at load | `raw.weather_hourly.precipitation` |
| `temperature` | real | °C | yes | 2 m | `raw.weather_hourly.temperature` |
| `is_wet` | boolean | | yes | wet hour: RH >= 85 % **or** precipitation > 0.2 mm | rule (below) |
| `wind_speed_2m_flag` | boolean | | no | true when source value is negative | `raw.weather_hourly.wind_speed_2m` |

**Transformation.**

```sql
SELECT grid_id, utc_time, date, local_time, relative_humidity, precipitation, temperature,
       CASE
         WHEN relative_humidity >= 85 OR precipitation > 0.2 THEN true
         WHEN relative_humidity IS NULL OR precipitation IS NULL THEN NULL   -- unknown, not dry
         ELSE false
       END AS is_wet,
       COALESCE(wind_speed_2m < 0, false) AS wind_speed_2m_flag
FROM raw.weather_hourly;
```

The thresholds 85 % and 0.2 mm are configuration, not code (see section 4). **DEPENDS ON #33** for the final values.

**Refresh.** After each weather load, for the loaded time range and all cells.

**Quality.** Measured for the Mazowieckie window: no NULLs in `raw.weather_hourly`, so `is_wet` is never NULL there; the NULL rule stays
for other regions. Negative `wind_speed_2m` (min -1.4 km/h) is flagged, not corrected.

**Consumers.** `curated.risk_assessment` (section 3). Optional QGIS layer: one point per `grid_id` (cell centres from
`raw.grid_cell.geom`), time-enabled on `utc_time`.

**Example rows (fictional).**

| grid_id | utc_time | relative_humidity | precipitation | is_wet |
| --- | --- | --- | --- | --- |
| G-0001 | 2024-05-20 04:00Z | 91 | 0.0 | true |
| G-0001 | 2024-05-20 05:00Z | 80 | 0.5 | true |
| G-0001 | 2024-05-20 06:00Z | 70 | 0.0 | false |
| G-0001 | 2024-05-20 07:00Z | NULL | NULL | NULL |

### 1.1 `curated.weather_daily_features` (needed for the growth stage)

Grain: cell × local `date`. Key `(grid_id, date)`. Derived from 1: `wet_hours` (count of `is_wet = true`), `valid_hours`
(count of non-NULL `is_wet`), `expected_hours` (24, 23 or 25 on clock-change days), `coverage = valid_hours / expected_hours`.
Added from the spray-window note (growth stage estimate): `t_mean` (real, °C, = `raw.weather_daily.avg_temperature`, which equals the mean of the hourly
`temperature` over the local day) and `gdd3` (real, °C·day) = `GREATEST(t_mean - 3, 0)`.

### 1.2 `curated.vegetation_resumption` (PROPOSAL)

Grain: cell × year. Key `(grid_id, year)`. `resumption_date` = first day after 1 February from which `t_mean >= 3` holds for 5 consecutive
days (team assumption); NULL if not found. Computed from `weather_daily_features`. Then, per cell and day,
`gdd_since_resumption` = sum of `gdd3` from `resumption_date` to that day (stored as a column of `weather_daily_features`).
Zones for the risk table: **A** < ~160 °C·day, **B** ~160 to ~510, **C** > ~510 (starting values from the spray-window note, to be calibrated).

**Built in v1.** Daily temperatures for the whole of 2024 are in `raw.weather_daily`, so `resumption_date` and `gdd_since_resumption` are
computed for every cell (2024: 2-3 February for all 2,428 cells, a very warm winter; zone B from early April, zone C from mid-May).
The BBCH 30-59 window for winter wheat is then the zone-based estimate (`growth_stage_source = 'estimated'`); the April to June calendar
window is the fallback when no resumption date exists (`calendar`), and a farmer's BBCH tile overrides both (`override`). The zone
thresholds are starting values and are calibrated by the team.

---

## 2. Field context (issue #36)

### 2.1 `curated.crop_mapping`

**Purpose.** Maps the farmer's crop choice to a CLMS CTY class code. **Grain:** one row per farmer crop. **Key:** `farmer_crop_id`.
Static table, filled by hand.

| Column | Type | NULL | Description | Source |
| --- | --- | --- | --- | --- |
| `farmer_crop_id` | text | no | id from `GET /crops` | farmer input |
| `class_code` | integer | no | CTY code | `raw.crop_class.code` |

Rows for v1: `wheat -> 1110`, `maize -> 1130` (from #36), `soy -> 1420` (name match in `raw.crop_class`: "Soybeans").
The `GET /crops` list is fictional today, so this table must be re-checked when the real list exists.

### 2.2 `curated.crop_area_crop_map`

**Purpose.** What the crop map says is growing inside a crop area. Stored **separately** from the farmer's crop, never overwriting it.

**Grain.** One row = crop area × year × class. **Key:** `(crop_area_id, year, class_code)`. **Time key:** `year`.

| Column | Type | Unit | NULL | Description | Source |
| --- | --- | --- | --- | --- | --- |
| `crop_area_id` | text | | no | | `app.crop_area` |
| `year` | integer | | no | | `raw.cropland_cty.year` |
| `class_code` | integer | | no | | pixel value, `raw.crop_class.code` |
| `pixel_count` | bigint | | no | pixels of this class in the polygon | `raw.cropland_cty.rast` |
| `share` | real | 0-1 | no | `pixel_count / total pixels counted` | rule |
| `is_map_crop` | boolean | | no | true for the dominant class | rule |

**Transformation (pseudocode).**

1. Build a mosaic of all tiles touching the polygon, resampled to one grid by nearest neighbour; where tiles overlap, **the non-zero value wins** (tiles overlap and padding is 0, see `RAW_SCHEMA.md`).
2. Clip the mosaic to the crop-area polygon and count pixels per class.
3. `share = pixel_count / sum(pixel_count)`. `is_map_crop` = class with the largest share (ties: lowest `class_code`).

**Refresh.** When a farmer saves one crop area (single polygon, not a batch).

**Quality.** A polygon outside the delivered tiles produces no rows (not a row of zeros). Report `total_pixels`.

**Consumers.** `curated.field_context` (2.3), QGIS attribute `map_crop_id` of the crop-area layer.

**Example rows, polygon on a tile border (fictional).**

| crop_area_id | year | class_code | pixel_count | share | is_map_crop |
| --- | --- | --- | --- | --- | --- |
| area-demo-1 | 2024 | 1110 | 5,200 | 0.65 | true |
| area-demo-1 | 2024 | 1130 | 2,000 | 0.25 | false |
| area-demo-1 | 2024 | 0 | 800 | 0.10 | false |

The row with `class_code = 0` is real "No cropland". Padding zeros were removed by the mosaic step; without it the same polygon would show about 1,900 extra zeros.

### 2.3 `curated.field_context`

**Purpose.** Soil values and crop-map result per crop area, one row.

**Grain.** One row = one crop area. **Key:** `crop_area_id`. **Time key:** none (soil is static); `crop_map_year` for the crop map.

| Column | Type | Unit | NULL | Description | Source |
| --- | --- | --- | --- | --- | --- |
| `crop_area_id` | text | | no | | `app.crop_area` |
| `soil_ph` | real | pH | yes | area-weighted mean of root-zone `ph` | `raw.soil_h3.ph` |
| `soil_clay`, `soil_sand`, `soil_silt` | real | fraction 0-1 | yes | area-weighted mean | `raw.soil_h3.clay` / `sand` / `silt` |
| `soil_om`, `soil_cec`, `soil_bulk_density` | real | as source | yes | area-weighted mean | `raw.soil_h3.om` / `cec` / `bulk_density` |
| `soil_texture` | text | USDA class | yes | class with the largest area share | `raw.soil_h3.soil_texture` |
| `soil_cell_count` | integer | | no | H3 cells intersecting the polygon | rule |
| `soil_coverage` | real | 0-1 | no | share of polygon area covered by cells with non-NULL values | rule |
| `crop_map_year` | integer | | yes | | `crop_area_crop_map.year` |
| `map_crop_class_code` | integer | | yes | dominant class | `crop_area_crop_map.class_code` |
| `farmer_class_code` | integer | | yes | farmer crop mapped to CTY | `crop_mapping.class_code` |
| `crop_differs` | boolean | | yes | `farmer_class_code <> map_crop_class_code`; NULL if either is NULL | rule |

**Transformation.** Soil: intersect the polygon with `raw.soil_h3.geom`; weight = intersection area in EPSG:2180; mean over cells with non-NULL values. NULL when no cell has a value (not 0). About 0.6 % of cells have no soil data. Layered depth columns are not used in v1 (**PROPOSAL**: only root-zone aggregates).

**Units.** `raw.soil_h3` root-zone `clay`/`sand`/`silt` are **fractions (0.04 to 0.92)**, while `data/soil.md` says `g/100g (%)`. The contract keeps the file's values; converting to percent is a presentation step.

**Refresh.** When a farmer saves a crop area (single polygon).

**Consumers.** The crop-area QGIS layer and the "Why?" screen. Endpoint: **PROPOSAL** `GET /fields/{id}` adds `context` per crop area.

**Example rows (fictional).**

| crop_area_id | soil_ph | soil_clay | soil_texture | soil_coverage | map_crop_class_code | farmer_class_code | crop_differs |
| --- | --- | --- | --- | --- | --- | --- | --- |
| area-demo-1 | 6.1 | 0.18 | Sandy Loam | 1.00 | 1110 | 1110 | false |
| area-demo-2 | NULL | NULL | NULL | 0.00 | NULL | 1420 | NULL |

---

## 3. `curated.risk_assessment` (issue #37)

**Purpose.** Septoria condition class per crop area and day, with the reasons. It states **conditions favourable to the disease, not
disease presence** and gives no spraying instruction.

**Grain (PROPOSAL).** Crop area × local `date`. **Key:** `(crop_area_id, disease, date)`. **Time key:** local `date`.
Hourly grain is not needed for the UI. The day's value is the indicator at the **last hour of the local day**.

| Column | Type | Unit | NULL | Description | Source |
| --- | --- | --- | --- | --- | --- |
| `crop_area_id` | text | | no | | `app.crop_area` |
| `disease` | text | | no | `septoria` in v1 | constant |
| `date` | date | | no | local day | rule |
| `grid_id` | text | | no | cell used | nearest cell to polygon centroid, `raw.grid_cell` |
| `h_hours` | integer | h | yes | H: longest run of consecutive wet hours in the 72 h ending at the last hour of `date` | `weather_hourly_features.is_wet` |
| `h_low`, `h_high` | integer | h | yes | H when missing hours are counted dry / wet | same |
| `risk_class` | text | | yes | `low` / `medium` / `high`; NULL when no class applies | rule |
| `status` | text | | no | see below | rule |
| `threshold_medium`, `threshold_high` | integer | h | no | thresholds used (10, 20) | configuration |
| `coverage` | real | 0-1 | no | valid hours / 72 | rule |
| `protected_until` | date | | yes | latest spray `date` + that spray's `protection_duration_days` | `app.spray` (`spray_date` + `protection_duration_days`) |
| `growth_stage_zone` | text | | yes | `A` / `B` / `C`, NULL when unknown | `weather_daily_features.gdd_since_resumption` |
| `growth_stage_source` | text | | yes | `estimated` (from weather, v1 default), `calendar` (April-June fallback when no estimate exists) or `override` (`app.crop_area.bbch_override`) | rule / farmer input |
| `gdd_since_resumption` | real | °C·day | yes | sum used for the zone | `weather_daily_features` |
| `conditions_met` | boolean | | no | true only when class = `high`, zone is B or C and the field is not protected | rule |
| `reasons` | jsonb | | no | components for the "Why?" screen (`h_hours`, window start and end, threshold origin) | rule |
| `computed_at` | timestamptz | | no | | system |
| `model_version` | text | | no | constant string | constant |
| `input_hash` | text | | no | hash of the inputs used | system |

**`status` vocabulary (PROPOSAL, merges #37 `ok`/`insufficient_data` with the team's logic note).**

| status | `risk_class` | Meaning |
| --- | --- | --- |
| `ok` | low / medium / high | computed normally |
| `uncertain` | NULL | `h_low < threshold <= h_high`; the UI shows the range `h_low`-`h_high` |
| `out_of_window` | NULL | outside BBCH 30-59 (**DEPENDS ON #33**) |
| `protected` | the class is kept | less than the protection duration since the last spray (default 10 days); the UI shows "protected until {date}" |
| `insufficient_data` | NULL | coverage below the minimum (**DEPENDS ON #33** for the minimum) |
| `stage_unknown` | NULL | growth stage cannot be estimated (spring wheat, or no daily temperatures from 1 February); the UI asks the farmer for BBCH |

A NULL `risk_class` is never shown as green "low".

**Classification (from the team's thresholds note).** `h_hours >= 20` -> `high`; `>= 10` -> `medium`; else `low`. The threshold 20 h is
"from literature" (SPOT-IT), the boundary 10 h is a "team assumption". The origin goes into `reasons`. Thresholds live in configuration.

**Conditions of application (DEPENDS ON #33).** Per the team's spray-window note the conditions flag (`conditions_met`) needs all of: class `high` (H >= 20 h),
growth zone B or C (BBCH 30-59, estimated or confirmed), and more days since the last spray than its `protection_duration_days`
(10 when the farmer gave no value; the farmer contract requires a positive duration for every recorded spray, so the default 10 only
applies in the UI). Growth stage is estimated for winter wheat only (section 1.2); farmer's BBCH tiles (31, 37, 39, 51, 59) override it.
Sowing date only separates winter from spring wheat and flags very late sowing (after end of October) as less certain.
Every input value carries an origin: `raw`, `estimated`, `override` or `synthetic`.

**Spray windows are not part of this table.** The window note computes up to three 72-hour weather windows from a live **Open-Meteo**
forecast (wind <= 4 m/s, no rain 2 h after the spray, 5-25 °C, gusts <= limit + 2 m/s, minimum 4 h). That is not a `curated` table
and needs no QGIS layer; it belongs to the API contract. In the demo the "forecast" is the actual weather of the next 72 h from
`raw.weather_hourly` (wind stored in **km/h**, converted with `/ 3.6` in the query or view), labelled "replay".

**Open decisions (from #37).**

1. **Keep or overwrite previous results?** PROPOSAL: overwrite the row for the same key, keep `computed_at`; keep history only if needed for the pitch.
2. **`as_of` selection.** PROPOSAL: the API converts `as_of` to the original date and reads `date`, no recomputation.
3. **Refresh triggers.** After a farmer saves a crop area (that area only) and after a weather load (all areas, loaded range).
4. **Continuous vs. total wet hours.** The thresholds note defines H as the longest consecutive run; its test section leaves "continuous or total" open.

**Consumers.**

- API (**PROPOSAL**): `GET /fields/{id}/risk?as_of=YYYY-MM-DD` and `GET /risk?as_of=YYYY-MM-DD` (all crop areas, GeoJSON features with the columns above); `GET /risk/thresholds` returns thresholds with origin.
- QGIS: layer "Septoria risk" = crop-area polygons joined on `crop_area_id`, categorized by `risk_class` / `status` (red, yellow, green, hatched yellow for `uncertain`, grey for `out_of_window` and `insufficient_data`), time-enabled on `date`.

**Example rows (fictional), one per class plus insufficient data.**

| crop_area_id | date | h_hours | h_low-h_high | risk_class | status | coverage | protected_until |
| --- | --- | --- | --- | --- | --- | --- | --- |
| area-demo-1 | 2024-05-20 | 26 | 26-26 | high | ok | 1.00 | NULL |
| area-demo-1 | 2024-05-21 | 14 | 14-14 | medium | ok | 1.00 | NULL |
| area-demo-1 | 2024-05-22 | 6 | 6-6 | low | ok | 1.00 | NULL |
| area-demo-1 | 2024-05-23 | NULL | 17-20 | NULL | uncertain | 0.94 | NULL |
| area-demo-2 | 2024-05-20 | 26 | 26-26 | high | protected | 1.00 | 2024-05-27 |
| area-demo-2 | 2024-04-02 | NULL | NULL | NULL | out_of_window | 1.00 | NULL |
| area-demo-3 | 2024-05-20 | NULL | NULL | NULL | insufficient_data | 0.40 | NULL |

---

## 4. Configuration (not in code)

The values live in [`config/septoria.toml`](../config/septoria.toml): TOML, because the repository already uses it and YAML would add a
dependency. Keys: `window_hours` (72), `wet_hour` (RH >= 85 %, precipitation > 0.2 mm), `thresholds` (medium 10, high 20) with their
`threshold_origin`, `protection_days_default` (10), `growth_stage` (resumption rule, degree-day base 3, zone limits 160 and 510, BBCH 30-59,
calendar fallback), plus `min_coverage` (0.80, **an assumption**, open in #33) and `max_gap_hours` (4, from the thresholds note).
White mould and yellow leaf spot are configured with `enabled = false`.

## 5. Open questions

**Decided (follows `RAW_SCHEMA.md` and #34):** weather window 2024-05-01 to 2024-06-30; the demo time shift is applied at the API
(`as_of`), not in the database; soil (`raw.soil_h3`) is in scope. The spray-window and loading notes of the team that differ from this
(shift in the database, no soil, months 2-8) are not followed.

1. ~~Growth stage in v1~~ **Decided by Piotrek:** only the sowing date is asked from the farmer. Winter wheat is in the window for all
   dates from April to June (calendar fallback of the spray-window note); spring wheat is `stage_unknown`. Known limitation, accepted:
   the note's source data put heading (end of BBCH 59) around the first decade of June, so late June may be treated as in the window.
2. Minimum coverage for a valid result and the fallback class. (#33)
3. Continuous or total wet hours. (#33 / #37) **Measured on 2024** (Mazowieckie, 1 April to 30 June, 2,428 cells, RH >= 85 %): with the longest
   continuous run (this contract) "high" is reached on 1 % of cell-days (0.6 days per cell per season), with the total number of wet hours in 72 h
   on 35 % (32 days). The choice decides whether the alert says anything; Piotrek decides. A check on 2020-2025 needs those years of hourly weather
   (`scripts/septoria_threshold_check.py`).
4. Crop area vs. cell: weather is per cell, so two crop areas in one cell differ only in window and protection.
5. Soil depth: root-zone aggregates only, or also layered depths?
6. Weather-cell polygons do not exist (`raw.grid_cell` has centres only); a QGIS layer of cells is points unless the backend generates approximate squares (step about 0.044 deg), labelled as approximate.
7. ~~Table names of the `app` schema~~ **Done** (PR #42, see the decisions above).
8. Section 6: names and shapes of `GET /fields/context` and `GET /weather/cells`, and whether the crop raster is exposed to QGIS or only per-field results (`crop_area_crop_map`).

## 6. Served to QGIS

**PROPOSAL.** The endpoints `GET /fields/context` and `GET /weather/cells` are not agreed yet; `GET /fields` is specified in
`FARMER_INPUT_CONTRACT.md`, `GET /risk` and `GET /risk/thresholds` are proposed in section 3.

QGIS reads the API as GeoJSON FeatureCollections (longitude/latitude, EPSG:4326). No QGIS-specific tables exist; every layer
below is a view of a `curated` table or of the farmer's input. All endpoints share the base prefix and the error object of
`FARMER_INPUT_CONTRACT.md` (`{"error": {"code", "message", "fields"?}}`, with stable codes such as `SERVICE_UNAVAILABLE`).

### 6.1 Common envelope

Every response carries a `meta` object next to `features`, so the plugin can always show what it displays:

| Field | Meaning |
| --- | --- |
| `meta.crs` | always `"EPSG:4326"` |
| `meta.data_status` | `mock` / `replay` / `live` |
| `meta.simulation` | `{"simulated": true, "shift_days": 730, "as_of": "2026-05-20"}`; `as_of` is the demo "now" |
| `meta.model_version` | constant string from `curated.risk_assessment` |
| `meta.generated_at` | timestamp of the response |

### 6.2 Layers

| QGIS layer | Endpoint | Geometry | One feature = | Join key | Source |
| --- | --- | --- | --- | --- | --- |
| Farmer crop areas | `GET /fields` | Polygon | crop area | `crop_area_id` | farmer input (already specified) |
| Septoria risk | `GET /risk?as_of=YYYY-MM-DD` | Polygon | crop area on one date | `crop_area_id` | `curated.risk_assessment` |
| Field context | `GET /fields/context` | Polygon | crop area | `crop_area_id` | `curated.field_context` |
| Weather cells | `GET /weather/cells?as_of=YYYY-MM-DD` | Point (cell centre) | grid cell | `grid_id` | `raw.grid_cell` + `curated.weather_hourly_features` |
| Risk thresholds | `GET /risk/thresholds` | none (JSON table) | threshold | `disease` | configuration |

`crop_area_id` is the single key that joins the risk, context and farmer layers; QGIS may also join them in its own project.

### 6.3 `GET /risk?as_of=2026-05-20`

`as_of` is a demo date; the API subtracts `meta.simulation.shift_days` and reads the row for the original local `date`. Without `as_of`
it uses the demo "now". `properties` repeat the columns of `curated.risk_assessment`; geometry is the crop-area polygon. The example
values are fictional.

```json
{
  "type": "FeatureCollection",
  "meta": {
    "crs": "EPSG:4326",
    "data_status": "replay",
    "simulation": {"simulated": true, "shift_days": 730, "as_of": "2026-05-20"},
    "model_version": "septoria-v1",
    "generated_at": "2026-11-21T12:00:00Z"
  },
  "features": [
    {
      "type": "Feature",
      "geometry": {"type": "Polygon", "coordinates": [[[20.750, 52.180], [20.755, 52.180], [20.755, 52.170], [20.750, 52.170], [20.750, 52.180]]]},
      "properties": {
        "crop_area_id": "area-demo-1",
        "field_id": "field-demo-1",
        "disease": "septoria",
        "date": "2024-05-20",
        "risk_class": "high",
        "status": "ok",
        "conditions_met": true,
        "h_hours": 26, "h_low": 26, "h_high": 26,
        "threshold_medium": 10, "threshold_high": 20,
        "coverage": 1.0,
        "growth_stage_source": "calendar",
        "protected_until": null,
        "reasons": {"window_start": "2024-05-17T22:00Z", "window_end": "2024-05-20T22:00Z", "threshold_origin": {"high": "literature", "medium": "team_assumption"}},
        "computed_at": "2026-11-21T11:40:00Z"
      }
    }
  ]
}
```

Rules for the client:

- `date` is the original source date; the shifted date is `meta.simulation.as_of`. Show both when they differ.
- `risk_class = null` is never drawn green. Use the `status` instead.
- Dates are `YYYY-MM-DD`, timestamps ISO 8601 with `Z`.
- A crop area without a row for the date is returned with `"status": "insufficient_data"`, not omitted.

### 6.4 `GET /weather/cells`

Point features at the cell centres of `raw.grid_cell`. `properties`: `grid_id`, `utc_time`, `local_time`, `relative_humidity`, `precipitation`,
`temperature`, `is_wet`, `coverage`. The grid has centres only; if cell polygons are needed they are generated by the API (square of about 0.044 deg)
and marked `"geometry_approximate": true`.

### 6.5 Styling and time

The plugin applies its own styles; the API sends none.

| Layer | Style | Time |
| --- | --- | --- |
| Septoria risk | categorized by `status`, then `risk_class`: `high` red, `medium` yellow, `low` green, `uncertain` yellow hatched, `out_of_window`, `insufficient_data` and `stage_unknown` grey | one feature set per `as_of`; the plugin refetches on a date change |
| Farmer crop areas | categorized by "farmer crop differs from crop map" (see `FARMER_FIELDS.md`) | none |
| Weather cells | graduated by `relative_humidity` | feature time field `utc_time` |

### 6.6 What the plugin guarantees

- Shows `meta.data_status` and `meta.simulation` as a banner on every layer it loads.
- Reports `error.code` and `error.message` unchanged, and leaves already loaded layers intact on failure.
- Does not compute any risk value itself.
