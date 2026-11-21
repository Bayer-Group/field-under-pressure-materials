import type { HealthStatus } from '../types/orchard';

export interface HealthColorToken {
  status: HealthStatus;
  hex: string;
  hex3d: number;
  softBgLight: string;
  softBgDark: string;
  borderLight: string;
  borderDark: string;
}

/**
 * Unified orchard tree health color scale:
 * - dead     -> black
 * - poor     -> red
 * - moderate -> orange
 * - healthy  -> green
 */
export const HEALTH_PALETTE: Record<HealthStatus, HealthColorToken> = {
  dead: {
    status: 'dead',
    hex: '#111113',
    hex3d: 0x16161a,
    softBgLight: 'rgba(17, 17, 19, 0.1)',
    softBgDark: 'rgba(161, 161, 170, 0.18)',
    borderLight: '#111113',
    borderDark: '#52525b',
  },
  poor: {
    status: 'poor',
    hex: '#dc2626',
    hex3d: 0xdc2626,
    softBgLight: 'rgba(220, 38, 38, 0.12)',
    softBgDark: 'rgba(239, 68, 68, 0.18)',
    borderLight: '#dc2626',
    borderDark: '#ef4444',
  },
  moderate: {
    status: 'moderate',
    hex: '#f97316',
    hex3d: 0xf97316,
    softBgLight: 'rgba(249, 115, 22, 0.14)',
    softBgDark: 'rgba(251, 146, 60, 0.18)',
    borderLight: '#ea580c',
    borderDark: '#fb923c',
  },
  healthy: {
    status: 'healthy',
    hex: '#16a34a',
    hex3d: 0x16a34a,
    softBgLight: 'rgba(22, 163, 74, 0.12)',
    softBgDark: 'rgba(34, 197, 94, 0.18)',
    borderLight: '#16a34a',
    borderDark: '#22c55e',
  },
};

export const HEALTH_STATUS_ORDER: HealthStatus[] = ['healthy', 'moderate', 'poor', 'dead'];
