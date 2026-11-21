import {
  scoreToHealthStatus,
  type HealthDistribution,
  type OrchardHealthSummary,
  type OrchardSceneResponse,
  type OrchardTree3D,
  type Point3D,
  type PointCloudData,
  type RowLineRecord,
} from '../types/orchard';

/**
 * [PLACEHOLDER] Deterministic 3D orchard generator (point cloud + row lines + calculated 3D trees).
 *
 * Simulates the real backend pipeline:
 *   user-drawn row lines -> tree position calculation along each polyline ->
 *   projection onto terrain point cloud -> per-tree health scoring.
 *
 * Remove `src/placeholders/` completely once the backend API is running.
 */

function seededRandom(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state * 1664525 + 1013904223) >>> 0;
    return state / 0xffffffff;
  };
}

/** Gentle orchard terrain relief (meters) */
function sampleTerrainElevation(x: number, z: number): number {
  return (
    Math.sin(x * 0.065) * 0.85 +
    Math.cos(z * 0.075) * 0.65 +
    Math.sin((x + z) * 0.04) * 0.45
  );
}

/**
 * Computes individual tree coordinates along a user-drawn polyline using uniform spacing.
 * Mirrors the calculation that the backend will perform after receiving POST /api/v1/orchard/row-lines.
 */
function samplePositionsAlongPolyline(vertices: Point3D[], spacingMeters: number): Point3D[] {
  if (vertices.length < 2 || spacingMeters <= 0) return [];

  const result: Point3D[] = [];
  let carry = 0;

  for (let segIdx = 0; segIdx < vertices.length - 1; segIdx += 1) {
    const a = vertices[segIdx];
    const b = vertices[segIdx + 1];
    const dx = b.x - a.x;
    const dz = b.z - a.z;
    const segLen = Math.hypot(dx, dz);
    if (segLen < 1e-4) continue;

    let dist = segIdx === 0 ? 0 : carry;
    while (dist <= segLen) {
      const t = dist / segLen;
      const x = a.x + dx * t;
      const z = a.z + dz * t;
      result.push({
        x: Number(x.toFixed(2)),
        y: Number(sampleTerrainElevation(x, z).toFixed(2)),
        z: Number(z.toFixed(2)),
      });
      dist += spacingMeters;
    }
    carry = dist - segLen;
  }

  return result;
}

let cachedScene: OrchardSceneResponse | null = null;

