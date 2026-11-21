/**
 * Pure TypeScript binary LAS (1.1 - 1.4) point cloud parser for browser WebGL / Three.js.
 *
 * Supports uncompressed LAS Point Data Record Formats 0, 1, 2, 3, 6, 7, 8
 * (including 16-bit / 8-bit RGB colors and ASPRS classification filtering).
 */

export type LasColorMode = 'rgb' | 'elevation' | 'classification';

export interface LasHeaderMeta {
  version: string;
  pointFormat: number;
  pointRecordLength: number;
  totalPointCount: number;
  renderedPointCount: number;
  hasRgb: boolean;
  boundsRaw: {
    minX: number;
    maxX: number;
    minY: number;
    maxY: number;
    minZ: number;
    maxZ: number;
  };
  spanMeters: {
    x: number;
    y: number;
    z: number;
  };
}

export interface ParsedLasCloud {
  header: LasHeaderMeta;
  /** Origin in native LAS CRS (e.g. EPSG:2180 meters) used to center Three.js coordinates */
  origin: {
    x: number;
    y: number;
    z: number;
  };
  /** Centered Three.js XYZ Float32Array (+X East, +Y Elevation Up, -Z North) */
  positions: Float32Array;
  /** True RGB colors from LAS (or elevation fallback if LAS format lacks RGB) */
  rgbColors: Float32Array;
  /** Hypsometric elevation ramp colors */
  elevationColors: Float32Array;
  /** ASPRS classification colors */
  classificationColors: Float32Array;
  /** Samples terrain ground elevation (Three.js +Y) at local scene (x, z) */
  sampleGroundY: (sceneX: number, sceneZ: number) => number;
}

export interface ParseLasOptions {
  /** Maximum number of points to retain for smooth WebGL rendering (default 180,000) */
  maxPoints?: number;
  /** Skip ASPRS noise classes 7 (low noise) and 18 (high noise) */
  filterNoise?: boolean;
}

function getRgbByteOffset(pointFormat: number): number | null {
  switch (pointFormat) {
    case 2:
      return 20;
    case 3:
      return 28;
    case 5:
      return 28;
    case 7:
      return 30;
    case 8:
      return 30;
    default:
      return null;
  }
}

function getClassificationByteOffset(pointFormat: number): number {
  return pointFormat >= 6 ? 16 : 15;
}

/** Smooth elevation color ramp: warm soil -> meadow green -> vibrant canopy -> golden crown */
function elevationColorRamp(t: number): [number, number, number] {
  const clamped = Math.max(0, Math.min(1, t));
  const stops: Array<[number, number, number, number]> = [
    [0.0, 0.32, 0.25, 0.19], // low ground soil
    [0.25, 0.28, 0.45, 0.27], // grass / ground cover
    [0.52, 0.16, 0.64, 0.3], // orchard canopy
    [0.78, 0.46, 0.78, 0.2], // upper foliage
    [1.0, 0.94, 0.82, 0.28], // tallest crowns
  ];

  for (let i = 0; i < stops.length - 1; i += 1) {
    const [t0, r0, g0, b0] = stops[i];
    const [t1, r1, g1, b1] = stops[i + 1];
    if (clamped >= t0 && clamped <= t1) {
      const f = (clamped - t0) / Math.max(1e-6, t1 - t0);
      return [r0 + (r1 - r0) * f, g0 + (g1 - g0) * f, b0 + (b1 - b0) * f];
    }
  }
  return [0.94, 0.82, 0.28];
}

/** ASPRS standard LiDAR classification palette */
function classificationColor(cls: number): [number, number, number] {
  switch (cls) {
    case 2: // Ground
      return [0.58, 0.46, 0.34];
    case 3: // Low Vegetation
      return [0.52, 0.78, 0.34];
    case 4: // Medium Vegetation (orchard trees)
      return [0.16, 0.68, 0.32];
    case 5: // High Vegetation
      return [0.08, 0.48, 0.24];
    case 6: // Building
      return [0.85, 0.35, 0.28];
    case 9: // Water
      return [0.18, 0.55, 0.88];
    case 12: // Overlap / Reserved
      return [0.32, 0.62, 0.56];
    default:
      return [0.56, 0.62, 0.68];
  }
}

