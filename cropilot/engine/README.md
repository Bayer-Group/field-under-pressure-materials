# Decision engine

**Owner:** Bartek · version 0.5 · data checklist: `python manage.py engine_check_data` · history and findings: [CHANGELOG.md](CHANGELOG.md)

The engine turns each field's data into a **risk per threat and day, each with an explanation of why**, and writes them to the `Risk` table. The map and the assistant only read those rows; they never compute risk themselves.

It is a **rule-based (expert) system** whose rules are stored in [`catalog.py`](catalog.py) (no document is read at run time): there are no observations of diseases in the data to train a model on. Two parts use data-driven models: the **crop** of a field (Sentinel-2 + LightGBM, trained on the crop maps) and the **growth stage** (degree days, calibrated to the field's satellite curve). Farmer reports from the chat adjust the risks.

## Contents

1. [Quick start](#quick-start)
2. [Interface](#interface)
3. [When and how to run it](#when-and-how-to-run-it)
4. [Data to load](#data-to-load)
5. [What it writes: Risk and the explanation](#what-it-writes-risk-and-the-explanation)
6. [How it works](#how-it-works)
7. [Threats](#threats)
8. [Assumptions, limits, validation](#assumptions-limits-validation)
9. [Open items for other components](#open-items-for-other-components)

## Quick start

```bash
# prerequisites: the data in "Data to load" (check: python manage.py engine_check_data)
python manage.py engine_load_threats                 # Threat rows for every rule (creates missing codes; keeps existing rows)
python manage.py engine_fetch_ndvi --season 2025     # optional: satellite curves per field (needs network)
python manage.py engine_predict --season                    # demo: previous season, then this one to its end
python manage.py engine_set_date 2025-06-20          # move the demo date (recomputes the days that change)
python manage.py engine_summary --date 2025-06-05    # fields ranked by urgency, with reasons
python manage.py test engine                         # synthetic data, no downloads needed
```

No platform import yet? `python manage.py engine_dev_seed` builds a **development-only** farm (5 fields near Krapkowice, Opolskie, season 2025) with weather, soil, crop history and the clock.

## Interface

Everything other components call. All functions use `core.clock.today()`, never the real date.

### `predict()` — compute and write risks

```python
from engine import predict

n = predict(field_ids=None, start=None, end=None, observations=None)
int(n)        # Risk rows written (n is a PredictResult: an int, so counting callers keep working)
n.field_ids   # every field rewritten, incl. nearby fields a symptoms report spread to -> updated_field_ids
```

| Argument | Default | Meaning |
|---|---|---|
| `field_ids` | all fields | Fields to recompute. Fields of the same crop within 3 km are added when a symptoms report on one of them spreads ([below](#farmer-reports)). |
| `start` | 1 September of the current season | First day to compute. |
| `end` | the later of today + 7 and the last day already stored for these fields | Last day to compute, so a recompute after a report or a crop change also replaces the precomputed days. Clipped to the last day with weather (observed, or in today's forecast): days without weather keep their rows. |
| `observations` | the `Observation` table | Farmer reports to use instead of the table (tests, scripted demos). |

- Writes in **one transaction**: deletes this range's rows for these fields, then bulk-inserts the new ones. Re-running is safe and gives the same result.
- **Which weather each day uses** ([details](#as-of-every-day)):

  | Day | Weather |
  |---|---|
  | ≤ today | observed up to that day ("as of that day") |
  | today + 1 … today + 7 (coming days) | observed up to **today**, then the **forecast issued today** (daily only: infection hours from daily estimates). No forecast issued today → no coming-day rows |
  | > today + 7 (demo precompute only) | observed up to that day; hidden by the API, and recomputed as coming days by `clock_moved()` when the date gets within 7 days |

- Reports count from their `observed_on`; satellite stages from the scene that confirmed them (coming days: scenes up to today).
- Coming days get lower confidence and `forecast_lead_days` / `forecast_issued_on` ([details](#confidence)).
- Speed: a full season for 5 fields takes a few seconds.

### `clock_moved()` — after the demo date moves

```python
from core import clock

clock.set_today(new_today)        # saves the date and calls engine.clock_moved(old, new) in one transaction
                                  # (PUT /api/clock/, the admin's clock page, engine_set_date)
```

There is **no signal**: every date change goes through `core.clock.set_today()`, never `Clock.objects.update()` or a bare `clock.save()` (the engine would not hear about it). `clock_moved(old, new)` rewrites (min(old, new), max(old, new) + 7]: days that were coming days and are now past go back to "as of that day"; the new coming days follow the forecast issued on the new date; nothing else is rewritten. A move into another season recomputes season by season, oldest first (each season's carry-over reads the previous one's peaks). From the shell: `python manage.py engine_set_date 2025-06-20`.

**Precomputed, so a move is a copy.** Every row the engine computes is also kept in its own cache table,
`engine.RiskSnapshot` (engine/models.py; one bundle per field and day: "as of that day", or "coming day of demo date
D"). `clock_moved()` copies the bundles it needs into `Risk` and computes only fields with a gap (then keeps those
too). `precompute_dates(first=None, last=None)` / `python manage.py engine_precompute_dates [--from D] [--to D]` fills
the cache ahead for a range of demo dates (default: the Clock's date - 7 … + 30; about 50 s for 8 fields), so the date
control's arrows take about 0.3 s instead of 1–4 s. `predict()` drops the bundles a report or a crop change makes
stale (that field, from `start` on). The cache is valid within one season; a move to another season computes. Copies
equal a full recompute row for row (`engine.tests.test_engine.SnapshotTests`).

### `precompute_season()` — the demo seed

```python
from engine import precompute_season

precompute_season(season=None)    # default: the clock's season -> PredictResult
```

Computes the previous season first (this season's carry-over reads its peaks from `Risk`), then this season to its end (maize to 31 December, clipped to the last day with weather). The seed calls only this. From the shell: `python manage.py engine_predict --season`.

### `what_if()` — dry run for the assistant

```python
from engine import what_if
from engine.observations import Report

what_if(field_id=15, day=date(2025, 6, 8), hypothetical=[
    Report(observed_on=date(2025, 6, 6), kind="treatment", threat_code="wheat.fusarium_head_blight", field_id=15)])
# -> [{"threat_code", "score_now", "score_if", "change", "level_if", "summary_if"}, ...]  (highest first)
```

Answers "what if I spray on Friday / sowed later / the neighbour has it". **Writes nothing.**

### `engine.summary` — one answer per field and day

```python
from engine.summary import field_day, farm_ranking

field_day(field_id, day)   # dict below
farm_ranking(day)          # list of field_day dicts, most urgent first, with "rank"
```

`field_day` is a pure read of `Risk` and the satellite cache; nothing is stored:

| Key | Content |
|---|---|
| `max_score`, `level` | Highest threat score of the day and its level. |
| `expected_loss`, `expected_loss_pct` | Share of the yield at risk: `1 - Π(1 - score × severity)` over all threats. Used to rank fields. |
| `top_threats` | Top 3 threats by expected loss, each with score, level, summary, action. |
| `actions` | `treat` / `monitor` actions, with the threshold and the spraying window. |
| `why` | One line for lists ("Fusarium head blight high (0.75); Grain aphids medium (0.53)"). |
| `growth_stage` | BBCH, name, method, confidence. |
| `harvest` | From BBCH 83: wheat — ready / next dry day / sprouting risk; maize — safe storage days of undried grain. |
| `crop_check` | Does the satellite curve fit the field's crop, plus the crop model's answer and probabilities. |
| `field_id`, `name`, `date`, `crop`, `confidence` | Identification; lowest confidence of the day's threats. |

### `engine.observations.Report` — farmer reports

```python
Report(observed_on: date, kind: str, threat_code: str | None = None, severity: float | None = None,
       distance_m: float | None = None, details: dict = {}, text: str = "", field_id: int | None = None)
```

`kind` is one of `symptoms`, `absence`, `neighbour`, `treatment`, `field_fact`, `event`; effects are in [Farmer reports](#farmer-reports). `field_id=None` means the whole farm.

### Other functions

| Function | Use |
|---|---|
| `engine.cropmodel.predict_field(field, season, today)` | Crop model for one field as of a day: `{"crop", "label", "confidence", "probabilities", ...}`. |
| `engine.harvest.safe_storage_days(moisture_pct, grain_temp_c)` | Maize grain storage table. |
| `engine.compute.adjust_for_lead(explanation, days_ahead, issued_on=None)` | The forecast discount of a coming day's confidence (used inside `predict()`). |

### Management commands

| Command | What |
|---|---|
| `engine_predict [--fields 1 2] [--start D] [--end D] [--season]` | `predict()` from the shell; `--season` = `precompute_season()`. Prints the rows and the field ids. |
| `engine_set_date D` | Save the Clock and call `clock_moved()`. |
| `engine_precompute_dates [--from D] [--to D]` | `precompute_dates()`: fill the cache so date moves copy instead of compute (default: Clock - 7 … + 30). |
| `engine_load_threats [--overwrite]` | Create the missing `Threat` rows of all 76 rules (existing rows kept unless `--overwrite`; rows without a rule listed) and the engine's `CropClass` rows if missing. |
| `engine_fetch_ndvi [--season Y] [--fields ...]` | Download and cache each field's Sentinel-2 NDVI series (network). |
| `engine_summary [--date D] [--json]` | Print the field ranking. |
| `engine_check_data [--season Y]` | Check that every table / file the engine needs is loaded; lists what is missing per field. |
| `engine_dev_seed` | **Development only**: demo farm + data. The platform's import replaces it. |
| `engine_dev_seed --season 2024 --today 2024-06-15 --crop-from-map` | **Development only**: the demo farm of 2024, all seven crops, crop from the 2024 crop map (no satellite, no network), Polish field names. |

## When and how to run it

`predict()` is the only thing that writes. It must run whenever an input of a field changes:

| When | Call | Who |
|---|---|---|
| **After the seed / import** (historical demo) | `precompute_season()` (previous season, then this one to its end) | platform seed |
| **After the demo date moves** | `clock_moved(old, new)`, right after saving the Clock | platform (`PUT /api/clock/`, admin clock page) |
| **After the seed, optional** (fast date moves) | `precompute_dates()` or `python manage.py engine_precompute_dates` | seed / by hand |
| **Daily, in live mode** (after the new forecast is stored) | `predict(start=today - 30 days)` | daily job |
| **After the assistant records a report** | `n = predict(field_ids=[field.id], start=report.observed_on)`; return `n.field_ids` (the field and nearby fields it spread to) in `updated_field_ids` | assistant tool |
| **After the farmer changes a field's crop** (`Field.crop`) | `predict(field_ids=[field.id], start=season start)` | platform (API) |
| **After `engine_fetch_ndvi`** (new satellite scenes) | `predict(field_ids=..., start=season start)` | daily job / by hand |
| **After threats, rules or imported data change** | `predict()` | by hand |

**Moving the demo date rewrites one window:** coming days depend on the forecast issued today, so after a move `clock_moved(old, new)` rewrites `(min(old, new), max(old, new) + 7]` and nothing else, copied from the precomputed cache where it can (see `clock_moved()` above) and computed otherwise (about 0.2 s per field). There is no signal on `Clock`: the caller does it. With the default `end`, every other call above already reaches the precomputed days.

**Order of a fresh setup:**

```bash
python manage.py migrate
# platform import (exact spec: "Data to load"): CropClass, WeatherGrid, Field, FieldCropYear, SoilCell,
#                  WeatherDaily (+ IMERG), WeatherHourly (+ IMERG), WeatherForecastDaily, Clock
python manage.py engine_load_threats            # or the platform's Threat fixture with the same codes
python manage.py engine_fetch_ndvi --season 2024
python manage.py engine_fetch_ndvi --season 2025   # both optional (network)
python manage.py engine_check_data              # must end with "Everything the engine requires is present."
python manage.py engine_predict --season               # last season first (carry-over), then this one to its end
```

Last season goes first because this season reads last season's risks: a pathogen that peaked on the field carries over in the residue.

## Data to load

Everything below must be in place **before** `predict()` runs. Check it with:

```bash
python manage.py engine_check_data        # per field: OK / MISSING (required) / OPTIONAL; exit code 1 if something required is missing
```

The engine reads only through the Django ORM and the platform helpers (`.observed(as_of=...)`, `.current(as_of=...)`, `field.soil_cells()`, `field.crop_years`); it never reads the raw files itself, except the two `DATA_DIR` files at the end.

### Which rows: scope and dates

- **Cells:** weather only for the grid cells the fields point to (`Field.weather_grid`), soil only for the fields' H3 cells (`Field.h3_cells`). One weather cell usually serves the whole farm.
- **Dates** (season = harvest year; winter crops 1 Sep – 31 Aug, maize to 31 Dec, sugar beet to 30 Nov, potato to 31 Oct):

| Data | From | To |
|---|---|---|
| `WeatherDaily`, `WeatherHourly` | **45 days before the season start** (trailing windows); for the demo season 2025: **2024-07-18** | the last day you compute: for a precomputed demo season **2025-10-31** (maize harvest); live: today |
| same, previous season (carry-over) | 2023-07-18 | 2024-08-31 |
| `WeatherForecastDaily` | issued on **every day** from the season start | issued on the last computed day (each issue covers +1 … +7) |
| `FieldCropYear` | at least the previous season (2024 for season 2025); ideally the 5 previous years (2020–2024) | |

### Tables, sources and columns

**Required** = no risks (or wrong risks) without it. Source paths are as in the organisers' package (`DATA_DIR/raw/...`).

| Table | Required | Rows | Columns the engine reads (format) | Source file → how |
|---|---|---|---|---|
| `Clock` | **yes** | 1 | `today` (date) | set by the seed: the demo date, e.g. 2025-06-15 |
| `CropClass` | **yes** | all 21 legend codes (at least every code in `FieldCropYear`) | `code`, `name` | cropland legend (`data/cropland.md`): 0 No cropland, 1110 Wheat, 1120 Barley, 1130 Maize, … |
| `Threat` | **yes** | 76 | `code` = the codes in [Threats](#threats), `crop` | `python manage.py engine_load_threats`: creates the missing engine codes and **keeps existing rows** (a platform fixture's names and texts stay; `--overwrite` rewrites them). Fixture codes without an engine rule get no risks (the command lists them). A missing engine code is skipped by `predict()` with a warning, not a crash |
| `WeatherGrid` | **yes** | the fields' cells | `grid_id`, `lat`, `lon` (floats) | `weather_data/weather_grids.zip` → `weather_grids.parquet` (`grid_id`, `lat`, `lon` are **decimals → cast to float**, `l1_name` = voivodeship) |
| `Field` | **yes** | the farm's fields | `geometry` (GeoJSON Polygon/MultiPolygon, EPSG:4326, **[lon, lat]**, non-empty), `centroid_lat/lon`, `area_ha` (EPSG:2180), `weather_grid` (**nearest grid point to the centroid**), `h3_cells` (**H3 level 10 cells whose centre is inside the polygon** — `h3.geo_to_cells(polygon, 10)`; the centroid's cell if none), `crop` (**this season's crop**: 1110 wheat, 1120 barley, 1130 maize, 1150 other cereals, 1310 potato, 1320 sugar beet, 1430 rapeseed get risks; other codes get none) | polygons drawn by us; crop from the farmer or the crop model (`field_day()["crop_check"]`) |
| `FieldCropYear` | **yes** | per field × year × class | `year`, `crop_class`, `share` (0–1, shares of a year sum to 1) | `cropland/cropland_pl_4326_<year>.zip` (48 GeoTIFF tiles, EPSG:4326, uint16 codes): pixels of each class inside the polygon ÷ all pixels. **2021 is a copy of 2022** in the package — store it but expect it to be wrong |
| `WeatherDaily` | **yes** | per cell × day | `avg_temperature`, `min_temperature`, `max_temperature` (°C), `avg_relative_humidity` (%), `eto` (mm/day), `avg_wind_speed` (km/h), `avg_soil_temperature_level_1`, `min_soil_temperature_level_1` (°C), `avg_soil_moisture_level_1` (m³/m³, 0–1), `avg_snow_depth` (mm w.e.), **precipitation: `total_precipitation` or `imerg_total_precipitation`** (mm/day) | `weather_data/daily/<year>/weather_daily_<year>_<Region>.zip` (same column names; **no precipitation in it**) + `weather_data/imerg_precipitation_daily.zip` → `daily/<year>/precip_daily_<year>_<Region>.zip` (nested zip) → `total_precipitation` **stored as `imerg_total_precipitation`**, joined on `grid_id` + `date` |
| `WeatherHourly` | recommended | per cell × hour | `utc_time` (aware, UTC), `date` (local Europe/Warsaw date), `temperature` (°C), `relative_humidity` (%), **`precipitation` or `imerg_precipitation`** (mm/h) | `weather_data/hourly/<year>/weather_hourly_<year>_<Region>.zip` (`utc_time` is naive UTC → make aware; drop `local_time`; year files **overlap by one hour** at New Year → ignore duplicates) + `imerg_precipitation_hourly.zip` → `hourly/<year>/precip_hourly_<year>_<Region>.zip` → `precipitation` stored as `imerg_precipitation`, joined on `grid_id` + `utc_time`. Without it infection hours are estimated from daily values (confidence × 0.7) |
| `WeatherForecastDaily` | **yes** (without it: no spraying window, no harvest dry days) | per cell × issue day × 7 | `max_temperature`, `min_temperature`, `avg_wind_speed`, `avg_relative_humidity`, `total_precipitation` | demo: for every day D copy `WeatherDaily` of D+1 … D+7 with `issued_on = D` (all daily columns except IMERG). Live: a real forecast |
| `SoilCell` | optional | the fields' H3 cells | `clay`, `sand` (fraction 0–1 **or** %; both accepted), `ph` | `soil_isric_250_v2/soil_<Region>_isric_250_v2.zip` → parquet keyed by `h3_index_10`; rename `soilTexture` → `soil_texture`; `BAND_om`/`BAND_pH`/`BAND_cec` are **text** (`low`/`moderate`/`high`) while the model columns are floats — leave them empty or change the model. Used only for the heavy-soil multiplier |
| `Observation` | optional | farmer reports | see [below](#observation-rows) | written by the chat (`assistant.Observation` now, `core.Observation` later) |
| `Risk` | — | written by `predict()` | — | last season's rows are read back for carry-over, so compute the previous season first |

`<Region>` in file names is the voivodeship without Polish letters (`Opolskie`, `Dolnoslaskie`, `Slaskie`; some packages spell `Łódzkie` as `odzkie` and `Małopolskie` as `Maopolskie`).

### Farmer input: facts on the field, events in Observation

What the farmer tells the chat is of two kinds, stored in two places (proposal for Jan + Szymek and Ola):

| Kind | Examples | Where it goes | Why |
|---|---|---|---|
| **Facts about the field** (a state that corrects our data) | "it's rapeseed, not wheat", "last year it was maize", "I sowed on 25 Sep", "I don't plough", "the variety is resistant to brown rust" | **core tables**: `Field.crop`, `FieldCropYear` (year, class, share 1.0), and new columns `Field.sowing_date` (date, null), `Field.tillage` (`plough` / `reduced`, blank), `Field.resistant_to` (JSON list of threat codes); `FieldCropYear.source` (`crop map` / `farmer`) would keep the two apart | one value per field; the map, the engine and the chat all read the same row |
| **Events in time** | "I see rust (12 Jun)", "I sprayed on 10 May", "my neighbour has head blight", "hail yesterday", "inspected, clean" | **`core.Observation`** (one row per report, columns below) | the engine recomputes every day *as of* that day, so it needs the date of each report; several reports per field; the explanation quotes them |

- The assistant writes both through **one validated tool** after the farmer confirms (like `record_observation`: idempotency key, threat resolved to a code), never with raw SQL from MCP (the MCP role stays read-only).
- A changed fact is also logged as an Observation (`kind = field_fact`), so it is clear who changed what and when.
- After the write: `predict(field_ids=[field.id], start=...)` — the day seen for an event, the season start (1 Sep; sowing date for spring crops) for a changed crop or sowing date.
- **Engine side (ready):** it reads `Field.crop` and `FieldCropYear` already; `Field.sowing_date`, `Field.tillage` and `Field.resistant_to` are read **if the columns exist** (`observations.from_field`) and explained as "Field record: …". A sowing date applies only to its own season; tillage and resistance (no date on the field) apply from the start of the current season, so they never rewrite last season. Until the columns exist, `field_fact` observations do the same job.

### Observation rows

Farmer reports **are stored in the database**: the engine recomputes each day "as of" that day, so it must
see every report made up to then, and the map and the chat show them in the explanation ("the farmer saw
rust on 12 June"). After storing a row the writer calls `predict(field_ids=[field.id], start=<date seen>)`.

**Status**

| Table | Owner | State | Engine reads it |
|---|---|---|---|
| `core.Observation` | Jan + Szymek (schema) | **not created yet** (agreed home, `docs/database.md` open questions) | yes (`observations.load_all()`) |
| `assistant.Observation` | Ola | **exists in `main`** (interim), written by the chat tool `record_observation`, which already calls `predict()` | **yes** (adapter `_from_assistant` in `engine/observations.py`; mapping below) |

**What the engine needs per row** (`assistant.Observation` today → what to add)

| Engine needs | Meaning | In `assistant.Observation` | To do |
|---|---|---|---|
| field | which field; none = the whole farm / "nearby" | `field` (FK, required) | – (farm-wide reports: pick any field, set `details.scope = "farm"`) |
| date seen | the day the farmer **saw** it, not the day they wrote | `date` | – |
| **kind** | `symptoms`, `absence`, `neighbour`, `treatment`, `field_fact`, `event` | only `category` (choroba / szkodnik / chwasty / uszkodzenie / inne) | **Ola: write `details.kind`** (top level or inside `details.draft`) for anything that is not "I see it on my field". Without it: choroba / szkodnik → `symptoms`, uszkodzenie → `event`, chwasty / inne → **skipped and logged** (never guessed as symptoms; the same for a `core.Observation` row without `kind`) |
| threat | threat code, e.g. `wheat.brown_rust`; empty: `symptoms` → every disease (choroba) or pest (szkodnik) × (1 + 0.3 × severity), `absence` → all threats, `treatment` → all fungal | `threat` (FK Threat, optional) | – (the code is read through the FK) |
| severity | how bad, 0–1 | `severity` niskie / srednie / wysokie | – (mapped to 0.3 / 0.6 / 0.9; a number 0–1 is used as is; empty = 0.5) |
| distance | `neighbour` only: metres to the reported case | – | **Ola: `details.distance_m`** (number; "next door" ≈ 300, "in the village" ≈ 1500; empty = 1000) |
| fact | `field_fact` only | – | **Ola: `details`** = `{"sowing_date": "2024-09-25"}`, `{"tillage": "reduced"}` or `"plough"`, `{"resistant_to": ["wheat.brown_rust"]}` |
| event type | `event` only | – | **Ola: `details.type`** = `hail`, `lodging` or `flood` (without it the engine looks for grad / wyległ / zalan in `note`; otherwise it counts as crop damage of unknown type: fungal × 1.1 for 14 days, shown as "Crop damage (type not given)") |
| text | the farmer's own words (quoted in the explanation) | `note` | – |
| id | stable id for drivers and logs | `id` | – |

**Examples of `details` the chat should write**

| The farmer says | `category` | `threat` | `severity` | `details` |
|---|---|---|---|---|
| "I see brown rust on the north field" | choroba | wheat.brown_rust | srednie | `{}` (or `{"kind": "symptoms"}`) |
| "I walked the field, it's clean" | choroba | (empty = all) | – | `{"kind": "absence"}` |
| "My neighbour has head blight, next field over" | choroba | wheat.fusarium_head_blight | – | `{"kind": "neighbour", "distance_m": 300}` |
| "I sprayed against septoria on 10 May" (date = 10 May) | choroba | wheat.septoria_leaf_blotch (empty = all fungal) | – | `{"kind": "treatment"}` |
| "I sowed on 25 September" | inne | – | – | `{"kind": "field_fact", "sowing_date": "2024-09-25"}` |
| "I don't plough, I leave the stubble" | inne | – | – | `{"kind": "field_fact", "tillage": "reduced"}` |
| "Hail yesterday" | uszkodzenie | – | – | `{"kind": "event", "type": "hail"}` |

**The reader accepts either shape** for both tables: date `observed_on` or `date`; threat `threat_code` (text) or `threat` (FK); severity a number 0–1 or niskie / srednie / wysokie; text `text` or `note`; kind `kind`, `details.kind` or the category. A row whose kind cannot be told is skipped with a log warning.

**Later `core.Observation`** (Jan + Szymek): the same information as plain columns: `field` (FK, null =
farm), `observed_on` (date), `recorded_at` (datetime), `kind` (text, values above), `threat_code` (text,
null), `severity` (float 0–1, null), `distance_m` (float, null), `details` (JSON: facts and event type),
`text` (the farmer's words). Moving the interim rows is a plain copy with the mapping above; the engine
reads both, so nothing breaks in between. Only engine-known keys of `details` are used (`kind`, `distance_m`, `sowing_date`, `tillage`, `resistant_to`, `type`, `scope`); others are ignored.

### Files in `DATA_DIR` (optional, not in git)

`DATA_DIR` is set in `.env` (default `../field-under-pressure-data`).

| File | Used for | How to produce |
|---|---|---|
| `satellite/fields/field<id>_<polygon hash>_s<season>.parquet` (columns `date`, `ndvi`, `ndvi_p25`, `ndvi_p75`, `clear_share`, `pixels`) | growth-stage calibration, crop check | `python manage.py engine_fetch_ndvi --season 2025` (and `--season 2024`) after the fields exist; needs internet (Earth Search, no account). A new polygon gets a new hash, so re-run after redrawing a field |
| `models/crop_lgbm.txt` + `models/crop_model.json` (≈ 15 MB) | crop check | copy from Bartek, or train: put the organisers' zips in `DATA_DIR/raw/` (`cropland/`, `weather_data/daily/<year>/`), then `python engine/scripts/clip_cropland.py DATA_DIR/raw/cropland DATA_DIR/cropland`, `python engine/scripts/build_crop_samples.py DATA_DIR` (internet), `python -m engine.cropmodel train DATA_DIR`; also needs `DATA_DIR/weather/weather_grids.parquet` |

Without them the engine still runs: stages from degree days only, no crop check.

**The dev seed** (`engine_dev_seed`, development only) reads: `DATA_DIR/cropland/cropland_<year>.tif` (from `clip_cropland.py`), `DATA_DIR/weather/weather_grids.parquet`, `DATA_DIR/raw/weather_data/{daily,hourly}/<year>/*.zip`, `DATA_DIR/raw/weather_data/imerg_precipitation_{daily,hourly}.zip`, `DATA_DIR/soil/<Region>_isric_250_v2.parquet`.

Units stay the dataset's (wind km/h, RH %, radiation MJ/m²); the engine converts where a rule uses another unit (wind 4 m/s = 14.4 km/h).

## What it writes: Risk and the explanation

One `Risk` row per **field × threat × day**: `score` (0–1), `explanation` (JSON below), `computed_at`.

**Score** = how favourable the recent days were for this threat on this field: **weather or pest activity × growth-stage weight × field multipliers**, adjusted by farmer reports, capped at 1. An index, not a probability. **Levels:** low < 0.33 ≤ medium < 0.66 ≤ high — the same cut-offs as the map (`frontend/src/risk.ts`) and the assistant (`assistant/domain.py`). Every explanation carries `level`; readers should show it rather than recompute it.

**`explanation` (version 1):**

```jsonc
{
  "version": 1,
  "summary": "High risk of Fusarium head blight (fuzarioza kłosów): hours at 15-25 °C with wet leaves (RH >= 95 % or rain) in the last 5 days: 16 h; crop at flowering, BBCH 63; previous crop was maize (residue carries the fungus).",
  "level": "high",
  "score": 0.83,
  "threat": {"code": "wheat.fusarium_head_blight", "name_pl": "fuzarioza kłosów", "name_en": "Fusarium head blight", "category": "fungal"},
  "as_of": "2025-06-07",
  "crop": {"code": 1110, "source": "field"},              // "crop map" for past seasons
  "growth_stage": {"bbch": 63, "name": "flowering", "method": "degree days calibrated to the satellite: NDVI peak 0.91 on 2025-05-24 (heading)",
                   "sowing_assumed": "2024-10-01", "confidence": 0.8},
  "drivers": [                                              // WHY: one entry per factor
    {"factor": "condition_hours", "label": "Hours at 15-25 °C with wet leaves ...", "value": 16, "unit": "h",
     "threshold": "4 h starts the risk, 16 h = full risk", "effect": 1.0},
    {"factor": "growth_stage", "label": "Growth stage BBCH 63 (flowering); susceptible BBCH 61-69", "value": 63, "unit": "BBCH", "effect": 0.0},
    {"factor": "previous_crop", "label": "Previous crop was maize (residue carries the fungus)", "multiplier": 1.5, "effect": 0.21},
    {"factor": "farmer_report", "kind": "neighbour", "label": "Reported Fusarium head blight about 400 m away on 2025-06-03 ...",
     "observed_on": "2025-06-03", "text": "Sąsiad ma fuzariozę...", "effect": 0.28},
    {"factor": "rain_days", "label": "Days with >= 1 mm rain in the window ...", "value": 2, "unit": "days", "effect": null}
  ],
  "action": {
    "type": "treat",                                        // wait / monitor / treat
    "text": "High risk: inspect the field now; if the threshold is exceeded, a treatment is justified.",
    "threshold": "Heading: ... (threshold for this stage)",
    "spray_window": {"date": "2025-06-08", "quality": "optimal", "conditions": {...}, "rule": "1-25 °C, next night >= 1 °C, ...",
                     "note": null}
  },
  "severity": 0.15,                 // potential yield loss if it happens (team assumption)
  "expected_loss": 0.12,            // score x severity
  "confidence": 0.8,                // stage method x data quality x forecast distance; 1.0 when the farmer saw it
  "confidence_observed": 0.8,       // only on days after today: confidence before the forecast discount
  "forecast_lead_days": 3,          // only on days after today
  "notes": ["Each 1 % of infected ears can add about 0.3 mg/kg DON ..."],
  "assumptions": {"hours_low": 4, "hours_high": 16, ...},   // the team's own numbers in this rule
  "model": "rules", "model_version": "0.1.0"
}
```

- `effect` = how much the score would drop without that factor; `null` = context only. The map can show `summary` and the drivers; the assistant explains from the same fields.
- No product names or doses anywhere (shared principle).

## How it works

```text
for each field, for each season in [start, end]:
    crop        = Field.crop (current season) | crop map (past seasons)
    weather     = daily + hourly for the field's grid cell (observed)
    stage       = BBCH from degree days                         (phenology.py)
                  → shifted through satellite anchors            (satellite/fieldndvi.py, from the day they are confirmed)
                  → farmer's sowing date if reported             (from the day it was reported)
    context     = previous crop, maize years in a row, soil, last season's peaks
    reports     = farmer reports + symptoms spread from nearby fields
    for each threat rule of the crop                             (catalog.py)
        base    = weather / activity term per day, trailing windows only     (scoring.py)
        score   = base × stage weight × multipliers, then report effects, capped at 1
        explanation: summary, drivers with effects, action + spraying window
write all rows (replace the range)                               (compute.py)
```

### As of every day

Every feature for day D is a **trailing** value over days ≤ D (sums or means over the last N days), so a whole season is computed in one pass without look-ahead. Reports affect days ≥ their `observed_on`; satellite stage anchors apply from the scene that confirmed them; the spraying window uses the forecast issued on D. A test changes the weather after D and checks that D's risks stay the same.

**Coming days** (today + 1 … + 7) are a projection: the trailing windows are filled with the weather observed up to today and then the forecast issued today (`features.load_forecast`), the stage curve continues on the forecast temperatures, satellite anchors stop at today, and the spraying window reads today's forecast for the days after D. The forecast is daily only, so hourly rules use the daily estimate (confidence × 0.7). In live mode, with nothing observed after today, the coming days still exist as long as a forecast is stored. Contract tests: `engine/test_predict_contract.py` (from the platform's review, `docs/archive/engine-predict-review.md`).

### Growth stage

- **Degree days** from a typical sowing date (`engine.phenology.PROFILES`, confidence 0.6):

| Crop | Sown (typical) | GDD base | Curve |
|---|---|---|---|
| Wheat | 1 Oct | 0 °C | autumn since sowing, spring since 1 Jan (satellite-calibrated) |
| Barley | 20 Sep | 0 °C | wheat curve reached with 82 % of the degree days (heading ~ mid May, harvest early July) |
| Other cereals | 25 Sep | 0 °C | wheat curve, 95 % of the degree days |
| Rapeseed | 25 Aug (before the season starts) | 5 °C | rosette (BBCH 18–19) before winter; spring: buds early April, flowering mid April – early May, harvest early/mid July |
| Maize | 25 Apr | 6 °C | since sowing |
| Sugar beet | 5 Apr | 3 °C | emergence ~ 20 Apr, canopy closing mid June, root growth to harvest |
| Potato | 20 Apr | 6 °C | emergence mid May, rows closing mid June, flowering early July, haulm senescence late August |
- **Satellite anchors** (wheat and maize only) from the field's NDVI curve: wheat — spring peak (May–June, ≥ 0.7) = heading BBCH 55, NDVI < 0.5 afterwards = ripening BBCH 83; maize — rise from bare soil after sowing = BBCH 13, summer peak = flowering BBCH 65. The degree-day curve is shifted through the anchor from the day it is confirmed. Confidence 0.8.
- **Farmer's sowing date** replaces the typical one. Confidence 0.85.
- The wheat table was calibrated to the satellite: heading ~1060, ripening ~2135 degree days since 1 January.
- Maize seasons run to 31 December, sugar beet to 30 November, potato to 31 October; winter crops 1 Sep – 31 Aug. Seasons after the current one are not computed (crop unknown).

### Rule kinds

| Kind | Weather / activity term | Example |
|---|---|---|
| `infection_hours` | Hours in the last N days with temperature in the rule's range **and** wet leaves (RH ≥ 95 % or rain) / humid air (RH ≥ 85 % or rain) / RH ≥ 90 % or rain (potato late blight, Smith-type periods) / humid but dry (RH 50–95 %, no rain); ramp from `hours_low` to `hours_high`. Rain-splash diseases also need rain days. Leaf diseases of winter crops switch off in cold weather (7-day mean < 3–8 °C). Maize fusarioses also rise with drought (30-day rain − evapotranspiration). | head blight, septoria, rusts |
| `soil_days` | Days with topsoil in the rule's temperature range (cold, e.g. < 12 °C, or warm, e.g. 20–30 °C) and wet (≥ 0.30 m³/m³) | seedling blights, beet Rhizoctonia, clubroot |
| `snow_days` | Days at ~0–5 °C, wet or under snow, soil not frozen | snow mould |
| `flood` | Days with saturated topsoil or ≥ 30 mm rain | crazy top |
| `vector_days` | Days warm enough for the insect to fly (max ≥ `flight_c`, 12–18 °C) since emergence, in the susceptible stage | aphid-borne viruses, rapeseed pests, beet flea beetle |
| `pest_activity` | Activity window from degree days (base 10 °C) or the crop stage, × warmth, × local pressure from the field's history (rotation pests: 1.0 with a host crop in the last 3 seasons, else 0.1) | corn borer, rootworm, Colorado beetle, cyst nematodes |

**Growth-stage weight:** 1 inside the threat's susceptible BBCH range, ramping to 0 outside it; 0 before sowing.

**Multipliers (from the field):** previous crop maize (head blight ×1.5, foot rot ×1.3), cereal after cereal (take-all ×1.5, eyespot ×1.5, tan spot ×1.3), maize monoculture (fusarioses ×1.3, corn borer ×1.4; rootworm only from the 2nd maize year), heavy soil (crazy top, beet damping-off and Rhizoctonia ×1.3), same crop last season (e.g. rapeseed after rapeseed: Sclerotinia ×1.5, Phoma ×1.4, clubroot ×1.5; beet after beet: Cercospora ×1.5; potato after potato: Colorado beetle ×1.4), other previous crops (beet after maize: Rhizoctonia ×1.4; rapeseed after sunflower / soybean: Sclerotinia ×1.3), acid soil pH < 6.5 (clubroot ×1.5), **last season's peak of the same pathogen ≥ 0.66** (×1.2; Fusarium is shared by maize and wheat).

### Farmer reports

| `kind` | Example from the chat | Effect | Duration |
|---|---|---|---|
| `symptoms` | "I see brown rust on the north field" | score at least 0.66 + 0.3 × severity (always high); confidence 1; spreads to same-crop fields within 3 km as `neighbour` | full 10 days, gone by day 21 |
| `absence` | "Inspected, clean" (`threat_code` empty = all) | × 0.5 | back to normal by day 10 |
| `neighbour` | "My neighbour has head blight" | × (1 + 0.5 × closeness), closeness 1 up to 500 m, 0 at 3 km | full 7 days, gone by day 21 |
| `treatment` | "Sprayed against septoria on 10 May" (empty = all fungal) | × 0.3; action becomes "wait" | full 14 days, gone by day 21 |
| `field_fact` | `{"sowing_date": "2024-09-25"}`, `{"tillage": "reduced"}`, `{"resistant_to": [codes]}` | real sowing date; reduced tillage × 1.3 for residue diseases; resistant variety × 0.6 | rest of the season |
| `event` | `{"type": "hail" / "lodging" / "flood"}` (no type: guessed from the text, else "damage") | hail: fungal × 1.3; lodging: fungal × 1.2; flood: crazy top at least 0.7; damage of unknown type: fungal × 1.1 | 14–28 days |

Every applied report is a driver with its `effect`, and its label is added to the summary. The numbers are team assumptions.

### Actions and spraying window

- `wait` (low, outside the susceptible stage, or protected by a recent treatment), `monitor` (medium; or high but no in-season treatment exists), `treat` (high: inspect now and treat if the threshold is exceeded).
- The threshold shown is the one **for the current stage**.
- Spraying window: first forecast day with 1–25 °C, next night ≥ 1 °C, RH 50–95 %, no rain, wind ≤ 4 m/s; "optimal" at 12–20 °C, RH 75–95 %, wind 0.5–1.5 m/s.

### Confidence

`confidence` = stage confidence (0.6 degree days / 0.8 satellite / 0.85 farmer's sowing date) × 0.7 if hourly weather was missing × (1 − 0.06 × days ahead, at least 0.4) for coming days (`confidence_observed` keeps the value before the discount, `forecast_lead_days` and `forecast_issued_on` say which forecast); 1.0 when the farmer reported symptoms.

### Crop

The engine uses `Field.crop`. The crop model ([`cropmodel.py`](cropmodel.py)) checks it: LightGBM on the half-month NDVI curve of the season known so far (slots after today empty), the previous crop, and NDVI at fixed degree-day points; trained on 30 windows × seasons 2020, 2022, 2023 of the crop maps across Opolskie. Its answer is in `field_day()["crop_check"]`, so the farmer can confirm or correct the crop; a corrected crop needs a `predict()` for that field.

## Threats

76 rules for 7 crops in [`catalog.py`](catalog.py), each with its numbers and the team's assumptions marked.
Together these crops cover about 96 % of the arable land in Opolskie (2024 crop map: wheat 32 %, maize 25 %,
rapeseed 14 %, barley 10 %, other cereals 10 %, sugar beet 3 %, potatoes 1.5 %). Other crop codes get no risks.
Rules shared by several cereals (same pathogen) are variants of the wheat rule with their own code.
Rapeseed numbers are general agronomy (no rapeseed guide in the package), all listed under `assumptions`.

| Crop (code) | Category | Threats (`code`) |
|---|---|---|
| Wheat (1110) | fungal | `wheat.fusarium_head_blight`, `wheat.septoria_leaf_blotch`, `wheat.brown_rust`, `wheat.powdery_mildew`, `wheat.yellow_rust`, `wheat.tan_spot`, `wheat.take_all`, `wheat.snow_mould`, `wheat.eyespot`, `wheat.fusarium_foot_rot`, `wheat.glume_blotch` |
| Wheat (1110) | viral | `wheat.barley_yellow_dwarf` |
| Wheat (1110) | pest | `wheat.aphids`, `wheat.cereal_leaf_beetle` |
| Barley (1120) | fungal | `barley.powdery_mildew`, `barley.fusarium_head_blight`, `barley.eyespot`, `barley.fusarium_foot_rot`, `barley.take_all`, `barley.snow_mould`, `barley.net_blotch`, `barley.scald`, `barley.brown_rust` |
| Barley (1120) | viral | `barley.barley_yellow_dwarf` |
| Barley (1120) | pest | `barley.aphids`, `barley.cereal_leaf_beetle` |
| Maize (1130) | fungal | `maize.seedling_blight`, `maize.fusarium_ear_rot`, `maize.fusarium_stalk_rot`, `maize.crazy_top`, `maize.northern_leaf_blight`, `maize.eyespot`, `maize.common_rust` |
| Maize (1130) | pest | `maize.european_corn_borer`, `maize.western_corn_rootworm`, `maize.aphids`, `maize.frit_fly` |
| Other cereals (1150) | fungal | `other_cereals.powdery_mildew`, `other_cereals.fusarium_head_blight`, `other_cereals.glume_blotch`, `other_cereals.yellow_rust`, `other_cereals.tan_spot`, `other_cereals.eyespot`, `other_cereals.fusarium_foot_rot`, `other_cereals.snow_mould`, `other_cereals.brown_rust`, `other_cereals.scald` |
| Other cereals (1150) | viral | `other_cereals.barley_yellow_dwarf` |
| Other cereals (1150) | pest | `other_cereals.aphids`, `other_cereals.cereal_leaf_beetle` |
| Potatoes (1310) | fungal | `potato.late_blight`, `potato.early_blight`, `potato.rhizoctonia` |
| Potatoes (1310) | viral | `potato.aphids` |
| Potatoes (1310) | pest | `potato.colorado_potato_beetle`, `potato.cyst_nematode` |
| Sugar beet (1320) | fungal | `sugar_beet.cercospora_leaf_spot`, `sugar_beet.ramularia_leaf_spot`, `sugar_beet.powdery_mildew`, `sugar_beet.downy_mildew`, `sugar_beet.seedling_damping_off`, `sugar_beet.rhizoctonia_root_rot` |
| Sugar beet (1320) | viral | `sugar_beet.aphids_virus_yellows` |
| Sugar beet (1320) | pest | `sugar_beet.flea_beetle`, `sugar_beet.beet_leaf_miner`, `sugar_beet.beet_cyst_nematode` |
| Rapeseed (1430) | fungal | `rapeseed.phoma_stem_canker`, `rapeseed.light_leaf_spot`, `rapeseed.sclerotinia_stem_rot`, `rapeseed.alternaria_black_spot`, `rapeseed.clubroot` |
| Rapeseed (1430) | viral | `rapeseed.aphids_tuyv` |
| Rapeseed (1430) | pest | `rapeseed.cabbage_stem_flea_beetle`, `rapeseed.stem_weevils`, `rapeseed.pollen_beetle`, `rapeseed.seed_weevil_pod_midge` |

## Assumptions, limits, validation

- **Not validated against real outbreaks**: the data has none. Ranges and stages follow integrated pest management practice; *how many hours make a risk high* is the team's choice, calibrated on 2025 near Krapkowice (a dry April, a wet June). Each explanation lists these numbers under `assumptions`.
- Severities (yield loss if a threat materialises) are team assumptions; they only rank fields.
- **The weather packages have no precipitation** (only IMERG): the demo seed fills the forecast's `total_precipitation` from the observed day's IMERG value. Without it the spraying window cannot check rain — the window says so.
- In the historical demo the forecast is a copy of the observed days, but daily only: coming days use daily estimates instead of hourly humidity, so they are less precise than past days, as with a real forecast.
- Weather is one 4 km cell: fields of one farm share it; they differ by crop, stage, history, soil and reports.
- **Crop model on 534 fields never seen in training (2024):** wheat / maize / other right 74 % by end of May, 77 % by end of August; "wheat" correct 71–80 %, "maize" 86–97 %; wheat vs maize 99–100 % from end of May. Wheat vs other winter cereals is the weak spot, hence the farmer's confirmation.
- Weather risks without a disease (frost, drought, heat) are not threats yet: `Threat.Category` has no such category.

## Open items for other components

| Item | Who | Engine side |
|---|---|---|
| **API endpoints for risks** (`/api/risks/?date=`, `/api/fields/{id}/risks/`, `/api/fields/{id}/risks/{date}/`), optionally `field_day` / `farm_ranking` | Jan + Szymek | ready: `Risk` rows, `engine.summary` |
| **Farmer reports** — `details.kind` / `distance_m` / facts in `assistant.Observation` ([Observation rows](#observation-rows)); later `core.Observation` | Ola (writes), Jan + Szymek (`core` schema) | reads `core.Observation` and `assistant.Observation`; an interim row whose `idempotency_key` is already in `core.Observation` counts once. Remove the interim reader once Ola has switched |
| **Facts on the field** — `Field.sowing_date`, `Field.tillage`, `Field.resistant_to`, `FieldCropYear.source`; the chat writes confirmed facts there ([Farmer input](#farmer-input-facts-on-the-field-events-in-observation)) | Jan + Szymek (columns), Ola (tool) | reads them if present |
| Assistant tools: record a report → `predict(field_ids=[...], start=observed_on)`, return its `.field_ids` as `updated_field_ids`; "what if" → `what_if()`; "which field first" → `farm_ranking()` | Ola | ready |
| Map: colour by `explanation.level` (cut-offs 0.33 / 0.66, the same as `frontend/src/risk.ts`), "why" panel from `summary` + `drivers`, crop check from `field_day()["crop_check"]` | Kuba | ready |
| Threat codes: use `engine_load_threats`, or a fixture with the same codes | Jan + Szymek | ready |
| **Demo date:** `PUT /api/clock/` and `ClockAdmin.save_model` call `engine.clock_moved(old, new)` after saving; the seed calls `engine.precompute_season()` and fills forecast rain from IMERG | Jan + Szymek | ready |
| New categories `weather` / `soil` / `harvest` for frost, drought, harvest risks | Jan + Szymek | rules would follow |
| **Data issues found:** the weather packages have **no precipitation** (only IMERG); soil `clay`/`sand` are fractions, `BAND_*` are text; grid lat/lon are decimals; hourly year files overlap by one hour; **the 2021 crop map is identical to 2022** (`FieldCropYear` 2021 is wrong) | Jan + Szymek, organisers | handled in the engine |
