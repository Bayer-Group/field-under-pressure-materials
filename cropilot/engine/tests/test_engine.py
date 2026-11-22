"""
Engine tests on synthetic weather (no downloaded data needed).

    python manage.py test engine
"""

from datetime import date, datetime, timedelta, timezone as dt_tz

import pandas as pd
from django.test import TestCase

from core.models import (Clock, CropClass, Field, FieldCropYear, Observation, Risk, Threat, WeatherDaily,
                         WeatherGrid, WeatherHourly)
from engine import predict
from engine.catalog import RULES
from engine.compute import field_context
from engine.satellite.season import season_of, slot_end, slot_of

SEASON_START = date(2024, 9, 1)
SEASON_END = date(2025, 7, 31)


def seasonal_temp(day: date) -> float:
    """A rough Polish annual temperature curve, °C."""
    import math
    doy = day.timetuple().tm_yday
    return 8.5 - 10.5 * math.cos(2 * math.pi * (doy - 15) / 365)


class EngineTestBase(TestCase):
    wet_days: set[date] = set()
    today = date(2025, 6, 15)  # the demo date; rule tests that score days after it set a later one (no forecast in the fixture)

    @classmethod
    def setUpTestData(cls):
        from engine.catalog import CROP_NAMES
        for code, name in ((0, "No cropland"), *CROP_NAMES.items()):
            CropClass.objects.create(code=code, name=name)
        for rule in RULES.values():
            Threat.objects.create(code=rule.code, crop_id=rule.crop, name=rule.name_pl, category=rule.category, source="test")
        cls.grid = WeatherGrid.objects.create(grid_id="g1", lat=50.35, lon=17.7)
        Clock(today=cls.today).save()
        cls.make_weather(cls.wet_days)
        cls.wheat = cls.make_field("wheat", 1110, prev=1130)
        cls.wheat_after_wheat = cls.make_field("wheat2", 1110, prev=1110)
        cls.maize = cls.make_field("maize", 1130, prev=1110)

    @classmethod
    def make_weather(cls, wet_days):
        daily, hourly = [], []
        d = SEASON_START - timedelta(days=60)
        while d <= SEASON_END:
            t = seasonal_temp(d)
            wet = d in wet_days
            daily.append(WeatherDaily(grid=cls.grid, date=d, avg_temperature=t, min_temperature=t - 5, max_temperature=t + 5,
                                      avg_relative_humidity=96 if wet else 65, total_precipitation=8 if wet else 0,
                                      eto=2.0, avg_wind_speed=8, avg_soil_temperature_level_1=t, min_soil_temperature_level_1=t - 2,
                                      avg_soil_moisture_level_1=0.25, avg_snow_depth=0))
            for h in range(24):
                ts = datetime(d.year, d.month, d.day, h, tzinfo=dt_tz.utc)
                hourly.append(WeatherHourly(grid=cls.grid, utc_time=ts, date=d, temperature=t + 4 * (1 if 10 <= h <= 18 else -1) * 0.5,
                                            dew_point_temperature=t - 1, relative_humidity=97 if wet else 65,
                                            precipitation=0.5 if wet else 0))
            d += timedelta(days=1)
        WeatherDaily.objects.bulk_create(daily)
        WeatherHourly.objects.bulk_create(hourly, batch_size=5000)

    @classmethod
    def make_field(cls, name, crop, prev):
        f = Field.objects.create(name=name, geometry={"type": "Polygon", "coordinates": []}, area_ha=10,
                                 centroid_lat=50.35, centroid_lon=17.7, weather_grid=cls.grid, h3_cells=[], crop_id=crop)
        FieldCropYear.objects.create(field=f, year=2024, crop_class_id=prev, share=1.0)
        return f


def copy_forecast(grid, first_issue: date, last_issue: date):
    """The platform's demo forecast: for each issue day D, the observed days D+1..D+7 (rain included)."""
    from core.models import WeatherForecastDaily
    cols = ["max_temperature", "min_temperature", "avg_temperature", "avg_relative_humidity", "total_precipitation",
            "avg_wind_speed", "eto", "avg_soil_temperature_level_1", "min_soil_temperature_level_1",
            "avg_soil_moisture_level_1", "avg_snow_depth"]
    obs = {d["date"]: d for d in WeatherDaily.objects.filter(grid=grid).values("date", *cols)}
    rows = []
    d = first_issue
    while d <= last_issue:
        for k in range(1, 8):
            o = obs.get(d + timedelta(days=k))
            if o:
                rows.append(WeatherForecastDaily(grid=grid, issued_on=d, **o))
        d += timedelta(days=1)
    WeatherForecastDaily.objects.bulk_create(rows)


class SeasonGridTests(TestCase):
    def test_season_and_slots(self):
        self.assertEqual(season_of(date(2024, 9, 1)), 2025)
        self.assertEqual(season_of(date(2025, 8, 31)), 2025)
        self.assertEqual(slot_of(date(2024, 9, 1)), 0)
        self.assertEqual(slot_of(date(2025, 8, 31)), 23)
        self.assertEqual(slot_end(2025, 0), date(2024, 9, 15))
        self.assertEqual(slot_end(2025, 23), date(2025, 8, 31))


