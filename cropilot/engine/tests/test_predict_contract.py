"""
predict() contract tests: each test states the intended behaviour (docs/interfaces.md).
They run on the engine's own synthetic fixture (EngineTestBase: clock 2025-06-15, weather to 2025-07-31).
"""

from datetime import date, timedelta

from core.models import Clock, Observation, Risk, Threat, WeatherDaily, WeatherForecastDaily, WeatherHourly
from engine import predict
from engine.tests.test_engine import EngineTestBase

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
        seed_forecast(TODAY)  # the platform seed provides the forecast; coming days are computed from it
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