export function parseLasArrayBuffer(
  buffer: ArrayBuffer,
  options: ParseLasOptions = {},
): ParsedLasCloud {
  const maxPoints = options.maxPoints ?? 180_000;
  const filterNoise = options.filterNoise ?? true;

  if (buffer.byteLength < 227) {
    throw new Error('Invalid LAS file: buffer smaller than 227-byte header.');
  }

  const view = new DataView(buffer);
  const sig =
    String.fromCharCode(view.getUint8(0)) +
    String.fromCharCode(view.getUint8(1)) +
    String.fromCharCode(view.getUint8(2)) +
    String.fromCharCode(view.getUint8(3));

  if (sig !== 'LASF') {
    throw new Error(`Unsupported point cloud format (expected "LASF", got "${sig}").`);
  }

  const versionMajor = view.getUint8(24);
  const versionMinor = view.getUint8(25);
  const offsetToPoints = view.getUint32(96, true);
  const rawFormat = view.getUint8(104);
  // High bits of format byte indicate LAZ compression in LAZ files
  if ((rawFormat & 0x80) !== 0) {
    throw new Error('Compressed LAZ files are not supported directly — please provide an uncompressed .las file.');
  }
  const pointFormat = rawFormat & 0x3f;
  const pointRecordLength = view.getUint16(105, true);
  const legacyCount = view.getUint32(107, true);

  let totalPointCount = legacyCount;
  if (versionMajor >= 1 && versionMinor >= 4 && buffer.byteLength >= 255) {
    const extCount = Number(view.getBigUint64(247, true));
    if (extCount > 0) totalPointCount = extCount;
  }

  const availableRecords = Math.floor((buffer.byteLength - offsetToPoints) / Math.max(1, pointRecordLength));
  if (totalPointCount <= 0 || totalPointCount > availableRecords) {
    totalPointCount = availableRecords;
  }

  const scaleX = view.getFloat64(131, true);
  const scaleY = view.getFloat64(139, true);
  const scaleZ = view.getFloat64(147, true);
  const offsetX = view.getFloat64(155, true);
  const offsetY = view.getFloat64(163, true);
  const offsetZ = view.getFloat64(171, true);

  const maxX = view.getFloat64(179, true);
  const minX = view.getFloat64(187, true);
  const maxY = view.getFloat64(195, true);
  const minY = view.getFloat64(203, true);
  const maxZ = view.getFloat64(211, true);
  const minZ = view.getFloat64(219, true);

  const originX = (minX + maxX) / 2;
  const originY = (minY + maxY) / 2;
  const originZ = minZ;

  const spanX = Math.max(1, maxX - minX);
  const spanY = Math.max(1, maxY - minY);
  const spanZ = Math.max(0.5, maxZ - minZ);

  const rgbOffset = getRgbByteOffset(pointFormat);
  const clsOffset = getClassificationByteOffset(pointFormat);
  const hasRgbLayout = rgbOffset !== null && rgbOffset + 6 <= pointRecordLength;

  // Detect whether RGB values are 16-bit (0..65535) or 8-bit (0..255) using a quick probe
  let rgbDivisor = 65535.0;
  let hasNonZeroRgb = false;
  if (hasRgbLayout && rgbOffset !== null) {
    let maxProbe = 0;
    const probeStep = Math.max(1, Math.floor(totalPointCount / 400));
    for (let i = 0; i < totalPointCount; i += probeStep) {
      const base = offsetToPoints + i * pointRecordLength + rgbOffset;
      const r = view.getUint16(base, true);
      const g = view.getUint16(base + 2, true);
      const b = view.getUint16(base + 4, true);
      if (r > maxProbe) maxProbe = r;
      if (g > maxProbe) maxProbe = g;
      if (b > maxProbe) maxProbe = b;
    }
    hasNonZeroRgb = maxProbe > 0;
    if (maxProbe > 0 && maxProbe <= 255) {
      rgbDivisor = 255.0;
    }
  }

  const stride = Math.max(1, Math.ceil(totalPointCount / maxPoints));
  const capacity = Math.ceil(totalPointCount / stride);

  const positions = new Float32Array(capacity * 3);
  const rgbColors = new Float32Array(capacity * 3);
  const elevationColors = new Float32Array(capacity * 3);
  const classificationColors = new Float32Array(capacity * 3);

  // Build coarse 2m terrain ground elevation grid for accurate 3D tree placement on LiDAR ground
  const cellSize = 2.5;
  const gridCols = Math.max(1, Math.ceil(spanX / cellSize) + 1);
  const gridRows = Math.max(1, Math.ceil(spanY / cellSize) + 1);
  const groundSum = new Float32Array(gridCols * gridRows);
  const groundCnt = new Uint32Array(gridCols * gridRows);
  const fallbackMinY = new Float32Array(gridCols * gridRows).fill(Number.POSITIVE_INFINITY);

  // Use a sensible elevation clamp (~minZ..minZ + 6.5m or full span) so orchard trees contrast strongly
  const elevColorMax = Math.min(spanZ, Math.max(4.5, spanZ * 0.72));

  let outIdx = 0;
  for (let i = 0; i < totalPointCount; i += stride) {
    const recOff = offsetToPoints + i * pointRecordLength;
    const rawCls = view.getUint8(recOff + clsOffset);
    // In LAS 1.1-1.3 lower 5 bits hold classification; in LAS 1.4 full byte
    const cls = pointFormat >= 6 ? rawCls : rawCls & 0x1f;

    if (filterNoise && (cls === 7 || cls === 18)) {
      continue;
    }

    const xi = view.getInt32(recOff, true);
    const yi = view.getInt32(recOff + 4, true);
    const zi = view.getInt32(recOff + 8, true);

    const worldX = xi * scaleX + offsetX;
    const worldY = yi * scaleY + offsetY;
    const worldZ = zi * scaleZ + offsetZ;

    const sx = worldX - originX;
    const sy = worldZ - originZ;
    const sz = -(worldY - originY);

    const p3 = outIdx * 3;
    positions[p3] = sx;
    positions[p3 + 1] = sy;
    positions[p3 + 2] = sz;

    // Update ground elevation grid
    const gx = Math.max(0, Math.min(gridCols - 1, Math.floor((worldX - minX) / cellSize)));
    const gy = Math.max(0, Math.min(gridRows - 1, Math.floor((worldY - minY) / cellSize)));
    const gIdx = gy * gridCols + gx;
    if (sy < fallbackMinY[gIdx]) fallbackMinY[gIdx] = sy;
    if (cls === 2) {
      groundSum[gIdx] += sy;
      groundCnt[gIdx] += 1;
    }

    // Elevation ramp color
    const [er, eg, eb] = elevationColorRamp(sy / elevColorMax);
    elevationColors[p3] = er;
    elevationColors[p3 + 1] = eg;
    elevationColors[p3 + 2] = eb;

    // Classification color
    const [cr, cg, cb] = classificationColor(cls);
    classificationColors[p3] = cr;
    classificationColors[p3 + 1] = cg;
    classificationColors[p3 + 2] = cb;

    // True RGB color (if present in LAS)
    if (hasNonZeroRgb && rgbOffset !== null) {
      const r = view.getUint16(recOff + rgbOffset, true) / rgbDivisor;
      const g = view.getUint16(recOff + rgbOffset + 2, true) / rgbDivisor;
      const b = view.getUint16(recOff + rgbOffset + 4, true) / rgbDivisor;
      rgbColors[p3] = Math.min(1, r);
      rgbColors[p3 + 1] = Math.min(1, g);
      rgbColors[p3 + 2] = Math.min(1, b);
    } else {
      rgbColors[p3] = er;
      rgbColors[p3 + 1] = eg;
      rgbColors[p3 + 2] = eb;
    }

    outIdx += 1;
  }

  // Compute global median-ish ground elevation fallback
  let globalGroundSum = 0;
  let globalGroundCnt = 0;
  for (let i = 0; i < groundCnt.length; i += 1) {
    if (groundCnt[i] > 0) {
      globalGroundSum += groundSum[i] / groundCnt[i];
      globalGroundCnt += 1;
    }
  }
  const defaultGroundY = globalGroundCnt > 0 ? globalGroundSum / globalGroundCnt : 0.8;

  const sampleGroundY = (sceneX: number, sceneZ: number): number => {
    const worldX = sceneX + originX;
    const worldY = -sceneZ + originY;
    const gx = Math.max(0, Math.min(gridCols - 1, Math.floor((worldX - minX) / cellSize)));
    const gy = Math.max(0, Math.min(gridRows - 1, Math.floor((worldY - minY) / cellSize)));
    const idx = gy * gridCols + gx;
    if (groundCnt[idx] > 0) {
      return groundSum[idx] / groundCnt[idx];
    }
    // Check 3x3 neighborhood if exact cell had no class-2 ground returns
    let nSum = 0;
    let nCnt = 0;
    for (let dy = -1; dy <= 1; dy += 1) {
      for (let dx = -1; dx <= 1; dx += 1) {
        const nx = gx + dx;
        const ny = gy + dy;
        if (nx >= 0 && nx < gridCols && ny >= 0 && ny < gridRows) {
          const nIdx = ny * gridCols + nx;
          if (groundCnt[nIdx] > 0) {
            nSum += groundSum[nIdx] / groundCnt[nIdx];
            nCnt += 1;
          }
        }
      }
    }
    if (nCnt > 0) return nSum / nCnt;
    if (Number.isFinite(fallbackMinY[idx])) return fallbackMinY[idx];
    return defaultGroundY;
  };

  return {
    header: {
      version: `${versionMajor}.${versionMinor}`,
      pointFormat,
      pointRecordLength,
      totalPointCount,
      renderedPointCount: outIdx,
      hasRgb: hasNonZeroRgb,
      boundsRaw: { minX, maxX, minY, maxY, minZ, maxZ },
      spanMeters: {
        x: Number(spanX.toFixed(2)),
        y: Number(spanY.toFixed(2)),
        z: Number(spanZ.toFixed(2)),
      },
    },
    origin: { x: originX, y: originY, z: originZ },
    positions: positions.subarray(0, outIdx * 3),
    rgbColors: rgbColors.subarray(0, outIdx * 3),
    elevationColors: elevationColors.subarray(0, outIdx * 3),
    classificationColors: classificationColors.subarray(0, outIdx * 3),
    sampleGroundY,
  };
}
