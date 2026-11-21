export type TimeRange = '24h' | '7d' | '30d' | '90d' | '1y';

export type HealthStatus = 'dead' | 'poor' | 'moderate' | 'healthy';

export type DataSourceMode = 'api' | 'placeholder';

export interface ApiResult<T> {
  data: T;
  source: DataSourceMode;
  endpoint: string;
}

export interface TemperaturePoint {
  timestamp: string; // ISO-8601
  label: string;
  minTempC: number;
  maxTempC: number;
}

export interface TemperatureSeriesResponse {
  orchardId: string;
  range: TimeRange;
  unit: 'C';
  points: TemperaturePoint[];
}

export interface HealthDistribution {
  dead: number;
  poor: number;
  moderate: number;
  healthy: number;
}

export interface OrchardHealthSummary {
  orchardId: string;
  updatedAt: string;
  /** Averaged orchard health score on a 0-100 scale */
  averageScore: number;
  /** Categorized overall orchard health */
  overallStatus: HealthStatus;
  totalTrees: number;
  distribution: HealthDistribution;
}

export interface Point3D {
  x: number;
  y: number;
  z: number;
}

export interface GeoCoord {
  lat: number;
  lng: number;
}

export interface RowLineInput {
  orchardId: string;
  rowLabel: string;
  /** Polyline vertices drawn by the user on the map screen */
  vertices: Point3D[];
  /** Distance between trees along the drawn line (meters) */
  treeSpacingMeters: number;
}

export interface RowLineRecord extends RowLineInput {
  id: string;
  createdAt: string;
}

export interface OrchardTree3D {
  id: string;
  rowId: string;
  rowLabel: string;
  indexInRow: number;
  /** 3D position calculated along the user-drawn row line and projected onto terrain */
  position: Point3D;
  geo: GeoCoord;
  heightMeters: number;
  canopyRadiusMeters: number;
  /** Individual tree health score 0-100 */
  healthScore: number;
  healthStatus: HealthStatus;
}

export interface PointCloudData {
  orchardId: string;
  pointCount: number;
  /** Interleaved XYZ coordinates: [x0, y0, z0, x1, y1, z1, ...] */
  positions: number[];
  /** Normalized RGB colors in [0, 1]: [r0, g0, b0, ...] */
  colors: number[];
  bounds: {
    min: Point3D;
    max: Point3D;
  };
}

export interface OrchardSceneResponse {
  orchardId: string;
  orchardName: string;
  pointCloud: PointCloudData;
  trees: OrchardTree3D[];
  rowLines: RowLineRecord[];
}

export interface TreeUpdatePayload {
  healthStatus?: HealthStatus;
  healthScore?: number;
  notes?: string;
}

export function scoreToHealthStatus(score: number): HealthStatus {
  if (score <= 15) return 'dead';
  if (score <= 45) return 'poor';
  if (score <= 72) return 'moderate';
  return 'healthy';
}
