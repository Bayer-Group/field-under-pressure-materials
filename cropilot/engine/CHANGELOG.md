# Decision engine — changelog

History of the engine's versions and the findings behind them. The reference documentation is [README.md](README.md).

## v0.13: fixes from the app audit (docs/audit-2026-11-21.md)

- **Late crops across seasons (E-1).** From 1 September a spring crop of the previous season (maize to 31 December,
  beet, potato) is scored as that season's crop until its harvest, whichever season the Clock is in; a winter crop of
  the new season takes the field from its assumed sowing. Before, with the Clock in September–December, maize days
  were scored as next year's maize "before sowing" (BBCH −1, every risk 0) and the season chart dropped to zero.
- **Moves into another season (E-2).** `clock_moved()` recomputes one season at a time, oldest first, from the start
  of the season before the later date at the earliest, so each season's carry-over reads the peaks the previous one
  has just written (one `predict()` over several seasons read stale peaks and did not return to the same state).
- **Effects of every factor (E-11, E-12).** Rain days, the 7-day temperature, the local pest pressure and the 30-day
  water balance change the score, so their drivers now carry an `effect` (leave one out) instead of `null`; the
  growth stage's and multipliers' effects are measured with the farmer's reports applied, like the score.
  `level` is computed from the rounded score, so the two never disagree at a boundary.
- **Neighbour reports without a threat (E-6)** raise every threat of their group (pest / disease) ×(1 + 0.25 × closeness).
- **Coming days' harvest outlook (E-14)** no longer reads observed weather after today: it continues with today's forecast.
- `engine_set_date` goes through `clock.set_today()` (one transaction; creates the Clock row; strict YYYY-MM-DD) (E-4).
- `clock_moved()` copies with `update_conflicts`, so a `predict()` from the chat at the same moment can't make it fail.
- `precompute_dates()` stops at the season's end (later dates are another season: never read).
- Satellite cache files are keyed by the polygon only (`field_<hash>_s<season>.parquet`; the old `field<id>_…` names
  are still read), so a scenario switch, which recreates fields with new ids, keeps their scenes (E-7).
- `farm_ranking()` lists fields without risk rows too ("Brak ocen ryzyka na ten dzień."), last.
- Texts: "≥" instead of ">=", "wilgotność względna powietrza" in the leaf-wetness label (the assistant read it as leaf
  humidity), a blanket treatment reads "Zabieg przeciw: choroby grzybowe (wszystkie)", a group neighbour report names
  the group. A symptoms report without a severity counts as 0.5 everywhere (it was 0.5 from the database, 0.6 in
  scripted reports).

## v0.12: date moves copy precomputed rows

Moving the demo date used to recompute `(min(old, new), max(old, new) + 7]` for every field (1–4 s per click on the
date control). The engine now keeps every row it computes in its own cache table, `engine.RiskSnapshot` (the engine's
first model and migration; farm data stays in `core`): one bundle per field and day, either "as of that day" or "coming
day of demo date D". `clock_moved()` copies the bundles it needs and computes only fields with a gap;
`precompute_dates()` / `engine_precompute_dates` fills the cache ahead (default: Clock - 7 … + 30). `predict()` drops
the stale bundles of a field from its `start` on (reports, crop changes). On the demo farm a move takes about 0.3 s.

The spraying window of a day assessed as of itself now always uses the forecast issued that day (days after today + 7
used the one issued today, which is empty that far ahead); those days are never shown before they become past or
coming days, where nothing changes. Tests: `SnapshotTests` (copies equal a full recompute, row for row; a report drops
stale bundles; gaps are computed and kept).

## v0.11: explanations in Polish

Every text that reaches the farmer is Polish, as explanation v1 requires (docs/database.md → "Text language"):
`summary` ("Wysokie ryzyko – mątwik burakowy: …"), driver labels, units and thresholds, `action.text`,
`action.threshold` and the stage thresholds, `notes`, growth-stage names and methods, farmer-report labels, the
spraying-window rule and notes, harvest texts, satellite anchors and crop checks, field summaries. Dates in texts are
DD.MM.YYYY; keys, codes, numbers and `threat.name_en` are unchanged. The forecast note on coming days starts with
"Dzień +N". `catalog.CROP_NAMES_PL` / `crop_pl()` give Polish crop names (CropClass rows keep the English legend).

