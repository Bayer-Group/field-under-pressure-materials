import type {
  DraftRow,
  DraftTree,
  GeoCoord,
  ObjectIdString,
  OrchardBoundaryDoc,
  SaveOrchardLayoutRequest,
  TreeDoc,
} from '../types/orchard';

export interface Vec2 {
  /** East offset in meters relative to orchard origin */
  x: number;
  /** North offset in meters relative to orchard origin */
  y: number;
}

const METERS_PER_DEG_LAT = 111_320;

function metersPerDegLng(originLat: number): number {
  return METERS_PER_DEG_LAT * Math.cos((originLat * Math.PI) / 180);
}

export function geoToLocalMeters(coord: GeoCoord, origin: GeoCoord): Vec2 {
  return {
    x: (coord.lng - origin.lng) * metersPerDegLng(origin.lat),
    y: (coord.lat - origin.lat) * METERS_PER_DEG_LAT,
  };
}

export function localMetersToGeo(pt: Vec2, origin: GeoCoord): GeoCoord {
  return {
    lat: Number((origin.lat + pt.y / METERS_PER_DEG_LAT).toFixed(7)),
    lng: Number((origin.lng + pt.x / metersPerDegLng(origin.lat)).toFixed(7)),
  };
}

export function distanceMeters(a: Vec2, b: Vec2): number {
  return Math.hypot(b.x - a.x, b.y - a.y);
}

/** Ray-casting point-in-polygon test in local metric coordinates */
export function pointInPolygon(pt: Vec2, polygon: Vec2[]): boolean {
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i, i += 1) {
    const xi = polygon[i].x;
    const yi = polygon[i].y;
    const xj = polygon[j].x;
    const yj = polygon[j].y;

    const intersect =
      yi > pt.y !== yj > pt.y &&
      pt.x < ((xj - xi) * (pt.y - yi)) / (yj - yi + Number.EPSILON) + xi;
    if (intersect) inside = !inside;
  }
  return inside;
}

/**
 * Computes intersection parameter t in [0, 1] for segment AB against segment CD.
 * Returns null if segments are parallel or do not intersect.
 */
function segmentIntersectionT(a: Vec2, b: Vec2, c: Vec2, d: Vec2): number | null {
  const rX = b.x - a.x;
  const rY = b.y - a.y;
  const sX = d.x - c.x;
  const sY = d.y - c.y;

  const denom = rX * sY - rY * sX;
  if (Math.abs(denom) < 1e-9) return null;

  const qpx = c.x - a.x;
  const qpy = c.y - a.y;
  const t = (qpx * sY - qpy * sX) / denom;
  const u = (qpx * rY - qpy * rX) / denom;

  if (t >= -1e-7 && t <= 1 + 1e-7 && u >= -1e-7 && u <= 1 + 1e-7) {
    return Math.max(0, Math.min(1, t));
  }
  return null;
}

export interface ClippedSegment {
  a: Vec2;
  b: Vec2;
  tStart: number;
  tEnd: number;
}

/**
 * Clips straight segment AB against a (convex or concave) orchard boundary polygon.
 * Returns all sub-segments lying inside the field geometry.
 */
export function clipSegmentToPolygon(a: Vec2, b: Vec2, polygon: Vec2[]): ClippedSegment[] {
  if (polygon.length < 3) return [];

  const ts: number[] = [0, 1];
  for (let i = 0; i < polygon.length; i += 1) {
    const c = polygon[i];
    const d = polygon[(i + 1) % polygon.length];
    const hitT = segmentIntersectionT(a, b, c, d);
    if (hitT !== null) {
      ts.push(hitT);
    }
  }

  ts.sort((p, q) => p - q);

  // Deduplicate close intersection parameters
  const uniqueTs: number[] = [];
  for (const t of ts) {
    if (uniqueTs.length === 0 || Math.abs(t - uniqueTs[uniqueTs.length - 1]) > 1e-5) {
      uniqueTs.push(t);
    }
  }

  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const insideSegments: ClippedSegment[] = [];

  for (let i = 0; i < uniqueTs.length - 1; i += 1) {
    const t0 = uniqueTs[i];
    const t1 = uniqueTs[i + 1];
    const tMid = (t0 + t1) / 2;
    const mid: Vec2 = { x: a.x + dx * tMid, y: a.y + dy * tMid };
    if (pointInPolygon(mid, polygon)) {
      insideSegments.push({
        a: { x: a.x + dx * t0, y: a.y + dy * t0 },
        b: { x: a.x + dx * t1, y: a.y + dy * t1 },
        tStart: t0,
        tEnd: t1,
      });
    }
  }

  return insideSegments;
}