class PredictTests(EngineTestBase):
    today = date(2025, 7, 31)  # every scored day is in the past: assessed as of that day
    # warm and wet around wheat flowering (the synthetic, cool season flowers ~20-25 June)
    wet_days = {date(2025, 6, d) for d in range(18, 24)}

    def test_writes_rows_within_bounds_with_explanations(self):
        n = predict(start=date(2025, 5, 1), end=date(2025, 6, 22))
        days = (date(2025, 6, 22) - date(2025, 5, 1)).days + 1
        n_rules = sum(1 for r in RULES.values() if r.crop == 1110) * 2 + sum(1 for r in RULES.values() if r.crop == 1130)
        self.assertEqual(n, days * n_rules)
        self.assertEqual(Risk.objects.count(), n)
        for r in Risk.objects.all()[:200]:
            self.assertTrue(0 <= r.score <= 1)
            e = r.explanation
            for key in ("summary", "level", "drivers", "action", "growth_stage", "confidence", "model_version"):
                self.assertIn(key, e)
            self.assertEqual(e["threat"]["code"], r.threat.code)

    def test_rerun_overwrites(self):
        n1 = predict(start=date(2025, 6, 1), end=date(2025, 6, 10))
        n2 = predict(start=date(2025, 6, 1), end=date(2025, 6, 10))
        self.assertEqual(n1, n2)
        self.assertEqual(Risk.objects.count(), n1)

    def test_fusarium_high_at_wet_flowering_and_previous_maize_raises_it(self):
        predict(start=date(2025, 6, 10), end=date(2025, 6, 24))
        fhb = Risk.objects.filter(threat__code="wheat.fusarium_head_blight", date=date(2025, 6, 23))
        after_maize = fhb.get(field=self.wheat)
        after_wheat = fhb.get(field=self.wheat_after_wheat)
        self.assertGreater(after_maize.score, 0.3, after_maize.explanation["summary"])
        self.assertGreaterEqual(after_maize.score, after_wheat.score)
        factors = {d["factor"] for d in after_maize.explanation["drivers"]}
        self.assertIn("previous_crop", factors)
        dry = Risk.objects.get(threat__code="wheat.fusarium_head_blight", date=date(2025, 6, 17), field=self.wheat)
        self.assertLess(dry.score, after_maize.score)

    def test_maize_not_sown_scores_zero(self):
        predict(start=date(2025, 3, 1), end=date(2025, 3, 31))
        rows = Risk.objects.filter(field=self.maize)
        self.assertTrue(rows.exists())
        self.assertEqual(max(r.score for r in rows), 0.0)
        self.assertIn("nie jest jeszcze zasiana", rows.first().explanation["summary"])

    def test_range_across_season_boundary(self):
        n = predict(field_ids=[self.wheat.id], start=date(2025, 7, 25), end=date(2025, 7, 31))
        self.assertEqual(n, 7 * sum(1 for r in RULES.values() if r.crop == 1110))

    def test_field_context_history(self):
        ctx = field_context(self.wheat, 2025)
        self.assertEqual(ctx.previous_crop, 1130)
        self.assertEqual(field_context(self.maize, 2025).maize_years_in_row, 1)


class NoLookAheadTests(EngineTestBase):
    wet_days = {date(2025, 6, d) for d in range(10, 15)}  # wet only AFTER the assessed day

    def test_future_weather_does_not_change_past_risk(self):
        predict(start=date(2025, 6, 1), end=date(2025, 6, 14))
        before = {(r.field_id, r.threat_id): r.score for r in Risk.objects.filter(date=date(2025, 6, 8))}
        # the wet spell after 8 June must not raise risks on 8 June: compare with a dry run of the same day
        WeatherHourly.objects.filter(date__gte=date(2025, 6, 9)).update(relative_humidity=40, precipitation=0)
        WeatherDaily.objects.filter(date__gte=date(2025, 6, 9)).update(avg_relative_humidity=40, total_precipitation=0)
        predict(start=date(2025, 6, 1), end=date(2025, 6, 14))
        after = {(r.field_id, r.threat_id): r.score for r in Risk.objects.filter(date=date(2025, 6, 8))}
        self.assertEqual(before, after)


