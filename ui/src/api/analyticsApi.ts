import { httpClient } from './httpClient';
import type { HealthStatus } from '../types/orchard';

export type RiskStatus = 'low' | 'watch' | 'high' | 'insufficient';
export type RiskFactor = 'moisture' | 'ndvi' | 'ph' | 'texture' | 'solar' | 'temperature' | 'forecast';
export const RASTER_KINDS = ['moisture', 'ndvi', 'ph', 'texture'] as const;
export type RasterKind = typeof RASTER_KINDS[number];
export type SolarLevel = 'poor' | 'moderate' | 'good' | 'excellent';
export type SampleStatus = 'sampled' | 'forecasted' | 'no_forecast' | 'no_soil_data' | 'outside_raster' | 'outside_orchard' | 'invalid_coordinates';
type ForecastMoistureStatus = 'available' | 'missing_sar' | 'stale_sar' | 'unavailable';

export type FieldJobStage = 'preparing' | 'exporting' | 'downloading' | 'saving';

export interface FieldJob {
  id: string;
  state: FieldJobStage | 'completed' | 'failed';
  done: number;
  total: number;
  error: string | null;
  ready_layers: RasterKind[];
  layer_errors: Partial<Record<RasterKind, string>>;
  export_status: Partial<Record<RasterKind, { state: string; attempt: number | null }>>;
}

export interface Risk {
  score: number | null;
  status: RiskStatus;
  coverage: number;
  min_coverage: number;
  factors: { id: RiskFactor; weight: number; severity: number | null }[];
}

export interface AnalystFieldOption {
  id: string;
  name: string;
  tree_count: number;
}

export interface AnalysisTree {
  id: string;
  species: string | null;
  coordinates: [number, number] | null;
  risk: Risk;
  healthScore: number | null;
  healthStatus: HealthStatus | null;
  healthSource: 'field' | 'estimate' | null;
  healthAssessedAt: string | null;
  healthCoverage: number;
  pixel_analysis: {
    status: SampleStatus | null;
    pixel: { row: number | null; column: number | null; crs: string | null } | null;
    moisture_m3_m3: number | null;
    ndvi: number | null;
    ph: number | null;
    texture: number | null;
    solar: SolarLevel | null;
  };
}

export interface AnalystField {
  id: string;
  name: string;
  geometry: object;
  risk: Risk;
  trees: AnalysisTree[];
  forecast_day?: {
    date_local: string;
    issued_at_utc: string;
    anchor_at_utc: string | null;
    moisture_status: ForecastMoistureStatus;
  } | null;
  metrics: {
    moisture: { mean_m3_m3: number | null; valid_pixels: number; acquired_at_utc: string | null; raster: string | null; valid_at_utc?: string | null } | null;
    ndvi: { mean: number | null; valid_pixels: number; raster: string | null } | null;
    ph: { mean: number | null; depth_cm: number | null; valid_pixels: number; raster: string | null } | null;
    texture: { dominant_class: number | null; depth_cm: number | null; valid_pixels: number; raster: string | null } | null;
    solar: { level: SolarLevel | null; date_local: string | null; energy_kwh_m2: number | null; clear_sky_kwh_m2: number | null; clear_sky_fraction: number | null } | null;
    weather: { mean_temperature_c: number | null; precipitation_mm: number | null; reference_et0_mm: number | null; date_local: string | null; mean_humidity_percent?: number | null; mean_wind_km_h?: number | null; mean_cloud_percent?: number | null } | null;
    forecast_min_m3_m3: number | null;
  };
}

const fieldsUrl = '/api/analytics/orchards';
const fieldUrl = (fieldId: string) => `${fieldsUrl}/${encodeURIComponent(fieldId)}`;

export function fetchAnalystFields(signal?: AbortSignal) {
  return httpClient.get<AnalystFieldOption[]>(fieldsUrl, { signal, timeoutMs: 15_000 });
}

export function fetchAnalystField(fieldId: string, signal?: AbortSignal) {
  return httpClient.get<AnalystField>(fieldUrl(fieldId), { signal, timeoutMs: 20_000 });
}

export function fetchAnalystForecast(fieldId: string, day: string, signal?: AbortSignal) {
  return httpClient.get<AnalystField>(`${fieldUrl(fieldId)}/forecast/${day}`, { signal, timeoutMs: 180_000 });
}

export function startFieldJob(fieldId: string, signal?: AbortSignal) {
  return httpClient.post<FieldJob>(`${fieldUrl(fieldId)}/jobs`, {}, { signal, timeoutMs: 20_000 });
}

export function fetchFieldJob(fieldId: string, signal?: AbortSignal) {
  return httpClient.get<FieldJob | null>(`${fieldUrl(fieldId)}/jobs/latest`, { signal, timeoutMs: 15_000 });
}

export async function fetchAnalystRaster(fieldId: string, kind: RasterKind, name: string, signal?: AbortSignal, day?: AnalystField['forecast_day']) {
  const projected = kind === 'moisture' ? day : null;
  const url = projected ? `${fieldUrl(fieldId)}/forecast/${projected.date_local}/raster` : `${fieldUrl(fieldId)}/rasters/${kind}`;
  const data = await httpClient.getBlob(url, { signal, timeoutMs: 180_000, params: projected ? { issued: projected.issued_at_utc, name } : undefined });
  return new File([data], name, { type: data.type });
}
