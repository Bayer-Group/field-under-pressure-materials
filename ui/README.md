# Field Under Pressure — UI (TypeScript Web App)

Web dashboard for orchard monitoring, microclimate analytics, tree health diagnostics, and 3D point-cloud + individual tree visualization.

## Running locally

```bash
cd ui
npm install
npm run dev
```

Build & type-check:

```bash
npm run typecheck
npm run build
```

## API Endpoints & Placeholder Architecture

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
- `POST /api/v1/orchard/row-lines` (prepared for the upcoming Row Line Editor screen)
- `PATCH /api/v1/orchard/trees/:treeId`

### Removing placeholders once the backend is live

All temporary placeholder generators are strictly isolated in `src/placeholders/`.
To switch cleanly to the real backend:
1. Copy `.env.example` to `.env` and set `VITE_USE_PLACEHOLDERS=false` and `VITE_API_BASE_URL=<backend_url>`.
2. Delete `src/placeholders/` and remove the single placeholder import/fallback in `src/api/orchardApi.ts`.