class ObservationTests(EngineTestBase):
    """Farmer reports change risks from their date on, and show up in the explanation."""
    wet_days = {date(2025, 6, d) for d in range(18, 24)}

    def run_day(self, code, day, field, reports):
        from engine.observations import Report  # noqa: F401  (import check)
        predict(field_ids=[field.id], start=day - timedelta(days=10), end=day, observations=reports)
        return Risk.objects.get(field=field, threat__code=code, date=day)

    def test_symptoms_floor_and_confidence(self):
        from engine.observations import Report
        day = date(2025, 6, 10)  # dry, so rules alone give a low score
        base = self.run_day("wheat.septoria_leaf_blotch", day, self.wheat, [])
        rep = Report(observed_on=date(2025, 6, 8), kind="symptoms", threat_code="wheat.septoria_leaf_blotch", severity=0.8, field_id=self.wheat.id)
        seen = self.run_day("wheat.septoria_leaf_blotch", day, self.wheat, [rep])
        self.assertLess(base.score, 0.3)
        self.assertGreaterEqual(seen.score, 0.8)
        self.assertEqual(seen.explanation["confidence"], 1.0)
        fr = [d for d in seen.explanation["drivers"] if d["factor"] == "farmer_report"]
        self.assertEqual(len(fr), 1)
        self.assertGreater(fr[0]["effect"], 0.5)
        self.assertIn("rolnik zgłosił na tym polu: septorioza paskowana", seen.explanation["summary"].lower())

    def test_report_does_not_change_earlier_days(self):
        from engine.observations import Report
        rep = Report(observed_on=date(2025, 6, 9), kind="symptoms", threat_code="wheat.septoria_leaf_blotch", severity=1.0, field_id=self.wheat.id)
        before = self.run_day("wheat.septoria_leaf_blotch", date(2025, 6, 8), self.wheat, [rep])
        self.assertLess(before.score, 0.3)
        self.assertFalse([d for d in before.explanation["drivers"] if d["factor"] == "farmer_report"])

    def test_neighbour_raises_treatment_lowers_absence_lowers(self):
        from engine.observations import Report
        code, day = "wheat.fusarium_head_blight", date(2025, 6, 23)
        f = self.wheat_after_wheat  # no previous-maize multiplier, so there is room to move
        base = self.run_day(code, day, f, []).score
        nb = self.run_day(code, day, f, [Report(observed_on=date(2025, 6, 20), kind="neighbour", threat_code=code, distance_m=300)]).score
        tr = self.run_day(code, day, f, [Report(observed_on=date(2025, 6, 21), kind="treatment", threat_code=code, field_id=f.id)])
        ab = self.run_day(code, day, f, [Report(observed_on=date(2025, 6, 22), kind="absence", field_id=f.id)]).score
        self.assertGreater(base, 0)
        self.assertGreaterEqual(nb, base)
        self.assertLess(tr.score, base)
        self.assertEqual(tr.explanation["action"]["type"], "wait")
        self.assertLess(ab, base)

    def test_reports_for_other_fields_are_ignored(self):
        from engine.observations import Report
        rep = Report(observed_on=date(2025, 6, 8), kind="symptoms", threat_code="wheat.septoria_leaf_blotch", severity=1.0, field_id=self.wheat_after_wheat.id)
        r = self.run_day("wheat.septoria_leaf_blotch", date(2025, 6, 10), self.wheat, [rep])
        self.assertLess(r.score, 0.3)

    def test_farmer_sowing_date_changes_stage(self):
        from engine.observations import Report
        day = date(2025, 6, 1)
        late = Report(observed_on=date(2025, 5, 1), kind="field_fact", details={"sowing_date": "2025-05-20"}, field_id=self.maize.id)
        r0 = self.run_day("maize.frit_fly", day, self.maize, [])
        r1 = self.run_day("maize.frit_fly", day, self.maize, [late])
        self.assertLess(r1.explanation["growth_stage"]["bbch"], r0.explanation["growth_stage"]["bbch"])
        self.assertEqual(r1.explanation["growth_stage"]["sowing_assumed"], "2025-05-20")
        self.assertIn("rolnika", r1.explanation["growth_stage"]["method"])


class AssistantObservationTests(EngineTestBase):
    """Reports the chat stores in the interim assistant.Observation reach the engine (no observations= passed)."""

    def obs(self, field, day, category, threat=None, severity="", note="", details=None, key="k"):
        from assistant.models import Observation
        return Observation.objects.create(field=field, date=day, category=category, severity=severity, note=note,
                                          threat=Threat.objects.get(code=threat) if threat else None,
                                          details=details or {}, idempotency_key=key)

    def test_chat_symptoms_raise_risk_from_the_table(self):
        code, day = "wheat.septoria_leaf_blotch", date(2025, 6, 10)
        predict(field_ids=[self.wheat.id], start=day, end=day)
        base = Risk.objects.get(field=self.wheat, threat__code=code, date=day).score
        self.obs(self.wheat, date(2025, 6, 8), "choroba", code, "wysokie", "widzę plamy na liściach")
        predict(field_ids=[self.wheat.id], start=day, end=day)
        r = Risk.objects.get(field=self.wheat, threat__code=code, date=day)
        self.assertLess(base, 0.3)
        self.assertGreaterEqual(r.score, 0.8)
        self.assertTrue([d for d in r.explanation["drivers"] if d["factor"] == "farmer_report"])

    def test_mapping_of_interim_rows(self):
        from engine.observations import _from_assistant
        nb = _from_assistant(self.obs(self.wheat, date(2025, 6, 1), "choroba", "wheat.brown_rust",
                                      details={"kind": "neighbour", "distance_m": 300}, key="a"))
        self.assertEqual((nb.kind, nb.threat_code, nb.distance_m), ("neighbour", "wheat.brown_rust", 300.0))
        hail = _from_assistant(self.obs(self.wheat, date(2025, 6, 1), "uszkodzenie", note="wczoraj spadł grad", key="b"))
        self.assertEqual((hail.kind, hail.details.get("type")), ("event", "hail"))
        sow = _from_assistant(self.obs(self.wheat, date(2025, 6, 1), "inne",
                                       details={"draft": {"kind": "field_fact", "sowing_date": "2024-09-25"}}, key="c"))
        self.assertEqual((sow.kind, sow.details["sowing_date"]), ("field_fact", "2024-09-25"))
        self.assertIsNone(_from_assistant(self.obs(self.wheat, date(2025, 6, 1), "chwasty", note="dużo chwastów", key="d")))
        sym = _from_assistant(self.obs(self.wheat, date(2025, 6, 1), "szkodnik", severity="srednie", key="e"))
        self.assertEqual((sym.kind, sym.group, sym.severity), ("symptoms", "pest", 0.6))

    def test_disease_without_threat_raises_only_diseases(self):
        from engine.catalog import RULES
        from engine.observations import _from_assistant, effects
        import pandas as pd
        rep = _from_assistant(self.obs(self.wheat, date(2025, 6, 1), "choroba", severity="wysokie", key="f"))
        days = pd.date_range("2025-06-01", "2025-06-05")
        self.assertTrue(effects(RULES["wheat.brown_rust"], [rep], days))
        self.assertFalse(effects(RULES["wheat.aphids"], [rep], days))