/** Generates a deterministic 24-character hex MongoDB ObjectId string */
export function makeDeterministicObjectId(prefixHex: string, rowNum: number, treeNum: number): ObjectIdString {
  const cleanPrefix = prefixHex.replace(/[^a-f0-9]/gi, '').slice(0, 12).padEnd(12, '0');
  const rowHex = Math.max(0, rowNum).toString(16).padStart(6, '0').slice(-6);
  const treeHex = Math.max(0, treeNum).toString(16).padStart(6, '0').slice(-6);
  return `${cleanPrefix}${rowHex}${treeHex}`.toLowerCase();
}

export interface CalculatedRowResult {
  row: DraftRow;
  totalLengthMeters: number;
  insideLengthMeters: number;
  clippedSegments: ClippedSegment[];
  trees: DraftTree[];
}

/**
 * Calculates individual tree coordinates along a straight row line clipped to the orchard field polygon.
 * Trees are spaced uniformly by `row.averageSpacingMeters`, respecting `edgeMarginMeters` at clipped polygon edges.
 */
export function calculateRowTrees(
  row: DraftRow,
  rowIndex: number,
  polygonLocal: Vec2[],
  origin: GeoCoord,
  edgeMarginMeters: number,
): CalculatedRowResult {
  const startLocal = geoToLocalMeters(row.start, origin);
  const endLocal = geoToLocalMeters(row.end, origin);
  const totalLengthMeters = distanceMeters(startLocal, endLocal);

  if (totalLengthMeters < 0.25) {
    return {
      row,
      totalLengthMeters,
      insideLengthMeters: 0,
      clippedSegments: [],
      trees: [],
    };
  }

  const clippedSegments = clipSegmentToPolygon(startLocal, endLocal, polygonLocal);
  const spacing = Math.max(0.5, row.averageSpacingMeters);
  const trees: DraftTree[] = [];
  let insideLengthMeters = 0;

  for (const seg of clippedSegments) {
    const segLen = distanceMeters(seg.a, seg.b);
    insideLengthMeters += segLen;
    if (segLen < 0.25) continue;

    // Apply boundary margin only when a segment end was clipped by the field border (or gently at both ends)
    const trimStart = seg.tStart > 1e-4 ? edgeMarginMeters : Math.min(edgeMarginMeters * 0.35, segLen * 0.25);
    const trimEnd = seg.tEnd < 1 - 1e-4 ? edgeMarginMeters : Math.min(edgeMarginMeters * 0.35, segLen * 0.25);
    const usableLen = segLen - trimStart - trimEnd;

    if (usableLen < 0) {
      // Single centered tree if the segment is very short but still inside the polygon
      if (segLen >= spacing * 0.45) {
        const mid: Vec2 = { x: (seg.a.x + seg.b.x) / 2, y: (seg.a.y + seg.b.y) / 2 };
        const treeIdx = trees.length;
        const species = row.treeSpeciesOverrides[treeIdx] ?? row.species;
        trees.push({
          tempId: makeDeterministicObjectId('67401e000001', rowIndex + 1, treeIdx + 1),
          rowId: row.id,
          indexInRow: treeIdx,
          coordinates: localMetersToGeo(mid, origin),
          healthIndex: null,
          species,
        });
      }
      continue;
    }

    const count = Math.floor(usableLen / spacing) + 1;
    const occupiedSpan = (count - 1) * spacing;
    // Center trees symmetrically inside the usable length
    const startOffset = trimStart + (usableLen - occupiedSpan) / 2;

    const dirX = (seg.b.x - seg.a.x) / segLen;
    const dirY = (seg.b.y - seg.a.y) / segLen;

    for (let k = 0; k < count; k += 1) {
      const dist = startOffset + k * spacing;
      const pt: Vec2 = {
        x: seg.a.x + dirX * dist,
        y: seg.a.y + dirY * dist,
      };
      const treeIdx = trees.length;
      const species = row.treeSpeciesOverrides[treeIdx] ?? row.species;
      trees.push({
        tempId: makeDeterministicObjectId('67401e000001', rowIndex + 1, treeIdx + 1),
        rowId: row.id,
        indexInRow: treeIdx,
        coordinates: localMetersToGeo(pt, origin),
        healthIndex: null,
        species,
      });
    }
  }

  return {
    row,
    totalLengthMeters: Number(totalLengthMeters.toFixed(1)),
    insideLengthMeters: Number(insideLengthMeters.toFixed(1)),
    clippedSegments,
    trees,
  };
}

