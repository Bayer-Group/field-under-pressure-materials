import { API_ENDPOINTS } from '../config/apiConfig';
import { ApiError, httpClient } from './httpClient';

export interface AnalysisDates {
  start: string;
  test_start: string;
  end: string;
}

export interface SoilMoistureTask {
  id: string;
  name: string;
}

export interface SoilMoistureTaskStatus {
  id: string;
  state: string;
  error: string | null;
}

export interface SoilMoistureRaster {
  id: string;
  name: string;
}

interface AnalysisSubmission {
  dates: AnalysisDates;
  tasks: SoilMoistureTask[];
}

export interface ForecastPoint {
  valid_at_utc: string;
  moisture_m3_m3: number;
  precipitation_mm: number;
  reference_et0_mm: number;
}

export interface SoilMoistureForecast {
  issued_at_utc: string;
  sar_acquired_at_utc: string;
  estimated_next_overpass_utc: string;
  fields: Array<{
    field_id: number;
    sar_moisture_m3_m3: number | null;
    forecasts: ForecastPoint[];
  }>;
}

export function submitAnalysis(dates: AnalysisDates, orchardId: string, signal?: AbortSignal) {
  return httpClient.post<AnalysisSubmission>(API_ENDPOINTS.soilMoisture.analysis, { ...dates, orchardId }, {
    signal,
    timeoutMs: 120_000,
  });
}

export function fetchTaskStatus(id: string, signal?: AbortSignal) {
  return httpClient.get<SoilMoistureTaskStatus>(API_ENDPOINTS.soilMoisture.task(id), {
    signal,
    timeoutMs: 15_000,
  });
}

export async function fetchRasters(taskId: string, signal?: AbortSignal) {
  const result = await httpClient.get<{ files: SoilMoistureRaster[] }>(
    API_ENDPOINTS.soilMoisture.rasters(taskId),
    { signal, timeoutMs: 30_000 },
  );
  return result.files;
}

export async function fetchRaster(taskId: string, raster: SoilMoistureRaster, signal?: AbortSignal) {
  const data = await httpClient.getBlob(API_ENDPOINTS.soilMoisture.raster(taskId, raster.id), {
    signal,
    timeoutMs: 180_000,
  });
  return new File([data], raster.name, { type: data.type });
}

export function fetchSoilMoistureForecast(orchardId: string, signal?: AbortSignal) {
  return httpClient.get<SoilMoistureForecast>(API_ENDPOINTS.soilMoisture.forecast, {
    params: { orchardId },
    signal,
    timeoutMs: 420_000,
  });
}

export function partialSubmission(error: unknown): SoilMoistureTask[] {
  const detail = error instanceof ApiError ? error.detail : null;
  if (!detail || typeof detail !== 'object' || !('submitted_tasks' in detail)) return [];
  if (!Array.isArray(detail.submitted_tasks)) return [];
  return detail.submitted_tasks.filter(
    (item: unknown): item is SoilMoistureTask =>
      !!item &&
      typeof item === 'object' &&
      'id' in item &&
      typeof item.id === 'string' &&
      'name' in item &&
      typeof item.name === 'string',
  );
}