## v0.10: demo farm 2024 and a stand-in API for the map

- `engine_dev_seed --crop-from-map`: parcels of all seven engine crops, crop from the crop map of the season itself
  (2024), Polish field names; no crop model, no network. The 2024 demo farm: 11 fields near Krapkowice.
- `engine_mock_api`: development-only server with the agreed platform endpoints and shapes (interfaces.md), used to
  build the map before the platform API exists; `PUT /api/clock/` calls `clock_moved()`. Tests: `engine/test_mock_api.py`.

## v0.9: predict() contract from the platform review

Closes the seven gaps in `docs/archive/engine-predict-review.md`; its contract tests are `engine/test_predict_contract.py` (all pass).

- **Coming days from the forecast:** today + 1 … + 7 use weather observed up to today, then the forecast issued today
  (`features.load_forecast`; daily only, so hourly rules use the daily estimate). Before, they read weather observed
  after today (hourly humidity and satellite rain no forecast has), and live mode had no coming days at all. The
  spraying window and the harvest outlook of a coming day read today's forecast, not one issued later. No forecast
  issued today → no coming-day rows (logged). New explanation key `forecast_issued_on`.
- **Default `end`** = the later of today + 7 and the last day already stored for these fields, so a report or a crop
  change also replaces the precomputed days. `end` is clipped to the last day with weather: days that can't be
  recomputed keep their rows instead of disappearing.
- **`PredictResult`**: `predict()` returns an int (rows) with `.field_ids` (every field rewritten, incl. spread).
- **`clock_moved(old, new)`** recomputes `(min, max + 7]`; the `post_save` signal on `Clock` and
  `refresh_forecast_confidence()` are gone. The platform calls it after saving the date; `engine_set_date D` does both.
- **`precompute_season(season)`** for the seed: previous season, then this one to its end. `predict --season`.
- **Reports count once:** an `assistant.Observation` row whose `idempotency_key` is in `core.Observation` is skipped.
- **Field facts without a date** (`tillage`, `resistant_to`) apply from the current season's start, not from 2000.
- Dev seed: forecast rain filled from IMERG, as the platform seed does.
- Tests: rule tests that score days after 15 June now run with the clock on 31 July (as-of days); new tests for the
  window of `clock_moved`, `precompute_season`, the result's field ids, the delete guard, no-forecast behaviour,
  today's forecast for coming-day spraying windows, and season-bound field facts.

## v0.8: cross-component consistency

- **Levels = the map's and the assistant's:** low < 0.33 ≤ medium < 0.66 ≤ high (was 0.3 / 0.6). A farmer-seen symptom is always high (floor 0.66 + 0.3 × severity).
- **Observation reader** accepts both table shapes (`observed_on`/`date`, `threat_code`/`threat` FK, numeric or Polish severity, `text`/`note`); a row without a recognisable kind is skipped and logged instead of being read as symptoms. Damage without a type counts as "crop damage" (fungal × 1.1) and is explained.
- **`engine_load_threats`** no longer overwrites existing Threat rows (platform fixture) unless `--overwrite`; lists Threat codes without a rule. `predict()` logs skipped engine codes.
- **Forecast lead follows the clock:** saving `Clock` re-measures `forecast_lead_days`, the confidence discount and the "Day +N" note of rows already written.
- docs/interfaces.md and docs/database.md point to explanation v1 in engine/README.md.

## v0.7: more crops

- **76 rules for 7 crops**: wheat, maize, plus barley (12), other cereals (13), rapeseed (10), sugar beet (10),
  potatoes (6); about 96 % of the arable land in Opolskie. Numbers from the integrated protection guides for barley,
  triticale, rye, sugar beet and potato; rapeseed from general agronomy (marked as assumptions).
- Growth-stage profiles per crop (`phenology.PROFILES`): sowing date, GDD base, curve, end of season (beet to 30 Nov,
  potato to 31 Oct). Checked on 2025 near Krapkowice: rapeseed flowering 14 Apr – 2 May, harvest ~9 Jul; barley heading
  ~14 May; potato rows closing mid June.
