import { API_ENDPOINTS, apiConfig } from '../config/apiConfig';
import {
  getPlaceholderCropPrefs,
  getPlaceholderOrchardBoundary,
  getPlaceholderOrchardHealth,
  getPlaceholderOrchardScene,
  getPlaceholderSaveOrchardLayoutResponse,
  getPlaceholderTemperatureSeries,
} from '../placeholders';
import type {
  ApiResult,
  CropPrefDoc,
  ObjectIdString,
  OrchardBoundaryDoc,
  OrchardHealthSummary,
  OrchardSceneResponse,
  OrchardTree3D,
  PointCloudData,
  RowLineInput,
  RowLineRecord,
  SaveOrchardLayoutRequest,
  SaveOrchardLayoutResponse,
  TemperatureSeriesResponse,
  TimeRange,
  TreeUpdatePayload,
} from '../types/orchard';
import { httpClient } from './httpClient';

/**
 * Orchard & Weather API transfer layer.
 *
 * Every endpoint is wired to send/receive typed payloads against `apiConfig.baseUrl`.
 * While `apiConfig.usePlaceholders` is enabled (no backend running yet), failed or skipped
 * calls fall back cleanly to `src/placeholders/` and return `source: 'placeholder'`.
 */

async function withPlaceholderFallback<T>(
  endpoint: string,
  liveRequest: () => Promise<T>,
  placeholderFactory: () => T,
): Promise<ApiResult<T>> {
  if (apiConfig.usePlaceholders) {
    // Still keep the live endpoint contract explicit without throwing console errors when offline
    return {
      data: placeholderFactory(),
      source: 'placeholder',
      endpoint,
    };
  }

  const data = await liveRequest();
  return {
    data,
    source: 'api',
    endpoint,
  };
}

export async function fetchTemperatureSeries(
  range: TimeRange,
  orchardId: string = apiConfig.defaultOrchardId,
  signal?: AbortSignal,
): Promise<ApiResult<TemperatureSeriesResponse>> {
  const endpoint = API_ENDPOINTS.weather.temperature;
  return withPlaceholderFallback(
    endpoint,
    () => httpClient.get<TemperatureSeriesResponse>(endpoint, { params: { orchardId, range }, signal }),
    () => getPlaceholderTemperatureSeries(orchardId, range),
  );
}

export async function fetchOrchardHealth(
  orchardId: string = apiConfig.defaultOrchardId,
  signal?: AbortSignal,
): Promise<ApiResult<OrchardHealthSummary>> {
  const endpoint = API_ENDPOINTS.orchard.health;
  return withPlaceholderFallback(
    endpoint,
    () => httpClient.get<OrchardHealthSummary>(endpoint, { params: { orchardId }, signal }),
    () => getPlaceholderOrchardHealth(orchardId),
  );
}

export async function fetchOrchardScene(
  orchardId: string = apiConfig.defaultOrchardId,
  signal?: AbortSignal,
): Promise<ApiResult<OrchardSceneResponse>> {
  const endpoint = API_ENDPOINTS.orchard.scene;
  return withPlaceholderFallback(
    endpoint,
    () => httpClient.get<OrchardSceneResponse>(endpoint, { params: { orchardId }, signal }),
    () => getPlaceholderOrchardScene(orchardId),
  );
}

export async function fetchOrchardPointCloud(
  orchardId: string = apiConfig.defaultOrchardId,
  signal?: AbortSignal,
): Promise<ApiResult<PointCloudData>> {
  const endpoint = API_ENDPOINTS.orchard.pointCloud;
  return withPlaceholderFallback(
    endpoint,
    () => httpClient.get<PointCloudData>(endpoint, { params: { orchardId }, signal }),
    () => getPlaceholderOrchardScene(orchardId).pointCloud,
  );
}