class OtherCropTests(EngineTestBase):
    """Barley, other cereals, rapeseed, sugar beet and potatoes get their own rules and growth stages."""
    today = date(2025, 7, 31)
    wet_days = {date(2025, 6, d) for d in range(18, 24)}

    def test_every_engine_crop_gets_risks(self):
        from engine.catalog import CROP_NAMES, rules_for_crop
        day = date(2025, 6, 20)
        for crop in CROP_NAMES:
            f = self.make_field(f"f{crop}", crop, prev=1110)
            n = predict(field_ids=[f.id], start=day, end=day)
            self.assertEqual(n, len(rules_for_crop(crop)), crop)
            r = Risk.objects.filter(field=f, date=day).first()
            self.assertTrue(r.explanation["summary"])
            self.assertGreaterEqual(r.explanation["growth_stage"]["bbch"], 0, crop)

    def test_stage_calendars(self):
        from engine.catalog import BARLEY, POTATO, RAPESEED, SUGAR_BEET
        from engine.phenology import bbch_series
        idx = pd.date_range("2024-07-01", "2025-11-30")
        temps = pd.Series([seasonal_temp(d.date()) for d in idx], index=idx)

        def first(crop, bbch):
            s = bbch_series(crop, temps, 2025)["bbch"]
            return s[s >= bbch].index[0].date()

        self.assertTrue(date(2025, 4, 10) <= first(RAPESEED, 60) <= date(2025, 5, 10))   # rapeseed flowering
        self.assertTrue(date(2025, 6, 25) <= first(RAPESEED, 89) <= date(2025, 7, 31))   # rapeseed harvest
        self.assertLess(first(BARLEY, 55), first(1110, 55))                              # barley heads before wheat
        self.assertTrue(date(2025, 4, 15) <= first(SUGAR_BEET, 10) <= date(2025, 5, 20))
        self.assertTrue(date(2025, 6, 1) <= first(POTATO, 31) <= date(2025, 7, 15))      # potato rows closing
        s = bbch_series(RAPESEED, temps, 2025)["bbch"]
        self.assertGreaterEqual(s[pd.Timestamp("2024-11-15")], 14)                       # rosette before winter

    def test_potato_late_blight_follows_wet_warm_days(self):
        f = self.make_field("potato", 1310, prev=1110)
        predict(field_ids=[f.id], start=date(2025, 6, 10), end=date(2025, 6, 24))
        dry = Risk.objects.get(field=f, threat__code="potato.late_blight", date=date(2025, 6, 12)).score
        wet = Risk.objects.get(field=f, threat__code="potato.late_blight", date=date(2025, 6, 22))
        self.assertLess(dry, 0.3)
        self.assertGreaterEqual(wet.score, 0.6)
        self.assertIn("zaraza ziemniaka", wet.explanation["summary"].lower())

    def test_rotation_pest_needs_a_host_in_the_last_seasons(self):
        day = date(2025, 7, 1)
        after_beet = self.make_field("beet_after_beet", 1320, prev=1320)
        after_wheat = self.make_field("beet_after_wheat", 1320, prev=1110)
        predict(field_ids=[after_beet.id, after_wheat.id], start=day, end=day)
        hi = Risk.objects.get(field=after_beet, threat__code="sugar_beet.beet_cyst_nematode", date=day)
        lo = Risk.objects.get(field=after_wheat, threat__code="sugar_beet.beet_cyst_nematode", date=day)
        self.assertGreater(hi.score, lo.score * 5)
        self.assertIn("roślina żywicielska", hi.explanation["summary"])

    def test_beet_season_runs_into_autumn(self):
        from engine.compute import crop_season_segments
        f = self.make_field("beet_autumn", 1320, prev=1110)
        segs = crop_season_segments(f, date(2025, 8, 1), date(2025, 12, 31))
        self.assertIn((2025, date(2025, 9, 1), date(2025, 11, 30), 1320, "field"), segs)   # beet to 30 Nov
        w = self.make_field("wheat_autumn", 1110, prev=1130)
        self.assertEqual([s[0] for s in crop_season_segments(w, date(2025, 8, 1), date(2025, 12, 31))], [2025])


class FieldRecordTests(TestCase):
    """Facts stored on the field (proposed Field columns) become field_fact reports; sowing dates stay in their season."""

    def test_from_field_and_sowing_window(self):
        from types import SimpleNamespace
        Clock(today=date(2025, 6, 15)).save()
        from engine.observations import from_field, sowing_override
        f = SimpleNamespace(id=7, sowing_date=date(2024, 9, 25), tillage="reduced", resistant_to=["wheat.brown_rust"])
        reps = from_field(f)
        self.assertEqual({r.kind for r in reps}, {"field_fact"})
        self.assertEqual(len(reps), 3)
        self.assertTrue(all(r.field_id == 7 for r in reps))
        self.assertTrue(reps[1].label().startswith("Dane z karty pola"))
        self.assertEqual(sowing_override(reps, (date(2024, 7, 3), date(2025, 8, 31))), (date(2024, 9, 25), date(2024, 9, 25)))
        self.assertIsNone(sowing_override(reps, (date(2023, 7, 3), date(2024, 8, 31))))   # not last season's sowing
        self.assertEqual(from_field(SimpleNamespace(id=1)), [])                           # columns absent: nothing


