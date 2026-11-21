# Synchronizacja pogody dla sadów

`main.py` odczytuje punkty centralne z kolekcji `Orchard`, tworzy obiekty `Orchard`, steruje harmonogramem i uruchamia API dla frontendu. `weather/orchard.py` zleca pracę procesom, `weather/jobs.py` wykonuje zadania, `weather/open_meteo.py` pobiera i waliduje dane, a `weather/repository.py` zapisuje je w MongoDB.

## Punkt centralny sadu

Domyślne pole `centroid` odpowiada formatowi aktualnego zrzutu MongoDB. Poniższy zapis używa współrzędnych testowych Berlina.

```json
{
  "centroid": { "lat": 52.52, "long": 13.41 }
}
```

Opcja `--point-field` pozwala wskazać inny klucz. Obsługiwane są też punkty z kluczami `lat` i `lng` oraz GeoJSON `Point` ze współrzędnymi `[longitude, latitude]`. Sad bez poprawnego punktu zostaje pominięty z ostrzeżeniem.

## Pierwszy import i harmonogram

Najkrótsza ścieżka od zrzutu bazy do działającego API to `python db/scripts/start_weather.py` po instalacji zależności. Szczegóły i tryb weryfikacji `--check` opisano w [instrukcji bazy](../db/SETUP.md).

### Połączenie z uruchomioną bazą

Uruchamiaj z katalogu głównego repozytorium. Ustaw `MONGO_URI` na adres Waszej instancji MongoDB. Przykład używa lokalnej instancji na porcie 27018. Opcjonalne `MONGO_DB` wybiera bazę i domyślnie ma wartość `field_under_pressure`. Strefa domyślnie wynika ze współrzędnych (`auto`). Można ją podać jawnie, np. `--timezone Europe/Warsaw`.

```powershell
python -m pip install -r backend/requirements.txt
$env:MONGO_URI = "mongodb://127.0.0.1:27018/field_under_pressure"
python -m backend.main backfill
python -m backend.main run
```

- `backfill` uzupełnia historię godzinową i dobową z 14 poprzednich pełnych dni dla każdego sadu. Import można ponowić. `--history-days` pozwala odzyskać dłuższy zakres do 92 dni.
- `run` uruchamia API na `http://127.0.0.1:8000` i od razu wykonuje pierwszy cykl. Co godzinę zleca aktualizację bieżącej pogody dla sadów i drzew oraz historii godzinowej. Co 24 godziny zleca aktualizację danych dobowych i prognozy. Uruchom jedną instancję `run`. `Ctrl+C` zamyka API i harmonogram. Port HTTP można zmienić przez `--port`.
- `current` i `daily` można też uruchomić pojedynczo przez `python -m backend.main current` i `python -m backend.main daily`. Po pobraniu punktów GPS uruchom pierwszy import przed startem harmonogramu.

Przy aktualizacji istniejącej bazy uruchom `python -m backend.main migrate` przed `run`. Polecenie przenosi zapisy z kolekcji `weather_current`, `weather_history` i `weather_forecast` do dokumentów sadów z oryginalnymi znacznikami czasu. Można je ponowić.

## Wywołania z maina

```python
orchard = Orchard(orchard_id=orchard_id, workers=weather_workers)
point = {"latitude": latitude, "longitude": longitude, "timezone": timezone}

# Każde wywołanie następuje w odpowiednim cyklu.
orchard.backfill_history(**point, days=14)
orchard.update_current(**point)
orchard.update_daily(**point, forecast_days=3, history_days=2)
```

Metody zwracają `Future[int]`. Wynik oznacza liczbę przetworzonych punktów, a wyjątek zawiera błąd pobrania lub zapisu. `main` sprawdza zakończenie całego cyklu przed ponownym uruchomieniem tego samego typu zadania. Każdy z dwóch procesów ma własne połączenie z MongoDB. Zadania dobowe i import używają tego samego procesu.

