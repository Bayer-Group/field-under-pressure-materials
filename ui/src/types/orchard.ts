export type TimeRange = '24h' | '7d' | '30d' | '90d' | '1y';

export type HealthStatus = 'dead' | 'poor' | 'moderate' | 'healthy';

export type DataSourceMode = 'api' | 'placeholder';

/** 24-character hexadecimal MongoDB ObjectId string */
export type ObjectIdString = string;

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

/* ==========================================================================
   MongoDB-aligned Row Line Editor contracts: CropPref, Tree, Orchard
   ========================================================================== */

/** Document from MongoDB collection `CropPref` */
export interface CropPrefDoc {
  _id: ObjectIdString;
  code: string;
  /** Botanical species name matching MongoDB `CropPref.species` */
  scientificName: string;
  namePl: string;
  nameEn: string;
  variety: string;
  category: 'pome' | 'stone' | 'nut';
  recommendedSpacingMeters: number;
  colorHex: string;
}

/** Document to be persisted into MongoDB collection `Tree` */
export interface TreeDoc {
  _id: ObjectIdString;
  orchardId: ObjectIdString;
  coordinates: GeoCoord;
  /** Computed asynchronously by the backend; null when created by UI */
  healthIndex: number | null;
  /** Reference (`ObjectId`) to `CropPref._id` */
  species: ObjectIdString;
}

/**
 * Row entry embedded inside MongoDB collection `Orchard.rows`.
 * Stores the two endpoints (`start`, `end`) plus ordered `treeIds` referencing `Tree._id`.
 */
export interface OrchardRowDoc {
  id: string;
  label: string;
  start: GeoCoord;
  end: GeoCoord;
  averageSpacingMeters: number;
  defaultSpecies: ObjectIdString;
  /** Ordered list of MongoDB ObjectIds pointing to documents in the `Tree` collection */
  treeIds: ObjectIdString[];
}

/** Georeferenced satellite/orthophoto image aligned in WGS 84 (EPSG:4326) */
export interface SatelliteOverlayMeta {
  imageUrl: string;
  crs: 'EPSG:4326';
  bounds: {
    westLng: number;
    southLat: number;
    eastLng: number;
    northLat: number;
  };
  sourceLabel: string;
}

/** Orchard parcel geometry & current rows from MongoDB collection `Orchard` */
export interface OrchardBoundaryDoc {
  _id: ObjectIdString;
  name: string;
  locationLabel: string;
  /** Ordered boundary polygon vertices in WGS 84 / EPSG:4326 (closed implicitly) */
  geometry: GeoCoord[];
  center: GeoCoord;
  areaHectares: number;
  shapeAreaM2?: number;
  shapeLengthM?: number;
  satelliteOverlay?: SatelliteOverlayMeta;
  rows: OrchardRowDoc[];
}

/** Draft tree calculated client-side before backend persistence */
export interface DraftTree {
  tempId: ObjectIdString;
  rowId: string;
  indexInRow: number;
  coordinates: GeoCoord;
  healthIndex: null;
  species: ObjectIdString;
}

/** Draft straight row drawn by the user on the orchard canvas */
export interface DraftRow {
  id: string;
  label: string;
  start: GeoCoord;
  end: GeoCoord;
  averageSpacingMeters: number;
  species: ObjectIdString;
  /** Optional per-tree species overrides keyed by tree index in row (0-based) */
  treeSpeciesOverrides: Record<number, ObjectIdString>;
}

/**
 * Request payload sent to backend to persist calculated `Tree` docs
 * and update `Orchard.rows` with ordered `treeIds`.
 */
export interface SaveOrchardLayoutRequest {
  orchardId: ObjectIdString;
  orchardRows: Array<{
    id: string;
    label: string;
    start: GeoCoord;
    end: GeoCoord;
    averageSpacingMeters: number;
    defaultSpecies: ObjectIdString;
    treeIds: ObjectIdString[];
  }>;
  trees: TreeDoc[];
}

export interface SaveOrchardLayoutResponse {
  orchardId: ObjectIdString;
  savedRowsCount: number;
  savedTreesCount: number;
  updatedAt: string;
  orchard: Pick<OrchardBoundaryDoc, '_id' | 'rows'>;
  trees: TreeDoc[];
}

export function scoreToHealthStatus(score: number): HealthStatus {
  if (score <= 15) return 'dead';
  if (score <= 45) return 'poor';
  if (score <= 72) return 'moderate';
  return 'healthy';
}
