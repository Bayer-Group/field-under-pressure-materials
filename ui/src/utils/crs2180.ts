import type { GeoCoord, Point3D } from '../types/orchard';

export interface Epsg2180Coord {
  /** Easting in meters (PUWG 1992 / EPSG:2180) */
  x: number;
  /** Northing in meters (PUWG 1992 / EPSG:2180) */
  y: number;
}

/**
 * Exact Transverse Mercator projection from WGS 84 (EPSG:4326) to PUWG 1992 (EPSG:2180 / ETRF2000-PL-CS92).
 * Used to align WGS 84 Orchard/Tree vectors with Polish GUGiK LiDAR `.las` clouds in EPSG:2180.
 */
export function wgs84ToEpsg2180(latDeg: number, lonDeg: number): Epsg2180Coord {
  const a = 6378137.0;
  const f = 1.0 / 298.257222101;
  const e2 = 2 * f - f * f;
  const ep2 = e2 / (1.0 - e2);

  const k0 = 0.9993;
  const lon0 = (19.0 * Math.PI) / 180.0;
  const falseEasting = 500000.0;
  const falseNorthing = -5300000.0;

  const phi = (latDeg * Math.PI) / 180.0;
  const lam = (lonDeg * Math.PI) / 180.0;

  const sinPhi = Math.sin(phi);
  const cosPhi = Math.cos(phi);
  const tanPhi = Math.tan(phi);

  const N = a / Math.sqrt(1.0 - e2 * sinPhi * sinPhi);
  const T = tanPhi * tanPhi;
  const C = ep2 * cosPhi * cosPhi;
  const A = cosPhi * (lam - lon0);

  const M =
    a *
    ((1 - e2 / 4 - (3 * e2 * e2) / 64 - (5 * e2 * e2 * e2) / 256) * phi -
      ((3 * e2) / 8 + (3 * e2 * e2) / 32 + (45 * e2 * e2 * e2) / 1024) * Math.sin(2 * phi) +
      ((15 * e2 * e2) / 256 + (45 * e2 * e2 * e2) / 1024) * Math.sin(4 * phi) -
      ((35 * e2 * e2 * e2) / 3072) * Math.sin(6 * phi));

  const A2 = A * A;
  const A3 = A2 * A;
  const A4 = A2 * A2;
  const A5 = A4 * A;
  const A6 = A4 * A2;

  const x =
    falseEasting +
    k0 *
      N *
      (A +
        ((1 - T + C) * A3) / 6.0 +
        ((5 - 18 * T + T * T + 72 * C - 58 * ep2) * A5) / 120.0);

  const y =
    falseNorthing +
    k0 *
      (M +
        N *
          tanPhi *
          (A2 / 2.0 +
            ((5 - T + 9 * C + 4 * C * C) * A4) / 24.0 +
            ((61 - 58 * T + T * T + 600 * C - 330 * ep2) * A6) / 720.0));

  return { x, y };
}

/**
 * Projects a WGS 84 coordinate into Three.js local coordinates centered on the LAS cloud origin.
 * Three.js axes: +X = East, +Y = Elevation Up, -Z = North.
 */
export function geoToLasSceneXZ(
  coord: GeoCoord,
  lasOrigin: { x: number; y: number },
): { x: number; z: number } {
  const projected = wgs84ToEpsg2180(coord.lat, coord.lng);
  return {
    x: Number((projected.x - lasOrigin.x).toFixed(3)),
    z: Number((-(projected.y - lasOrigin.y)).toFixed(3)),
  };
}

export function lasToScenePoint(
  lasX: number,
  lasY: number,
  lasZ: number,
  origin: { x: number; y: number; z: number },
): Point3D {
  return {
    x: lasX - origin.x,
    y: lasZ - origin.z,
    z: -(lasY - origin.y),
  };
}