export async function fetchOrchardTrees(
  orchardId: string = apiConfig.defaultOrchardId,
  signal?: AbortSignal,
): Promise<ApiResult<OrchardTree3D[]>> {
  const endpoint = API_ENDPOINTS.orchard.trees;
  return withPlaceholderFallback(
    endpoint,
    () => httpClient.get<OrchardTree3D[]>(endpoint, { params: { orchardId }, signal }),
    () => getPlaceholderOrchardScene(orchardId).trees,
  );
}

export async function fetchRowLines(
  orchardId: string = apiConfig.defaultOrchardId,
  signal?: AbortSignal,
): Promise<ApiResult<RowLineRecord[]>> {
  const endpoint = API_ENDPOINTS.orchard.rowLines;
  return withPlaceholderFallback(
    endpoint,
    () => httpClient.get<RowLineRecord[]>(endpoint, { params: { orchardId }, signal }),
    () => getPlaceholderOrchardScene(orchardId).rowLines,
  );
}

/**
 * Input transfer endpoint prepared for the upcoming Row-Line Drawing screen:
 * sends user-drawn row polylines + tree spacing so the backend computes 3D tree placements.
 */
export async function submitRowLines(
  payload: RowLineInput[],
  signal?: AbortSignal,
): Promise<ApiResult<RowLineRecord[]>> {
  const endpoint = API_ENDPOINTS.orchard.rowLines;
  return withPlaceholderFallback(
    endpoint,
    () => httpClient.post<RowLineRecord[]>(endpoint, { rows: payload }, { signal }),
    () =>
      payload.map((item, idx) => ({
        ...item,
        id: `row-draft-${idx + 1}`,
        createdAt: new Date().toISOString(),
      })),
  );
}

/**
 * Input transfer endpoint prepared for updating individual tree metadata or manual overrides.
 */
export async function updateTreeMetadata(
  treeId: string,
  payload: TreeUpdatePayload,
  signal?: AbortSignal,
): Promise<ApiResult<{ id: string; updated: boolean }>> {
  const endpoint = API_ENDPOINTS.orchard.treeById(treeId);
  return withPlaceholderFallback(
    endpoint,
    () => httpClient.patch<{ id: string; updated: boolean }>(endpoint, payload, { signal }),
    () => ({ id: treeId, updated: true }),
  );
}

/**
 * Fetches available tree species definitions from MongoDB `CropPref` collection.
 */
export async function fetchCropPrefs(signal?: AbortSignal): Promise<ApiResult<CropPrefDoc[]>> {
  const endpoint = API_ENDPOINTS.cropPrefs.list;
  return withPlaceholderFallback(
    endpoint,
    () => httpClient.get<CropPrefDoc[]>(endpoint, { signal }),
    () => getPlaceholderCropPrefs(),
  );
}

/**
 * Fetches orchard parcel geometry and existing rows from MongoDB `Orchard` collection.
 * For a first-time user, `rows` starts empty so they can draw rows onto the field shape.
 */
export async function fetchOrchardBoundary(
  orchardId: ObjectIdString = apiConfig.defaultOrchardId,
  signal?: AbortSignal,
): Promise<ApiResult<OrchardBoundaryDoc>> {
  const endpoint = API_ENDPOINTS.orchard.byId(orchardId);
  return withPlaceholderFallback(
    endpoint,
    () => httpClient.get<OrchardBoundaryDoc>(endpoint, { signal }),
    () => getPlaceholderOrchardBoundary(orchardId),
  );
}

/**
 * Persists user-drawn rows (`Orchard.rows` with start/end points & ordered `treeIds`)
 * and calculated individual trees (`Tree` collection with coordinates, `healthIndex: null`,
 * and `species` ObjectId pointing to `CropPref`).
 */
export async function saveOrchardLayout(
  payload: SaveOrchardLayoutRequest,
  signal?: AbortSignal,
): Promise<ApiResult<SaveOrchardLayoutResponse>> {
  const endpoint = API_ENDPOINTS.orchard.layout(payload.orchardId);
  return withPlaceholderFallback(
    endpoint,
    () => httpClient.post<SaveOrchardLayoutResponse>(endpoint, payload, { signal }),
    () => getPlaceholderSaveOrchardLayoutResponse(payload),
  );
}