class ConsistencyTests(EngineTestBase):
    """Fixes from the cross-component review: readers, levels, threat loader, forecast lead."""

    def test_reader_never_guesses_symptoms(self):
        from types import SimpleNamespace as NS
        from engine.observations import _to_report
        core_like = NS(pk=1, observed_on=date(2025, 6, 1), kind="treatment", threat_code=None, severity=None, distance_m=None,
                       details={}, text="sprayed", field_id=3)
        self.assertEqual(_to_report(core_like, "observed_on").kind, "treatment")
        no_kind = NS(pk=2, observed_on=date(2025, 6, 1), details={}, text="?", field_id=3)
        self.assertIsNone(_to_report(no_kind, "observed_on"))                      # skipped, not "symptoms"
        dmg = NS(pk=3, date=date(2025, 6, 1), category="uszkodzenie", details={}, note="coś połamało", field_id=3, threat_id=None)
        rep = _to_report(dmg, "date")
        self.assertEqual((rep.kind, rep.details["type"]), ("event", "damage"))
        self.assertIn("Uszkodzenie uprawy", rep.label())
        num = NS(pk=4, date=date(2025, 6, 1), category="choroba", severity=0.8, details={}, note="", field_id=3, threat_id=None)
        self.assertEqual(_to_report(num, "date").severity, 0.8)

    def test_levels_match_the_map(self):
        from engine.scoring import level_of
        self.assertEqual([level_of(s) for s in (0.32, 0.33, 0.65, 0.66)], ["low", "medium", "medium", "high"])

    def test_load_threats_keeps_platform_rows(self):
        from django.core.management import call_command
        import io
        Threat.objects.filter(code="wheat.brown_rust").update(name="rdza brunatna (fixture)", source="fixture")
        call_command("engine_load_threats", stdout=io.StringIO())
        self.assertEqual(Threat.objects.get(code="wheat.brown_rust").source, "fixture")
        call_command("engine_load_threats", "--overwrite", stdout=io.StringIO())
        self.assertEqual(Threat.objects.get(code="wheat.brown_rust").source, "engine rules")

    def test_forecast_lead_follows_the_clock(self):
        from engine import clock_moved
        copy_forecast(self.grid, date(2025, 6, 10), date(2025, 6, 25))
        day = date(2025, 6, 18)  # clock 2025-06-15 -> day +3
        predict(field_ids=[self.wheat.id], start=day, end=day)
        r = Risk.objects.filter(field=self.wheat, date=day).first()
        self.assertEqual(r.explanation["forecast_lead_days"], 3)
        self.assertEqual(r.explanation["forecast_issued_on"], "2025-06-15")
        c = Clock.objects.get(); c.today = date(2025, 6, 17); c.save()
        clock_moved(date(2025, 6, 15), date(2025, 6, 17))                   # day +1
        r = Risk.objects.get(field=self.wheat, threat=r.threat, date=day)
        self.assertEqual(r.explanation["forecast_lead_days"], 1)
        self.assertEqual(r.explanation["forecast_issued_on"], "2025-06-17")
        c.today = date(2025, 6, 20); c.save()
        clock_moved(date(2025, 6, 17), date(2025, 6, 20))                   # now in the past
        r = Risk.objects.get(field=self.wheat, threat=r.threat, date=day)
        self.assertNotIn("forecast_lead_days", r.explanation)
        self.assertFalse([n for n in r.explanation["notes"] if n.startswith("Dzień +")])
        c.today = date(2025, 6, 15); c.save()

    def test_clock_save_has_no_side_effects(self):
        predict(field_ids=[self.wheat.id], start=date(2025, 6, 10), end=date(2025, 6, 14))
        before = list(Risk.objects.order_by("id").values_list("id", "computed_at"))
        c = Clock.objects.get(); c.today = date(2025, 6, 16); c.save()      # no signal: nothing recomputed
        self.assertEqual(list(Risk.objects.order_by("id").values_list("id", "computed_at")), before)
        c.today = date(2025, 6, 15); c.save()


class ContractExtrasTests(EngineTestBase):
    """docs/archive/engine-predict-review.md: clock_moved, precompute_season, result field ids, guards."""
    wet_days = {date(2025, 6, d) for d in range(18, 24)}

    def test_clock_moved_rewrites_only_the_window_and_fixes_coming_days(self):
        from engine import clock_moved
        copy_forecast(self.grid, date(2025, 6, 10), date(2025, 6, 30))
        predict(start=date(2025, 6, 1), end=date(2025, 7, 31))
        stamp = {r.id: r.computed_at for r in Risk.objects.all()}
        c = Clock.objects.get(); c.today = date(2025, 6, 18); c.save()
        res = clock_moved(date(2025, 6, 15), date(2025, 6, 18))
        self.assertGreater(int(res), 0)
        lo, hi = date(2025, 6, 16), date(2025, 6, 25)
        outside = Risk.objects.exclude(date__range=(lo, hi))
        self.assertTrue(all(stamp.get(r.id) == r.computed_at for r in outside))      # untouched
        inside = Risk.objects.filter(date__range=(lo, hi))
        self.assertTrue(all(r.id not in stamp for r in inside))                       # recomputed
        coming = Risk.objects.filter(date__gt=date(2025, 6, 18), date__lte=date(2025, 6, 25))
        self.assertTrue(all(r.explanation["forecast_lead_days"] == (r.date - date(2025, 6, 18)).days for r in coming))
        past = Risk.objects.filter(date__range=(date(2025, 6, 16), date(2025, 6, 18)))
        self.assertTrue(all("forecast_lead_days" not in r.explanation for r in past))
        c.today = date(2025, 6, 15); c.save()

    def test_precompute_season_covers_both_seasons_in_order(self):
        from engine import precompute_season
        copy_forecast(self.grid, date(2025, 6, 15), date(2025, 6, 15))
        res = precompute_season()
        self.assertEqual(sorted(res.field_ids), sorted([self.wheat.id, self.wheat_after_wheat.id, self.maize.id]))
        last = Risk.objects.order_by("-date").values_list("date", flat=True).first()
        self.assertEqual(last, date(2025, 7, 31))                                     # season end (last weather day)
        self.assertTrue(Risk.objects.filter(date__lt=date(2024, 9, 1)).exists())      # previous season too
        self.assertEqual(int(res), Risk.objects.filter(date__gte=date(2024, 6, 1)).count())

    def test_result_is_an_int_with_field_ids(self):
        res = predict(field_ids=[self.maize.id], start=date(2025, 6, 10), end=date(2025, 6, 12))
        self.assertIsInstance(res, int)
        self.assertEqual(res.field_ids, [self.maize.id])
        self.assertEqual(int(res + res), 2 * int(res))

    def test_days_without_weather_keep_their_rows(self):
        predict(field_ids=[self.wheat.id], start=date(2025, 7, 25), end=date(2025, 7, 31))
        n = Risk.objects.filter(field=self.wheat).count()
        predict(field_ids=[self.wheat.id], start=date(2025, 7, 25), end=date(2025, 8, 15))  # no weather after 31 July
        self.assertEqual(Risk.objects.filter(field=self.wheat).count(), n)

    def test_no_forecast_no_coming_days(self):
        predict(start=date(2025, 6, 10), end=date(2025, 6, 22))
        self.assertFalse(Risk.objects.filter(date__gt=date(2025, 6, 15)).exists())
        self.assertTrue(Risk.objects.filter(date=date(2025, 6, 15)).exists())

    def test_coming_days_spray_window_uses_todays_forecast(self):
        from engine.compute import _forecast
        copy_forecast(self.grid, date(2025, 6, 15), date(2025, 6, 20))
        fc = _forecast("g1", date(2025, 6, 18), today=date(2025, 6, 15))
        self.assertEqual([d for d in fc.index], [date(2025, 6, 19), date(2025, 6, 20), date(2025, 6, 21), date(2025, 6, 22)])

    def test_field_facts_hold_from_this_season_only(self):
        from types import SimpleNamespace
        from engine.observations import from_field
        rep = from_field(SimpleNamespace(id=1, resistant_to=["wheat.brown_rust"]))[0]
        self.assertEqual(rep.observed_on, date(2024, 9, 1))


