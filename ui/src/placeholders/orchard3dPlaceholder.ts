import {
  scoreToHealthStatus,
  type GeoCoord,
  type HealthDistribution,
  type OrchardHealthSummary,
  type OrchardSceneResponse,
  type OrchardTree3D,
  type PointCloudData,
  type RowLineRecord,
} from '../types/orchard';
import { wgs84ToEpsg2180 } from '../utils/crs2180';

/**
 * [PLACEHOLDER] Scene metadata for `Grojec A` (`_id: 6b01933c1dc02a368703a020`).
 *
 * Uses the REAL parcel boundary, rows (`R-01`, `R-02`), and 12 `Tree` GPS coordinates
 * from local MongoDB `field_under_pressure`, paired with the real LiDAR file `/las/grojec.las`.
 * Health scores are temporary demo placeholders until the backend calculates `Tree.healthIndex`.
 *
 * Remove `src/placeholders/` once the backend API is live.
 */

const GROJEC_A_BOUNDARY_GEO: GeoCoord[] = [
  { lat: 51.84447031436461, lng: 20.85185092156493 },
  { lat: 51.845577735233036, lng: 20.85194842604751 },
  { lat: 51.845542724553376, lng: 20.853352285976772 },
  { lat: 51.845774353581064, lng: 20.853382621744633 },
  { lat: 51.845798670667115, lng: 20.855111625449258 },
  { lat: 51.84446227417943, lng: 20.853588952884014 },
];

const GROJEC_A_ROWS_GEO = [
  {
    id: 'row-1795270903529-10',
    label: 'R-01',
    start: { lat: 51.845536, lng: 20.8539662 },
    end: { lat: 51.8456036, lng: 20.8542839 },
    spacing: 3.8,
  },
  {
    id: 'row-1795271865542-2',
    label: 'R-02',
    start: { lat: 51.8454844, lng: 20.8543872 },
    end: { lat: 51.845375, lng: 20.8541249 },
    spacing: 3.8,
  },
];

// Real 12 Tree documents from live local MongoDB `Tree` for `Grojec A`
// (demo healthScore assigned temporarily until backend computes `healthIndex`)
const GROJEC_A_TREES_RAW: Array<{
  id: string;
  rowId: string;
  rowLabel: string;
  indexInRow: number;
  geo: GeoCoord;
  healthScore: number;
  heightMeters: number;
  canopyRadiusMeters: number;
}> = [
  { id: '67401e000001000001000001', rowId: 'row-1795270903529-10', rowLabel: 'R-01', indexInRow: 1, geo: { lat: 51.845542, lng: 20.8539944 }, healthScore: 86, heightMeters: 3.4, canopyRadiusMeters: 1.35 },
  { id: '67401e000001000001000002', rowId: 'row-1795270903529-10', rowLabel: 'R-01', indexInRow: 2, geo: { lat: 51.8455531, lng: 20.8540467 }, healthScore: 79, heightMeters: 3.2, canopyRadiusMeters: 1.25 },
  { id: '67401e000001000001000003', rowId: 'row-1795270903529-10', rowLabel: 'R-01', indexInRow: 3, geo: { lat: 51.8455642, lng: 20.8540989 }, healthScore: 62, heightMeters: 3.0, canopyRadiusMeters: 1.2 },
  { id: '67401e000001000001000004', rowId: 'row-1795270903529-10', rowLabel: 'R-01', indexInRow: 4, geo: { lat: 51.8455754, lng: 20.8541512 }, healthScore: 36, heightMeters: 2.7, canopyRadiusMeters: 1.05 },
  { id: '67401e000001000001000005', rowId: 'row-1795270903529-10', rowLabel: 'R-01', indexInRow: 5, geo: { lat: 51.8455865, lng: 20.8542034 }, healthScore: 10, heightMeters: 2.2, canopyRadiusMeters: 0.85 },
  { id: '67401e000001000001000006', rowId: 'row-1795270903529-10', rowLabel: 'R-01', indexInRow: 6, geo: { lat: 51.8455976, lng: 20.8542557 }, healthScore: 81, heightMeters: 3.3, canopyRadiusMeters: 1.3 },
  { id: '67401e000001000002000001', rowId: 'row-1795271865542-2', rowLabel: 'R-02', indexInRow: 1, geo: { lat: 51.8454775, lng: 20.8543705 }, healthScore: 88, heightMeters: 4.1, canopyRadiusMeters: 1.55 },
  { id: '67401e000001000002000002', rowId: 'row-1795271865542-2', rowLabel: 'R-02', indexInRow: 2, geo: { lat: 51.8454584, lng: 20.8543247 }, healthScore: 84, heightMeters: 4.0, canopyRadiusMeters: 1.5 },
  { id: '67401e000001000002000003', rowId: 'row-1795271865542-2', rowLabel: 'R-02', indexInRow: 3, geo: { lat: 51.8454393, lng: 20.8542789 }, healthScore: 67, heightMeters: 3.7, canopyRadiusMeters: 1.35 },
  { id: '67401e000001000002000004', rowId: 'row-1795271865542-2', rowLabel: 'R-02', indexInRow: 4, geo: { lat: 51.8454201, lng: 20.8542332 }, healthScore: 91, heightMeters: 4.2, canopyRadiusMeters: 1.6 },
  { id: '67401e000001000002000005', rowId: 'row-1795271865542-2', rowLabel: 'R-02', indexInRow: 5, geo: { lat: 51.845401, lng: 20.8541874 }, healthScore: 41, heightMeters: 3.1, canopyRadiusMeters: 1.15 },
  { id: '67401e000001000002000006', rowId: 'row-1795271865542-2', rowLabel: 'R-02', indexInRow: 6, geo: { lat: 51.8453819, lng: 20.8541416 }, healthScore: 76, heightMeters: 3.9, canopyRadiusMeters: 1.45 },
];

