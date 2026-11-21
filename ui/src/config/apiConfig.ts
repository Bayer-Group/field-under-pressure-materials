/** Common API configuration and endpoint registry. */

const rawBaseUrl = import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000';
const rawUsePlaceholders = import.meta.env.VITE_USE_PLACEHOLDERS as string | undefined;

export const apiConfig = {
  baseUrl: rawBaseUrl.replace(/\/+$/, ''),
  /** Controls orchard and temperature demo widgets. */
  usePlaceholders: rawUsePlaceholders !== 'false',
  requestTimeoutMs: 4000,
  defaultOrchardId: '6b01933c1dc02a368703a020',
} as const;

export const API_ENDPOINTS = {
  soilMoisture: {
    analysis: '/api/soil-moisture',
    task: (id: string) => `/api/soil-moisture/tasks/${encodeURIComponent(id)}`,
    forecast: '/api/soil-moisture/forecast',
  },
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
    trees: '/api/v1/orchard/trees',
    treeById: (treeId: string) => `/api/v1/orchard/trees/${encodeURIComponent(treeId)}`,
    rowLines: '/api/v1/orchard/row-lines',
    byId: (orchardId: string) => `/api/v1/orchards/${encodeURIComponent(orchardId)}`,
    layout: (orchardId: string) => `/api/v1/orchards/${encodeURIComponent(orchardId)}/layout`,
  },
} as const;