- New rule options: same crop last season, specific previous crops, acid soil, rotation pests (host crop in the last
  N seasons), soil temperature range for `soil_days`, flight temperature for `vector_days`, moisture `rh90` (late blight).
- `engine_load_threats` creates the engine's `CropClass` rows if missing.
- Facts on the field: reads proposed `Field.sowing_date` / `tillage` / `resistant_to` if the columns exist (`observations.from_field`); sowing dates only apply to their own season. README: facts go to core tables, events to `core.Observation`.

## v0.6: no document citations

- Rules stay in `catalog.py`; removed every reference to the guide files (`Rule.sources`, `explanation.sources`,
  `spray_window.source`, harvest `sources`, page numbers in notes and thresholds). Nothing reads documents at run time.
- `Threat.source` is now `"engine rules"`.
- Farmer reports from the chat: reads the interim `assistant.Observation` (mapping in README → Observation rows); a disease / pest report without a threat raises every threat of that group. Merged `main`.

## v0.1: rules from the guides

```bash
python manage.py engine_load_threats   # Threat rows for every rule in engine/catalog.py (upsert by code)
python manage.py predict               # all fields, 1 September .. today + 7
python manage.py predict --fields 3 --start 2025-05-01 --end 2025-06-30
python manage.py test engine           # synthetic weather, no data needed
```

From Python (the assistant after recording an observation): `from engine import predict; predict(field_ids=[3], start=day)`.

| File | What |
|------|------|
| [`catalog.py`](catalog.py) | Every threat rule: temperature / humidity ranges, susceptible growth stages, multipliers, the guide's thresholds, **sources with page numbers**. Numbers the guides don't give are marked as team assumptions. |
| [`phenology.py`](phenology.py) | Growth stage (BBCH) per day from degree days and a typical sowing date (wheat 1 Oct, maize 25 Apr). |
| [`features.py`](features.py) | Weather features per day, all trailing windows (a day never sees later weather). |
| [`scoring.py`](scoring.py) | Score + explanation per field, threat and day; spraying window from the forecast. |
| [`compute.py`](compute.py) | `predict()`: loads, scores, bulk-overwrites `Risk`. |
| [`satellite/`](satellite/) | Sentinel-2 NDVI from Earth Search (only the needed window), season calendar grid. For the crop model. |
| [`management/commands/engine_dev_seed.py`](management/commands/engine_dev_seed.py) | **Dev only:** a 6-field farm near Krapkowice (Opolskie) with weather, soil and crop history, until the platform import exists. |

Threats (25): **wheat** — fusarium head blight, septoria leaf blotch, glume blotch, brown rust, yellow rust, powdery mildew, tan spot, eyespot, fusarium foot rot, take-all, snow mould (fungal); grain aphids, cereal leaf beetle (pests); barley yellow dwarf virus carried by aphids in warm autumns (viral). **Maize** — seedling blight, fusarium ear rot, fusarium stalk rot, northern leaf blight, eyespot (Kabatiella), common rust, crazy top (fungal); European corn borer, western corn rootworm, aphids, frit fly (pests). Codes like `wheat.fusarium_head_blight`.

### What the score means (proposal)

`score` (0–1) = how favourable the last days were for this threat on this field: **weather (or pest activity) × growth-stage weight × field multipliers** (previous crop, monoculture, heavy soil), capped at 1. It is an index, not a probability. Levels (proposal, to agree with Kuba): **low < 0.3 ≤ medium < 0.6 ≤ high**.

### `Risk.explanation` format (proposal, version 1)

