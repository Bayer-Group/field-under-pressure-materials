"""
Kontrakt danych (schemat) opisujący pojedynczy scenariusz symulacji.

Definicje scenariuszy przechowywane są jako lekkie pliki JSON w `scenarios/definitions/`
i mogą być częściowo nadpisywane parametrami przekazanymi z linii poleceń (CLI).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path
from typing import Any

from scenarios.exceptions import ScenarioNotFoundError, ScenarioValidationError

VALID_OBSERVATION_KINDS: frozenset[str] = frozenset(
    {"symptoms", "absence", "neighbour", "treatment", "field_fact", "event"}
)
VALID_OBSERVATION_CATEGORIES: frozenset[str] = frozenset(
    {"", "disease", "pest", "weeds", "damage", "other"}
)
VALID_GEOMETRY_TYPES: frozenset[str] = frozenset({"Polygon", "MultiPolygon"})


@dataclass(frozen=True)
class FieldSpec:
    """Specyfikacja pojedynczego pola w scenariuszu.

    Attributes:
        name: Nazwa pola wyświetlana w interfejsie (np. "Pole Północne").
        crop_code: Kod uprawy wg legendy CLMS (np. 1110 dla pszenicy, 1130 dla kukurydzy).
        geometry: Geometria GeoJSON (Polygon lub MultiPolygon) w układzie EPSG:4326 [lon, lat].
        crop_history: Opcjonalne nadpisanie historii upraw {rok: {kod_uprawy: udział_0_1}}.
    """

    name: str
    crop_code: int
    geometry: dict[str, Any]
    crop_history: dict[int, dict[int, float]] | None = None


@dataclass(frozen=True)
class ObservationSpec:
    """Specyfikacja raportu/obserwacji rolnika wstrzykiwanej do `core.Observation`.

    Attributes:
        kind: Typ zdarzenia (`symptoms`, `absence`, `neighbour`, `treatment`, `field_fact`, `event`).
        observed_on: Data zaobserwowania zdarzenia w kalendarzu symulacji.
        field_name: Nazwa pola z `FieldSpec.name` lub `None` dla całego gospodarstwa.
        category: Kategoria problemu (`disease`, `pest`, `weeds`, `damage`, `other`).
        threat_code: Kod zagrożenia z tabeli `Threat` (np. `wheat.septoria_leaf_blotch`).
        severity: Nasilenie w skali 0.0–1.0.
        distance_m: Odległość w metrach (wyłącznie dla `kind="neighbour"`).
        details: Dodatkowe metadane JSON (`sowing_date`, `tillage`, `resistant_to`, `type`).
        text: Opis słowny rolnika cytowany w wyjaśnieniach silnika.
    """

    kind: str
    observed_on: date
    field_name: str | None = None
    category: str = ""
    threat_code: str | None = None
    severity: float | None = None
    distance_m: float | None = None
    details: dict[str, Any] = field(default_factory=dict)
    text: str = ""


@dataclass(frozen=True)
class SimulationWindow:
    """Zakres czasowy symulacji oraz ustawienie zegara demo (`core.Clock`).

    Attributes:
        season: Rok głównego sezonu wegetacyjnego (np. 2025).
        season_start: Data początku przeliczania sezonu (np. 2024-09-01).
        season_end: Data końca prekomputacji sezonu (np. 2025-07-31).
        clock_today: Początkowa data „dzisiaj” zapisywana w `core.Clock`.
        include_previous_season: Czy ładować dane i przeliczyć sezon `season - 1` (dla efektu carry-over).
    """

    season: int
    season_start: date
    season_end: date
    clock_today: date
    include_previous_season: bool = True


@dataclass(frozen=True)
class ScenarioDefinition:
    """Pełna definicja przypadku testowego (test-case) ładowana z pliku JSON.

    Attributes:
        slug: Unikalny identyfikator scenariusza (nazwa pliku bez rozszerzenia).
        title: Krótki tytuł opisujący cel scenariusza.
        description: Szczegółowy opis sytuacji agronomicznej i oczekiwanych ryzyk.
        region: Nazwa województwa używana do lokalizacji plików w `DATA_DIR` (np. "Opolskie").
        window: Konfiguracja dat sezonu i zegara `Clock`.
        fields: Lista definicji pól wchodzących w skład gospodarstwa.
        observations: Lista początkowych obserwacji rolnika do załadowania.
        weather_overrides: Opcjonalne modyfikacje parametrów pogodowych dla wybranych dat.
    """

    slug: str
    title: str
    description: str
    region: str
    window: SimulationWindow
    fields: list[FieldSpec]
    observations: list[ObservationSpec] = field(default_factory=list)
    weather_overrides: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class SwitchOptions:
    """Parametry sterujące wykonaniem przełączenia scenariusza z poziomu CLI lub API.

    Attributes:
        today_override: Opcjonalne nadpisanie daty `Clock.today` względem definicji JSON.
        keep_weather: Czy zachować istniejące rekordy `WeatherDaily`/`WeatherHourly`, jeśli siatka się pokrywa.
        reset_chat: Czy usunąć historię konwersacji z tabel `assistant.Conversation` i `Message`.
        skip_predict: Czy pominąć wywołanie `engine.predict()` po załadowaniu danych wejściowych.
        allow_synthetic_fallback: Czy wygenerować dane syntetyczne w razie braku plików w `DATA_DIR`.
    """

    today_override: date | None = None
    keep_weather: bool = False
    reset_chat: bool = False
    skip_predict: bool = False
    allow_synthetic_fallback: bool = False


class ScenarioParser:
    """Parser i walidator plików definicji scenariuszy JSON."""

    @classmethod
    def from_file(cls, path: Path) -> ScenarioDefinition:
        """Wczytuje plik JSON i buduje zwalidowany obiekt `ScenarioDefinition`.

        Args:
            path: Ścieżka do pliku `.json` z definicją scenariusza.

        Returns:
            Sparsowany i zweryfikowany obiekt `ScenarioDefinition`.

        Raises:
            ScenarioNotFoundError: Gdy plik nie istnieje.
            ScenarioValidationError: Gdy struktura JSON, daty lub geometria są niepoprawne.
        """
        if not path.is_file():
            raise ScenarioNotFoundError(f"Nie znaleziono pliku scenariusza: {path}")

        try:
            raw_text = path.read_text(encoding="utf-8")
            payload = json.loads(raw_text)
        except OSError as exc:
            raise ScenarioValidationError(f"Nie można odczytać pliku {path}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise ScenarioValidationError(f"Niepoprawny składniowo JSON w {path}: {exc}") from exc

        if not isinstance(payload, dict):
            raise ScenarioValidationError(f"Główny element w {path} musi być obiektem JSON.")

        return cls.from_dict(payload, slug=path.stem)

    @classmethod
    def from_dict(cls, data: dict[str, Any], slug: str) -> ScenarioDefinition:
        """Buduje i waliduje `ScenarioDefinition` ze słownika Pythona.

        Args:
            data: Słownik z danymi scenariusza.
            slug: Identyfikator scenariusza (zwykle nazwa pliku bez rozszerzenia).

        Returns:
            Zwalidowany obiekt `ScenarioDefinition`.

        Raises:
            ScenarioValidationError: Gdy brakuje wymaganych kluczy lub typy danych są niepoprawne.
        """
        try:
            title = cls._require_str(data, "title", slug)
            description = str(data.get("description", "")).strip()
            region = cls._require_str(data, "region", slug)
            window = cls._parse_window(data.get("window"), slug)
            fields = cls._parse_fields(data.get("fields"), slug)
            observations = cls._parse_observations(data.get("observations", []), slug)
            weather_overrides = data.get("weather_overrides", [])
        except ScenarioValidationError:
            raise
        except (TypeError, ValueError) as exc:
            raise ScenarioValidationError(f"[{slug}] Błąd parsowania struktury scenariusza: {exc}") from exc

        if not isinstance(weather_overrides, list) or not all(isinstance(item, dict) for item in weather_overrides):
            raise ScenarioValidationError(f"[{slug}] Pole 'weather_overrides' musi być listą obiektów.")

        definition = ScenarioDefinition(
            slug=slug,
            title=title,
            description=description,
            region=region,
            window=window,
            fields=fields,
            observations=observations,
            weather_overrides=weather_overrides,
        )
        cls.validate(definition)
        return definition

    @classmethod
    def apply_overrides(cls, definition: ScenarioDefinition, options: SwitchOptions) -> ScenarioDefinition:
        """Zwraca definicję scenariusza z uwzględnieniem nadpisań z parametrów uruchomienia.

        Jeśli `options.today_override` jest ustawione, tworzy nową kopię `ScenarioDefinition`
        ze zaktualizowaną datą `window.clock_today` i ponownie waliduje spójność okna czasowego.
        W przeciwnym razie zwraca niezmieniony obiekt wejściowy.

        Args:
            definition: Bazowa definicja scenariusza wczytana z pliku.
            options: Opcje przełączania przekazane z CLI lub warstwy wywołującej.

        Returns:
            Zwalidowany obiekt `ScenarioDefinition` gotowy do załadowania do bazy.

        Raises:
            ScenarioValidationError: Gdy nadpisana data `clock_today` wykracza poza
                zakres `[season_start, season_end]`.
        """
        if options.today_override is None:
            return definition

        updated_window = replace(definition.window, clock_today=options.today_override)
        updated_definition = replace(definition, window=updated_window)
        cls.validate(updated_definition)
        return updated_definition

    @staticmethod
    def validate(definition: ScenarioDefinition) -> None:
        """Sprawdza spójność logiczną scenariusza (zakresy dat, kody upraw, poligony).

        Args:
            definition: Obiekt definicji scenariusza do sprawdzenia.

        Raises:
            ScenarioValidationError: Gdy wykryto naruszenie reguł domenowych.
        """
        slug = definition.slug
        win = definition.window

        if win.season_start > win.season_end:
            raise ScenarioValidationError(
                f"[{slug}] Data 'season_start' ({win.season_start}) nie może być późniejsza niż 'season_end' ({win.season_end})."
            )
        if not (win.season_start <= win.clock_today <= win.season_end):
            raise ScenarioValidationError(
                f"[{slug}] Data 'clock_today' ({win.clock_today}) musi mieścić się w przedziale "
                f"[{win.season_start}, {win.season_end}]."
            )

        # the season is named by its harvest year and starts on 1 September of the year before
        expected_season = win.season_start.year + 1 if win.season_start.month >= 9 else win.season_start.year
        if win.season != expected_season:
            raise ScenarioValidationError(
                f"[{slug}] 'season' ({win.season}) nie pasuje do 'season_start' ({win.season_start}): "
                f"sezon zaczynający się tego dnia to {expected_season} (rok zbioru)."
            )

        if not definition.fields:
            raise ScenarioValidationError(f"[{slug}] Scenariusz musi definiować co najmniej jedno pole w 'fields'.")

        from engine.catalog import RULES, rules_for_crop

        seen_names: set[str] = set()
        for fld in definition.fields:
            if not fld.name.strip():
                raise ScenarioValidationError(f"[{slug}] Nazwa pola nie może być pusta.")
            if fld.name in seen_names:
                raise ScenarioValidationError(f"[{slug}] Zduplikowana nazwa pola: '{fld.name}'.")
            seen_names.add(fld.name)
            if not rules_for_crop(fld.crop_code):
                raise ScenarioValidationError(
                    f"[{slug}] Pole '{fld.name}': silnik nie ma reguł dla uprawy {fld.crop_code}, więc nie policzy ryzyk."
                )

            geom_type = fld.geometry.get("type")
            coords = fld.geometry.get("coordinates")
            if geom_type not in VALID_GEOMETRY_TYPES or not isinstance(coords, list) or not coords:
                raise ScenarioValidationError(
                    f"[{slug}] Pole '{fld.name}' ma niepoprawną geometrię GeoJSON (wymagany Polygon lub MultiPolygon)."
                )

            if fld.crop_history is not None:
                for year, shares in fld.crop_history.items():
                    if not shares:
                        raise ScenarioValidationError(
                            f"[{slug}] Pusta historia upraw dla pola '{fld.name}' w roku {year}."
                        )
                    total_share = 0.0
                    for crop_code, share in shares.items():
                        if not (0.0 <= share <= 1.0):
                            raise ScenarioValidationError(
                                f"[{slug}] Udział uprawy {crop_code} w roku {year} dla '{fld.name}' musi być w [0, 1]."
                            )
                        total_share += share
                    if abs(total_share - 1.0) > 0.02:
                        raise ScenarioValidationError(
                            f"[{slug}] Suma udziałów upraw w roku {year} dla '{fld.name}' wynosi {total_share:.2f} (oczekiwano ~1.0)."
                        )

        for idx, obs in enumerate(definition.observations):
            if obs.kind not in VALID_OBSERVATION_KINDS:
                raise ScenarioValidationError(
                    f"[{slug}] Obserwacja #{idx}: nieznany typ kind='{obs.kind}'."
                )
            if obs.category not in VALID_OBSERVATION_CATEGORIES:
                raise ScenarioValidationError(
                    f"[{slug}] Obserwacja #{idx}: nieznana kategoria category='{obs.category}'."
                )
            if obs.field_name is not None and obs.field_name not in seen_names:
                raise ScenarioValidationError(
                    f"[{slug}] Obserwacja #{idx}: odwołanie do nieistniejącego pola '{obs.field_name}'."
                )
            if obs.observed_on > win.clock_today:  # a report "from the future" would change the coming days
                raise ScenarioValidationError(
                    f"[{slug}] Obserwacja #{idx}: 'observed_on' ({obs.observed_on}) jest po 'clock_today' ({win.clock_today})."
                )
            if obs.threat_code:
                rule = RULES.get(obs.threat_code)
                if rule is None:
                    raise ScenarioValidationError(f"[{slug}] Obserwacja #{idx}: nieznany kod zagrożenia '{obs.threat_code}'.")
                crop = next((f.crop_code for f in definition.fields if f.name == obs.field_name), None)
                if crop is not None and rule.crop != crop:
                    raise ScenarioValidationError(
                        f"[{slug}] Obserwacja #{idx}: '{obs.threat_code}' nie dotyczy uprawy pola '{obs.field_name}' ({crop})."
                    )
            if obs.severity is not None and not (0.0 <= obs.severity <= 1.0):
                raise ScenarioValidationError(
                    f"[{slug}] Obserwacja #{idx}: 'severity' ({obs.severity}) musi być w przedziale [0.0, 1.0]."
                )
            if obs.distance_m is not None and obs.distance_m < 0.0:
                raise ScenarioValidationError(
                    f"[{slug}] Obserwacja #{idx}: 'distance_m' ({obs.distance_m}) nie może być ujemne."
                )

        ScenarioParser._validate_weather_overrides(definition)

    @staticmethod
    def _validate_weather_overrides(definition: ScenarioDefinition) -> None:
        """Every override: start_date (or date) and end_date as YYYY-MM-DD, start <= end, known WeatherDaily columns."""
        from core.models import WeatherDaily

        slug = definition.slug
        columns = {f.attname for f in WeatherDaily._meta.concrete_fields} - {"id", "grid_id", "date"}
        for idx, entry in enumerate(definition.weather_overrides or []):
            start_raw = entry.get("start_date") or entry.get("date")
            end_raw = entry.get("end_date") or start_raw
            try:
                start, end = date.fromisoformat(str(start_raw)), date.fromisoformat(str(end_raw))
            except ValueError:
                raise ScenarioValidationError(
                    f"[{slug}] weather_overrides[{idx}]: daty muszą mieć format YYYY-MM-DD (start_date / end_date)."
                ) from None
            if start > end:
                raise ScenarioValidationError(f"[{slug}] weather_overrides[{idx}]: start_date jest po end_date.")
            values = entry.get("values")
            if not isinstance(values, dict) or not values:
                raise ScenarioValidationError(f"[{slug}] weather_overrides[{idx}]: brak obiektu 'values'.")
            unknown = sorted(set(values) - columns)
            if unknown:
                raise ScenarioValidationError(f"[{slug}] weather_overrides[{idx}]: nieznane kolumny pogody {unknown}.")

    @classmethod
    def _parse_window(cls, raw: Any, slug: str) -> SimulationWindow:
        if not isinstance(raw, dict):
            raise ScenarioValidationError(f"[{slug}] Brak lub niepoprawny obiekt 'window'.")

        season = cls._require_int(raw, "season", slug)
        season_start = cls._require_date(raw, "season_start", slug)
        season_end = cls._require_date(raw, "season_end", slug)
        clock_today = cls._require_date(raw, "clock_today", slug)
        include_previous_season = raw.get("include_previous_season", True)
        if not isinstance(include_previous_season, bool):  # "false" (a string) used to mean True
            raise ScenarioValidationError(f"[{slug}] 'include_previous_season' musi być true albo false (bez cudzysłowu).")

        return SimulationWindow(
            season=season,
            season_start=season_start,
            season_end=season_end,
            clock_today=clock_today,
            include_previous_season=include_previous_season,
        )

    @classmethod
    def _parse_fields(cls, raw: Any, slug: str) -> list[FieldSpec]:
        if not isinstance(raw, list):
            raise ScenarioValidationError(f"[{slug}] Pole 'fields' musi być listą.")

        result: list[FieldSpec] = []
        for idx, item in enumerate(raw):
            if not isinstance(item, dict):
                raise ScenarioValidationError(f"[{slug}] Element fields[{idx}] musi być obiektem JSON.")
            name = cls._require_str(item, "name", slug)
            crop_code = cls._require_int(item, "crop_code", slug)
            geometry = item.get("geometry")
            if not isinstance(geometry, dict):
                raise ScenarioValidationError(f"[{slug}] Pole '{name}' musi zawierać obiekt 'geometry'.")

            raw_history = item.get("crop_history")
            crop_history: dict[int, dict[int, float]] | None = None
            if raw_history is not None:
                if not isinstance(raw_history, dict):
                    raise ScenarioValidationError(f"[{slug}] 'crop_history' dla pola '{name}' musi być słownikiem.")
                crop_history = {
                    int(year_str): {int(code_str): float(share) for code_str, share in classes.items()}
                    for year_str, classes in raw_history.items()
                }

            result.append(
                FieldSpec(
                    name=name,
                    crop_code=crop_code,
                    geometry=geometry,
                    crop_history=crop_history,
                )
            )
        return result

    @classmethod
    def _parse_observations(cls, raw: Any, slug: str) -> list[ObservationSpec]:
        if not isinstance(raw, list):
            raise ScenarioValidationError(f"[{slug}] Pole 'observations' musi być listą.")

        result: list[ObservationSpec] = []
        for idx, item in enumerate(raw):
            if not isinstance(item, dict):
                raise ScenarioValidationError(f"[{slug}] Element observations[{idx}] musi być obiektem JSON.")

            kind = cls._require_str(item, "kind", slug)
            observed_on = cls._require_date(item, "observed_on", slug)
            field_name = item.get("field_name")
            if field_name is not None and not isinstance(field_name, str):
                raise ScenarioValidationError(f"[{slug}] observations[{idx}].field_name musi być tekstem lub null.")

            severity = float(item["severity"]) if item.get("severity") is not None else None
            distance_m = float(item["distance_m"]) if item.get("distance_m") is not None else None
            details = item.get("details") or {}
            if not isinstance(details, dict):
                raise ScenarioValidationError(f"[{slug}] observations[{idx}].details musi być obiektem JSON.")

            result.append(
                ObservationSpec(
                    kind=kind,
                    observed_on=observed_on,
                    field_name=field_name,
                    category=str(item.get("category", "")).strip(),
                    threat_code=item.get("threat_code"),
                    severity=severity,
                    distance_m=distance_m,
                    details=details,
                    text=str(item.get("text", "")),
                )
            )
        return result

    @staticmethod
    def _require_str(obj: dict[str, Any], key: str, slug: str) -> str:
        val = obj.get(key)
        if not isinstance(val, str) or not val.strip():
            raise ScenarioValidationError(f"[{slug}] Wymagane niepuste pole tekstowe '{key}'.")
        return val.strip()

    @staticmethod
    def _require_int(obj: dict[str, Any], key: str, slug: str) -> int:
        val = obj.get(key)
        if isinstance(val, bool) or not isinstance(val, int):
            raise ScenarioValidationError(f"[{slug}] Wymagana liczba całkowita '{key}'.")
        return val

    @staticmethod
    def _require_date(obj: dict[str, Any], key: str, slug: str) -> date:
        val = obj.get(key)
        if not isinstance(val, str):
            raise ScenarioValidationError(f"[{slug}] Wymagana data ISO (YYYY-MM-DD) w polu '{key}'.")
        try:
            return date.fromisoformat(val)
        except ValueError as exc:
            raise ScenarioValidationError(f"[{slug}] Niepoprawny format daty '{val}' w polu '{key}'.") from exc