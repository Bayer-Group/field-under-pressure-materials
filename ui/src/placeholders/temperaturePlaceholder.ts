import type { TemperaturePoint, TemperatureSeriesResponse, TimeRange } from '../types/orchard';

/**
 * [PLACEHOLDER] Deterministic temperature min/max series generator.
 * Remove this entire directory (`src/placeholders/`) once the backend API is live.
 */

function seededRandom(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state * 1664525 + 1013904223) >>> 0;
    return state / 0xffffffff;
  };
}

export function getPlaceholderTemperatureSeries(
  orchardId: string,
  range: TimeRange,
): TemperatureSeriesResponse {
  const now = new Date();
  const points: TemperaturePoint[] = [];

  const config: Record<
    TimeRange,
    { count: number; stepMs: number; seed: number; baseMean: number; spread: number; format: 'hour' | 'day' | 'month' }
  > = {
    '24h': { count: 24, stepMs: 3600 * 1000, seed: 101, baseMean: 11, spread: 4.5, format: 'hour' },
    '7d': { count: 14, stepMs: 12 * 3600 * 1000, seed: 202, baseMean: 12, spread: 7.5, format: 'day' },
    '30d': { count: 30, stepMs: 24 * 3600 * 1000, seed: 303, baseMean: 10.5, spread: 9.2, format: 'day' },
    '90d': { count: 45, stepMs: 2 * 24 * 3600 * 1000, seed: 404, baseMean: 13.5, spread: 10.5, format: 'day' },
    '1y': { count: 52, stepMs: 7 * 24 * 3600 * 1000, seed: 505, baseMean: 9.5, spread: 11.2, format: 'month' },
  };

  const cfg = config[range];
  const rand = seededRandom(cfg.seed);

  for (let i = cfg.count - 1; i >= 0; i -= 1) {
    const dt = new Date(now.getTime() - i * cfg.stepMs);
    const idx = cfg.count - 1 - i;
    const progress = idx / Math.max(1, cfg.count - 1);

    let wave = 0;
    if (range === '24h') {
      const hour = dt.getHours();
      wave = Math.sin(((hour - 5) / 24) * Math.PI * 2) * 5.2;
    } else if (range === '1y') {
      // Full annual seasonal curve
      wave = Math.sin((progress * 2 - 0.5) * Math.PI) * 12.5;
    } else {
      // Multi-day weather fronts + slight frost event in middle of range
      wave = Math.sin(progress * Math.PI * 2.4) * 4.8 - Math.exp(-Math.pow((progress - 0.35) / 0.12, 2)) * 6.5;
    }

    const noise = (rand() - 0.5) * 2.6;
    const dailySpread = cfg.spread * (0.65 + rand() * 0.55);
    const mid = cfg.baseMean + wave + noise;

    const minTempC = Number((mid - dailySpread * 0.52).toFixed(1));
    const maxTempC = Number((mid + dailySpread * 0.48).toFixed(1));

    let label: string;
    if (cfg.format === 'hour') {
      label = `${String(dt.getHours()).padStart(2, '0')}:00`;
    } else if (cfg.format === 'day') {
      label = `${String(dt.getDate()).padStart(2, '0')}.${String(dt.getMonth() + 1).padStart(2, '0')}`;
    } else {
      label = `${String(dt.getDate()).padStart(2, '0')}.${String(dt.getMonth() + 1).padStart(2, '0')}.${String(dt.getFullYear()).slice(-2)}`;
    }

    points.push({
      timestamp: dt.toISOString(),
      label,
      minTempC,
      maxTempC,
    });
  }

  return {
    orchardId,
    range,
    unit: 'C',
    points,
  };
}
