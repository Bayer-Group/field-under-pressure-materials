"""Tests of the platform API (docs/interfaces.md -> Platform API, docs/archive/implementation-plan.md -> Part A)."""

import tempfile
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse

from core import clock
from core.models import Clock, CropClass, Field, FieldCropYear, Risk, SoilCell, Threat, WeatherGrid

TODAY = date(2024, 5, 15)
HORIZON = TODAY + timedelta(days=clock.FORECAST_DAYS)  # 2024-05-22


def iso(day: date) -> str:
    return day.isoformat()


class ApiTestCase(TestCase):
    """Two crops, two fields, three threats, the clock at TODAY."""

    @classmethod
    def setUpTestData(cls):
        Clock.objects.create(today=TODAY)
        cls.grid = WeatherGrid.objects.create(grid_id="G1", lat=50.0, lon=19.0)
        cls.wheat = CropClass.objects.create(code=CropClass.WHEAT, name="Wheat")
        cls.maize = CropClass.objects.create(code=CropClass.MAIZE, name="Maize")
        cls.no_crop = CropClass.objects.create(code=CropClass.NO_CROPLAND, name="No cropland")
        cls.geometry = {"type": "Polygon", "coordinates": [[[19.0, 50.0], [19.01, 50.0], [19.0, 50.01], [19.0, 50.0]]]}
        cls.field = Field.objects.create(
            name="North field", geometry=cls.geometry, area_ha=20.4, centroid_lat=50.003, centroid_lon=19.003,
            weather_grid=cls.grid, h3_cells=["8a1e20000000fff", "8a1e20000007fff", "8a1e2000000ffff"], crop=cls.wheat,
        )
        cls.other = Field.objects.create(
            name="East field", geometry=cls.geometry, area_ha=5.0, centroid_lat=50.0, centroid_lon=19.1,
            weather_grid=cls.grid, h3_cells=[], crop=cls.maize,
        )
        cls.septoria = cls.threat("wheat.septoria_leaf_blotch", cls.wheat, "septorioza paskowana liści pszenicy")
        cls.rust = cls.threat("wheat.brown_rust", cls.wheat, "rdza brunatna pszenicy")
        cls.borer = cls.threat("maize.european_corn_borer", cls.maize, "omacnica prosowianka", Threat.Category.PEST)

    @classmethod
    def threat(cls, code, crop, name, category=Threat.Category.FUNGAL) -> Threat:
        return Threat.objects.create(code=code, crop=crop, name=name, category=category, source="test")

    def risk(self, field, threat, day, score, explanation=None) -> Risk:
        explanation = explanation if explanation is not None else {"version": 1, "summary": "test"}
        return Risk.objects.create(field=field, threat=threat, date=day, score=score, explanation=explanation)

    def get(self, name, *args, **query):
        return self.client.get(reverse(name, args=args), query)

    def assertDetail(self, response, status: int, detail: str | None = None):
        self.assertEqual(response.status_code, status, response.content)
        self.assertEqual(list(response.json()), ["detail"])
        if detail is not None:
            self.assertEqual(response.json()["detail"], detail)


# --- General rules ----------------------------------------------------------------------------


