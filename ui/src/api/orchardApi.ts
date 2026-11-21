import { API_ENDPOINTS, apiConfig } from "../config/apiConfig";
import type {
  ApiResult,
  CropPrefDoc,
  ObjectIdString,
  OrchardBoundaryDoc,
  OrchardHealthSummary,
  OrchardOption,
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
  UserPreferencesDoc,
} from "../types/orchard";
import { httpClient } from "./httpClient";
async function fetchWidgetData<T>(
  endpoint: string,
  liveRequest: () => Promise<T>,
): Promise<ApiResult<T>> {
  const data = await liveRequest();
  return {
    data,
    source: "api",
    endpoint,
  };
}
export async function fetchTemperatureSeries(
  range: TimeRange,
  orchardId: string = apiConfig.defaultOrchardId,
  signal?: AbortSignal,
): Promise<ApiResult<TemperatureSeriesResponse>> {
  const endpoint = API_ENDPOINTS.weather.temperature;
  return fetchWidgetData(endpoint, () =>
    httpClient.get<TemperatureSeriesResponse>(endpoint, {
      params: { orchardId, range },
      signal,
    }),
  );
}
export async function fetchOrchardHealth(
  orchardId: string = apiConfig.defaultOrchardId,
  signal?: AbortSignal,
): Promise<ApiResult<OrchardHealthSummary>> {
  const endpoint = API_ENDPOINTS.orchard.health;
  return fetchWidgetData(endpoint, () =>
    httpClient.get<OrchardHealthSummary>(endpoint, {
      params: { orchardId },
      signal,
    }),
  );
}
export async function fetchOrchardScene(
  orchardId: string = apiConfig.defaultOrchardId,
  signal?: AbortSignal,
): Promise<ApiResult<OrchardSceneResponse>> {
  const endpoint = API_ENDPOINTS.orchard.scene;
  return fetchWidgetData(endpoint, () =>
    httpClient.get<OrchardSceneResponse>(endpoint, {
      params: { orchardId },
      signal,
    }),
  );
}
export async function fetchOrchardPointCloud(
  orchardId: string = apiConfig.defaultOrchardId,
  signal?: AbortSignal,
): Promise<ApiResult<PointCloudData>> {
  const endpoint = API_ENDPOINTS.orchard.pointCloud;
  return fetchWidgetData(endpoint, () =>
    httpClient.get<PointCloudData>(endpoint, { params: { orchardId }, signal }),
  );
}
function isValidLasMagic(buffer: ArrayBuffer): boolean {
  if (buffer.byteLength < 227) return false;
  const bytes = new Uint8Array(buffer, 0, 4);
  return (
    bytes[0] === 0x4c &&
    bytes[1] === 0x41 &&
    bytes[2] === 0x53 &&
    bytes[3] === 0x46
  ); // "LASF"
}
/**
 * Fetches binary `.las` point cloud for an orchard (`<orchardId>.las`).
 * Returns `data: null` when no `.las` file exists for that orchard so the 3D viewer
 * seamlessly renders the geometric parcel + rows + trees fallback.
 */
export async function fetchOrchardLasBuffer(
  orchardId: ObjectIdString = apiConfig.defaultOrchardId,
  signal?: AbortSignal,
): Promise<ApiResult<ArrayBuffer | null>> {
  const endpoint = API_ENDPOINTS.orchard.lasPointCloud(orchardId);
  try {
    const buffer = await httpClient.getArrayBuffer(endpoint, { signal });
    return {
      data: isValidLasMagic(buffer) ? buffer : null,
      source: "api",
      endpoint,
    };
  } catch (err) {
    if ((err as Error).name === "AbortError") throw err;
    return {
      data: null,
      source: "api",
      endpoint,
    };
  }
}
export async function fetchOrchardTrees(
  orchardId: string = apiConfig.defaultOrchardId,
  signal?: AbortSignal,
): Promise<ApiResult<OrchardTree3D[]>> {
  const endpoint = API_ENDPOINTS.orchard.trees;
  return fetchWidgetData(endpoint, () =>
    httpClient.get<OrchardTree3D[]>(endpoint, {
      params: { orchardId },
      signal,
    }),
  );
}
export async function fetchRowLines(
  orchardId: string = apiConfig.defaultOrchardId,
  signal?: AbortSignal,
): Promise<ApiResult<RowLineRecord[]>> {
  const endpoint = API_ENDPOINTS.orchard.rowLines;
  return fetchWidgetData(endpoint, () =>
    httpClient.get<RowLineRecord[]>(endpoint, {
      params: { orchardId },
      signal,
    }),
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
  return fetchWidgetData(endpoint, () =>
    httpClient.post<RowLineRecord[]>(endpoint, { rows: payload }, { signal }),
  );
}
/**
 * Input transfer endpoint prepared for updating individual tree metadata or manual overrides.
 */
export async function updateTreeMetadata(
  treeId: string,
  payload: TreeUpdatePayload,
  signal?: AbortSignal,
): Promise<
  ApiResult<{
    id: string;
    updated: boolean;
  }>
> {
  const endpoint = API_ENDPOINTS.orchard.treeById(treeId);
  return fetchWidgetData(endpoint, () =>
    httpClient.patch<{
      id: string;
      updated: boolean;
    }>(endpoint, payload, { signal }),
  );
}
/**
 * Fetches available tree species definitions from MongoDB `CropPref` collection.
 */
export async function fetchCropPrefs(
  signal?: AbortSignal,
): Promise<ApiResult<CropPrefDoc[]>> {
  const endpoint = API_ENDPOINTS.cropPrefs.list;
  return fetchWidgetData(endpoint, () =>
    httpClient.get<CropPrefDoc[]>(endpoint, { signal }),
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
  return fetchWidgetData(endpoint, () =>
    httpClient.get<OrchardBoundaryDoc>(endpoint, { signal }),
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
  return fetchWidgetData(endpoint, () =>
    httpClient.post<SaveOrchardLayoutResponse>(endpoint, payload, { signal }),
  );
}
/**
 * Fetches all available orchards (`_id`, `name`, `areaHectares`, `centroid`) for the topbar selector.
 */
export async function fetchOrchardsList(
  signal?: AbortSignal,
): Promise<ApiResult<OrchardOption[]>> {
  const endpoint = API_ENDPOINTS.orchard.list;
  return fetchWidgetData(endpoint, () =>
    httpClient.get<OrchardOption[]>(endpoint, { signal }),
  );
}
/**
 * Fetches persisted `User.preferences` (`theme`: Light|Dark|OS, `lang`, `activeOrchardId`).
 */
export async function fetchUserPreferences(
  userId: ObjectIdString = apiConfig.defaultUserId,
  signal?: AbortSignal,
): Promise<ApiResult<UserPreferencesDoc>> {
  const endpoint = API_ENDPOINTS.users.preferences(userId);
  return fetchWidgetData(endpoint, () =>
    httpClient.get<UserPreferencesDoc>(endpoint, { signal }),
  );
}
/**
 * Persists user UI preferences (`theme`, `lang`, `activeOrchardId`) to `User.preferences`.
 */
export async function updateUserPreferences(
  preferences: Partial<UserPreferencesDoc>,
  userId: ObjectIdString = apiConfig.defaultUserId,
  signal?: AbortSignal,
): Promise<ApiResult<UserPreferencesDoc>> {
  const endpoint = API_ENDPOINTS.users.preferences(userId);
  return fetchWidgetData(endpoint, () =>
    httpClient.patch<UserPreferencesDoc>(endpoint, preferences, { signal }),
  );
}
