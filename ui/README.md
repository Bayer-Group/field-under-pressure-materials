# Panel S.A.G.E.

Dashboard pobiera pogodę, kondycję sadu, lokalizacje drzew i chmurę LAS z backendu oraz MongoDB. Analityka udostępnia mapę wilgotności, NDVI, pH, teksturę gleby, ocenę drzew, prognozy i zadania Earth Engine. Zakładka Layers & Scans pozostaje pusta.

## Start całej aplikacji

Z głównego katalogu repozytorium, w aktywnym środowisku Python 3.12+ z zależnościami backendu:

```powershell
python -m pip install -r backend/requirements.txt
python db/scripts/start_weather.py --with-ui
```

Potrzebujesz MongoDB Server i MongoDB Database Tools w PATH albo parametrów `--mongo-bin` i `--tools-bin`. Launcher instaluje UI z lockfile, odtwarza pustą bazę z dołączonego checkpointu i uruchamia API oraz Vite. Podaje adres `http://127.0.0.1:5173`. Opcja `--check` wykonuje test startu i zamyka usługi.

## Praca nad samym frontendem

Uruchom backend na porcie 8000, a w katalogu `ui` wykonaj:

```powershell
npm ci
npm run dev
```

Vite przekazuje `/api` do `http://127.0.0.1:8000`. Inny adres backendu ustawia `ORCHARD_API_URL`. Przy użyciu launchera konfiguracja jest automatyczna. Aplikacja korzysta z danych API. Brak danych daje pusty stan lub komunikat błędu.

```powershell
npm run typecheck
npm run build
```

## Analityka

Sad wybiera się w górnym pasku. Przycisk pobierania danych pola rozpoczyna eksporty i analizę w tle. Wybór daty pozwala odczytać prognozę na dzisiaj i trzy kolejne dni. Mapa pokazuje warstwy i drzewa, a tabela ich oceny. Rozwijany panel Earth Engine zawiera ręczny wybór dat treningu i testu oraz prognozę do kolejnego szacowanego przelotu.

Zapisane rastry są odczytywane z MongoDB. Nowa analiza wymaga konfiguracji i logowania Google na backendzie. Wynik kondycji oznaczony jako ML estimate jest szacunkiem wymagającym kalibracji terenowej. Szczegóły opisuje [integracja ML](../docs/ML_INTEGRATION.md).

Kontrakty frontendu znajdują się w [API_SPEC.md](API_SPEC.md), `src/types/orchard.ts`, `src/api/analyticsApi.ts` i `src/api/orchardApi.ts`. Instrukcje bazy znajdują się w [db/SETUP.md](../db/SETUP.md).