/**
 * Builds the exact payload expected by the backend to persist:
 * - `Tree` collection documents (`_id`, `orchardId`, `coordinates`, `healthIndex: null`, `species: CropPref ObjectId`)
 * - `Orchard.rows` embedded entries (`start`, `end`, `averageSpacingMeters`, `defaultSpecies`, ordered `treeIds`)
 */
export function buildOrchardLayoutPayload(
  orchard: OrchardBoundaryDoc,
  calculatedRows: CalculatedRowResult[],
): SaveOrchardLayoutRequest {
  const trees: TreeDoc[] = [];
  const orchardRows: SaveOrchardLayoutRequest['orchardRows'] = [];

  for (const calc of calculatedRows) {
    const rowTreeIds: ObjectIdString[] = [];
    for (const draftTree of calc.trees) {
      rowTreeIds.push(draftTree.tempId);
      trees.push({
        _id: draftTree.tempId,
        orchardId: orchard._id,
        coordinates: draftTree.coordinates,
        healthIndex: null,
        species: draftTree.species,
      });
    }

    orchardRows.push({
      id: calc.row.id,
      label: calc.row.label,
      start: calc.row.start,
      end: calc.row.end,
      averageSpacingMeters: calc.row.averageSpacingMeters,
      defaultSpecies: calc.row.species,
      treeIds: rowTreeIds,
    });
  }

  return {
    orchardId: orchard._id,
    orchardRows,
    trees,
  };
}

/** Snaps drawn endpoint angle to parallel with a reference row or 15° increments */
export function snapEndpointAngle(
  start: Vec2,
  rawEnd: Vec2,
  referenceAngleRad?: number | null,
): Vec2 {
  const dx = rawEnd.x - start.x;
  const dy = rawEnd.y - start.y;
  const len = Math.hypot(dx, dy);
  if (len < 0.1) return rawEnd;

  const angle = Math.atan2(dy, dx);

  if (referenceAngleRad !== null && referenceAngleRad !== undefined) {
    // Snap to reference angle or opposite direction (180°) if close
    const candidates = [referenceAngleRad, referenceAngleRad + Math.PI];
    let bestAngle = angle;
    let bestDiff = Infinity;
    for (const cand of candidates) {
      const diff = Math.abs(Math.atan2(Math.sin(angle - cand), Math.cos(angle - cand)));
      if (diff < bestDiff) {
        bestDiff = diff;
        bestAngle = cand;
      }
    }
    if (bestDiff < (18 * Math.PI) / 180) {
      return {
        x: start.x + Math.cos(bestAngle) * len,
        y: start.y + Math.sin(bestAngle) * len,
      };
    }
  }

  const step = Math.PI / 12; // 15 deg
  const snapped = Math.round(angle / step) * step;
  return {
    x: start.x + Math.cos(snapped) * len,
    y: start.y + Math.sin(snapped) * len,
  };
}

/**
 * Generates a parallel row shifted perpendicular by `offsetMeters`, clipped nicely across the polygon.
 * Automatically tries the opposite perpendicular side if the first side falls outside the parcel.
 */
