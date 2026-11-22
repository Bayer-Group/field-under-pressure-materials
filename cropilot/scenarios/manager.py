"""
Główny kontroler zarządzania scenariuszami (test-cases).

Odpowiada za odkrywanie definicji scenariuszy, atomowe czyszczenie danych
scenariuszowych w bazie PostgreSQL, orkiestrację ładowania danych, ustawianie
zegara symulacji (`core.Clock`) oraz uruchamianie prekomputacji ryzyk (`engine.predict()`).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field as dc_field
from datetime import date, timedelta
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.db import transaction
from django.db.models import Max, Min

from core import clock
from core.models import (
    Clock,
    Field,
    FieldCropYear,
    Observation,
    Risk,
    WeatherDaily,
    WeatherForecastDaily,
    WeatherHourly,
)
from scenarios.exceptions import ScenarioNotFoundError, ScenarioValidationError
from scenarios.loaders import (
    FieldAndSoilLoader,
    ObservationLoader,
    ReferenceDataLoader,
    WeatherAndForecastLoader,
    SYNTHETIC_USED,
)
from scenarios.schema import ScenarioDefinition, ScenarioParser, SwitchOptions

DEFAULT_DEFINITIONS_DIR = Path(__file__).resolve().parent / "definitions"


@dataclass(frozen=True)
class DatabaseStatus:
    """Migawka aktualnego stanu bazy danych aplikacji.

    Attributes:
        clock_today: Aktualna data w `core.Clock` lub `None`, jeśli zegar nie jest ustawiony.
        fields_count: Liczba pól w tabeli `core.Field`.
        weather_grids_count: Liczba aktywnych komórek pogodowych powiązanych z polami.
        weather_daily_range: Krotka `(min_date, max_date)` dla `WeatherDaily` lub `None`.
        observations_count: Liczba raportów w `core.Observation`.
        risks_count: Liczba przeliczonych wierszy w `core.Risk`.
        conversations_count: Liczba konwersacji w `assistant.Conversation`.
    """

    clock_today: str | None
    fields_count: int
    weather_grids_count: int
    weather_daily_range: tuple[str, str] | None
    observations_count: int
    risks_count: int
    conversations_count: int


@dataclass(frozen=True)
class SwitchReport:
    """Podsumowanie operacji przełączenia bazy danych na nowy scenariusz.

    Attributes:
        scenario_slug: Identyfikator załadowanego scenariusza.
        clock_today: Ustawiona data `Clock.today` (ISO 8601).
        fields_created: Liczba utworzonych pól.
        weather_daily_rows: Liczba rekordów `WeatherDaily` w bazie dla pól scenariusza.
        weather_hourly_rows: Liczba rekordów `WeatherHourly` w bazie dla pól scenariusza.
        forecast_rows: Liczba wygenerowanych rekordów `WeatherForecastDaily`.
        observations_created: Liczba zapisanych obserwacji `core.Observation`.
        risk_rows_written: Liczba wierszy ryzyk zapisanych przez `engine.predict()`.
    """

    scenario_slug: str
    clock_today: str
    fields_created: int
    weather_daily_rows: int
    weather_hourly_rows: int
    forecast_rows: int
    observations_created: int
    risk_rows_written: int
    # what DATA_DIR lacked and was generated instead (empty = real data only)
    synthetic_sources: list[str] = dc_field(default_factory=list)
    # engine.RiskSnapshot bundles written ahead, so date moves copy rows (engine.precompute_dates)
    date_cache_bundles: int = 0
    # why --keep-weather was ignored (the previous scenario had overridden the weather), or None
    weather_reloaded_reason: str | None = None


def _state_path() -> Path:
    """The last scenario switched in this database (slug, whether it overrode the weather), in logs/ (git-ignored).
    One file per database: a test switch in another POSTGRES_DB must not speak for the demo's."""
    from django.db import connection

    return Path(settings.BASE_DIR) / "logs" / f"scenario_state_{connection.settings_dict['NAME']}.json"


def _read_state() -> dict:
    try:
        return json.loads(_state_path().read_text())
    except (OSError, ValueError):
        return {}