class PureFunctionTests(TestCase):
    def test_safe_storage_days_matches_table_37(self):
        from engine.harvest import safe_storage_days
        self.assertAlmostEqual(safe_storage_days(22, 15.6), 17, delta=0.5)
        self.assertAlmostEqual(safe_storage_days(18, -1.1), 648, delta=1)
        self.assertGreater(safe_storage_days(20, 5), safe_storage_days(26, 5))
        self.assertGreater(safe_storage_days(24, 5), safe_storage_days(24, 20))

    def test_spray_window_rules(self):
        import pandas as pd
        from engine.scoring import spray_window
        fc = pd.DataFrame({
            "max_temperature": [28, 18, 18], "min_temperature": [12, 8, 0.5], "total_precipitation": [0, 0, 0],
            "avg_wind_speed": [5, 5, 5], "avg_relative_humidity": [80, 80, 80],
        }, index=[date(2025, 6, 2), date(2025, 6, 3), date(2025, 6, 4)])
        self.assertIsNone(spray_window(fc))  # 2 Jun too hot; 3 Jun ok but the next night is 0.5 °C; 4 Jun itself 0.5 °C
        fc.loc[date(2025, 6, 4), "min_temperature"] = 6
        w = spray_window(fc)
        self.assertEqual(w["date"], "2025-06-03")
        self.assertEqual(w["quality"], "optimal")

    def test_lead_adjust_is_idempotent(self):
        from engine.compute import adjust_for_lead
        e = {"confidence": 0.6, "notes": []}
        adjust_for_lead(e, 5); adjust_for_lead(e, 5)
        self.assertAlmostEqual(e["confidence"], round(0.6 * 0.7, 2))
        self.assertEqual(len([n for n in e["notes"] if n.startswith("Dzień +")]), 1)


class FarmFeatureTests(EngineTestBase):
    wet_days = {date(2025, 6, d) for d in range(18, 24)}

    def test_ranking_orders_by_expected_loss(self):
        from engine.summary import farm_ranking
        predict(start=date(2025, 6, 15), end=date(2025, 6, 23))
        r = farm_ranking(date(2025, 6, 23))
        self.assertEqual([x["rank"] for x in r], list(range(1, len(r) + 1)))
        losses = [x["expected_loss"] for x in r]
        self.assertEqual(losses, sorted(losses, reverse=True))
        self.assertIn("why", r[0])

    def test_symptoms_spread_to_nearby_same_crop_field(self):
        from engine.observations import Report
        code = "wheat.fusarium_head_blight"
        predict(start=date(2025, 6, 15), end=date(2025, 6, 23))
        before = Risk.objects.get(field=self.wheat_after_wheat, threat__code=code, date=date(2025, 6, 23)).score
        rep = Report(observed_on=date(2025, 6, 20), kind="symptoms", threat_code=code, severity=0.8, field_id=self.wheat.id)
        predict(field_ids=[self.wheat.id], start=date(2025, 6, 15), end=date(2025, 6, 23), observations=[rep])
        after = Risk.objects.get(field=self.wheat_after_wheat, threat__code=code, date=date(2025, 6, 23))
        self.assertGreaterEqual(after.score, before)  # may already be saturated at 1.0
        self.assertTrue(any(d["factor"] == "farmer_report" and d["kind"] == "neighbour" for d in after.explanation["drivers"]))

    def test_what_if_does_not_write(self):
        from engine import what_if
        from engine.observations import Report
        code = "wheat.fusarium_head_blight"
        predict(start=date(2025, 6, 15), end=date(2025, 6, 23))
        stored = Risk.objects.get(field=self.wheat, threat__code=code, date=date(2025, 6, 23)).score
        res = what_if(self.wheat.id, date(2025, 6, 23), [Report(observed_on=date(2025, 6, 22), kind="treatment", threat_code=code, field_id=self.wheat.id)])
        fhb = next(x for x in res if x["threat_code"] == code)
        self.assertLess(fhb["score_if"], fhb["score_now"])
        self.assertEqual(Risk.objects.get(field=self.wheat, threat__code=code, date=date(2025, 6, 23)).score, stored)

    def test_coming_days_have_lower_confidence(self):
        copy_forecast(self.grid, date(2025, 6, 15), date(2025, 6, 15))
        predict(start=date(2025, 6, 14), end=date(2025, 6, 20))  # clock: 15 June
        today_row = Risk.objects.filter(field=self.wheat, date=date(2025, 6, 15)).first()
        ahead = Risk.objects.get(field=self.wheat, threat=today_row.threat, date=date(2025, 6, 20))
        self.assertEqual(ahead.explanation["forecast_lead_days"], 5)
        self.assertLess(ahead.explanation["confidence"], today_row.explanation["confidence"])

    def test_maize_season_continues_after_1_september(self):
        n = predict(field_ids=[self.maize.id], start=date(2025, 7, 25), end=date(2025, 7, 31))
        self.assertGreater(n, 0)


