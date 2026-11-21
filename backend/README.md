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

Uruchamiaj z katalogu głównego repozytorium. Ustaw `MONGO_URI` na adres Waszej instancji MongoDB. Przykład używa lokalnej instancji na porcie 27018. Opcjonalne `MONGO_DB` wybiera bazę i domyślnie ma wartość `field_under_pressure`. Strefa domyślnie wynika ze współrzędnych (`auto`). Można ją podać jawnie, np. `--timezone Europe/Warsaw`.

```powershell
python -m pip install -r backend/requirements.txt
$env:MONGO_URI = "mongodb://127.0.0.1:27018/field_under_pressure"
python -m backend.main backfill
python -m backend.main run
```

- `backfill` pobiera dane godzinowe z 14 poprzednich dni dla każdego sadu. Zapytanie zawiera także dzisiejszy dzień, ale zapis obejmuje wyłącznie godziny przed początkiem dzisiejszego dnia w odpowiedzi API. Import można ponowić. `--history-days` pozwala odzyskać dłuższy zakres do 92 dni.
- `run` uruchamia API na `http://127.0.0.1:8000`. Pierwszy cykl wykonuje od razu, a następnie zleca `current` co godzinę i `daily` co 24 godziny. Uruchom jedną instancję `run`. `Ctrl+C` zamyka API i harmonogram. Port HTTP można zmienić przez `--port`.
- `current` i `daily` można też uruchomić pojedynczo przez `python -m backend.main current` i `python -m backend.main daily`. Po pobraniu punktów GPS uruchom pierwszy import przed startem harmonogramu.

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

- `weather_history` przechowuje rekord na sad i godzinę pod unikatowym kluczem `(orchard_id, valid_at)`. `daily` dociąga domyślnie dwa poprzednie dni, aby uzupełnić krótką przerwę. Dłuższą przerwę uzupełnia `backfill` z odpowiednim `--history-days`.
- `weather_current` przechowuje ostatnie bieżące warunki. `weather_forecast` przechowuje trzy dni prognozy godzinowej w jednym dokumencie. W obu kolekcjach `_id` odpowiada identyfikatorowi sadu.
- Znaczniki czasu są datami UTC. Dokumenty zachowują wartości, jednostki z odpowiedzi i `fetched_at`, czyli czas rozpoczęcia pobrania. Brakujące wartości zapisujemy jako `null`. Prognozę podmieniamy atomowo, a spóźnione zapisy nie zastępują nowszych danych.

## Integracja wykresu

`GET /api/v1/weather/temperature?orchardId=<ObjectId>&range=7d` czyta `weather_history` z MongoDB. Obsługuje zakresy `24h`, `7d`, `30d`, `90d` i `1y` z `ui/API_SPEC.md` na gałęzi `ui`. Zwraca `orchardId`, `range`, `unit: "C"` i posortowane punkty z `timestamp`, `label`, `minTempC` i `maxTempC`. Po pierwszym imporcie dłuższe zakresy pokażą dostępną część historii.

Adres API w UI ustaw przez `VITE_API_BASE_URL=http://localhost:8000`. Przełącznik `VITE_USE_PLACEHOLDERS=false` włącza prawdziwe wywołania dla całego UI. Ten backend udostępnia ścieżkę wykresu temperatury.
