from datetime import date, timedelta

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from core import clock
from core.models import (
    Clock,
    CropClass,
    Field,
    FieldCropYear,
    Observation,
    Risk,
    SoilCell,
    Threat,
    WeatherDaily,
    WeatherForecastDaily,
    WeatherGrid,
)

TODAY = date(2024, 5, 15)


class HealthEndpointTests(TestCase):
    def test_health_reports_database_ok(self):
        from unittest import mock
        status = {"available": False, "llm": False, "rag": False, "reason": "x"}
        with mock.patch("assistant.status.assistant_status", return_value=status):
            response = self.client.get(reverse("health"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "database": True, "clock": False, "assistant": status})

    def test_health_says_whether_the_clock_is_set(self):
        Clock.objects.create(today=TODAY)
        self.assertTrue(self.client.get(reverse("health")).json()["clock"])


class ClockTests(TestCase):
    def test_today_raises_when_clock_row_is_missing(self):
        with self.assertRaises(clock.ClockNotSetError):
            clock.today()

    def test_today_returns_the_clock_date(self):
        Clock.objects.create(today=TODAY)
        self.assertEqual(clock.today(), TODAY)

    def test_saving_another_clock_overwrites_the_single_row(self):
        Clock.objects.create(today=TODAY)
        Clock(today=TODAY + timedelta(days=1)).save()
        self.assertEqual(Clock.objects.count(), 1)
        self.assertEqual(clock.today(), TODAY + timedelta(days=1))

    def test_database_rejects_a_second_clock_row(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Clock.objects.bulk_create([Clock(id=2, today=TODAY)])  # bulk_create skips save()


class FarmTestCase(TestCase):
    """One grid cell, one wheat field and one threat, with the clock at TODAY."""

    @classmethod
    def setUpTestData(cls):
        Clock.objects.create(today=TODAY)
        cls.grid = WeatherGrid.objects.create(grid_id="G1", lat=50.0, lon=19.0)
        cls.wheat = CropClass.objects.create(code=CropClass.WHEAT, name="Wheat")
        cls.field = Field.objects.create(
            name="North field",
            geometry={"type": "Polygon", "coordinates": [[[19.0, 50.0], [19.01, 50.0], [19.0, 50.01], [19.0, 50.0]]]},
            area_ha=20.0,
            centroid_lat=50.003,
            centroid_lon=19.003,
            weather_grid=cls.grid,
            h3_cells=["8a1e20000000fff", "8a1e20000007fff"],
            crop=cls.wheat,
        )
        cls.threat = Threat.objects.create(
            code="wheat.septoria_leaf_blotch",
            crop=cls.wheat,
            name="septorioza paskowana liści pszenicy",
            category=Threat.Category.FUNGAL,
            temp_min_c=4,
            temp_max_c=18,
            source="ryzyka_zebrane.xlsx / pszenica",
        )


class WeatherTests(FarmTestCase):
    def test_observed_excludes_days_after_today(self):
        for offset in (-1, 0, 1):
            WeatherDaily.objects.create(grid=self.grid, date=TODAY + timedelta(days=offset))
        observed = WeatherDaily.objects.observed().values_list("date", flat=True)
        self.assertEqual(sorted(observed), [TODAY - timedelta(days=1), TODAY])

    def test_current_forecast_is_the_one_issued_today(self):
        WeatherForecastDaily.objects.create(grid=self.grid, issued_on=TODAY - timedelta(days=1), date=TODAY)
        WeatherForecastDaily.objects.create(grid=self.grid, issued_on=TODAY, date=TODAY + timedelta(days=1))
        current = WeatherForecastDaily.objects.current().values_list("date", flat=True)
        self.assertEqual(list(current), [TODAY + timedelta(days=1)])

    def test_observed_as_of_cuts_at_the_given_day(self):
        for offset in (-2, -1, 0):
            WeatherDaily.objects.create(grid=self.grid, date=TODAY + timedelta(days=offset))
        observed = WeatherDaily.objects.observed(as_of=TODAY - timedelta(days=1)).values_list("date", flat=True)
        self.assertEqual(sorted(observed), [TODAY - timedelta(days=2), TODAY - timedelta(days=1)])

    def test_current_as_of_returns_the_forecast_issued_that_day(self):
        issued = TODAY - timedelta(days=3)
        WeatherForecastDaily.objects.create(grid=self.grid, issued_on=issued, date=issued + timedelta(days=1))
        WeatherForecastDaily.objects.create(grid=self.grid, issued_on=TODAY, date=TODAY + timedelta(days=1))
        dates = WeatherForecastDaily.objects.current(as_of=issued).values_list("date", flat=True)
        self.assertEqual(list(dates), [issued + timedelta(days=1)])

    def test_forecast_must_be_1_to_7_days_after_issue(self):
        WeatherForecastDaily.objects.create(grid=self.grid, issued_on=TODAY, date=TODAY + timedelta(days=7))
        for bad_offset in (0, 8):
            with self.subTest(offset=bad_offset), self.assertRaises(IntegrityError), transaction.atomic():
                WeatherForecastDaily.objects.create(
                    grid=self.grid, issued_on=TODAY, date=TODAY + timedelta(days=bad_offset)
                )

    def test_daily_weather_is_unique_per_grid_and_date(self):
        WeatherDaily.objects.create(grid=self.grid, date=TODAY)
        with self.assertRaises(IntegrityError), transaction.atomic():
            WeatherDaily.objects.create(grid=self.grid, date=TODAY)


class FieldTests(FarmTestCase):
    def test_soil_cells_returns_cells_under_the_field(self):
        SoilCell.objects.create(h3_index_10="8a1e20000000fff", ph=6.5)
        SoilCell.objects.create(h3_index_10="8a1e20000017fff", ph=5.0)  # not under the field
        self.assertEqual([c.h3_index_10 for c in self.field.soil_cells()], ["8a1e20000000fff"])

    def test_crop_share_must_be_between_0_and_1(self):
        FieldCropYear.objects.create(field=self.field, year=2024, crop_class=self.wheat, share=1.0)
        with self.assertRaises(IntegrityError), transaction.atomic():
            FieldCropYear.objects.create(field=self.field, year=2023, crop_class=self.wheat, share=1.2)


class RiskTests(FarmTestCase):
    def make_risk(self, offset_days: int, score: float = 0.5) -> Risk:
        return Risk.objects.create(
            field=self.field,
            threat=self.threat,
            date=TODAY + timedelta(days=offset_days),
            score=score,
            explanation={"summary": "test"},
        )

    def test_score_must_be_between_0_and_1(self):
        for bad_score in (-0.1, 1.1):
            with self.subTest(score=bad_score), self.assertRaises(IntegrityError), transaction.atomic():
                self.make_risk(0, score=bad_score)

    def test_one_risk_per_field_threat_and_day(self):
        self.make_risk(0)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.make_risk(0)

    def test_season_so_far_and_coming_days_split_at_today(self):
        for offset in (-3, 0, 1, 7, 8):
            self.make_risk(offset)
        season = sorted(Risk.objects.season_so_far().values_list("date", flat=True))
        coming = sorted(Risk.objects.coming_days().values_list("date", flat=True))
        self.assertEqual(season, [TODAY - timedelta(days=3), TODAY])
        self.assertEqual(coming, [TODAY + timedelta(days=1), TODAY + timedelta(days=7)])

    def test_helpers_work_on_related_managers(self):
        self.make_risk(0)
        self.make_risk(1)
        self.assertEqual(self.field.risks.season_so_far().count(), 1)
        self.assertEqual(self.threat.risks.coming_days().count(), 1)

    def test_update_or_create_overwrites_the_days_risk(self):
        for score in (0.2, 0.9):
            Risk.objects.update_or_create(
                field=self.field, threat=self.threat, date=TODAY, defaults={"score": score, "explanation": {}}
            )
        self.assertEqual(list(Risk.objects.values_list("score", flat=True)), [0.9])

    def test_bulk_upsert_overwrites_existing_rows(self):
        old = self.make_risk(0, score=0.2)
        Risk.objects.bulk_create(
            [
                Risk(field=self.field, threat=self.threat, date=TODAY, score=0.9, explanation={"v": 2}),
                Risk(field=self.field, threat=self.threat, date=TODAY + timedelta(days=1), score=0.4, explanation={}),
            ],
            update_conflicts=True,
            unique_fields=["field", "threat", "date"],
            update_fields=["score", "explanation", "computed_at"],
        )
        old.refresh_from_db()
        self.assertEqual(Risk.objects.count(), 2)
        self.assertEqual((old.score, old.explanation), (0.9, {"v": 2}))



class ObservationTests(FarmTestCase):
    def report(self, **kwargs) -> Observation:
        values = {"field": self.field, "observed_on": TODAY, "kind": Observation.Kind.SYMPTOMS} | kwargs
        return Observation.objects.create(**values)

    def test_a_report_can_be_about_the_whole_farm(self):
        self.assertIsNone(self.report(field=None).field)

    def test_severity_must_be_between_0_and_1(self):
        self.report(severity=0.9)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.report(severity=1.5)

    def test_distance_cannot_be_negative(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.report(kind=Observation.Kind.NEIGHBOUR, distance_m=-1)

    def test_idempotency_key_prevents_duplicates_but_is_optional(self):
        self.report(idempotency_key="abc")
        self.report()  # no key
        self.report()  # several rows without a key are fine
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.report(idempotency_key="abc")

    def test_observed_excludes_reports_after_today(self):
        self.report(observed_on=TODAY - timedelta(days=2))
        self.report(observed_on=TODAY + timedelta(days=1))
        self.assertEqual(Observation.objects.observed().count(), 1)
        self.assertEqual(Observation.objects.observed(as_of=TODAY + timedelta(days=1)).count(), 2)

    def test_deleting_a_threat_keeps_the_report(self):
        threat = Threat.objects.create(
            code="wheat.brown_rust", crop=self.wheat, name="rdza brunatna", category=Threat.Category.FUNGAL, source="test"
        )
        obs = self.report(threat=threat)
        threat.delete()
        obs.refresh_from_db()
        self.assertIsNone(obs.threat)

    def test_field_reports_are_reachable_from_the_field(self):
        self.report()
        self.report(field=None)
        self.assertEqual(self.field.observations.count(), 1)


class SoilBandTests(TestCase):
    def test_bands_store_the_source_text(self):
        SoilCell.objects.create(h3_index_10="8a1e20000000fff", band_ph=SoilCell.Band.MODERATE, clay=0.18)
        cell = SoilCell.objects.get()
        self.assertEqual((cell.band_ph, cell.clay), ("moderate", 0.18))


class AdminSmokeTests(FarmTestCase):
    def test_every_core_admin_page_renders(self):
        user = get_user_model().objects.create_superuser("admin", "admin@example.com", "pw")
        self.client.force_login(user)
        for model in admin.site._registry:
            if model._meta.app_label != "core":
                continue
            name = model._meta.model_name
            with self.subTest(model=name):
                self.assertEqual(self.client.get(reverse(f"admin:core_{name}_changelist")).status_code, 200)
        self.assertEqual(
            self.client.get(reverse("admin:core_field_change", args=[self.field.pk])).status_code, 200
        )
