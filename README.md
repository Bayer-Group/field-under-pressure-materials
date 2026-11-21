# S.A.G.E.

Panel pogody, kondycji drzew i analizy wilgotności gleby na podstawie Sentinel‑1 i ERA5‑Land. Earth Engine trenuje model i eksportuje GeoTIFF na Google Drive. Backend pobiera gotowy raster, a UI pokazuje go na mapie. MongoDB przechowuje granice pól, drzewa i obserwacje przypisane do pikseli.

## Uruchomienie z Docker Compose

Z głównego katalogu repozytorium skopiuj konfigurację i wpisz swój `project_id` do `earthengine.json`. Plik lokalny jest ignorowany przez Git.

```powershell
Copy-Item earthengine.example.json earthengine.json
python -m pip install earthengine-api
earthengine authenticate
docker compose -f docker-compose.yml -f docker-compose.gee.yml up -d --build
```

Otwórz [UI](http://127.0.0.1:5173) lub [Swagger API](http://127.0.0.1:8000/docs). W **Analityce** wybierz pole i kliknij **Pobierz dane pola**, aby rozpocząć eksporty i automatyczny zapis wyników. Konto Earth Engine musi mieć dostęp do Google Drive. Polecenie `docker compose up -d --build` uruchamia panel i odtwarza rzeczywisty zrzut MongoDB. Odczyt zapisanych danych i lokalny podgląd GeoTIFF działają bez logowania do Earth Engine.

Nadpisania konfiguracji

| Ustawienie | Zastosowanie |
| --- | --- |
| `EARTHENGINE_PROJECT` | Nadpisuje `project_id` z pliku JSON. Argument `--project` w CLI ma najwyższy priorytet. |
| `EARTHENGINE_CREDENTIALS_FILE` | Ścieżka do pliku logowania na hoście. Domyślnie `~/.config/earthengine/credentials`. |
| `EARTHENGINE_MODEL_ASSET` | Identyfikator zapisanego modelu radarowego używanego w prognozie API. |
| `MONGO_ORCHARD_ID` | Ogranicza polecenia CLI i starsze zadania wilgotności do wybranego pola. |
| `MONGO_URI` | Adres MongoDB dla skryptów i backendu uruchamianych bezpośrednio na hoście. |
| `BACKEND_MONGO_URI` | Opcjonalny adres MongoDB dla backendu w Dockerze. Domyślnie backend łączy się z usługą `mongodb`. |
| `UI_PORT`, `BACKEND_PORT`, `MONGO_PORT` | Porty udostępnione na hoście. |

## Kod i dane

| Katalog | Zawartość |
| --- | --- |
| [`ui/`](ui/README.md) | Panel React oraz lokalny i automatyczny podgląd GeoTIFF |
| [`backend/`](backend/README.md) | API FastAPI, eksporty GEE i prognoza wilgotności |
| [`ML/soil_moisture/`](ML/soil_moisture/README.md) | Skrypty ML, import pól i analiza drzew |
| [`db/`](db/SETUP.md) | MongoDB, import do `Orchard` i struktura danych drzew |
| [Materiały hackathonu](docs/HACKATHON.md) | Instrukcje organizatora, źródła danych i notebook startowy |

## Start lokalny MongoDB, API i panelu

Z głównego katalogu, z Pythonem 3.12+ oraz Node.js i npm lub pnpm, uruchom:

```powershell
python -m pip install -r backend/requirements.txt
python db/scripts/start_weather.py --with-ui
```

Dodaj `--mongo-bin` i `--tools-bin`, jeśli MongoDB Server i Database Tools są poza PATH. Skrypt używa zrzutu `230119`, rozpoczyna aktualizacje pogody, uruchamia API oraz Vite. Dokumentacja opisuje konfigurację Earth Engine i ocen. [Integracja analityki](docs/ML_INTEGRATION.md)

## Praca lokalna

Zainstaluj zależności w środowisku Python 3.12. W Dockerze Python i Node są dostarczane przez obrazy.

```powershell
python -m pip install -r requirements.txt
python -m pip install pre-commit
python -m pre_commit install
```

Pre-commit sprawdza Python przez Ruff i nazwy commitów według Conventional Commits. Instalacja pakietów do szablonu [`ML/template.ipynb`](ML/template.ipynb) jest opcjonalna.

```powershell
python -m pip install -r ML/requirements-notebook.txt
```