```jsonc
{
  "version": 1,
  "summary": "High risk of Fusarium head blight (fuzarioza kłosów): hours at 15-25 °C with wet leaves (RH >= 95 % or rain) in the last 5 days: 16 h; crop at flowering, BBCH 63.",
  "level": "high",                     // low / medium / high
  "score": 1.0,
  "threat": {"code": "wheat.fusarium_head_blight", "name_pl": "fuzarioza kłosów", "name_en": "Fusarium head blight", "category": "fungal"},
  "as_of": "2025-06-07",               // assessed with weather up to this day
  "crop": {"code": 1110, "source": "field"},
  "growth_stage": {"bbch": 63, "name": "flowering", "method": "degree days, typical sowing date", "sowing_assumed": "2024-10-01", "confidence": 0.6},
  "drivers": [                         // why: one entry per factor, biggest first
    {"factor": "condition_hours", "label": "Hours at 15-25 °C with wet leaves ...", "value": 16, "unit": "h",
     "threshold": "4 h starts the risk, 16 h = full risk", "effect": 1.0},
    {"factor": "growth_stage", "label": "Growth stage BBCH 63 (flowering); susceptible BBCH 61-69", "value": 63, "unit": "BBCH", "effect": 0.0},
    {"factor": "previous_crop", "label": "Previous crop was maize (residue carries the fungus)", "multiplier": 1.5, "effect": 0.33},
    {"factor": "rain_days", "label": "Days with >= 1 mm rain in the window", "value": 2, "unit": "days", "effect": null}
  ],
  "action": {"type": "treat",          // wait / monitor / treat
             "text": "High risk: inspect the field now; if the threshold is exceeded, a treatment is justified.",
             "threshold": "Infection happens at flowering (BBCH 61-69) ...",   // quoted from the guide
             "spray_window": {"date": "2025-06-08", "rule": "1-25 °C, no rain, wind <= 14.4 km/h (4 m/s)", "conditions": {...}, "source": {...}}},
  "severity": 0.15,                    // potential yield loss if it happens (assumption)
  "expected_loss": 0.15,               // score x severity, for ranking fields
  "confidence": 0.6,                   // lower when the stage is estimated or hourly data is missing
  "sources": [{"document": "metodyka_-_PSZENICA_-_www.pdf", "page": 74, "note": "Tabela 26: ..."}],  // same shape as the chat's guide citations
  "notes": ["Maize residue ... raises the risk"],
  "assumptions": {"hours_low": 4, "hours_high": 16, ...},
  "model": "rules", "model_version": "0.1.0"
}
```

`effect` = how much the score would drop without that factor (`null` for context-only values). The map can show `summary` + the drivers; the assistant can cite `sources` directly. No product or dose advice anywhere.

### Data findings (for Jan + Szymek)

- **The weather packages contain no precipitation** (daily or hourly): `total_precipitation` / `precipitation` stay empty. Rain only comes from IMERG. The engine uses the weather value if present, else IMERG. The forecast (seeded from daily weather) therefore has no rain either.
- **Soil `clay`, `sand` are fractions (0.18), not % as in the doc;** `om` is 2.5–12 (looks like %). `BAND_om` / `BAND_pH` / `BAND_cec` are text (`"low"`, `"moderate"`, `"high"`), but the model columns are floats; the source names are upper-case (`BAND_*`, `soilTexture`).
- **Grid `lat` / `lon` are decimals** in `weather_grids.parquet` (cast to float).
- **Hourly year files overlap** by one UTC hour at New Year (unique constraint).
- Weather 2025 is complete (1 Jan – 31 Dec) for daily and hourly; IMERG covers 2020–2025.

### Crop model (satellite) — first results

[`cropmodel.py`](cropmodel.py): LightGBM on the half-month NDVI curve of the season known so far (one model for every day; slots after today are empty). Trained on 30 random 3×3 km windows across Opolskie, seasons 2020, 2022, 2023 (pixels, crop-map labels); tested on 2024 in 6 windows never seen in training.

| As of (2024) | wheat / maize / other: accuracy | "wheat" correct (precision) | "maize" correct | wheat vs maize, when it says one of them |
|---|---|---|---|---|
| 31 Mar | 0.72 | 0.44 | 0.21 | 0.82 |
| 30 Apr | 0.72 | 0.52 | 0.26 | 0.93 |
| 31 May | 0.75 | 0.51 | 0.46 | 0.98 |
| 30 Jun | 0.78 | 0.56 | 0.54 | 0.98 |
| 31 Aug | 0.82 | 0.60 | 0.73 | 0.99 |