function buildPlaceholderScene(orchardId: string): OrchardSceneResponse {
  if (cachedScene && cachedScene.orchardId === orchardId) {
    return cachedScene;
  }

  const rand = seededRandom(20261121);
  const nowIso = new Date().toISOString();

  // 1. Simulated user-drawn row lines (polylines across the orchard parcel)
  const rowCount = 9;
  const rowSpacingZ = 5.4;
  const treeSpacingX = 4.4;
  const halfWidthX = 28;
  const startZ = -((rowCount - 1) * rowSpacingZ) / 2;

  const rowLines: RowLineRecord[] = [];
  for (let r = 0; r < rowCount; r += 1) {
    const baseZ = startZ + r * rowSpacingZ;
    // Slight natural curve / parcel contour bend in the drawn line
    const bend = Math.sin(r * 0.55) * 1.1;
    const vertices: Point3D[] = [
      { x: -halfWidthX, y: sampleTerrainElevation(-halfWidthX, baseZ), z: baseZ },
      { x: 0, y: sampleTerrainElevation(0, baseZ + bend), z: baseZ + bend },
      { x: halfWidthX, y: sampleTerrainElevation(halfWidthX, baseZ - bend * 0.4), z: baseZ - bend * 0.4 },
    ];

    rowLines.push({
      id: `row-${String(r + 1).padStart(2, '0')}`,
      orchardId,
      rowLabel: `R-${String(r + 1).padStart(2, '0')}`,
      vertices,
      treeSpacingMeters: treeSpacingX,
      createdAt: nowIso,
    });
  }

  // 2. Calculate individual 3D tree placements along the drawn row lines
  const trees: OrchardTree3D[] = [];
  const baseLat = 51.8412; // Mazowieckie / Grójec orchard region placeholder
  const baseLng = 20.8674;

  for (const row of rowLines) {
    const sampledPositions = samplePositionsAlongPolyline(row.vertices, row.treeSpacingMeters);
    sampledPositions.forEach((pos, idx) => {
      // Simulate two spatial stress pockets (e.g. frost hollow + disease cluster)
      const distPocketA = Math.hypot(pos.x - 12, pos.z - 9);
      const distPocketB = Math.hypot(pos.x + 15, pos.z + 11);

      let healthScore = 82 + (rand() - 0.5) * 24;
      if (distPocketA < 13) {
        healthScore -= (1 - distPocketA / 13) * 74;
      }
      if (distPocketB < 10.5) {
        healthScore -= (1 - distPocketB / 10.5) * 52;
      }

      // A few isolated dead/stressed trees
      const outlierRoll = rand();
      if (outlierRoll < 0.035) {
        healthScore = 6 + rand() * 8;
      } else if (outlierRoll < 0.09) {
        healthScore = 24 + rand() * 18;
      }

      healthScore = Math.max(0, Math.min(100, Math.round(healthScore)));
      const healthStatus = scoreToHealthStatus(healthScore);

      const heightFactor = healthStatus === 'dead' ? 0.68 : healthStatus === 'poor' ? 0.82 : 1.0;
      const heightMeters = Number(((3.0 + rand() * 1.3) * heightFactor).toFixed(2));
      const canopyRadiusMeters = Number(((1.15 + rand() * 0.45) * heightFactor).toFixed(2));

      trees.push({
        id: `T-${row.rowLabel.replace('R-', '')}-${String(idx + 1).padStart(2, '0')}`,
        rowId: row.id,
        rowLabel: row.rowLabel,
        indexInRow: idx + 1,
        position: pos,
        geo: {
          lat: Number((baseLat + pos.z * 0.000009).toFixed(6)),
          lng: Number((baseLng + pos.x * 0.000014).toFixed(6)),
        },
        heightMeters,
        canopyRadiusMeters,
        healthScore,
        healthStatus,
      });
    });
  }

  // 3. Generate orchard LiDAR / photogrammetry point cloud (ground + canopy returns)
  const positions: number[] = [];
  const colors: number[] = [];

  const groundPointsCount = 5200;
  for (let i = 0; i < groundPointsCount; i += 1) {
    const x = (rand() - 0.5) * 72;
    const z = (rand() - 0.5) * 58;
    const y = sampleTerrainElevation(x, z) + (rand() - 0.5) * 0.14;

    positions.push(Number(x.toFixed(2)), Number(y.toFixed(2)), Number(z.toFixed(2)));

    // Subtle earthy elevation gradient
    const elevNorm = Math.max(0, Math.min(1, (y + 2.0) / 4.0));
    colors.push(
      Number((0.36 + elevNorm * 0.18).toFixed(3)),
      Number((0.44 + elevNorm * 0.16).toFixed(3)),
      Number((0.34 + elevNorm * 0.12).toFixed(3)),
    );
  }

  // Canopy point cloud returns around each calculated tree
  const statusRgb: Record<OrchardTree3D['healthStatus'], [number, number, number]> = {
    dead: [0.16, 0.16, 0.18],
    poor: [0.86, 0.2, 0.2],
    moderate: [0.95, 0.52, 0.14],
    healthy: [0.18, 0.68, 0.34],
  };

  const pointsPerCanopy = 46;
  for (const tree of trees) {
    const [rBase, gBase, bBase] = statusRgb[tree.healthStatus];
    const crownCenterY = tree.position.y + tree.heightMeters * 0.62;
    const rMax = tree.canopyRadiusMeters * 1.15;

    for (let p = 0; p < pointsPerCanopy; p += 1) {
      const theta = rand() * Math.PI * 2;
      const phi = Math.acos(2 * rand() - 1);
      const radius = rMax * Math.cbrt(rand());

      const px = tree.position.x + radius * Math.sin(phi) * Math.cos(theta);
      const py = crownCenterY + radius * 0.85 * Math.cos(phi);
      const pz = tree.position.z + radius * Math.sin(phi) * Math.sin(theta);

      positions.push(Number(px.toFixed(2)), Number(py.toFixed(2)), Number(pz.toFixed(2)));
      const jitter = (rand() - 0.5) * 0.08;
      colors.push(
        Number(Math.max(0, Math.min(1, rBase + jitter)).toFixed(3)),
        Number(Math.max(0, Math.min(1, gBase + jitter)).toFixed(3)),
        Number(Math.max(0, Math.min(1, bBase + jitter)).toFixed(3)),
      );
    }
  }

  const pointCloud: PointCloudData = {
    orchardId,
    pointCount: positions.length / 3,
    positions,
    colors,
    bounds: {
      min: { x: -36, y: -2.2, z: -29 },
      max: { x: 36, y: 6.5, z: 29 },
    },
  };

  cachedScene = {
    orchardId,
    orchardName: 'Sad Grójec — Sektor A (Placeholder)',
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
