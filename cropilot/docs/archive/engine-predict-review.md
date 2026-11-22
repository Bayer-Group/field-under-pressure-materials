# `predict()`: how it should work vs how it works

> **Historical document (the review that led to predict()'s contract; its contract tests pass now).** Kept for the decisions and their reasons. Current behaviour: [interfaces.md](../interfaces.md) (the demo date moves only through `core.clock.set_today()`; chat messages carry `chart` and `pending_action`; engine texts are Polish) and [audit-2026-11-21.md](../audit-2026-11-21.md).

For Bartek · from Jan + Szymek (platform) · 21 Nov 2026

We integrated the engine (`feat/decision-engine` at `bb3ece1`) with the platform's database, including the new `core.Observation` table (`core/migrations/0002_observation_and_soil_formats.py`, committed on this branch). The engine itself integrates cleanly: it reads and writes only through the ORM, writes only `Risk`, and picks up reports from `core.Observation` without any change. But `predict()` does not yet behave as the contract in [interfaces.md → Decision engine](../interfaces.md#decision-engine) and the shared principles need. This document lists each gap with what should happen, what happens, the evidence, and options for fixing it.

Some gaps come from **our** contract being ambiguous; those are marked, and we will update `interfaces.md` once we agree on the behaviour. Every gap has a test that fails today ([appendix](#appendix-contract-tests)); they run on your own synthetic fixture (`EngineTestBase`: clock 15 June 2025, weather to 31 July 2025, 3 fields). Timings in this document come from that fixture too.

## What a risk score means

- **The score for day D is the disease or pest pressure built up by the end of D.** Every feature is a trailing window over days ≤ D ("hours at 15–25 °C with wet leaves in the last N days", rain days, the 7-day mean temperature, degree days since 1 January; `features.py`, `scoring.py`). Farmer reports count from their own date. It is a reading of the state on D, not a forecast.
- **The spraying window is the only part that looks past D.** It reads the forecast issued on D (D + 1 … D + 7) to suggest a day to spray (`compute.py:244-249`). It goes into the recommended action and **does not change the score**.
- **Today + 1 … today + 7 (the "coming days", [interfaces.md](../interfaces.md#risks)) are a projected risk:** "if the forecast holds, pressure will be high by Thursday". They are computed by filling the trailing windows with the weather known today: observations up to today, then the forecast issued today. That is why their confidence drops by 6 % per day ahead (`compute.py:255`) and why the API's cut-off is today + 7.

## Summary

| # | Topic | Should | Does | Seen in the demo | Fix by |
|---|-------|--------|------|------------------|--------|
| 1 | [Recompute after a report or a crop change](#1-recompute-after-a-report-or-a-crop-change-leaves-later-days-stale) | Every stored day that changes is rewritten | Only days up to today + 7; precomputed later days keep the old score or the old crop's threats | Yes: move the date forward and the report's effect is gone, or a maize field still shows wheat threats | Engine (+ contract wording by us) |
| 2 | [Fields rewritten by a spreading report](#2-fields-rewritten-by-a-spreading-report-are-not-reported) | The caller learns every field `predict()` rewrote | Returns only a row count | Yes: the map doesn't reload nearby fields | Engine (+ contract by us) |
| 3 | [Coming days](#3-coming-days-use-observed-weather-instead-of-the-forecast) | Weather observed up to today, then the forecast issued today | Weather **observed after today**, including hourly data and satellite rain that no forecast has | Yes: coming days look more certain than any farmer could know; live mode has **no coming days at all** | Engine (+ contract wording by us) |
| 4 | [Moving the demo date](#4-moving-the-demo-date-rewrites-the-rest-of-the-season) | Recompute only the window that changes (sub-second) | A `Clock` signal rewrites every stored row after today: **5.3 s per date change** | Yes: the date control would freeze for seconds | Engine (+ a call from the platform) |
| 5 | [Reading farmer reports](#5-the-same-farmer-report-can-count-twice) | Each report counts once | Reads both `core.Observation` and `assistant.Observation`, so a moved report counts twice | Yes, once Ola moves her rows | Engine + Ola |
| 6 | [Precomputing the season for the demo](#6-precomputing-the-demo-season) | One agreed call precomputes the season | A bare `predict()` stops at today + 7; the full season needs two explicit calls in the right order | Yes: no risks after today + 7 until called right | Engine (+ contract by us) |

## What already matches the contract

- Signature `predict(field_ids=None, start=None, end=None)`, returning the number of rows written; the extra `observations=` argument is a harmless addition.
- Database only through the ORM and the platform helpers; writes only `Risk`; one transaction per call.
- One row per field, threat and day, replaced on every run (delete the range, then insert).
- Days up to today are computed **as of that day** ([above](#what-a-risk-score-means)): trailing windows only, reports from their `observed_on`, satellite anchors from the scene that confirmed them; your look-ahead test covers this.
- The spraying window uses the forecast issued that day (`.current(as_of=day)`).
- `core.Observation` rows (with `threat` as a foreign key, `category`, numeric `severity`, empty `field` for the whole farm) reach the engine. We checked this with three tests on your fixture.

## 1. Recompute after a report or a crop change leaves later days stale

**Should.** When a field's input changes, every stored day that depends on it is rewritten:
- after a farmer report, with the agreed call `predict(field_ids=[field.id], start=observed_on)`. A symptoms report lasts up to 21 days;
- after the farmer changes the field's crop, with the call from your README, `predict(field_ids=[field.id], start=season start)`.

**Does.** `end` defaults to today + 7 (`compute.py:46`), so only `[start, today + 7]` is deleted and rewritten (`compute.py:54`). The seed precomputes the whole season ([database.md → How the demo is filled](../database.md#how-the-demo-is-filled)), so days after today + 7 keep what they had: the pre-report score, or **the old crop's threats**. When the demo date moves forward, those rows come into view.

**Evidence.**
- `ReportRecomputeTests`: the season is precomputed to 31 July, septoria symptoms are reported on 14 June (severity 0.9), then the agreed call runs. 20 June scores ≥ 0.8, but 24 June (day 10, when the symptoms still count fully) stays at **0.0**.
- `CropChangeTests`: the wheat field is changed to maize and the crop-change call runs. **546** wheat-threat rows remain on that field after today + 7.

**Our part.** The contract gives both "default `end`: today + 7" and "the seed precomputes the season". Together they produce this.

**Options.**
- **(Recommended)** When `end` is not given, use the later of today + 7 and the last day already stored for these fields. Every existing call then becomes correct without callers knowing about the precompute.
- Callers pass `end` explicitly (the season end). This is easy to forget, and the assistant would need to know about the demo.

## 2. Fields rewritten by a spreading report are not reported

**Should.** The caller learns **every field** whose rows changed, so the assistant can return them in `updated_field_ids` and the map reloads them ([interfaces.md → Writing observations](../interfaces.md#writing-observations)).

**Does.** Symptoms on one field also rewrite fields of the same crop within 3 km (`compute.py:72`), but `predict()` returns only `len(rows)` (`compute.py:60`).

**Evidence** (`SpreadReportingTests`): after a report on the wheat field, the second wheat field has a new "neighbour" driver, but the return value is a plain `int`.

**Our part.** The contract only asked for a row count.

**Options.**
- **(Recommended)** Return an `int` subclass that carries `.field_ids` (every field rewritten). Existing callers that treat the result as a number keep working: Ola's tool stores it as `rows_written`, and the management command prints it.
- An opt-in argument, e.g. `predict(..., with_fields=True) -> (rows, field_ids)`.

## 3. Coming days use observed weather instead of the forecast

**Should.** The shared principle is *historical demo, live-ready: nothing in the design depends on the past season* ([architecture_overview.md](../../architecture_overview.md)). A farmer on the demo's today knows the weather up to today and the forecast issued today. So:

| Day `d` | Computed from |
|---------|---------------|
| `d` ≤ today | weather observed up to `d` (as now) |
| today < `d` ≤ today + 7 | weather observed up to **today**, then the **forecast issued today** for the days after |
| `d` > today + 7 (only when the seed precomputes the demo season) | weather observed up to `d`. Acceptable only because these rows stay hidden until the date comes within 7 days, and they are recomputed then ([4](#4-moving-the-demo-date-rewrites-the-rest-of-the-season)) |

**Does.** `features.load_daily` and `load_hourly` read `.observed(as_of=end)` (`features.py:36`, `:51`) with `end` up to today + 7, so the trailing windows of the coming days read weather **observed after today**. The forecast is used only for the spraying window. The notes call this a "perfect forecast", but it is better than any forecast:

1. **It uses data no forecast has.**
   - The forecast table is daily only, so the coming days still get **hourly** humidity and temperature, which drive the infection-hours rules.
   - The forecast has no precipitation (IMERG rain isn't forecast), but the coming days get **satellite rain**, which drives the rain-days, waterlogging and maize-drought rules.
   - Only the confidence number is lowered; the score itself uses information a farmer couldn't have. So even in the demo, the coming days look more precise than they could be.
2. **Live mode produces nothing.** With real data `WeatherDaily` has no rows after today, and the days are clipped to the last day with weather (`compute.py:219`). So `predict()` silently stops at today and there are no coming-day risks at all.
3. **It goes against the helper's rule.** `as_of` is documented as being for assessing *past* days (`core/models.py`, `observed()`). Here it gets a future date.

**Why it was built this way** (`engine/README.md:135`): if row D depends only on data up to D, the whole season is computed once and moving the demo date needs no recompute. Using the forecast properly makes the coming-day rows depend on the day the forecast was issued, so they must be recomputed whenever the date moves. That turns out to be cheap ([4](#4-moving-the-demo-date-rewrites-the-rest-of-the-season)).

**Evidence** (`ComingDaysFromForecastTests`):
- The observed weather is wet around flowering (18–23 June), while the forecast issued on 15 June says dry. Head blight on 22 June scores **1.0**; following the forecast it should be low.
- With the weather after 15 June removed (live mode) and the forecast present: **0** coming-day rows.

**Our part.** "Each one as of that day" in `interfaces.md` doesn't say what "as of" means for a day after today. We meant the table above.

**Things to know for the fix.**
- On forecast days the hourly-based features (infection hours) need your daily fallback (`daily_moisture_estimate`, confidence × 0.7).
- Forecast precipitation: the demo seed will fill `WeatherForecastDaily.total_precipitation` from the observed day's IMERG value ([database.md](../database.md#how-the-demo-is-filled)), so rain is there in the demo. A live forecast would provide its own.
- One possible shape: load observed weather with `as_of=min(end, today)`, then append the rows of `WeatherForecastDaily.objects.current()` for the days after today, marked as forecast; the trailing windows then work unchanged.

## 4. Moving the demo date rewrites the rest of the season

**Should.** Once the coming days come from the forecast ([3](#3-coming-days-use-observed-weather-instead-of-the-forecast)), moving the date from `old` to `new` changes exactly one window of days: **`(min(old, new), max(old, new) + 7]`**.
- Days that were coming days but are now past go back to "as of that day".
- The new coming days are computed from the forecast issued on `new`.
- Nothing else changes, so nothing else is rewritten.

The date control in the header calls `PUT /api/clock/` and must stay responsive.

**Does.** A `post_save` signal on `core.Clock` (`apps.py:9`, `:23`) runs `refresh_forecast_confidence()` (`compute.py:267`). It loads **every** row after today and rewrites the clock-dependent parts of its explanation (`forecast_lead_days`, the discounted `confidence`, the "Day +N" note), while the scores stay the same.

**Evidence** (`ClockMoveTests`, plus timings):
- A one-day move rewrote **1,482 of 2,067** rows that lie outside the window that actually changed.
- With the whole season precomputed for 3 fields (13,026 rows), every `clock.save()` took **5.3 s**, inside the `PUT /api/clock/` request.
- `Clock.objects.update(...)` skips the signal, so the rows silently go stale.

**What the right recompute costs** (`predict()` over the window, all 3 fields, best of 3):

| Date move | Days recomputed | Time |
|-----------|-----------------|------|
| 1 day | 8 | 0.62 s |
| 7 days | 14 | 0.73 s |
| 30 days | 37 | 1.16 s |
| 1 day, one field only | 8 | 0.24 s |

Most of the time is per-field setup (loading the season's hourly weather and the stages); the number of days matters little. That's about 10× faster than today's signal, and the scores in the window become correct, not just the confidence.

**Options.**
- **(Recommended)** An engine function `clock_moved(old, new)` that recomputes that window, called **explicitly by the platform** when the date changes (`PUT /api/clock/` and the admin's clock page); remove the signal. The rows in the window are recomputed with the right `forecast_lead_days` and confidence, so nothing clock-dependent ever needs patching elsewhere.
- Keep a signal, but make it compute that window (it needs the old date from a `pre_save`). This is more hidden: a plain `Clock.objects.update()` still skips it.

## 5. The same farmer report can count twice

**Should.** Each report counts once.

**Does.** `_query` reads `core.Observation` **and** `assistant.Observation` (`observations.py:144`, `:148`). The agreed move is "copy the interim rows into `core`, then delete them" ([interfaces.md → Writing observations](../interfaces.md#writing-observations)), so any moment where both hold the row doubles the effect.

**Evidence** (`DoubleReadTests`): the same report in both tables (same idempotency key) produces **2** farmer-report drivers.

**Options.**
- **Now:** skip interim rows whose `idempotency_key` already exists in `core.Observation`.
- **After Ola switches her tool to `core.Observation`:** remove the `assistant.Observation` adapter.

## 6. Precomputing the demo season

**Should.** The contract says that after the seed, one `predict()` precomputes the season "so moving the demo date is instant".

**Does.**
- A bare `predict()` covers 1 September → today + 7. On your fixture: 11,505 rows, last day **22 June**. With the demo date moved past that, there are no risks.
- Your README asks the seed for two explicit calls, the previous season first, because this season reads last season's peaks from `Risk` (`compute.py:304`, carry-over). So results depend on earlier runs: recomputing last season doesn't refresh this one.

**Our part.** "Default `end`: today + 7" and "precompute the season" are both in the contract (see also [1](#1-recompute-after-a-report-or-a-crop-change-leaves-later-days-stale)).

**Options.**
- **(Recommended)** One engine function for the seed, e.g. `engine.precompute_season(season)`. It computes the previous season (for the carry-over), then the current one to its end, in the right order. The platform seed calls only that.
- The platform seed makes your two calls itself. This works, but the ordering rule then lives outside the engine.

## Minor

- **Rows deleted but not recreated:** the delete covers `[start, end]` for every field (`compute.py:54`), even days that can't be recomputed (no weather yet, a season after the current one). Those rows disappear rather than being replaced. With [3](#3-coming-days-use-observed-weather-instead-of-the-forecast) fixed this mostly goes away; worth a guard.
- **Field facts apply to past seasons:** facts stored on a field without a date (`tillage`, `resistant_to`) apply from `KNOWN_SINCE = 2000-01-01` (`observations.py:176`), so a resistant variety sown this season also lowers last season's risks.
- **Level names:** your `explanation.level` is `low` / `medium` / `high`, and the frontend uses `low` / `mid` / `high`. We'll align the frontend to your names; no action for you.

## Proposed contract (to agree, then we update interfaces.md)

```python
def predict(field_ids=None, start=None, end=None) -> PredictResult:
    """
    PredictResult is an int (rows written) with .field_ids: every field rewritten, including
    nearby fields a symptoms report spread to.
    start: default the season start.
    end:   default the later of today + 7 and the last day already stored for these fields.
    """

def clock_moved(old: date, new: date) -> PredictResult:
    """Recompute (min(old, new), max(old, new) + 7]. Called by the platform whenever the demo date changes."""

def precompute_season(season: int | None = None) -> PredictResult:
    """For the demo seed: previous season (carry-over), then this season to its end."""
```

- **Days up to today:** as of that day.
- **Today + 1 … today + 7:** as of today (observed weather up to today plus the forecast issued today).
- **Days after today + 7 (demo precompute only):** as of that day, recomputed by `clock_moved()` when the date comes within 7 days.
- **Writes:** only `Risk`. Moving the date rewrites only the changed window, through `clock_moved()`; no signal.
- **Recompute triggers:** a farmer report, a crop change and new satellite data all call `predict(field_ids=[...], start=...)`; the default `end` reaches every stored day.
- **Farmer reports:** each counts once; `core.Observation` is the only source once Ola has moved hers.

## Appendix: contract tests

Save as `engine/test_predict_contract.py` and run `python manage.py test engine.test_predict_contract`. It needs the `core.Observation` migration, which is on this branch. All seven tests fail today, each at the assertion that describes its gap; when they pass, the gaps are closed.

```python
"""
predict() contract tests: each test states the intended behaviour (docs/interfaces.md).
They run on the engine's own synthetic fixture (EngineTestBase: clock 2025-06-15, weather to 2025-07-31).
"""

from datetime import date, timedelta

from core.models import Clock, Observation, Risk, Threat, WeatherDaily, WeatherForecastDaily, WeatherHourly
from engine import predict
from engine.tests import EngineTestBase

TODAY = date(2025, 6, 15)
SEASON_LAST_DAY = date(2025, 7, 31)  # last day with weather in the fixture
SEPTORIA = "wheat.septoria_leaf_blotch"
FHB = "wheat.fusarium_head_blight"


def score(field, code, day):
    return Risk.objects.get(field=field, threat__code=code, date=day).score


def report_drivers(field, code, day):
    r = Risk.objects.get(field=field, threat__code=code, date=day)
    return [d for d in r.explanation["drivers"] if d["factor"] == "farmer_report"]


def seed_forecast(issued: date, overrides: dict | None = None):
    """Forecast issued on `issued`: copy of the observed days +1..+7, optionally overridden."""
    for k in range(1, 8):
        d = WeatherDaily.objects.get(date=issued + timedelta(days=k))
        values = {f: getattr(d, f) for f in ("max_temperature", "min_temperature", "avg_temperature",
                                             "avg_relative_humidity", "total_precipitation", "avg_wind_speed")}
        values.update(overrides or {})
        WeatherForecastDaily.objects.create(grid=d.grid, issued_on=issued, date=d.date, **values)


class ReportRecomputeTests(EngineTestBase):
    """1. A farmer report must change every stored day it affects, not only days up to today + 7."""

    def test_agreed_call_updates_precomputed_days_after_today_plus_7(self):
        predict(start=date(2025, 6, 1), end=SEASON_LAST_DAY)  # the seed precomputes the season
        Observation.objects.create(field=self.wheat, observed_on=TODAY - timedelta(days=1), kind="symptoms",
                                   threat=Threat.objects.get(code=SEPTORIA), severity=0.9, text="plamy na liściach")
        predict(field_ids=[self.wheat.id], start=TODAY - timedelta(days=1))  # the agreed call after a report
        day = TODAY + timedelta(days=9)  # 24 June: 10 days after the report, the symptoms still count fully
        self.assertGreaterEqual(score(self.wheat, SEPTORIA, TODAY + timedelta(days=5)), 0.8)  # inside today + 7: updated
        self.assertGreaterEqual(score(self.wheat, SEPTORIA, day), 0.8,
                                "24 June still has the score from before the report")


class CropChangeTests(EngineTestBase):
    """1b. Changing a field's crop must replace every stored day, not only days up to today + 7."""

    def test_crop_change_replaces_precomputed_days(self):
        predict(start=date(2025, 6, 1), end=SEASON_LAST_DAY)  # the seed precomputes the season
        self.wheat.crop_id = 1130  # the farmer says the field is maize
        self.wheat.save()
        predict(field_ids=[self.wheat.id], start=date(2024, 9, 1))  # the call engine/README.md gives for a crop change
        stale = Risk.objects.filter(field=self.wheat, date__gt=TODAY + timedelta(days=7), threat__crop_id=1110).count()
        self.assertEqual(stale, 0, f"{stale} wheat-threat rows after today + 7 remain on a field that is now maize")


class SpreadReportingTests(EngineTestBase):
    """2. The caller must learn every field predict() rewrote (for updated_field_ids)."""

    def test_spread_fields_are_reported_back(self):
        Observation.objects.create(field=self.wheat, observed_on=TODAY - timedelta(days=1), kind="symptoms",
                                   threat=Threat.objects.get(code=SEPTORIA), severity=0.9)
        result = predict(field_ids=[self.wheat.id], start=TODAY - timedelta(days=1), end=TODAY)
        neighbour = report_drivers(self.wheat_after_wheat, SEPTORIA, TODAY)
        self.assertTrue(neighbour, "the nearby wheat field was rewritten with a 'neighbour' driver")
        self.assertIsNot(type(result), int, "predict() returned only a row count: the caller cannot tell "
                                            f"that field {self.wheat_after_wheat.id} changed too")


class ComingDaysFromForecastTests(EngineTestBase):
    """3. Today + 1 ... today + 7 must come from the forecast issued today, not from observed weather after today."""
    wet_days = {date(2025, 6, d) for d in range(18, 24)}  # observed: wet at wheat flowering

    def test_coming_day_follows_the_forecast(self):
        seed_forecast(TODAY, {"avg_relative_humidity": 50, "total_precipitation": 0})  # issued today: dry week
        predict(start=date(2025, 6, 1))
        self.assertLess(score(self.wheat, FHB, TODAY + timedelta(days=7)), 0.33,
                        "22 June uses the wet observed weather although the forecast known on 15 June says dry")

    def test_live_mode_still_has_coming_days(self):
        seed_forecast(TODAY)
        WeatherDaily.objects.filter(date__gt=TODAY).delete()  # live: nothing is observed after today
        WeatherHourly.objects.filter(date__gt=TODAY).delete()
        predict(start=date(2025, 6, 1))
        coming = Risk.objects.filter(date__gt=TODAY, date__lte=TODAY + timedelta(days=7)).count()
        self.assertGreater(coming, 0, "no coming-day risks at all when weather after today is not observed")


class ClockMoveTests(EngineTestBase):
    """4. Moving the demo date may recompute only the window that changes, never the rest of the season."""

    def test_clock_save_leaves_rows_outside_the_window_alone(self):
        predict(start=date(2025, 6, 1), end=SEASON_LAST_DAY)
        new_today = TODAY + timedelta(days=1)
        outside = Risk.objects.exclude(date__gt=TODAY, date__lte=new_today + timedelta(days=7))  # (old today, new today + 7]
        before = {r.id: r.explanation for r in outside}
        c = Clock.objects.get()
        c.today = new_today
        c.save()
        changed = sum(1 for r in Risk.objects.filter(id__in=before) if r.explanation != before[r.id])
        self.assertEqual(changed, 0, f"{changed} of {len(before)} rows outside the changed window were rewritten")


class DoubleReadTests(EngineTestBase):
    """5. One report must count once, even while core.Observation and assistant.Observation both exist."""

    def test_same_report_in_both_tables_counts_once(self):
        from assistant.models import Observation as InterimObservation
        threat = Threat.objects.get(code=SEPTORIA)
        Observation.objects.create(field=self.wheat, observed_on=TODAY - timedelta(days=1), kind="symptoms",
                                   threat=threat, severity=0.9, idempotency_key="k1")
        InterimObservation.objects.create(field=self.wheat, date=TODAY - timedelta(days=1), category="choroba",
                                          threat=threat, severity="wysokie", note="plamy", idempotency_key="k1")
        predict(field_ids=[self.wheat.id], start=TODAY - timedelta(days=1), end=TODAY)
        self.assertEqual(len(report_drivers(self.wheat, SEPTORIA, TODAY)), 1)
```

Results on `bb3ece1` + the core change:

| Test | Result today |
|------|--------------|
| `ReportRecomputeTests` | 24 June: 0.0 (expected ≥ 0.8) |
| `CropChangeTests` | 546 wheat-threat rows left on a field that is now maize (expected 0) |
| `SpreadReportingTests` | returned a plain `int`; the nearby wheat field changed anyway |
| `ComingDaysFromForecastTests.test_coming_day_follows_the_forecast` | 1.0 (expected < 0.33) |
| `ComingDaysFromForecastTests.test_live_mode_still_has_coming_days` | 0 coming-day rows |
| `ClockMoveTests` | 1,482 of 2,067 rows outside the changed window rewritten (expected 0) |
| `DoubleReadTests` | 2 farmer-report drivers (expected 1) |
