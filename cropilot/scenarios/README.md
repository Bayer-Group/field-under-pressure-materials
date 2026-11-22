# Scenarios — Test-Case & Simulation Controller

Moduł zarządzający stanem bazy danych dla prezentacji oraz testów integracyjnych platformy **Field Under Pressure (Cropilot)**. Umożliwia deterministyczne zasilanie bazy na podstawie parametrów scenariusza i zewnętrznych zbiorów danych (`DATA_DIR`) oraz szybkie przełączanie pomiędzy przypadkami testowymi.

## Zakres odpowiedzialności

- Ładowanie i weryfikacja danych referencyjnych (`WeatherGrid`, `CropClass`, `Threat`).
- Tworzenie konfiguracji gospodarstwa (`Field`, `FieldCropYear`, `SoilCell`) oraz historii pogody (`WeatherDaily`, `WeatherHourly`).
- Generowanie syntetycznej prognozy 7-dniowej (`WeatherForecastDaily`) dla każdego dnia sezonu.
- Wstrzykiwanie zdarzeń początkowych rolnika (`core.Observation`).
- Ustawianie zegara symulacji (`core.Clock`) i uruchamianie prekomputacji ryzyk (`engine.precompute_season()`).

## Dostępne scenariusze (`scenarios/definitions/`)

- `baseline_farm` — gospodarstwo bazowe w woj. opolskim (2x pszenica ozima, 1x kukurydza) bez aktywnych ognisk chorób.
- `wheat_septoria_outbreak` — presja septoriozy paskowanej liści pszenicy pod koniec maja (BBCH 39–51; w czerwcu pszenica jest już poza fazą podatną).
- `maize_drought_stress` — fala upałów i presja szkodników w uprawie kukurydzy w lipcu.

## Użycie (CLI)

```bash
# Lista dostępnych scenariuszy
python manage.py scenario list

# Podgląd aktualnego stanu bazy i zegara symulacji
python manage.py scenario status

# Przełączenie na wybrany scenariusz (wymaga plików źródłowych w DATA_DIR)
python manage.py scenario switch wheat_septoria_outbreak

# Przełączenie z nadpisaniem parametrów lub trybem offline (dane syntetyczne)
python manage.py scenario switch wheat_septoria_outbreak --today 2025-05-27 --reset-chat --keep-weather
python manage.py scenario switch maize_drought_stress --allow-synthetic-fallback