class SatelliteStageTests(TestCase):
    def test_calibration_only_from_detection_day(self):
        import pandas as pd
        from engine.phenology import bbch_series, calibrate
        from engine.satellite.fieldndvi import phenology_anchors
        idx = pd.date_range("2024-07-01", "2025-08-31")
        temp = pd.Series([seasonal_temp(d.date()) for d in idx], index=idx)
        st = bbch_series(1110, temp, 2025)
        # NDVI: green in spring, peak 0.9 on 25 May, falling after
        days = pd.date_range("2025-03-01", "2025-08-15", freq="5D")
        ndvi = [0.5 + 0.4 * min(1, (d - days[0]).days / 85) if d <= pd.Timestamp("2025-05-25") else max(0.2, 0.9 - (d - pd.Timestamp("2025-05-25")).days * 0.012) for d in days]
        series = pd.DataFrame({"date": days, "ndvi": ndvi})
        anchors = phenology_anchors(series, 1110, 2025)
        self.assertTrue(anchors)
        cal = calibrate(st, 1110, anchors)
        first = min(a.detected_on for a in anchors)
        before = st.index < pd.Timestamp(first)
        self.assertTrue((cal.loc[before, "bbch"] == st.loc[before, "bbch"]).all())
        self.assertAlmostEqual(cal.loc[pd.Timestamp(anchors[0].detected_on), "confidence"], 0.8)

    def test_crop_check_flags_bare_spring_for_wheat(self):
        import pandas as pd
        from engine.satellite.fieldndvi import crop_check
        days = pd.date_range("2025-03-15", "2025-06-30", freq="7D")
        maize_like = pd.DataFrame({"date": days, "ndvi": [0.2] * 9 + [0.5] * (len(days) - 9)})
        r = crop_check(maize_like, 1110, 2025, date(2025, 6, 30))
        self.assertFalse(r["consistent"])
        self.assertIn("wiosną goła gleba", r["text"])


class SnapshotTests(EngineTestBase):
    """clock_moved() copies precomputed rows (engine.RiskSnapshot): same result as computing, no computing."""
    wet_days = {date(2025, 6, d) for d in (12, 13, 17, 18, 19, 24)}

    def setUp(self):
        copy_forecast(self.grid, date(2025, 6, 1), date(2025, 7, 20))
        predict(start=date(2025, 6, 1), end=date(2025, 7, 31))  # the seed

    def state(self):
        return {(r.field_id, r.threat_id, r.date): (r.score, r.explanation) for r in Risk.objects.all()}

    def truth(self, today):
        """Risk as a full recompute at `today` writes it (snapshots out of the way)."""
        from engine.models import RiskSnapshot
        saved = list(RiskSnapshot.objects.all())
        RiskSnapshot.objects.all().delete()
        Clock.objects.update(today=today)
        predict(start=date(2025, 6, 1), end=date(2025, 7, 31))
        out = self.state()
        RiskSnapshot.objects.all().delete()
        RiskSnapshot.objects.bulk_create(saved)
        return out

    def move(self, new):
        from engine import clock_moved
        from core import clock
        old = clock.today()
        Clock.objects.update(today=new)
        return clock_moved(old, new)

    def test_moves_copy_and_match_a_full_recompute(self):
        from unittest import mock
        from engine import precompute_dates
        self.assertGreater(precompute_dates(date(2025, 6, 10), date(2025, 6, 25)), 0)
        seen = []
        with mock.patch("engine.compute.compute_rows", side_effect=AssertionError("computed")):
            for new in (date(2025, 6, 18), date(2025, 6, 16), date(2025, 6, 25), date(2025, 6, 10), date(2025, 6, 15)):
                res = self.move(new)
                self.assertEqual(sorted(res.field_ids), sorted(f.id for f in Field.objects.all()))
                seen.append((new, self.state()))
        for new, got in seen:
            self.assertEqual(got, self.truth(new), f"clock moved to {new}")

    def test_without_snapshots_it_computes_and_keeps_them(self):
        from engine.models import RiskSnapshot
        RiskSnapshot.objects.all().delete()
        self.move(date(2025, 6, 18))
        self.assertEqual(self.state(), self.truth(date(2025, 6, 18)))
        Clock.objects.update(today=date(2025, 6, 18))
        self.move(date(2025, 6, 15))
        Clock.objects.update(today=date(2025, 6, 15))
        from unittest import mock
        with mock.patch("engine.compute.compute_rows", side_effect=AssertionError("computed")):
            self.move(date(2025, 6, 18))  # both directions were stored on the first moves

    def test_a_report_drops_stale_snapshots(self):
        from engine import precompute_dates
        precompute_dates(date(2025, 6, 10), date(2025, 6, 25))
        Observation.objects.create(field=self.wheat, observed_on=date(2025, 6, 14), kind="symptoms",
                                   threat=Threat.objects.get(code="wheat.septoria_leaf_blotch"), severity=0.9, text="plamy")
        predict(field_ids=[self.wheat.id], start=date(2025, 6, 14))  # what the assistant calls after the report
        res = self.move(date(2025, 6, 20))
        self.assertIn(self.wheat.id, res.field_ids)
        self.assertEqual(self.state(), self.truth(date(2025, 6, 20)))