def _write_state(state: dict) -> None:
    try:
        _state_path().parent.mkdir(parents=True, exist_ok=True)
        _state_path().write_text(json.dumps(state))
    except OSError:
        pass


class ScenarioRepository:
    """Repozytorium plików definicji scenariuszy przechowywanych w `scenarios/definitions/`."""

    def __init__(self, definitions_dir: Path | None = None) -> None:
        """Inicjalizuje repozytorium ścieżką do katalogu z plikami JSON.

        Args:
            definitions_dir: Opcjonalna ścieżka niestandardowa; domyślnie `scenarios/definitions/`.
        """
        self.definitions_dir = definitions_dir or DEFAULT_DEFINITIONS_DIR

    def list_scenarios(self) -> list[ScenarioDefinition]:
        """Zwraca listę wszystkich poprawnych definicji scenariuszy posortowaną po `slug`.

        Returns:
            Lista obiektów `ScenarioDefinition` wczytanych z plików `*.json`.

        Raises:
            ScenarioValidationError: Gdy którykolwiek z plików w katalogu ma niepoprawny format.
        """
        if not self.definitions_dir.is_dir():
            return []

        definitions: list[ScenarioDefinition] = []
        for json_path in sorted(self.definitions_dir.glob("*.json")):
            definitions.append(ScenarioParser.from_file(json_path))
        return definitions

    def get_scenario(self, slug: str) -> ScenarioDefinition:
        """Pobiera i parsuje pojedynczy scenariusz po jego identyfikatorze (`slug`).

        Args:
            slug: Nazwa scenariusza (bez rozszerzenia `.json`).

        Returns:
            Sparsowana i zwalidowana definicja scenariusza.

        Raises:
            ScenarioValidationError: Gdy `slug` zawiera niedozwolone znaki ścieżki.
            ScenarioNotFoundError: Gdy scenariusz o podanym `slug` nie istnieje.
        """
        clean_slug = slug.strip()
        if not clean_slug or "/" in clean_slug or "\\" in clean_slug or ".." in clean_slug:
            raise ScenarioValidationError(f"Niepoprawny identyfikator scenariusza: '{slug}'.")

        target_path = self.definitions_dir / f"{clean_slug}.json"
        if not target_path.is_file():
            raise ScenarioNotFoundError(
                f"Scenariusz '{clean_slug}' nie istnieje w katalogu {self.definitions_dir}."
            )
        return ScenarioParser.from_file(target_path)


class DatabaseStateCleaner:
    """Komponent odpowiedzialny za bezpieczne czyszczenie danych poprzedniego scenariusza."""

    def clear_scenario_data(self, keep_weather: bool = False, reset_chat: bool = False) -> None:
        """Usuwa dane specyficzne dla poprzedniego scenariusza z zachowaniem tabel słownikowych.

        Czyści kolejno: `Risk`, `Observation`, `FieldCropYear`, `Field`, `WeatherForecastDaily`
        (oraz warunkowo `WeatherDaily`, `WeatherHourly` i `assistant.Conversation`).

        Args:
            keep_weather: Jeśli `True`, nie usuwa `WeatherDaily` ani `WeatherHourly`.
            reset_chat: Jeśli `True`, usuwa wszystkie rekordy `assistant.Conversation` i `Message`.
        """
        Risk.objects.all().delete()
        Observation.objects.all().delete()
        FieldCropYear.objects.all().delete()
        Field.objects.all().delete()
        WeatherForecastDaily.objects.all().delete()

        if not keep_weather:
            WeatherDaily.objects.all().delete()
            WeatherHourly.objects.all().delete()

        if reset_chat:
            self._clear_assistant_chat()

    @staticmethod
    def _clear_assistant_chat() -> None:
        """Czyści tabele czatu (`assistant.Message`, `assistant.Conversation`), jeśli aplikacja jest dostępna."""
        if not apps.is_installed("assistant"):
            return

        message_model = apps.get_model("assistant", "Message")
        conversation_model = apps.get_model("assistant", "Conversation")
        message_model.objects.all().delete()
        conversation_model.objects.all().delete()


