"""
Testy jednostkowe i integracyjne modułu `scenarios`.

Weryfikują poprawność parsowania definicji JSON, izolację czyszczenia danych
scenariuszowych, generowanie prognoz 7-dniowych, ustawianie `core.Clock`
oraz działanie komendy CLI `python manage.py scenario`.
"""

from __future__ import annotations

import io
import json
import tempfile
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from assistant.models import Conversation, Message
from core import clock
from core.models import (
    CropClass,
    Field,
    Observation,
    Risk,
    Threat,
    WeatherDaily,
    WeatherForecastDaily,
    WeatherGrid,
    WeatherHourly,
)
from scenarios.exceptions import DataSourceError, ScenarioValidationError
from scenarios.loaders import ReferenceDataLoader, WeatherAndForecastLoader
from scenarios.manager import ScenarioManager, ScenarioRepository
from scenarios.schema import ScenarioParser, SwitchOptions


def _sample_polygon() -> dict:
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [17.640, 50.365],
                [17.648, 50.365],
                [17.648, 50.370],
                [17.640, 50.370],
                [17.640, 50.365],
            ]
        ],
    }


def _sample_scenario_payload() -> dict:
    return {
        "title": "Testowy scenariusz",
        "description": "Opis testowy",
        "region": "Opolskie",
        "window": {
            "season": 2025,
            "season_start": "2025-05-01",
            "season_end": "2025-05-20",
            "clock_today": "2025-05-10",
            "include_previous_season": False,
        },
        "fields": [
            {
                "name": "Pole Testowe 1",
                "crop_code": CropClass.WHEAT,
                "geometry": _sample_polygon(),
            }
        ],
        "observations": [
            {
                "kind": "symptoms",
                "observed_on": "2025-05-09",
                "field_name": "Pole Testowe 1",
                "category": "disease",
                "threat_code": "wheat.septoria_leaf_blotch",
                "severity": 0.8,
                "text": "Plamy na liściach.",
            }
        ],
    }


class ScenarioParserTests(TestCase):
    """Testy walidacji schematu JSON oraz wykrywania błędnych konfiguracji."""

    def test_valid_scenario_parses_correctly(self) -> None:
        """Poprawny słownik/plik JSON buduje obiekt `ScenarioDefinition` z właściwymi typami."""
        definition = ScenarioParser.from_dict(_sample_scenario_payload(), slug="unit_test_case")

        self.assertEqual(definition.slug, "unit_test_case")
        self.assertEqual(definition.window.clock_today, date(2025, 5, 10))
        self.assertFalse(definition.window.include_previous_season)
        self.assertEqual(len(definition.fields), 1)
        self.assertEqual(definition.fields[0].crop_code, CropClass.WHEAT)
        self.assertEqual(len(definition.observations), 1)
        self.assertEqual(definition.observations[0].severity, 0.8)

    def test_invalid_dates_raise_validation_error(self) -> None:
        """Niespójne okno czasowe (`clock_today` poza zakresem sezonu) rzuca `ScenarioValidationError`."""
        payload = _sample_scenario_payload()
        payload["window"]["clock_today"] = "2025-08-01"

        with self.assertRaises(ScenarioValidationError):
            ScenarioParser.from_dict(payload, slug="invalid_clock")

    def test_observation_referencing_unknown_field_raises_validation_error(self) -> None:
        """Obserwacja wskazująca nieistniejące pole rzuca `ScenarioValidationError`."""
        payload = _sample_scenario_payload()
        payload["observations"][0]["field_name"] = "Nieistniejące Pole"

        with self.assertRaises(ScenarioValidationError):
            ScenarioParser.from_dict(payload, slug="unknown_field_obs")

    def test_apply_overrides_updates_clock_today_and_validates(self) -> None:
        """Metoda `apply_overrides` aktualizuje `clock_today` i odrzuca datę spoza okna."""
        definition = ScenarioParser.from_dict(_sample_scenario_payload(), slug="override_test")

        updated = ScenarioParser.apply_overrides(
            definition, SwitchOptions(today_override=date(2025, 5, 15))
        )
        self.assertEqual(updated.window.clock_today, date(2025, 5, 15))

        with self.assertRaises(ScenarioValidationError):
            ScenarioParser.apply_overrides(
                definition, SwitchOptions(today_override=date(2025, 4, 15))
            )