class GeneralRulesTests(ApiTestCase):
    def test_put_needs_no_csrf_token_while_logged_in_to_admin(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(get_user_model().objects.create_superuser("admin", "a@example.com", "pw"))
        with mock.patch("engine.clock_moved"):
            response = client.put(reverse("clock"), {"today": "2024-05-16"}, content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)

    def test_endpoints_that_need_today_answer_503_without_clock_row(self):
        Clock.objects.all().delete()
        for name, args in [("clock", ()), ("risks", ()), ("field-risks", (self.field.id,)),
                           ("field-day-risks", (self.field.id, iso(TODAY)))]:
            with self.subTest(endpoint=name):
                self.assertDetail(self.get(name, *args), 503, "The demo date is not set: set it in /admin/ or run the seed.")

    def test_endpoints_without_dates_work_without_clock_row(self):
        Clock.objects.all().delete()
        for name, args in [("threats", ()), ("fields", ()), ("field-detail", (self.field.id,))]:
            with self.subTest(endpoint=name):
                self.assertEqual(self.get(name, *args).status_code, 200)


# --- Clock ------------------------------------------------------------------------------------


class ClockApiTests(ApiTestCase):
    def put(self, body):
        return self.client.put(reverse("clock"), body, content_type="application/json")

    def test_get(self):
        self.assertEqual(self.get("clock").json(),
                         {"today": "2024-05-15", "forecast_days": 7, "min_date": None, "max_date": None})

    def test_put_updates_the_date_and_lets_the_engine_recompute(self):
        with mock.patch("engine.clock_moved") as clock_moved:
            response = self.put({"today": "2024-06-01"})
        self.assertEqual(response.json(), {"today": "2024-06-01", "forecast_days": 7, "min_date": None, "max_date": None})
        self.assertEqual(clock.today(), date(2024, 6, 1))
        clock_moved.assert_called_once_with(TODAY, date(2024, 6, 1))

    def test_put_creates_the_row_when_missing(self):
        Clock.objects.all().delete()
        with mock.patch("engine.clock_moved") as clock_moved:
            response = self.put({"today": "2024-06-01"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(clock.today(), date(2024, 6, 1))
        clock_moved.assert_not_called()  # no old date: nothing to recompute

    def test_put_same_date_recomputes_nothing(self):
        with mock.patch("engine.clock_moved") as clock_moved:
            self.assertEqual(self.put({"today": "2024-05-15"}).status_code, 200)
        clock_moved.assert_not_called()

    def test_put_accepts_any_valid_date_without_weather(self):
        with mock.patch("engine.clock_moved"):
            self.assertEqual(self.put({"today": "2031-01-01"}).json()["today"], "2031-01-01")

    def test_put_stays_within_the_days_with_a_forecast(self):
        from core.models import WeatherForecastDaily
        for issued in (date(2023, 9, 1), date(2024, 12, 31)):
            WeatherForecastDaily.objects.create(grid=self.grid, issued_on=issued, date=issued + timedelta(days=1))
        self.assertEqual(self.get("clock").json()["min_date"], "2023-09-01")
        self.assertEqual(self.get("clock").json()["max_date"], "2024-12-31")
        with mock.patch("engine.clock_moved") as clock_moved:
            self.assertDetail(self.put({"today": "0002-05-31"}), 400,
                              "today must be between 2023-09-01 and 2024-12-31 (the days with weather)")
            self.assertEqual(self.put({"today": "2024-12-31"}).status_code, 200)
        clock_moved.assert_called_once()

    def test_iso_weeks_and_basic_dates_are_not_dates(self):
        for value in ("2024-W22-1", "20240601", "2024-06-01T00:00"):
            with self.subTest(value=value):
                self.assertDetail(self.get("risks", date=value), 400, "date must be YYYY-MM-DD")

    def test_unknown_api_paths_answer_json(self):
        for url in ("/api/fields/abc/", "/api/nothing-here/"):
            with self.subTest(url=url):
                self.assertDetail(self.client.get(url), 404, "Not found.")

    def test_form_posts_are_refused(self):
        """No CSRF on the API: a urlencoded body (what a form on another site sends) is refused."""
        response = self.client.put(reverse("clock"), "today=2024-06-01", content_type="application/x-www-form-urlencoded")
        self.assertEqual(response.status_code, 415)
        self.assertEqual(clock.today(), TODAY)

    def test_put_rejects_an_invalid_body(self):
        for body in [{"today": "2024-6-1"}, {"today": "yesterday"}, {"today": 20240601}, {}, ["2024-06-01"]]:
            with self.subTest(body=body):
                self.assertDetail(self.put(body), 400, "today must be YYYY-MM-DD")
        self.assertEqual(clock.today(), TODAY)

    def test_engine_failure_keeps_the_old_date(self):
        with mock.patch("engine.clock_moved", side_effect=RuntimeError("engine down")):
            with self.assertRaises(RuntimeError):
                self.put({"today": "2024-06-01"})
        self.assertEqual(clock.today(), TODAY)

    def test_the_real_engine_runs_on_put(self):
        # no weather in the test database: the engine computes nothing, but the call must not fail
        self.assertEqual(self.put({"today": "2024-05-16"}).status_code, 200)

    def test_admin_clock_page_also_lets_the_engine_recompute(self):
        self.client.force_login(get_user_model().objects.create_superuser("admin", "a@example.com", "pw"))
        with mock.patch("engine.clock_moved") as clock_moved:
            response = self.client.post(reverse("admin:core_clock_change", args=[1]), {"today": "2024-05-20"})
        self.assertEqual(response.status_code, 302, response.content)
        self.assertEqual(clock.today(), date(2024, 5, 20))
        clock_moved.assert_called_once_with(TODAY, date(2024, 5, 20))

    def test_admin_can_add_the_clock_when_missing(self):
        Clock.objects.all().delete()
        self.client.force_login(get_user_model().objects.create_superuser("admin", "a@example.com", "pw"))
        with mock.patch("engine.clock_moved") as clock_moved:
            response = self.client.post(reverse("admin:core_clock_add"), {"today": "2024-05-20"})
        self.assertEqual(response.status_code, 302, response.content)
        self.assertEqual(clock.today(), date(2024, 5, 20))
        clock_moved.assert_not_called()


# --- Threats ----------------------------------------------------------------------------------


class ThreatApiTests(ApiTestCase):
    def test_shape_and_order_by_crop_then_code(self):
        self.assertEqual(
            self.get("threats").json(),
            [
                {"code": "wheat.brown_rust", "name": "rdza brunatna pszenicy",
                 "crop": {"code": 1110, "name": "Wheat"}, "category": "fungal"},
                {"code": "wheat.septoria_leaf_blotch", "name": "septorioza paskowana liści pszenicy",
                 "crop": {"code": 1110, "name": "Wheat"}, "category": "fungal"},
                {"code": "maize.european_corn_borer", "name": "omacnica prosowianka",
                 "crop": {"code": 1130, "name": "Maize"}, "category": "pest"},
            ],
        )


# --- Fields -----------------------------------------------------------------------------------


class FieldApiTests(ApiTestCase):
    def test_list_is_a_geojson_feature_collection(self):
        data = self.get("fields").json()
        self.assertEqual(data["type"], "FeatureCollection")
        self.assertEqual(
            data["features"][0],
            {
                "type": "Feature",
                "id": self.field.id,
                "geometry": self.geometry,
                "properties": {"id": self.field.id, "name": "North field",
                               "crop": {"code": 1110, "name": "Wheat"}, "area_ha": 20.4},
            },
        )
        self.assertEqual([f["id"] for f in data["features"]], [self.field.id, self.other.id])

    def test_detail_shape(self):
        data = self.get("field-detail", self.field.id).json()
        self.assertEqual(
            {k: v for k, v in data.items() if k not in {"crop_history", "soil"}},
            {"id": self.field.id, "name": "North field", "crop": {"code": 1110, "name": "Wheat"}, "area_ha": 20.4,
             "centroid": {"lat": 50.003, "lon": 19.003}, "weather_grid_id": "G1"},
        )

    def test_crop_history_by_year_then_share(self):
        for year, crop, share in [(2023, self.no_crop, 0.08), (2023, self.maize, 0.92), (2022, self.wheat, 1.0)]:
            FieldCropYear.objects.create(field=self.field, year=year, crop_class=crop, share=share)
        self.assertEqual(
            self.get("field-detail", self.field.id).json()["crop_history"],
            [
                {"year": 2022, "classes": [{"code": 1110, "name": "Wheat", "share": 1.0}]},
                {"year": 2023, "classes": [{"code": 1130, "name": "Maize", "share": 0.92},
                                           {"code": 0, "name": "No cropland", "share": 0.08}]},
            ],
        )

    def test_soil_is_the_average_of_the_cells_with_the_most_common_texture(self):
        cells = [("8a1e20000000fff", 6.0, 0.10, "silt loam"), ("8a1e20000007fff", 7.0, 0.20, "loam"),
                 ("8a1e2000000ffff", 6.5, 0.30, "silt loam")]
        for h3, ph, clay, texture in cells:
            SoilCell.objects.create(h3_index_10=h3, ph=ph, clay=clay, sand=0.3, silt=0.5, om=24.0,
                                    bulk_density=1.3, soil_texture=texture)  # cec null in every cell
        SoilCell.objects.create(h3_index_10="8a1e20000017fff", ph=1.0, soil_texture="clay")  # not under the field
        soil = self.get("field-detail", self.field.id).json()["soil"]
        self.assertEqual(set(soil), {"ph", "soil_texture", "clay", "sand", "silt", "om", "cec", "bulk_density"})
        self.assertAlmostEqual(soil["ph"], 6.5)
        self.assertAlmostEqual(soil["clay"], 0.2)
        self.assertIsNone(soil["cec"])
        self.assertEqual(soil["soil_texture"], "silt loam")

    def test_texture_tie_is_broken_alphabetically_and_missing_textures_are_null(self):
        SoilCell.objects.create(h3_index_10="8a1e20000000fff", soil_texture="silt loam")
        SoilCell.objects.create(h3_index_10="8a1e20000007fff", soil_texture="loam")
        self.assertEqual(self.get("field-detail", self.field.id).json()["soil"]["soil_texture"], "loam")
        SoilCell.objects.update(soil_texture=None)
        self.assertIsNone(self.get("field-detail", self.field.id).json()["soil"]["soil_texture"])

    def test_soil_is_null_without_cells(self):
        self.assertIsNone(self.get("field-detail", self.other.id).json()["soil"])

    def test_unknown_field_is_404(self):
        self.assertDetail(self.get("field-detail", 999), 404, "field 999 not found")


# --- Risks ------------------------------------------------------------------------------------


class DayRisksApiTests(ApiTestCase):
    def test_every_fields_risks_on_the_day_with_level(self):
        self.risk(self.field, self.septoria, TODAY, 0.72, {"version": 1, "level": "high"})
        self.risk(self.field, self.rust, TODAY, 0.5, {"version": 1, "level": "medium"})
        self.risk(self.other, self.borer, TODAY, 0.1, {"version": 1, "level": "low"})
        self.risk(self.field, self.septoria, TODAY - timedelta(days=1), 0.9)  # another day
        self.assertEqual(
            self.get("risks", date=iso(TODAY)).json(),
            {"date": "2024-05-15", "risks": [
                {"field_id": self.field.id, "threat_code": "wheat.brown_rust", "score": 0.5, "level": "medium"},
                {"field_id": self.field.id, "threat_code": "wheat.septoria_leaf_blotch", "score": 0.72, "level": "high"},
                {"field_id": self.other.id, "threat_code": "maize.european_corn_borer", "score": 0.1, "level": "low"},
            ]},
        )

    def test_level_is_copied_from_the_explanation_not_recomputed(self):
        self.risk(self.field, self.septoria, TODAY, 0.9, {"version": 1, "level": "medium"})
        self.assertEqual(self.get("risks").json()["risks"][0]["level"], "medium")

    def test_level_falls_back_to_the_cut_offs_without_explanation_level(self):
        for threat, score in [(self.septoria, 0.329), (self.rust, 0.33)]:
            self.risk(self.field, threat, TODAY, score, {"summary": "toy row"})
        self.risk(self.other, self.borer, TODAY, 0.66, {"level": "unknown"})
        levels = [r["level"] for r in self.get("risks").json()["risks"]]
        self.assertEqual(levels, ["medium", "low", "high"])  # brown_rust 0.33, septoria 0.329, borer 0.66

    def test_date_defaults_to_today(self):
        self.risk(self.field, self.septoria, TODAY, 0.5)
        data = self.get("risks").json()
        self.assertEqual((data["date"], len(data["risks"])), ("2024-05-15", 1))

    def test_a_day_without_rows_is_an_empty_list(self):
        self.assertEqual(self.get("risks", date="2024-01-01").json(), {"date": "2024-01-01", "risks": []})

    def test_cut_off_at_today_plus_7(self):
        self.risk(self.field, self.septoria, HORIZON, 0.5)
        self.assertEqual(len(self.get("risks", date=iso(HORIZON)).json()["risks"]), 1)
        self.assertDetail(self.get("risks", date=iso(HORIZON + timedelta(days=1))), 400, "date is after today + 7")

    def test_moving_the_clock_moves_the_limit(self):
        later = HORIZON + timedelta(days=1)
        self.assertEqual(self.get("risks", date=iso(later)).status_code, 400)
        Clock(today=TODAY + timedelta(days=1)).save()
        self.assertEqual(self.get("risks", date=iso(later)).status_code, 200)

    def test_malformed_date_is_400(self):
        for value in ["2024-5-15", "15.05.2024", "tomorrow"]:
            with self.subTest(value=value):
                self.assertDetail(self.get("risks", date=value), 400, "date must be YYYY-MM-DD")


class FieldRiskSeriesApiTests(ApiTestCase):
    def setUp(self):
        for offset in (-300, -1, 0, 7, 8, 30):  # 8 and 30 are after the horizon: precomputed, never shown
            day = TODAY + timedelta(days=offset)
            self.risk(self.field, self.septoria, day, 0.4)
            self.risk(self.field, self.rust, day, 0.6)
        self.risk(self.other, self.borer, TODAY, 0.2)

    def test_shape_threats_by_code_points_by_date(self):
        data = self.get("field-risks", self.field.id, **{"from": "2024-05-14", "to": "2024-05-15"}).json()
        self.assertEqual(
            data,
            {"field_id": self.field.id, "from": "2024-05-14", "to": "2024-05-15", "threats": [
                {"threat_code": "wheat.brown_rust",
                 "points": [{"date": "2024-05-14", "score": 0.6}, {"date": "2024-05-15", "score": 0.6}]},
                {"threat_code": "wheat.septoria_leaf_blotch",
                 "points": [{"date": "2024-05-14", "score": 0.4}, {"date": "2024-05-15", "score": 0.4}]},
            ]},
        )

    def test_defaults_cover_the_season_and_never_pass_today_plus_7(self):
        data = self.get("field-risks", self.field.id).json()
        self.assertEqual((data["from"], data["to"]), ("2023-09-01", iso(HORIZON)))
        dates = [p["date"] for p in data["threats"][0]["points"]]
        self.assertEqual(dates, [iso(TODAY - timedelta(days=d)) for d in (1, 0)] + [iso(HORIZON)])

    def test_default_from_is_1_september_of_the_year_before(self):
        start = TODAY - timedelta(days=300)  # 2023-07-20: before 1 September
        self.assertEqual(start, date(2023, 7, 20))
        data = self.get("field-risks", self.field.id).json()
        self.assertNotIn(iso(start), [p["date"] for p in data["threats"][0]["points"]])
        data = self.get("field-risks", self.field.id, **{"from": iso(start)}).json()
        self.assertEqual(data["threats"][0]["points"][0]["date"], iso(start))

    def test_to_is_cut_at_today_plus_7_and_reported(self):
        data = self.get("field-risks", self.field.id, to="2024-12-31").json()
        self.assertEqual(data["to"], iso(HORIZON))
        self.assertEqual(data["threats"][0]["points"][-1]["date"], iso(HORIZON))

    def test_moving_the_clock_moves_the_limit(self):
        Clock(today=TODAY + timedelta(days=1)).save()
        data = self.get("field-risks", self.field.id, to="2024-12-31").json()
        self.assertEqual(data["to"], iso(HORIZON + timedelta(days=1)))
        self.assertEqual(data["threats"][0]["points"][-1]["date"], iso(TODAY + timedelta(days=8)))

    def test_from_is_never_before_the_previous_season(self):
        data = self.get("field-risks", self.field.id, **{"from": "0001-01-01"}).json()
        self.assertEqual(data["from"], "2022-09-01")

    def test_default_from_in_autumn_keeps_this_years_late_crops(self):
        Clock(today=date(2024, 10, 15)).save()
        self.assertEqual(self.get("field-risks", self.field.id).json()["from"], "2024-01-01")

    def test_bad_ranges_are_400(self):
        cases = [({"from": "2024-05-10", "to": "2024-05-01"}, "from is after to"),
                 ({"to": "2023-01-01"}, "to is before the default from (2023-09-01)"),
                 ({"from": iso(HORIZON + timedelta(days=1))}, "from is after today + 7"),
                 ({"from": "2024-13-01"}, "from must be YYYY-MM-DD"),
                 ({"to": "soon"}, "to must be YYYY-MM-DD")]
        for query, detail in cases:
            with self.subTest(query=query):
                self.assertDetail(self.get("field-risks", self.field.id, **query), 400, detail)

    def test_a_range_without_rows_is_an_empty_list(self):
        data = self.get("field-risks", self.field.id, **{"from": "2024-01-01", "to": "2024-01-31"}).json()
        self.assertEqual(data["threats"], [])

    def test_unknown_field_is_404(self):
        self.assertDetail(self.get("field-risks", 999), 404, "field 999 not found")


class FieldDayRisksApiTests(ApiTestCase):
    EXPLANATION = {
        "version": 1, "summary": "Wysokie ryzyko…", "level": "high", "score": 0.72,
        "drivers": [{"factor": "condition_hours", "label": "Godziny…", "effect": 0.72}],
        "action": {"type": "treat", "text": "Obejrzyj pole.", "spray_window": {"date": "2024-05-17"}},
        "future_key": {"nested": [1, 2]},
    }

    def test_highest_score_first_with_explanation_unchanged(self):
        self.risk(self.field, self.rust, TODAY, 0.3)
        self.risk(self.field, self.septoria, TODAY, 0.72, self.EXPLANATION)
        self.risk(self.other, self.borer, TODAY, 0.99)  # another field
        data = self.get("field-day-risks", self.field.id, iso(TODAY)).json()
        self.assertEqual((data["field_id"], data["date"]), (self.field.id, "2024-05-15"))
        self.assertEqual(
            data["risks"][0],
            {"threat": {"code": "wheat.septoria_leaf_blotch", "name": "septorioza paskowana liści pszenicy",
                        "category": "fungal"},
             "score": 0.72, "explanation": self.EXPLANATION},
        )
        self.assertEqual([r["threat"]["code"] for r in data["risks"]],
                         ["wheat.septoria_leaf_blotch", "wheat.brown_rust"])

    def test_a_day_without_rows_is_an_empty_list(self):
        self.assertEqual(self.get("field-day-risks", self.field.id, iso(TODAY)).json()["risks"], [])

    def test_cut_off_at_today_plus_7(self):
        self.assertEqual(self.get("field-day-risks", self.field.id, iso(HORIZON)).status_code, 200)
        self.assertDetail(self.get("field-day-risks", self.field.id, iso(HORIZON + timedelta(days=1))), 400,
                          "date is after today + 7")

    def test_malformed_date_is_400(self):
        self.assertDetail(self.get("field-day-risks", self.field.id, "2024-5-15"), 400, "date must be YYYY-MM-DD")

    def test_unknown_field_is_404(self):
        self.assertDetail(self.get("field-day-risks", 999, iso(TODAY)), 404, "field 999 not found")


# --- Schema file ------------------------------------------------------------------------------


class SchemaFileTests(TestCase):
    """frontend/openapi.yml is committed; the TypeScript types are generated from it (npm run api:types)."""

    def test_committed_schema_matches_the_code(self):
        committed = Path(settings.BASE_DIR) / "frontend" / "openapi.yml"
        with tempfile.TemporaryDirectory() as tmp:
            fresh = Path(tmp) / "openapi.yml"
            call_command("spectacular", "--file", str(fresh), "--validate", "--fail-on-warn")
            self.assertTrue(committed.exists(), "frontend/openapi.yml is missing")
            self.assertEqual(
                committed.read_text(encoding="utf-8"),
                fresh.read_text(encoding="utf-8"),
                "frontend/openapi.yml is stale. Run: python manage.py spectacular --file frontend/openapi.yml, "
                "then cd frontend && npm run api:types",
            )
