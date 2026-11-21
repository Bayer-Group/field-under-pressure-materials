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

## Moduły analityczne i Earth Engine

# Backend analizy wilgotności gleby

Uruchom w PowerShellu z głównego katalogu repozytorium, w aktywnym środowisku Python. Przygotuj `earthengine.json` i zaloguj się zgodnie z [konfiguracją projektu](../README.md#uruchomienie-z-docker-compose).

```powershell
python -m pip install -r backend/requirements.txt
$env:MONGO_URI = "mongodb://admin:admin123@localhost:27017/field_under_pressure?authSource=admin"
python -m backend.main run --host 127.0.0.1 --port 8000
```

Formularz możesz przetestować przez [Swagger UI](http://127.0.0.1:8000/docs).

## Panel analityka

- `GET /api/analytics/orchards` zwraca identyfikatory i nazwy pól z MongoDB.
- `GET /api/analytics/orchards/{orchard_id}` zwraca geometrię, wskaźniki, ocenę pola i punkty drzew.
- `GET /api/analytics/orchards/{orchard_id}/rasters/{kind}` zwraca zapisany GeoTIFF dla `moisture`, `ndvi`, `ph` albo `texture`. Najpierw odczytuje GridFS MongoDB. Starsze wyniki mogą wymagać dostępu do eksportu na Dysku Google.
- `POST /api/analytics/orchards/{orchard_id}/jobs` uruchamia analizę pola w tle. `GET /api/analytics/orchards/{orchard_id}/jobs/latest` zwraca ostatni stan zadania.

Analiza używa geometrii jednego pola i tworzy cztery eksporty w folderze `field_analytics` na Dysku Google. Trening radarowy zachowuje opóźnione okno ERA5-Land. Predykcja wybiera najnowszą dostępną scenę Sentinel-1 z ostatnich 45 dni. NDVI obejmuje 45 dni do daty sceny włącznie. pH i tekstura dotyczą głębokości 0 cm. Raport pogody i nasłonecznienia dotyczy ostatniej zakończonej doby w strefie Warszawy. Prognoza obejmuje trzy dni, gdy jest dostępna. Automatyczny import przyjmuje po jednym GeoTIFF-ie na warstwę. Zadanie zatrzymane przez restart backendu można ponowić po wygaśnięciu blokady.

Ocena jest orientacyjna. Wagi startowe to wilgotność 25%, NDVI 20%, pH 15%, tekstura 10%, nasłonecznienie 10%, temperatura 10% i prognoza wilgotności 10%. Wynik jest średnią ważoną z dostępnych czynników. Przy pokryciu poniżej 55% API zwraca status „za mało danych”. Wynik 30–59 wskazuje obserwację, a 60–100 oznacza zagrożenie. Ocena drzewa korzysta z wartości pod drzewem i wspólnych warunków pola. Porównania pH, tekstury, światła i temperatury korzystają z `CropPref.Ecology`. Panel pokazuje też opady i ET₀, które wchodzą do prognozy wilgotności. Wagi oraz progi wymagają kalibracji na pomiarach terenowych.

Grupy tekstury są uproszczeniem kodów USDA z OpenLandMap. Progi wilgotności zależą od grupy tekstury i pełnią funkcję orientacyjną. [Kody OpenLandMap](https://developers.google.com/earth-engine/datasets/catalog/OpenLandMap_SOL_SOL_TEXTURE-CLASS_USDA-TT_M_v02) · [Pojemność wodna gleby USDA](https://www.nrcs.usda.gov/sites/default/files/2022-10/nrcs142p2_051590.pdf)

## Dane przesyłane z UI

Wyślij `POST /api/soil-moisture` jako JSON z `orchardId` i datami `YYYY-MM-DD`. Przedział od `start` do `test_start` służy do treningu, a przedział od `test_start` do `end` do testu. Data `end` jest wyłączona z zakresu.

```javascript
const response = await fetch('http://127.0.0.1:8000/api/soil-moisture', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    orchardId: selectedOrchardId,
    start: startInput.value,
    test_start: testStartInput.value,
    end: endInput.value,
  }),
});
const result = await response.json();
```

Odpowiedź `202` zawiera przesłane daty oraz `tasks` z polami `id` i `name` dla każdego uruchomionego eksportu. Odczytaj stan zadania przez `GET /api/soil-moisture/tasks/{id}`. Ukończone pliki trafiają do folderu `soil_moisture` na Google Drive konta, które zalogowało się do Earth Engine na backendzie.

UI automatycznie odczytuje listę plików mapy przez `GET /api/soil-moisture/tasks/{id}/rasters` i pobiera wskazany GeoTIFF z `GET /api/soil-moisture/tasks/{id}/rasters/{fileId}`. Gdy plik pojawi się na Dysku po zakończeniu zadania, lista zawiera pliki przypisane do tej analizy. Backend używa istniejących poświadczeń Earth Engine z dostępem do Dysku Google. Jeśli Google zgłosi wyłączone Drive API, włącz je w projekcie wskazanym w komunikacie Google lub ustawionym jako projekt limitów OAuth.

Vite i Nginx przekazują `/api` do backendu z tego samego adresu co panel. Launcher automatycznie ustawia docelowy port API.

## Prognoza do następnego przelotu

Frontend może pobrać aktualną prognozę przez `GET /api/soil-moisture/forecast?orchardId=<ObjectId>`. Parametr `relative_orbit` pozwala wybrać konkretną orbitę. Ten sam przepływ można uruchomić z głównego katalogu repozytorium.

```powershell
python -m ML.soil_moisture.forecast
```

Przy każdym uruchomieniu skrypt szuka scen Sentinel‑1 z ostatnich 45 dni i preferuje najnowszą scenę obejmującą wszystkie wybrane pola. Las losowy w GEE wyznacza wilgotność początkową. Regresja Ridge uczy się godzinowych zmian wilgotności na 180 dniach danych archiwalnych ERA5‑Seamless. Następnie aktualizuje wynik godzinowo z prognozowanych opadów, temperatury i ewapotranspiracji referencyjnej (ET₀). Dane pogodowe pochodzą ze środka analizowanego obszaru i są wspólne dla wybranych pól. [Archiwum Open‑Meteo](https://open-meteo.com/en/docs/historical-weather-api) · [Prognoza Open‑Meteo](https://open-meteo.com/en/docs)

JSON podaje stan na teraz, prognozy na kolejne północe UTC i ostatnią prognozę na godzinę szacowanego przelotu. Termin przelotu wynika z wcześniejszych odstępów na tej samej orbicie. Jeśli pole nie ma ważnego odczytu SAR, jego seria jest pusta. Pole `historical_weather_validation` porównuje model z utrzymaniem stałej wilgotności w testach 24‑godzinnych na pogodzie historycznej. Do oceny prognozy operacyjnej na poziomie pola potrzebne są archiwalne prognozy dostępne w dniu predykcji i pomiary terenowe.

Bez zapisanego modelu skrypt trenuje etap radarowy w GEE na historycznych scenach wybranej orbity. Aby nie powtarzać tego treningu, wyeksportuj las do zasobów GEE i po zakończeniu eksportu podaj jego identyfikator.

```powershell
python -m ML.soil_moisture.earth_engine --export-model-asset projects/TWOJ-PROJEKT-GCP/assets/soil_moisture_rf
python -m ML.soil_moisture.forecast --model-asset projects/TWOJ-PROJEKT-GCP/assets/soil_moisture_rf
```

Dla backendu ustaw przed startem `EARTHENGINE_MODEL_ASSET` na identyfikator zasobu. Jeśli model radarowy był trenowany dla jednej orbity, podaj tę samą orbitę przy prognozie. [Zapis modelu w GEE](https://developers.google.com/earth-engine/guides/classification#save-classifiers)

Szczegóły wersjonowania ocen i odbioru integracji są w [instrukcji ML](../docs/ML_INTEGRATION.md).