// Default EPSG:2180 center matching grojec.las bounds ([627527.17..627747.74], [443637.04..443790.30])
const GROJEC_LAS_ORIGIN = {
  x: (627527.17 + 627747.74) / 2,
  y: (443637.04 + 443790.3) / 2,
};

let cachedScene: OrchardSceneResponse | null = null;

function buildPlaceholderScene(orchardId: string): OrchardSceneResponse {
  if (cachedScene && cachedScene.orchardId === orchardId) {
    return cachedScene;
  }

  const nowIso = new Date().toISOString();

  const rowLines: RowLineRecord[] = GROJEC_A_ROWS_GEO.map((r) => {
    const pStart = wgs84ToEpsg2180(r.start.lat, r.start.lng);
    const pEnd = wgs84ToEpsg2180(r.end.lat, r.end.lng);
    return {
      id: r.id,
      orchardId,
      rowLabel: r.label,
      vertices: [
        { x: Number((pStart.x - GROJEC_LAS_ORIGIN.x).toFixed(2)), y: 0, z: Number((-(pStart.y - GROJEC_LAS_ORIGIN.y)).toFixed(2)) },
        { x: Number((pEnd.x - GROJEC_LAS_ORIGIN.x).toFixed(2)), y: 0, z: Number((-(pEnd.y - GROJEC_LAS_ORIGIN.y)).toFixed(2)) },
      ],
      treeSpacingMeters: r.spacing,
      createdAt: nowIso,
    };
  });

  const trees: OrchardTree3D[] = GROJEC_A_TREES_RAW.map((item) => {
    const p = wgs84ToEpsg2180(item.geo.lat, item.geo.lng);
    return {
      id: item.id,
      rowId: item.rowId,
      rowLabel: item.rowLabel,
      indexInRow: item.indexInRow,
      position: {
        x: Number((p.x - GROJEC_LAS_ORIGIN.x).toFixed(2)),
        y: 0,
        z: Number((-(p.y - GROJEC_LAS_ORIGIN.y)).toFixed(2)),
      },
      geo: item.geo,
      heightMeters: item.heightMeters,
      canopyRadiusMeters: item.canopyRadiusMeters,
      healthScore: item.healthScore,
      healthStatus: scoreToHealthStatus(item.healthScore),
    };
  });

  // Minimal fallback PointCloudData (real rendering uses binary `/las/grojec.las` via `fetchOrchardLasBuffer`)
  const pointCloud: PointCloudData = {
    orchardId,
    pointCount: 0,
    positions: [],
    colors: [],
    bounds: {
      min: { x: -115, y: 0, z: -80 },
      max: { x: 115, y: 10, z: 80 },
    },
  };

  cachedScene = {
    orchardId,
    orchardName: 'Grojec A',
    boundaryGeo: GROJEC_A_BOUNDARY_GEO,
    rowsGeo: GROJEC_A_ROWS_GEO.map(({ id, label, start, end }) => ({ id, label, start, end })),
    pointCloud,
    trees,
    rowLines,
  };

  return cachedScene;
}

export function getPlaceholderOrchardScene(orchardId: string): OrchardSceneResponse {
  return buildPlaceholderScene(orchardId);
}

export function getPlaceholderOrchardHealth(orchardId: string): OrchardHealthSummary {
  const scene = buildPlaceholderScene(orchardId);
  const distribution: HealthDistribution = {
    dead: 0,
    poor: 0,
    moderate: 0,
    healthy: 0,
  };

  let scoreSum = 0;
  for (const tree of scene.trees) {
    distribution[tree.healthStatus] += 1;
    scoreSum += tree.healthScore;
  }

  const totalTrees = scene.trees.length;
  const averageScore = totalTrees > 0 ? Math.round(scoreSum / totalTrees) : 0;

  return {
    orchardId,
    updatedAt: new Date().toISOString(),
    averageScore,
    overallStatus: scoreToHealthStatus(averageScore),
    totalTrees,
    distribution,
  };
}