Reading: **wheat vs maize is reliable from late May; wheat vs other winter cereals (barley, triticale, rye) and maize vs other summer crops (sugar beet, potato) are not** from NDVI alone. So the satellite *proposes* the crop and the farmer confirms it. Next steps for accuracy: red-edge / SWIR bands, timing normalised by degree days, field-level averaging (pixel numbers above are a lower bound).

**Data problem:** the organisers' 2021 crop map is pixel-identical to the 2022 map (the 2021 package holds the 2022 data; its labels fit the 2022 imagery). Season 2021 is excluded from training; `FieldCropYear` rows for 2021 are wrong too.

### Farmer reports and field history (v0.2)

[`observations.py`](observations.py). Reports from the chat change risks **from the day they were observed on** (never earlier days) and each one is a driver in the explanation, with its effect:

| `kind` | Example | Effect | For how long |
|---|---|---|---|
| `symptoms` | "I see brown rust on the north field" | score at least 0.6 + 0.3 × severity; confidence 1 | full 10 days, gone by day 21 |
| `absence` | "Inspected, clean" (`threat_code` empty = all) | × 0.5 | back to normal by day 10 |
| `neighbour` | "My neighbour has head blight" | × (1 + 0.5 × closeness), closeness 1 up to 500 m, 0 at 3 km | full 7 days, gone by day 21 |
| `treatment` | "Sprayed against septoria on 10 May" (empty = all fungal) | × 0.3, action becomes "wait" | full 14 days, gone by day 21 |
| `field_fact` | `{"sowing_date": "2024-09-25"}`, `{"tillage": "reduced"}`, `{"resistant_to": [codes]}` | real sowing date replaces the assumed one (stage confidence 0.85); reduced tillage × 1.3 for residue diseases; resistant variety × 0.6 | rest of the season |
| `event` | `{"type": "hail" / "lodging" / "flood"}` | hail: fungal × 1.3; lodging: fungal × 1.2; flood: crazy top at least 0.7 | 14-28 days |