## Dane w MongoDB

- `Orchard.environmentalData.current` jest tablicą z ostatnim zapisem bieżącej pogody. Cykl godzinowy kopiuje ten zapis także do `Tree.weather_current` przez `Tree.orchardId`.
- `Orchard.environmentalData.history` jest tablicą godzin uporządkowanych według `valid_at`. Cykl godzinowy pobiera dane z ostatnich 24 godzin wraz z bieżącą granicą godziny, a cykl dobowy uzupełnia dwa poprzednie dni. Nakładające się zakresy aktualizują istniejącą godzinę na podstawie czasu pobrania. Dłuższą przerwę uzupełnia `backfill` z odpowiednim `--history-days`.
- `Orchard.environmentalData.forecast` jest tablicą z trzydniową prognozą godzinową. Każdy cykl dobowy podmienia pełną tablicę w jednej operacji.
- `weather_daily` przechowuje rekord na sad i datę lokalną pod unikatowym kluczem `(orchard_id, date)`. Pole `is_forecast` wskazuje prognozę dobową. Po zamknięciu dnia kolejny cykl aktualizuje jego rekord.
- Znaczniki czasu są datami UTC. Zapisy zawierają wartości, jednostki i `fetched_at`, czyli czas rozpoczęcia pobrania. Brakujące wartości przyjmują `null`.

## Integracja wykresu

`GET /api/v1/weather/temperature?orchardId=<ObjectId>&range=7d` czyta `Orchard.environmentalData.history` z MongoDB. Obsługuje zakresy `24h`, `7d`, `30d`, `90d` i `1y` z `ui/API_SPEC.md` na gałęzi `ui`. Zwraca `orchardId`, `range`, `unit: "C"` i posortowane punkty z `timestamp`, `label`, `minTempC` i `maxTempC`. Po pierwszym imporcie dłuższe zakresy pokażą dostępną część historii.

Adres API w UI ustaw przez `VITE_API_BASE_URL=http://localhost:8000`. Przełącznik `VITE_USE_PLACEHOLDERS=false` włącza prawdziwe wywołania dla całego UI. Ten backend udostępnia ścieżkę wykresu temperatury.

Przykładowe wywołanie dla domyślnego sadu UI:

```text
GET /api/v1/weather/temperature?orchardId=6b01933c1dc02a368703a020&range=7d
```

## Pozycje drzew i edytor sadu

- `GET /api/v1/orchard/trees?orchardId=<ObjectId>` i `GET /api/v1/orchard/scene?orchardId=<ObjectId>` zwracają dla każdego drzewa jego `geo` z `Tree.coordinates` w WGS 84. Scena zawiera również granicę sadu i końce rzędów w tym samym układzie.
- `GET /api/v1/orchards/<ObjectId>` zwraca granicę i zapisane rzędy, a `GET /api/v1/crop-prefs` udostępnia gatunki z bazy. Edytor przesyła kompletny układ jako `orchardRows` i `trees` do `POST /api/v1/orchards/<ObjectId>/layout`. Odpowiedź zawiera trwałe identyfikatory MongoDB i powiązane z nimi rzędy. Ponowienie identycznego zapisu zachowuje identyfikatory.
- `healthIndex` oraz `healthScore` zwracają wynik od 0 do 100 lub `null`. Przy `null` pole `healthStatus` także wynosi `null`. W UI taki stan wymaga neutralnego koloru i etykiety „brak oceny”. Wysokość i promień korony bez pomiarów korzystają z domyślnych wymiarów renderowania.
- `GET /api/v1/orchards/<ObjectId>/point-cloud.las` przesyła plik binarnie. Skopiuj lub wskaż folder `ui/public/las` przez `ORCHARD_LAS_DIR`, jeśli frontend jest w osobnym katalogu. Backend obsługuje pliki `<ObjectId>.las` oraz nazwę `grojec.las` dla sadu demonstracyjnego.