class ScenarioManager:
    """Fasada orkiestrująca cały proces inspekcji, walidacji i przełączania scenariuszy."""

    def __init__(
        self,
        repository: ScenarioRepository | None = None,
        cleaner: DatabaseStateCleaner | None = None,
        reference_loader: ReferenceDataLoader | None = None,
        field_loader: FieldAndSoilLoader | None = None,
        weather_loader: WeatherAndForecastLoader | None = None,
        observation_loader: ObservationLoader | None = None,
    ) -> None:
        """Inicjalizuje menedżer scenariuszy z wstrzykiwalnymi zależnościami (ułatwia testowanie).

        Args:
            repository: Repozytorium definicji scenariuszy JSON.
            cleaner: Komponent czyszczący poprzedni stan bazy.
            reference_loader: Loader tabel słownikowych (`CropClass`, `Threat`, `WeatherGrid`).
            field_loader: Loader pól, historii upraw i gleby.
            weather_loader: Loader pogody obserwowanej i generator prognoz.
            observation_loader: Loader raportów rolnika (`core.Observation`).
        """
        data_dir = Path(getattr(settings, "DATA_DIR", "../field-under-pressure-data")).resolve()

        self.repository = repository or ScenarioRepository()
        self.cleaner = cleaner or DatabaseStateCleaner()
        self.reference_loader = reference_loader or ReferenceDataLoader(data_dir=data_dir)
        self.field_loader = field_loader or FieldAndSoilLoader(
            data_dir=data_dir, reference_loader=self.reference_loader
        )
        self.weather_loader = weather_loader or WeatherAndForecastLoader(data_dir=data_dir)
        self.observation_loader = observation_loader or ObservationLoader()

    def get_status(self) -> DatabaseStatus:
        """Zwraca bieżący stan tabel platformy i zegara `core.Clock`.

        Returns:
            Obiekt `DatabaseStatus` ze statystykami aktualnej bazy danych.
        """
        try:
            current_today: str | None = clock.today().isoformat()
        except clock.ClockNotSetError:
            current_today = None

        weather_agg = WeatherDaily.objects.aggregate(min_date=Min("date"), max_date=Max("date"))
        weather_range: tuple[str, str] | None = None
        if weather_agg["min_date"] is not None and weather_agg["max_date"] is not None:
            weather_range = (
                weather_agg["min_date"].isoformat(),
                weather_agg["max_date"].isoformat(),
            )

        conversations_count = 0
        if apps.is_installed("assistant"):
            conversation_model = apps.get_model("assistant", "Conversation")
            conversations_count = conversation_model.objects.count()

        active_grids_count = Field.objects.values("weather_grid_id").distinct().count()

        return DatabaseStatus(
            clock_today=current_today,
            fields_count=Field.objects.count(),
            weather_grids_count=active_grids_count,
            weather_daily_range=weather_range,
            observations_count=Observation.objects.count(),
            risks_count=Risk.objects.count(),
            conversations_count=conversations_count,
        )

    def switch_to(self, slug: str, options: SwitchOptions | None = None) -> SwitchReport:
        """Przełącza główną bazę danych aplikacji na wskazany scenariusz.

        Przebieg operacji:
        1. Wczytanie i walidacja definicji scenariusza (`ScenarioRepository`).
        2. Synchronizacja tabel referencyjnych (`CropClass`, `Threat`).
        3. Atomowy reset stanu poprzedniego scenariusza (`DatabaseStateCleaner`).
        4. Załadowanie pól, gleby, historii upraw, pogody, prognoz i obserwacji.
        5. Ustawienie `core.Clock` oraz pełna prekomputacja sezonu przez `engine.predict()`.

        Args:
            slug: Identyfikator scenariusza do załadowania.
            options: Opcjonalne flagi modyfikujące proces przełączania.

        Returns:
            Raport podsumowujący wprowadzone zmiany (`SwitchReport`).

        Raises:
            ScenarioNotFoundError: Gdy wskazany scenariusz nie istnieje.
            ScenarioValidationError: Gdy definicja lub opcje przełączenia są niespójne.
            DataSourceError: Gdy brakuje wymaganych plików źródłowych przy wyłączonym fallbacku.
        """
        effective_options = options or SwitchOptions()
        raw_definition = self.repository.get_scenario(slug)
        definition = ScenarioParser.apply_overrides(raw_definition, effective_options)
        SYNTHETIC_USED.clear()

        # --keep-weather keeps the stored weather, including what the previous scenario overrode (a heat wave, a
        # wet week): its overrides would leak into this scenario. Reload the weather in that case.
        keep_weather = effective_options.keep_weather
        reload_reason = None
        previous = _read_state()
        if keep_weather and previous.get("weather_overrides"):
            keep_weather = False
            reload_reason = (f"poprzedni scenariusz ('{previous.get('slug')}') nadpisywał pogodę, "
                             "więc pogoda jest ładowana od nowa")

        # Synchronizacja tabel referencyjnych przed otwarciem głównej transakcji scenariuszowej
        self.reference_loader.ensure_crop_classes()
        self.reference_loader.ensure_threats()

        prev_start = self._previous_season_start(definition)
        effective_start = prev_start if definition.window.include_previous_season else definition.window.season_start
        years_to_load = list(range(effective_start.year, definition.window.season_end.year + 1))

        with transaction.atomic():
            self.cleaner.clear_scenario_data(
                keep_weather=keep_weather,
                reset_chat=effective_options.reset_chat,
            )

            created_fields = self.field_loader.build_fields(
                specs=definition.fields,
                region=definition.region,
                allow_fallback=effective_options.allow_synthetic_fallback,
            )
            grid_ids = sorted({fld.weather_grid_id for fld in created_fields})

            daily_rows, hourly_rows = self.weather_loader.load_observed_weather(
                grid_ids=grid_ids,
                region=definition.region,
                years=years_to_load,
                overrides=definition.weather_overrides,
                allow_fallback=effective_options.allow_synthetic_fallback,
            )

            forecast_rows = self.weather_loader.generate_forecast_series(
                grid_ids=grid_ids,
                start=effective_start,
                end=definition.window.season_end,
            )

            fields_by_name = {fld.name: fld for fld in created_fields}
            observations_created = self.observation_loader.load_observations(
                specs=definition.observations,
                fields_by_name=fields_by_name,
            )

            # Ustawienie zegara demo na pustej tabeli Risk przed uruchomieniem prekomputacji
            Clock(today=definition.window.clock_today).save()

            risk_rows_written = 0
            if not effective_options.skip_predict:
                risk_rows_written = self._run_engine_precompute(definition)

        _write_state({"slug": definition.slug, "weather_overrides": bool(definition.weather_overrides)})
        bundles = 0
        if not effective_options.skip_predict:  # date moves then copy precomputed rows (about 0.3 s instead of 2-5 s)
            from engine import precompute_dates
            bundles = int(precompute_dates())

        return SwitchReport(
            scenario_slug=definition.slug,
            clock_today=definition.window.clock_today.isoformat(),
            fields_created=len(created_fields),
            weather_daily_rows=daily_rows,
            weather_hourly_rows=hourly_rows,
            forecast_rows=forecast_rows,
            observations_created=observations_created,
            risk_rows_written=risk_rows_written,
            synthetic_sources=sorted(SYNTHETIC_USED),
            date_cache_bundles=bundles,
            weather_reloaded_reason=reload_reason,
        )

    @staticmethod
    def _previous_season_start(definition: ScenarioDefinition) -> date:
        """Wyznacza datę startu poprzedniego sezonu (1 września roku `season - 2`) dla efektu carry-over."""
        return date(definition.window.season - 2, 9, 1)

    def _run_engine_precompute(self, definition: ScenarioDefinition) -> int:
        """Uruchamia prekomputację sezonu (wraz z poprzednim sezonem dla carry-over) w silniku decyzyjnym.

        Args:
            definition: Zwalidowana definicja scenariusza.

        Returns:
            Łączna liczba wierszy `Risk` zapisanych przez `engine.precompute_season()`.
        """
        from engine import precompute_season

        result = precompute_season(season=definition.window.season)
        return int(result)