class WeatherForecastGeneratorTests(TestCase):
    """Testy tworzenia prognozy 7-dniowej (`WeatherForecastDaily`) z danych obserwowanych."""

    def test_forecast_copies_next_seven_days_and_imerg_rain(self) -> None:
        """Dla dnia D powstają rekordy D+1..D+7, a opad IMERG trafia do `total_precipitation`."""
        grid = WeatherGrid.objects.create(grid_id="g_test_1", lat=50.36, lon=17.64)
        base_day = date(2025, 5, 1)

        for offset in range(10):
            day = base_day + timedelta(days=offset)
            WeatherDaily.objects.create(
                grid=grid,
                date=day,
                avg_temperature=15.0 + offset,
                total_precipitation=None,
                imerg_total_precipitation=2.5 * offset,
            )

        loader = WeatherAndForecastLoader(data_dir=Path("/nonexistent"))
        created_count = loader.generate_forecast_series(
            grid_ids=[grid.grid_id],
            start=base_day,
            end=base_day + timedelta(days=1),
        )

        self.assertEqual(created_count, 14)  # 2 dni emisji * 7 dni prognozy
        day_plus_3 = WeatherForecastDaily.objects.get(
            grid=grid, issued_on=base_day, date=base_day + timedelta(days=3)
        )
        self.assertEqual(day_plus_3.avg_temperature, 18.0)
        self.assertEqual(day_plus_3.total_precipitation, 7.5)


