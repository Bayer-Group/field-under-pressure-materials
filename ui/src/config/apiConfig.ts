/**
 * Central API configuration and backend endpoint registry.
 *
 * When the backend becomes available:
 * 1. Set VITE_API_BASE_URL in ui/.env
 * 2. Set VITE_USE_PLACEHOLDERS=false
 * 3. Delete ui/src/placeholders/ and remove its fallback import in ui/src/api/orchardApi.ts
 */

const rawBaseUrl = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? 'http://localhost:8000';
const rawUsePlaceholders = import.meta.env.VITE_USE_PLACEHOLDERS as string | undefined;

export const apiConfig = {
  baseUrl: rawBaseUrl.replace(/\/+$/, ''),
  /** Defaults to true while backend endpoints are not yet live */
  usePlaceholders: rawUsePlaceholders !== 'false',
  requestTimeoutMs: 4000,
  binaryTimeoutMs: 25000,
  defaultOrchardId: '6b01933c1dc02a368703a020',
  defaultOrchardName: 'Grojec A',
  /** Static repo LAS asset used while backend `.las` endpoint is in placeholder mode */
  defaultLasAssetUrl: '/las/grojec.las',
} as const;

export const API_ENDPOINTS = {
  weather: {
    temperature: '/api/v1/weather/temperature',
  },
  cropPrefs: {
    list: '/api/v1/crop-prefs',
  },
  orchard: {
    health: '/api/v1/orchard/health',
    scene: '/api/v1/orchard/scene',
    pointCloud: '/api/v1/orchard/point-cloud',
    lasPointCloud: (orchardId: string) => `/api/v1/orchards/${encodeURIComponent(orchardId)}/point-cloud.las`,
    trees: '/api/v1/orchard/trees',
    treeById: (treeId: string) => `/api/v1/orchard/trees/${encodeURIComponent(treeId)}`,
    rowLines: '/api/v1/orchard/row-lines',
    byId: (orchardId: string) => `/api/v1/orchards/${encodeURIComponent(orchardId)}`,
    layout: (orchardId: string) => `/api/v1/orchards/${encodeURIComponent(orchardId)}/layout`,
  },
} as const;
