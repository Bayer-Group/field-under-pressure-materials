# Backend analizy wilgotności gleby

Uruchom w PowerShellu z głównego katalogu repozytorium, w aktywnym środowisku Python. Przygotuj `earthengine.json` i zaloguj się zgodnie z [konfiguracją projektu](../README.md#uruchomienie-z-docker-compose).

```powershell
python -m pip install -r backend/requirements.txt
$env:MONGO_URI = "mongodb://admin:admin123@localhost:27017/field_under_pressure?authSource=admin"
python -m uvicorn backend.main:my_app --host 127.0.0.1 --port 8000
```

Formularz możesz przetestować przez [Swagger UI](http://127.0.0.1:8000/docs).

## Panel analityka

- `GET /api/analytics/orchards` zwraca identyfikatory i nazwy pól z MongoDB.
- `GET /api/analytics/orchards/{orchard_id}` zwraca geometrię, wskaźniki, ocenę pola i punkty drzew.
- `GET /api/analytics/orchards/{orchard_id}/rasters/{kind}` zwraca zapisany GeoTIFF dla `moisture` albo `ndvi`.
- `POST /api/analytics/orchards/{orchard_id}/jobs` uruchamia analizę pola w tle. `GET /api/analytics/orchards/{orchard_id}/jobs/latest` zwraca ostatni stan zadania.

Analiza używa geometrii jednego pola i tworzy cztery eksporty w folderze `field_analytics` na Dysku Google. Wilgotność opiera się na scenie z 45-dniowego okna kończącego się 14 dni przed uruchomieniem, aby uwzględnić dostępność ERA5-Land. NDVI obejmuje 45 dni do daty sceny włącznie. pH i tekstura dotyczą głębokości 0 cm. Raport pogody i nasłonecznienia dotyczy ostatniej zakończonej doby w strefie Warszawy. Prognoza obejmuje trzy dni, gdy jest dostępna. Automatyczny import przyjmuje po jednym GeoTIFF-ie na warstwę. Zadanie zatrzymane przez restart backendu można ponowić po wygaśnięciu blokady.

Ocena jest orientacyjna. Wagi startowe to wilgotność 25%, NDVI 20%, pH 15%, tekstura 10%, nasłonecznienie 10%, temperatura 10% i prognoza wilgotności 10%. Wynik jest średnią ważoną z dostępnych czynników. Przy pokryciu poniżej 55% API zwraca status „za mało danych”. Wynik 30–59 wskazuje obserwację, a 60–100 oznacza zagrożenie. Ocena drzewa korzysta z wartości pod drzewem i wspólnych warunków pola. Porównania pH, tekstury, światła i temperatury korzystają z `CropPref.Ecology`. Panel pokazuje też opady i ET₀, które wchodzą do prognozy wilgotności. Wagi oraz progi wymagają kalibracji na pomiarach terenowych.

Grupy tekstury są uproszczeniem kodów USDA z OpenLandMap. Progi wilgotności zależą od grupy tekstury i pełnią funkcję orientacyjną. [Kody OpenLandMap](https://developers.google.com/earth-engine/datasets/catalog/OpenLandMap_SOL_SOL_TEXTURE-CLASS_USDA-TT_M_v02) · [Pojemność wodna gleby USDA](https://www.nrcs.usda.gov/sites/default/files/2022-10/nrcs142p2_051590.pdf)

## Dane przesyłane z UI

Wyślij `POST /api/soil-moisture` jako JSON z datami `YYYY-MM-DD`. Przedział od `start` do `test_start` służy do treningu, a przedział od `test_start` do `end` do testu. Data `end` jest wyłączona z zakresu.

```javascript
const response = await fetch('http://127.0.0.1:8000/api/soil-moisture', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    start: startInput.value,
    test_start: testStartInput.value,
    end: endInput.value,
  }),
});
const result = await response.json();
```

Odpowiedź `202` zawiera przesłane daty oraz `tasks` z polami `id` i `name` dla każdego uruchomionego eksportu. Odczytaj stan zadania przez `GET /api/soil-moisture/tasks/{id}`. Ukończone pliki trafiają do folderu `soil_moisture` na Google Drive konta, które zalogowało się do Earth Engine na backendzie.

UI automatycznie odczytuje listę plików mapy przez `GET /api/soil-moisture/tasks/{id}/rasters` i pobiera wskazany GeoTIFF z `GET /api/soil-moisture/tasks/{id}/rasters/{fileId}`. Gdy plik pojawi się na Dysku po zakończeniu zadania, lista zawiera pliki przypisane do tej analizy. Backend używa istniejących poświadczeń Earth Engine z dostępem do Dysku Google. Jeśli Google zgłosi wyłączone Drive API, włącz je w projekcie wskazanym w komunikacie Google lub ustawionym jako projekt limitów OAuth.

Backend dopuszcza lokalny frontend na portach 3000 i 5173. Dla innego adresu ustaw przed startem np. `$env:FRONTEND_ORIGINS = "http://localhost:5500"`. Kilka adresów można podać po przecinku.

## Prognoza do następnego przelotu

Frontend może pobrać aktualną prognozę przez `GET /api/soil-moisture/forecast`. Parametr `relative_orbit` pozwala wybrać konkretną orbitę. Ten sam przepływ można uruchomić z głównego katalogu repozytorium.

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