Until the `Observation` table exists, `observations.load()` returns nothing; `predict(..., observations=[Report(...)])` takes reports directly (tests, scripted demo). **Proposed `Observation` columns** (Jan, Szymek, Ola): `field` (FK, null = whole farm), `observed_on` (date), `recorded_at`, `kind` (one of the above), `threat_code` (null), `severity` (0-1, null), `distance_m` (null), `details` (JSON), `text` (the farmer's words). The engine reads them through `observations.load()`, so column names can still change in one place.

**Field history:**
- Previous crop and maize monoculture (crop maps) - multipliers per threat.
- **Carry-over from last season:** if the same pathogen peaked >= 0.6 on this field last season, × 1.2 (infected residue). Fusarium is shared by maize and wheat, so a bad maize year raises next year's head blight. Last season is scored with last season's crop from the crop map, not with `Field.crop`.


### v0.3: more from the guides, field ranking, what-if, harvest

From a second read of the metodyki and the GIORiN guide:
- **9 more threats** (above): Tabela 25 lists eyespot and fusarium foot rot as "+++" for winter wheat; Tabela 31/33 the wheat pests and their thresholds; p. 100 "a long, warm autumn favours aphids and the spread of viruses"; maize leaf diseases from p. 86.
- **Thresholds per growth stage** (Tabela 30, p. 94-95): the action shows the guide's threshold for the field's current stage (tillering / stem elongation / heading).
- **Spraying window = Tabela 40/42 in full:** 1-25 °C, the following night >= 1 °C, RH 50-95 %, no rain, wind <= 4 m/s; "optimal" at 12-20 °C, RH 75-95 %, wind 0.5-1.5 m/s.
- **Head blight:** Fusarium species conditions and "+1 % infected ears = about +0.3 mg/kg DON" (GIORiN p. 4) in the notes.
- **Harvest outlook** ([`harvest.py`](harvest.py)): wheat - fully ripe, next dry day, sprouting risk after 2+ rainy days in a row (p. 176); maize - safe storage days of undried grain by moisture and temperature (Tab. 37, p. 202).
- European corn borer calendar from p. 118.

Engine features:
- **Field ranking** ([`summary.py`](summary.py), `python manage.py engine_summary --date ...`): per field and day the highest score, the share of yield at risk (1 - prod(1 - score x severity)), top 3 threats, actions with spraying windows, the harvest outlook, and the fields ordered by urgency with the reason. Pure read of `Risk`, nothing stored - the API or the assistant can call `field_day(field_id, day)` / `farm_ranking(day)`.
- **What-if for the assistant**: `from engine import what_if; what_if(field_id, day, [Report(...)])` -> per threat the score now and with the hypothetical reports ("if I spray on Friday", "if I sowed on 10 October"). Writes nothing.
- **Spread within the farm**: symptoms reported on one field raise the risk on fields of the same crop within 3 km (as a "neighbour" report with the distance); those fields are recomputed too.
- **Coming days are less certain**: days after today get `forecast_lead_days` and confidence x (1 - 0.06 x days ahead); `adjust_for_lead()` can redo it when the clock moves.
- **Maize season runs to 31 December** (sown in April, harvested in autumn); seasons after the current one are not computed (crop unknown). `predict()` replaces the whole range for the fields it computes, so rows of threats that no longer apply disappear.


### v0.4: growth stage from the satellite, crop check

- [`satellite/fieldndvi.py`](satellite/fieldndvi.py) + `python manage.py engine_fetch_ndvi --season 2025`: each field's NDVI per Sentinel-2 scene (mean of clear pixels in the polygon), cached in `DATA_DIR/satellite/fields/` - `predict()` never needs the network.
- **Stage anchors from the curve:** wheat - spring NDVI peak in May-June (>= 0.7) = heading (BBCH 55), NDVI below 0.5 afterwards = ripening (BBCH 83); maize - the rise from bare soil after sowing = young plants (BBCH 13), summer peak = flowering (BBCH 65). From the day an anchor is confirmed the degree-day curve is shifted through it (confidence 0.6 -> 0.8); earlier days keep the old estimate (no look-ahead).
- **Finding:** on 7 wheat field-seasons near Krapkowice the degree-day model matched heading well (BBCH 53-60 vs 55 in 5 of 7) but ran **1-2 weeks early at ripening** (BBCH 92 where the satellite shows ~83). The wheat table was re-calibrated: heading ~1060, ripening ~2135 degree days since 1 January.
- **Crop check** (`summary.field_day(...)["crop_check"]`): explainable mismatches between the curve and the crop ("bare in spring: winter wheat is green then") so the farmer is asked to confirm.


### v0.5: crop model with crop history and degree-day timing; realistic dev farm

- Crop model features: **last season's crop** (crop map at the pixel; not for 2021/2022 because of the broken 2021 map) and **NDVI read at fixed degree-day points** (300 ... 2100 since 1 January) so early and late years line up. Pixel-level gain is modest (wheat precision 0.60 -> 0.64 at season end, 0.51 -> 0.58 at end of May).
- **Field-level evaluation** (`engine/scripts/eval_crop_fields.py`, 534 fields of >= 1 ha in 6 windows never seen in training, season 2024):

| As of | wheat / maize / other | "wheat" correct | "maize" correct | wheat vs maize |
|---|---|---|---|---|
| 30 Apr | 0.68 | 0.68 | 0.69 | 0.92 |
| 31 May | 0.74 | 0.71 | 0.86 | 0.99 |
| 30 Jun | 0.74 | 0.78 | 0.84 | 1.00 |
| 31 Aug | 0.77 | 0.80 | 0.97 | 1.00 |

  When the model is confident (>= 0.7, about half of the fields) wheat / maize / other is right 82-84 %.
- `summary.field_day(...)["crop_check"]["model"]`: the model's crop and probabilities for the field as of the day, from the cached NDVI.
- **Dev farm fixed:** fields were whole patches of one crop on the 2024 map (up to 233 ha, several farmers' parcels with different 2025 crops). Now: 5-40 ha, one class in both 2023 and 2024, 2025 crop from the crop model (>= 60 %). Result near Krapkowice: 3 wheat (one after maize -> head blight), 2 maize (one in its 5th year of maize -> rootworm).
