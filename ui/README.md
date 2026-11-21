# Frontend Field Under Pressure

Dashboard pokazuje mapę wilgotności gleby, stan eksportów GEE i prognozy do kolejnego przelotu. Temperatury, zdrowie sadu i widok 3D w trybie demonstracyjnym korzystają z danych przykładowych.

## Uruchamianie

Pełny stos znajdziesz w [README projektu](../README.md#uruchomienie-z-docker-compose). Przy pracy nad samym frontendem uruchom w katalogu `ui`:

```powershell
npm ci
npm run dev
```

Build & type-check:

```bash
npm run typecheck
npm run build
```

## Analityka pól

W zakładce **Analityka** wybierz pole z kolekcji `Orchard` i kliknij **Pobierz dane pola**. Backend uruchomi eksporty wilgotności, NDVI, pH i tekstury. Gdy pojawi się GeoTIFF, backend odczyta wartości pola i drzew, a panel pokaże je i przełączy mapę na nową warstwę. Ukończone warstwy można przeglądać po odświeżeniu strony i po błędzie innego eksportu. Wybierz drzewo na mapie lub w tabeli, aby sprawdzić przypisany piksel Sentinel‑1 i dostępne odczyty. Po zapisaniu rastrów backend uzupełni pogodę, nasłonecznienie i dostępną prognozę. Pola DEMO od razu pokazują dane przykładowe.

Jeśli chcesz samodzielnie wybrać daty eksportu, możesz wykonać [analizę pola w CLI](../db/SETUP.md#podsumowanie-pola-w-orchard). Panel pobiera zapisane GeoTIFF-y z Google Drive według nazw w `Orchard.analysis`. Gdy plik jest niedostępny lub nazwa jest powielona na Dysku, można wczytać lokalny GeoTIFF do podglądu.

## API Endpoints & Placeholder Architecture

Pełna specyfikacja wszystkich endpointów, parametrów, schematów MongoDB oraz podkładu satelitarnego znajduje się w [`API_SPEC.md`](./API_SPEC.md).

All backend transfer contracts live in:
- `src/config/apiConfig.ts` — base URL, `VITE_USE_PLACEHOLDERS` toggle, and endpoint paths
- `src/types/orchard.ts` — request & response TypeScript models
- `src/api/httpClient.ts` — typed HTTP transport (`GET`, `POST`, `PATCH`, `DELETE`)
- `src/api/orchardApi.ts` — endpoint functions consumed by UI components

Prepared endpoints:
- `GET /api/v1/weather/temperature?orchardId=...&range=24h|7d|30d|90d|1y`
- `GET /api/v1/orchard/health?orchardId=...`
- `GET /api/v1/orchard/scene?orchardId=...`
- `GET /api/v1/orchard/point-cloud?orchardId=...`
- `GET /api/v1/orchard/trees?orchardId=...`
- `GET /api/v1/orchard/row-lines?orchardId=...`
- `GET /api/v1/crop-prefs` (`CropPref` collection — tree species catalog)
- `GET /api/v1/orchards/:orchardId` (`Orchard` collection — field polygon geometry & rows)
- `POST /api/v1/orchards/:orchardId/layout` (saves `Orchard.rows` with start/end + ordered `treeIds` and inserts calculated `Tree` docs with `coordinates`, `healthIndex: null`, `species: ObjectId`)
- `PATCH /api/v1/orchard/trees/:treeId`

### Removing placeholders once the backend is live

All temporary placeholder generators are strictly isolated in `src/placeholders/`.
To switch cleanly to the real backend:
1. Copy `.env.example` to `.env` and set `VITE_USE_PLACEHOLDERS=false` and `VITE_API_BASE_URL=<backend_url>`.
2. Delete `src/placeholders/` and remove the single placeholder import/fallback in `src/api/orchardApi.ts`.
