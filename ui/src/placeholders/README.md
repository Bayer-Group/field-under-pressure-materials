# Placeholder Data Module (`src/placeholders/`)

This directory contains **temporary placeholder data** used while the backend API is still under development.

All UI components consume data strictly through `src/api/orchardApi.ts` and never import from `src/placeholders/` directly.

## How to remove placeholders when the backend goes live

1. Configure `ui/.env`:
   ```env
   VITE_API_BASE_URL=http://localhost:8000
   VITE_USE_PLACEHOLDERS=false
   ```
2. Delete the entire `ui/src/placeholders/` directory.
3. Remove the single `import { ... } from '../placeholders'` block and fallback branches in `ui/src/api/orchardApi.ts`.