class ScenarioSwitchIntegrationTests(TestCase):
    """Testy pełnego przełączania scenariuszy z wykorzystaniem trybu syntetycznego."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)

        self.defs_dir = Path(self.tmp_dir.name) / "definitions"
        self.defs_dir.mkdir(parents=True, exist_ok=True)
        self.empty_data_dir = Path(self.tmp_dir.name) / "data"
        self.empty_data_dir.mkdir(parents=True, exist_ok=True)

        # Przygotuj katalog zagrożeń w bazie testowej, aby uniknąć zależności od zewnętrznego pliku XLSX
        wheat_class, _ = CropClass.objects.update_or_create(
            code=CropClass.WHEAT, defaults={"name": "Wheat"}
        )
        self.threat, _ = Threat.objects.update_or_create(
            code="wheat.septoria_leaf_blotch",
            defaults={
                "crop": wheat_class,
                "name": "septorioza paskowana liści pszenicy",
                "category": Threat.Category.FUNGAL,
                "source": "test",
            },
        )

        (self.defs_dir / "case_a.json").write_text(
            json.dumps(_sample_scenario_payload()), encoding="utf-8"
        )

        payload_b = _sample_scenario_payload()
        payload_b["title"] = "Scenariusz B"
        payload_b["window"]["clock_today"] = "2025-05-12"
        payload_b["fields"][0]["name"] = "Pole Testowe B"
        payload_b["observations"][0]["field_name"] = "Pole Testowe B"
        (self.defs_dir / "case_b.json").write_text(json.dumps(payload_b), encoding="utf-8")

        ref_loader = ReferenceDataLoader(data_dir=self.empty_data_dir)
        self.manager = ScenarioManager(
            repository=ScenarioRepository(definitions_dir=self.defs_dir),
            reference_loader=ref_loader,
        )
        self.manager.field_loader.data_dir = self.empty_data_dir
        self.manager.weather_loader.data_dir = self.empty_data_dir

    @patch("engine.precompute_season", return_value=20)
    @patch("scenarios.loaders.call_command")
    def test_switch_replaces_fields_and_preserves_reference_tables(
        self, _mock_call_command, mock_precompute
    ) -> None:
        """Przełączenie scenariusza usuwa stare pola i obserwacje, ale zachowuje `CropClass` i `Threat`."""
        report_a = self.manager.switch_to("case_a", options=SwitchOptions(allow_synthetic_fallback=True))
        self.assertEqual(report_a.fields_created, 1)
        self.assertEqual(report_a.risk_rows_written, 20)
        self.assertEqual(Field.objects.count(), 1)
        self.assertEqual(Field.objects.first().name, "Pole Testowe 1")
        mock_precompute.assert_called_once_with(season=2025)

        # Dodaj sztuczny wiersz Risk oraz rozmowę czatu przed przełączeniem na case_b
        fld = Field.objects.first()
        Risk.objects.create(
            field=fld,
            threat=self.threat,
            date=date(2025, 5, 10),
            score=0.5,
            explanation={"version": 1, "level": "medium"},
        )
        conv = Conversation.objects.create(title="Stara rozmowa")
        Message.objects.create(conversation=conv, role="user", text="Cześć")

        report_b = self.manager.switch_to(
            "case_b",
            options=SwitchOptions(reset_chat=True, allow_synthetic_fallback=True),
        )

        self.assertEqual(report_b.scenario_slug, "case_b")
        self.assertEqual(Field.objects.count(), 1)
        self.assertEqual(Field.objects.first().name, "Pole Testowe B")
        self.assertEqual(Observation.objects.count(), 1)
        self.assertEqual(Risk.objects.count(), 0)
        self.assertEqual(Conversation.objects.count(), 0)
        self.assertEqual(CropClass.objects.count(), 21)
        self.assertTrue(Threat.objects.filter(code="wheat.septoria_leaf_blotch").exists())
        self.assertEqual(mock_precompute.call_count, 2)

    @patch("scenarios.loaders.call_command")
    def test_switch_fails_by_default_when_data_dir_files_are_missing(self, _mock_call_command) -> None:
        """Domyślnie (bez flagi fallbacku) brak plików w `DATA_DIR` rzuca `DataSourceError`."""
        with self.assertRaises(DataSourceError):
            self.manager.switch_to("case_a")

    @patch("engine.precompute_season", return_value=20)
    @patch("scenarios.loaders.call_command")
    def test_switch_sets_clock_and_respects_today_override(
        self, _mock_call_command, _mock_precompute
    ) -> None:
        """Zegar `core.Clock` ustawia się na datę ze scenariusza lub parametr `--today`."""
        self.manager.switch_to("case_a", options=SwitchOptions(allow_synthetic_fallback=True))
        self.assertEqual(clock.today(), date(2025, 5, 10))

        self.manager.switch_to(
            "case_a",
            options=SwitchOptions(today_override=date(2025, 5, 18), allow_synthetic_fallback=True),
        )
        self.assertEqual(clock.today(), date(2025, 5, 18))

    @patch("engine.precompute_season", return_value=10)
    @patch("scenarios.loaders.call_command")
    def test_cli_list_status_and_switch_commands(self, _mock_call_command, _mock_precompute) -> None:
        """Komenda `python manage.py scenario` poprawnie obsługuje `list`, `validate`, `switch` i `status`."""
        from scenarios.management.commands.scenario import Command as ScenarioCommand

        cmd = ScenarioCommand(manager=self.manager)
        out = io.StringIO()
        cmd.stdout = out

        call_command(cmd, "list")
        self.assertIn("case_a", out.getvalue())

        out.truncate(0)
        out.seek(0)
        call_command(cmd, "validate", "case_a")
        self.assertIn("jest poprawny", out.getvalue())

        out.truncate(0)
        out.seek(0)
        call_command(cmd, "switch", "case_a", "--today", "2025-05-14", "--allow-synthetic-fallback")
        self.assertIn("Clock.today = 2025-05-14", out.getvalue())

        out.truncate(0)
        out.seek(0)
        call_command(cmd, "status")
        self.assertIn("2025-05-14", out.getvalue())

class AuditFixTests(TestCase):
    """Fixes from docs/audit-2026-11-21.md: validation (E-16j), weather overrides (E-5), synthetic data (R-4),
    the year check (E-16l), --keep-weather after overridden weather (E-10)."""

    def assert_invalid(self, payload: dict, slug: str) -> None:
        with self.assertRaises(ScenarioValidationError):
            ScenarioParser.from_dict(payload, slug=slug)

    def test_window_and_observations_are_checked(self) -> None:
        p = _sample_scenario_payload()
        p["window"]["season"] = 2026  # 1 May 2025 belongs to season 2025
        self.assert_invalid(p, "season")
        p = _sample_scenario_payload()
        p["window"]["include_previous_season"] = "false"
        self.assert_invalid(p, "string_bool")
        p = _sample_scenario_payload()
        p["observations"][0]["observed_on"] = "2025-05-11"  # after clock_today
        self.assert_invalid(p, "future_report")
        p = _sample_scenario_payload()
        p["observations"][0]["threat_code"] = "wheat.no_such_threat"
        self.assert_invalid(p, "unknown_threat")
        p = _sample_scenario_payload()
        p["observations"][0]["threat_code"] = "maize.european_corn_borer"  # a maize pest on a wheat field
        self.assert_invalid(p, "wrong_crop")
        p = _sample_scenario_payload()
        p["fields"][0]["crop_code"] = 2100  # vineyards: no engine rules
        self.assert_invalid(p, "no_rules")

    def test_weather_overrides_are_checked(self) -> None:
        for override in ({"start_date": "2025-05-03", "end_date": "2025-05-01", "values": {"avg_temperature": 15}},
                         {"start_date": "2025-5-1", "values": {"avg_temperature": 15}},
                         {"start_date": "2025-05-01", "values": {"no_such_column": 1}}):
            p = _sample_scenario_payload()
            p["weather_overrides"] = [override]
            self.assert_invalid(p, "override")

    def test_an_override_shifts_the_hours_instead_of_flattening_them(self) -> None:
        """E-5: a flat 18.5 °C all day was outside septoria's 4-18 °C, so the "outbreak week" had no infection hours."""
        from datetime import datetime, timezone as tz
        grid = WeatherGrid.objects.create(grid_id="g_override", lat=50.0, lon=17.0)
        day = date(2025, 6, 10)
        WeatherDaily.objects.create(grid=grid, date=day, avg_temperature=20.0, avg_relative_humidity=60.0,
                                    min_temperature=14.0, max_temperature=26.0, imerg_total_precipitation=0.0)
        for h in range(24):
            WeatherHourly.objects.create(grid=grid, date=day, utc_time=datetime(2025, 6, 10, h, tzinfo=tz.utc),
                                         temperature=20.0 + (6 if 10 <= h <= 16 else -3), relative_humidity=60.0,
                                         imerg_precipitation=0.0)
        override = [{"start_date": "2025-06-10", "values": {"avg_temperature": 15.5, "avg_relative_humidity": 91.0,
                                                            "imerg_total_precipitation": 12.0}}]
        WeatherAndForecastLoader._apply_weather_overrides(["g_override"], override)
        temps = list(WeatherHourly.objects.filter(grid=grid).values_list("temperature", flat=True))
        self.assertEqual(max(temps) - min(temps), 9.0)  # the daily cycle is kept
        self.assertAlmostEqual(min(temps), 17.0 - 4.5, places=2)  # every hour moves by the same 4.5 °C
        self.assertEqual(max(WeatherHourly.objects.filter(grid=grid).values_list("relative_humidity", flat=True)), 91.0)
        rain = sum(WeatherHourly.objects.filter(grid=grid).values_list("imerg_precipitation", flat=True))
        self.assertAlmostEqual(rain, 12.0, places=2)
        d = WeatherDaily.objects.get(grid=grid, date=day)
        self.assertEqual((d.avg_temperature, d.min_temperature, d.max_temperature), (15.5, 9.5, 21.5))
        # applying the same override again changes nothing
        WeatherAndForecastLoader._apply_weather_overrides(["g_override"], override)
        self.assertEqual(sorted(WeatherHourly.objects.filter(grid=grid).values_list("temperature", flat=True)), sorted(temps))

    def test_one_leftover_row_is_not_a_loaded_year(self) -> None:
        """E-16l: a year with a single stored day is loaded again, not taken as complete."""
        grid = WeatherGrid.objects.create(grid_id="g_partial", lat=50.0, lon=17.0)
        WeatherDaily.objects.create(grid=grid, date=date(2024, 1, 1), avg_temperature=1.0)
        loader = WeatherAndForecastLoader(data_dir=Path(tempfile.mkdtemp()))
        with patch.object(loader, "_try_load_grid_from_archives", return_value=False) as load, \
                patch.object(loader, "_generate_synthetic_weather") as synth:
            loader.load_observed_weather(["g_partial"], "Opolskie", [2024], allow_fallback=True)
        load.assert_called_once()
        synth.assert_called_once()
        from scenarios.loaders import SYNTHETIC_USED
        self.assertIn("pogoda", SYNTHETIC_USED)  # reported by `scenario switch` as synthetic data (R-4)

    def test_keep_weather_is_ignored_after_a_scenario_that_overrode_the_weather(self) -> None:
        """E-10: the previous scenario's heat wave must not stay in the next one's weather."""
        from scenarios import manager as M
        state = Path(tempfile.mkdtemp()) / "state.json"
        with patch.object(M, "_state_path", return_value=state):
            M._write_state({"slug": "hot", "weather_overrides": True})
            self.assertEqual(M._read_state()["slug"], "hot")
            state.write_text("not json")
            self.assertEqual(M._read_state(), {})  # a broken file never stops a switch