class AuditFixTests(EngineTestBase):
    """Fixes from docs/audit-2026-11-21.md (E-1, E-2, E-4, E-6, E-11, E-12, E-16d)."""

    wet_days = {date(2025, 5, d) for d in (20, 21, 24, 25, 26)}

    def test_last_seasons_maize_stays_until_its_harvest(self):
        """E-1: maize of season N is still in the field from 1 September to 31 December, whichever season the
        Clock is in; a winter crop of season N+1 takes the field from its sowing."""
        from engine.compute import crop_season_segments
        maize = self.make_field("maize after maize", 1130, prev=1130)
        segs = crop_season_segments(maize, date(2024, 9, 1), date(2025, 1, 10))
        self.assertEqual(segs[0][:5], (2024, date(2024, 9, 1), date(2024, 12, 31), 1130, "crop map"))
        self.assertEqual(segs[1][:4], (2025, date(2025, 1, 1), date(2025, 1, 10), 1130))
        # wheat after maize: the maize stays until the day before the assumed wheat sowing (1 October)
        segs = crop_season_segments(self.wheat, date(2024, 9, 1), date(2024, 10, 5))
        self.assertEqual(segs[0][:4], (2024, date(2024, 9, 1), date(2024, 9, 30), 1130))
        self.assertEqual(segs[1][:4], (2025, date(2024, 10, 1), date(2024, 10, 5), 1110))
        # wheat after wheat: nothing late, one segment
        self.assertEqual(len(crop_season_segments(self.wheat_after_wheat, date(2024, 9, 1), date(2024, 10, 5))), 1)

    def test_a_move_into_another_season_computes_oldest_season_first(self):
        """E-2: one predict() per season, in order, so carry-over reads the previous season just written."""
        from unittest import mock
        from engine import compute
        with mock.patch.object(compute, "predict", return_value=compute.PredictResult(0)) as p:
            compute.clock_moved(date(2025, 8, 30), date(2025, 9, 2))
        ranges = [(c.kwargs["start"], c.kwargs["end"]) for c in p.call_args_list]
        self.assertEqual(ranges, [(date(2025, 8, 31), date(2025, 8, 31)), (date(2025, 9, 1), date(2025, 9, 9))])

    def test_engine_set_date_goes_through_set_today(self):
        """E-4: the command moves the date and recomputes in one transaction, and rejects other date formats."""
        from unittest import mock
        from django.core.management import call_command
        from django.core.management.base import CommandError
        with mock.patch("engine.clock_moved") as moved:
            call_command("engine_set_date", "2025-06-16", stdout=open("/dev/null", "w"))
        moved.assert_called_once_with(date(2025, 6, 15), date(2025, 6, 16))
        self.assertEqual(Clock.objects.get(pk=1).today, date(2025, 6, 16))
        with self.assertRaises(CommandError):
            call_command("engine_set_date", "2025-W25-1")

    def test_a_neighbour_report_without_a_threat_raises_its_group(self):
        """E-6: "the neighbour has pests" (no threat named) raises the pests, not the diseases."""
        from engine import observations as OBS
        days = pd.date_range("2025-06-01", "2025-06-10", freq="D")
        r = OBS.Report(observed_on=date(2025, 6, 1), kind="neighbour", group="pest", distance_m=500)
        pest = OBS.effects(RULES["maize.european_corn_borer"], [r], days)
        self.assertTrue(pest and pest[0].mult.max() > 1)
        self.assertEqual(OBS.effects(RULES["wheat.septoria_leaf_blotch"], [r], days), [])
        self.assertIn("szkodniki", r.label())

    def test_every_score_changing_factor_has_an_effect(self):
        """E-11: rain days, 7-day temperature, local pressure and water balance change the score, so they carry an
        effect (final minus the score without them); E-16d: the level always matches the rounded score."""
        from engine.scoring import level_of
        predict(start=date(2025, 5, 1), end=date(2025, 6, 15))
        seen = set()
        for r in Risk.objects.all():
            e = r.explanation
            self.assertEqual(e["level"], level_of(r.score), r)
            for d in e["drivers"]:
                if d["factor"] in ("rain_days", "mean_temperature_7d", "local_pressure", "water_balance_30d"):
                    self.assertIsInstance(d["effect"], float, (r.threat.code, d))
                    seen.add(d["factor"])
        self.assertTrue({"rain_days", "local_pressure"} <= seen, seen)

    def test_stage_effect_counts_the_farmers_reports(self):
        """E-12: with a symptoms report (score floored to high) the growth stage's effect is measured with the
        report applied too, so it is never larger than the score itself."""
        Observation.objects.create(field=self.wheat, observed_on=date(2025, 6, 10), kind="symptoms",
                                   threat=Threat.objects.get(code="wheat.septoria_leaf_blotch"), severity=0.5)
        predict(field_ids=[self.wheat.id], start=date(2025, 6, 1), end=date(2025, 6, 15))
        r = Risk.objects.get(field=self.wheat, threat__code="wheat.septoria_leaf_blotch", date=date(2025, 6, 12))
        stage = next(d for d in r.explanation["drivers"] if d["factor"] == "growth_stage")
        self.assertLessEqual(abs(stage["effect"]), r.score + 1e-9)