export function createParallelRowEndpoints(
  sourceRow: DraftRow,
  offsetMeters: number,
  polygonLocal: Vec2[],
  origin: GeoCoord,
): { start: GeoCoord; end: GeoCoord } | null {
  const a = geoToLocalMeters(sourceRow.start, origin);
  const b = geoToLocalMeters(sourceRow.end, origin);
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const len = Math.hypot(dx, dy);
  if (len < 0.5) return null;

  // Unit perpendicular vector
  const nx = -dy / len;
  const ny = dx / len;
  const ux = dx / len;
  const uy = dy / len;

  for (const sign of [1, -1]) {
    const shiftX = nx * offsetMeters * sign;
    const shiftY = ny * offsetMeters * sign;

    // Extend generously along the row axis, then clip to polygon so the cloned row adapts to irregular field borders
    const midX = (a.x + b.x) / 2 + shiftX;
    const midY = (a.y + b.y) / 2 + shiftY;
    const ext = 250;
    const extA: Vec2 = { x: midX - ux * ext, y: midY - uy * ext };
    const extB: Vec2 = { x: midX + ux * ext, y: midY + uy * ext };

    const clipped = clipSegmentToPolygon(extA, extB, polygonLocal);
    if (clipped.length > 0) {
      const longest = clipped.reduce((best, cur) =>
        distanceMeters(cur.a, cur.b) > distanceMeters(best.a, best.b) ? cur : best,
      );
      if (distanceMeters(longest.a, longest.b) >= 2) {
        return {
          start: localMetersToGeo(longest.a, origin),
          end: localMetersToGeo(longest.b, origin),
        };
      }
    }
  }

  return null;
}

/* ==========================================================================
   Web Mercator Satellite Tile Alignment (Esri World Imagery)
   ========================================================================== */

export interface SatelliteTilePlacement {
  key: string;
  url: string;
  /** Local meters bounding box (North-up: xMin..xMax, yMin..yMax) */
  xMin: number;
  xMax: number;
  yMin: number;
  yMax: number;
}

function lngToTileX(lng: number, zoom: number): number {
  return Math.floor(((lng + 180) / 360) * Math.pow(2, zoom));
}

function latToTileY(lat: number, zoom: number): number {
  const rad = (lat * Math.PI) / 180;
  return Math.floor(
    ((1 - Math.log(Math.tan(rad) + 1 / Math.cos(rad)) / Math.PI) / 2) * Math.pow(2, zoom),
  );
}

function tileXToLng(x: number, zoom: number): number {
  return (x / Math.pow(2, zoom)) * 360 - 180;
}

function tileYToLat(y: number, zoom: number): number {
  const n = Math.PI - (2 * Math.PI * y) / Math.pow(2, zoom);
  return (180 / Math.PI) * Math.atan(0.5 * (Math.exp(n) - Math.exp(-n)));
}

/**
 * Computes Web Mercator satellite map tiles covering the given local-meter bounds around `origin`.
 */
export function buildSatelliteTiles(
  origin: GeoCoord,
  minLocal: Vec2,
  maxLocal: Vec2,
  zoom = 18,
): SatelliteTilePlacement[] {
  const sw = localMetersToGeo({ x: minLocal.x, y: minLocal.y }, origin);
  const ne = localMetersToGeo({ x: maxLocal.x, y: maxLocal.y }, origin);

  const txMin = lngToTileX(sw.lng, zoom) - 1;
  const txMax = lngToTileX(ne.lng, zoom) + 1;
  const tyMin = latToTileY(ne.lat, zoom) - 1;
  const tyMax = latToTileY(sw.lat, zoom) + 1;

  const tiles: SatelliteTilePlacement[] = [];
  const maxTilesPerAxis = 7;

  const clampedTxMax = Math.min(txMax, txMin + maxTilesPerAxis);
  const clampedTyMax = Math.min(tyMax, tyMin + maxTilesPerAxis);

  for (let tx = txMin; tx <= clampedTxMax; tx += 1) {
    for (let ty = tyMin; ty <= clampedTyMax; ty += 1) {
      const westLng = tileXToLng(tx, zoom);
      const eastLng = tileXToLng(tx + 1, zoom);
      const northLat = tileYToLat(ty, zoom);
      const southLat = tileYToLat(ty + 1, zoom);

      const swLocal = geoToLocalMeters({ lat: southLat, lng: westLng }, origin);
      const neLocal = geoToLocalMeters({ lat: northLat, lng: eastLng }, origin);

      tiles.push({
        key: `${zoom}-${tx}-${ty}`,
        url: `https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/${zoom}/${ty}/${tx}`,
        xMin: swLocal.x,
        xMax: neLocal.x,
        yMin: swLocal.y,
        yMax: neLocal.y,
      });
    }
  }

  return tiles;
}
