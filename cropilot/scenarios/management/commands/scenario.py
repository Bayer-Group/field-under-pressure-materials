"""
Cienka komenda Django CLI delegująca operacje do pakietu `scenarios`.

Przykłady użycia:
    python manage.py scenario list
    python manage.py scenario status
    python manage.py scenario validate wheat_septoria_outbreak
    python manage.py scenario switch wheat_septoria_outbreak --today 2025-06-15 --reset-chat
"""

from __future__ import annotations

from datetime import date
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from scenarios.exceptions import ScenarioError
from scenarios.manager import ScenarioManager
from scenarios.schema import SwitchOptions


class Command(BaseCommand):
    """Interfejs wiersza poleceń do zarządzania przypadkami testowymi symulacji."""

    help = "Zarządza scenariuszami symulacji (list, status, validate, switch)."

    def __init__(self, *args: Any, manager: ScenarioManager | None = None, **kwargs: Any) -> None:
        """Inicjalizuje komendę z opcjonalnym wstrzyknięciem `ScenarioManager`.

        Args:
            *args: Pozycyjne argumenty przekazywane do `BaseCommand`.
            manager: Opcjonalna instancja `ScenarioManager` (ułatwia testowanie).
            **kwargs: Nazwane argumenty przekazywane do `BaseCommand`.
        """
        super().__init__(*args, **kwargs)
        self.manager = manager or ScenarioManager()

    def add_arguments(self, parser: CommandParser) -> None:
        """Definiuje podkomendy CLI: `list`, `status`, `validate`, `switch` oraz ich flagi.

        Args:
            parser: Główny parser argumentów Django `BaseCommand`.
        """
        subparsers = parser.add_subparsers(dest="subcommand", required=True, help="Dostępne akcje")

        subparsers.add_parser("list", help="Wyświetla listę dostępnych scenariuszy.")
        subparsers.add_parser("status", help="Wyświetla aktualny stan bazy danych i zegara symulacji.")

        validate_parser = subparsers.add_parser(
            "validate", help="Waliduje plik definicji wskazanego scenariusza bez modyfikacji bazy."
        )
        validate_parser.add_argument("slug", type=str, help="Identyfikator scenariusza (nazwa pliku bez .json).")

        switch_parser = subparsers.add_parser(
            "switch", help="Przełącza bazę danych na wybrany scenariusz testowy."
        )
        switch_parser.add_argument("slug", type=str, help="Identyfikator scenariusza (nazwa pliku bez .json).")
        switch_parser.add_argument(
            "--today",
            type=str,
            default=None,
            help="Nadpisuje początkową datę zegara symulacji (format YYYY-MM-DD).",
        )
        switch_parser.add_argument(
            "--keep-weather",
            action="store_true",
            help="Zachowuje istniejące rekordy WeatherDaily i WeatherHourly, jeśli pokrywają lata scenariusza.",
        )
        switch_parser.add_argument(
            "--reset-chat",
            action="store_true",
            help="Czyści historię konwersacji asystenta AI (assistant.Conversation i Message).",
        )
        switch_parser.add_argument(
            "--skip-predict",
            action="store_true",
            help="Pomija uruchomienie engine.precompute_season() po załadowaniu danych wejściowych.",
        )
        switch_parser.add_argument(
            "--allow-synthetic-fallback",
            action="store_true",
            help="Włącza generator syntetyczny w razie braku wymaganych plików źródłowych w DATA_DIR.",
        )
        switch_parser.add_argument(
            "--strict-data",
            action="store_true",
            help="Bez danych syntetycznych (domyślnie i tak). Zostaje, bo używają go README, skrypt demo i start.sh.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        """Kieruje wywołanie do odpowiedniej metody obsługującej wybraną podkomendę.

        Args:
            *args: Nieużywane argumenty pozycyjne.
            **options: Sparsowane argumenty i flagi z linii poleceń.

        Raises:
            CommandError: Gdy wystąpi błąd walidacji, brak pliku scenariusza lub błąd danych.
        """
        subcommand = options["subcommand"]
        try:
            if subcommand == "list":
                self._handle_list()
            elif subcommand == "status":
                self._handle_status()
            elif subcommand == "validate":
                self._handle_validate(slug=options["slug"])
            elif subcommand == "switch":
                self._handle_switch(options)
            else:
                raise CommandError(f"Nieznana podkomenda: {subcommand}")
        except ScenarioError as exc:
            raise CommandError(str(exc)) from exc

    def _handle_list(self) -> None:
        """Wypisuje tabelę dostępnych scenariuszy z katalogu `scenarios/definitions/`."""
        scenarios = self.manager.repository.list_scenarios()
        if not scenarios:
            self.stdout.write(
                self.style.WARNING(
                    f"Brak zdefiniowanych scenariuszy w {self.manager.repository.definitions_dir}."
                )
            )
            return

        self.stdout.write(self.style.MIGRATE_HEADING("Dostępne scenariusze:"))
        for item in scenarios:
            self.stdout.write(
                f"  • {item.slug:<28} | {item.title} "
                f"[region: {item.region}, pola: {len(item.fields)}, today: {item.window.clock_today.isoformat()}]"
            )
            if item.description:
                self.stdout.write(f"      {item.description}")

    def _handle_status(self) -> None:
        """Wypisuje aktualny stan bazy danych i zegara `core.Clock`."""
        status = self.manager.get_status()
        weather_span = (
            f"{status.weather_daily_range[0]} .. {status.weather_daily_range[1]}"
            if status.weather_daily_range
            else "brak danych"
        )

        self.stdout.write(self.style.MIGRATE_HEADING("Aktualny stan bazy danych:"))
        self.stdout.write(f"  Clock (today):        {status.clock_today or 'NIE USTAWIONY'}")
        self.stdout.write(f"  Pola (Field):         {status.fields_count}")
        self.stdout.write(f"  Komórki siatki (Grid):{status.weather_grids_count}")
        self.stdout.write(f"  Zakres pogody:        {weather_span}")
        self.stdout.write(f"  Obserwacje:           {status.observations_count}")
        self.stdout.write(f"  Wiersze ryzyk (Risk): {status.risks_count}")
        self.stdout.write(f"  Konwersacje czatu:    {status.conversations_count}")

    def _handle_validate(self, slug: str) -> None:
        """Waliduje plik definicji wskazanego scenariusza bez modyfikacji bazy danych.

        Args:
            slug: Identyfikator scenariusza do sprawdzenia.
        """
        definition = self.manager.repository.get_scenario(slug)
        self.stdout.write(
            self.style.SUCCESS(
                f"Scenariusz '{definition.slug}' jest poprawny "
                f"(pola: {len(definition.fields)}, obserwacje: {len(definition.observations)}, "
                f"okno: {definition.window.season_start} .. {definition.window.season_end})."
            )
        )

    def _handle_switch(self, options: dict[str, Any]) -> None:
        """Wykonuje przełączenie bazy na wskazany scenariusz i wypisuje raport końcowy.

        Args:
            options: Słownik opcji przekazanych z parsera CLI.

        Raises:
            CommandError: Gdy format flagi `--today` nie jest poprawną datą ISO 8601.
        """
        today_override: date | None = None
        if options.get("today"):
            try:
                today_override = date.fromisoformat(options["today"])
            except ValueError as exc:
                raise CommandError(
                    f"Niepoprawny format daty dla --today: '{options['today']}' (oczekiwano YYYY-MM-DD)."
                ) from exc

        switch_options = SwitchOptions(
            today_override=today_override,
            keep_weather=bool(options.get("keep_weather", False)),
            reset_chat=bool(options.get("reset_chat", False)),
            skip_predict=bool(options.get("skip_predict", False)),
            allow_synthetic_fallback=bool(options.get("allow_synthetic_fallback", False)),
        )

        self.stdout.write(f"Przełączanie bazy na scenariusz '{options['slug']}'...")
        report = self.manager.switch_to(slug=options["slug"], options=switch_options)

        if report.weather_reloaded_reason:
            self.stdout.write(self.style.WARNING(f"--keep-weather pominięte: {report.weather_reloaded_reason}."))
        self.stdout.write(
            self.style.SUCCESS(
                f"Gotowe! Załadowano '{report.scenario_slug}' (Clock.today = {report.clock_today}):\n"
                f"  - Utworzone pola:       {report.fields_created}\n"
                f"  - Pogoda (daily/hourly):{report.weather_daily_rows} / {report.weather_hourly_rows}\n"
                f"  - Prognozy 7-dniowe:    {report.forecast_rows}\n"
                f"  - Obserwacje rolnika:   {report.observations_created}\n"
                f"  - Wiersze ryzyk (Risk): {report.risk_rows_written}\n"
                f"  - Cache zmiany daty:    {report.date_cache_bundles} paczek"
            )
        )
        if report.synthetic_sources:
            self.stdout.write(self.style.WARNING(
                "UWAGA: dane SYNTETYCZNE (brak plików w DATA_DIR): " + ", ".join(report.synthetic_sources)
                + ". Liczby będą inne niż w docs/demo-script.md."))