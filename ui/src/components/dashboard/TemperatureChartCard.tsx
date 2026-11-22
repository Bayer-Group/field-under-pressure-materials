import { useEffect, useMemo, useRef, useState } from 'react';
import { Thermometer } from 'lucide-react';
import { fetchTemperatureSeries } from '../../api/orchardApi';
import { useLanguage } from '../../contexts/LanguageContext';
import { useOrchard } from '../../contexts/OrchardContext';
import type { TemperaturePoint, TemperatureSeriesResponse, TimeRange } from '../../types/orchard';
import { readPagePref, writePagePref } from '../../utils/pagePrefs';

const TIME_RANGES: TimeRange[] = ['24h', '7d', '30d', '90d'];

interface TemperaturePrefs {
  range: TimeRange;
  windowPercent: number;
}

const DEFAULT_TEMP_PREFS: TemperaturePrefs = { range: '30d', windowPercent: 100 };

function readTemperaturePrefs(): TemperaturePrefs {
  const saved = readPagePref<Partial<TemperaturePrefs>>('dashboard.temperature', DEFAULT_TEMP_PREFS);
  const range = saved && TIME_RANGES.includes(saved.range as TimeRange) ? (saved.range as TimeRange) : '30d';
  const rawPct = typeof saved?.windowPercent === 'number' && Number.isFinite(saved.windowPercent) ? saved.windowPercent : 100;
  return { range, windowPercent: Math.max(20, Math.min(100, Math.round(rawPct))) };
}

function buildPath(coords: Array<{ x: number; y: number }>): string {
  if (coords.length === 0) return '';
  if (coords.length === 1) return `M ${coords[0].x} ${coords[0].y}`;
  return coords.map((pt, i) => `${i === 0 ? 'M' : 'L'} ${pt.x.toFixed(1)} ${pt.y.toFixed(1)}`).join(' ');
}

function pointHourlyTemp(p: TemperaturePoint): number {
  return Number(((p.minTempC + p.maxTempC) / 2).toFixed(1));
}

export function TemperatureChartCard() {
  const { t } = useLanguage();
  const { selectedOrchardId } = useOrchard();
  const initialPrefs = useMemo(readTemperaturePrefs, []);
  const [range, setRange] = useState<TimeRange>(initialPrefs.range);
  const [windowPercent, setWindowPercent] = useState<number>(initialPrefs.windowPercent);
  const [series, setSeries] = useState<TemperatureSeriesResponse | null>(null);
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);

  useEffect(() => {
    writePagePref('dashboard.temperature', { range, windowPercent });
  }, [range, windowPercent]);

  const isHourlyMode = range === '24h';

  useEffect(() => {
    const controller = new AbortController();
    fetchTemperatureSeries(range, selectedOrchardId, controller.signal)
      .then((res) => {
        setSeries(res.data);
        setHoverIndex(null);
      })
      .catch((err) => {
        if ((err as Error).name !== 'AbortError') {
          console.error('Failed to fetch temperature series:', err);
        }
      });

    return () => controller.abort();
  }, [range, selectedOrchardId]);

  const visiblePoints: TemperaturePoint[] = useMemo(() => {
    if (!series || series.points.length === 0) return [];
    const total = series.points.length;
    const count = Math.max(4, Math.round((total * windowPercent) / 100));
    return series.points.slice(total - count);
  }, [series, windowPercent]);

  const stats = useMemo(() => {
    if (visiblePoints.length === 0) {
      return { min: 0, max: 0, avgSpread: 0, avgTemp: 0, latestTemp: 0 };
    }
    let min = Infinity;
    let max = -Infinity;
    let spreadSum = 0;
    let avgSum = 0;
    for (const p of visiblePoints) {
      if (p.minTempC < min) min = p.minTempC;
      if (p.maxTempC > max) max = p.maxTempC;
      spreadSum += p.maxTempC - p.minTempC;
      avgSum += pointHourlyTemp(p);
    }
    const last = visiblePoints[visiblePoints.length - 1];
    return {
      min,
      max,
      avgSpread: Number((spreadSum / visiblePoints.length).toFixed(1)),
      avgTemp: Number((avgSum / visiblePoints.length).toFixed(1)),
      latestTemp: pointHourlyTemp(last),
    };
  }, [visiblePoints]);

  // Responsive SVG coordinate system
  const width = 680;
  const height = 240;
  const pad = { top: 18, right: 20, bottom: 34, left: 44 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;

  const yDomain = useMemo(() => {
    const rawMin = Math.min(stats.min, 0);
    const rawMax = Math.max(stats.max, 5);
    const span = Math.max(6, rawMax - rawMin);
    const margin = span * 0.14;
    const yMin = Math.floor((rawMin - margin) / 2) * 2;
    const yMax = Math.ceil((rawMax + margin) / 2) * 2;
    return { yMin, yMax };
  }, [stats.min, stats.max]);

  const toX = (idx: number) => {
    if (visiblePoints.length <= 1) return pad.left + plotW / 2;
    return pad.left + (idx / (visiblePoints.length - 1)) * plotW;
  };

  const toY = (temp: number) => {
    const ratio = (temp - yDomain.yMin) / Math.max(1, yDomain.yMax - yDomain.yMin);
    return pad.top + plotH - ratio * plotH;
  };

  const yTicks = useMemo(() => {
    const tickCount = 5;
    const step = (yDomain.yMax - yDomain.yMin) / (tickCount - 1);
    return Array.from({ length: tickCount }, (_, i) => Number((yDomain.yMin + i * step).toFixed(0)));
  }, [yDomain]);

  const xTickIndices = useMemo(() => {
    const n = visiblePoints.length;
    if (n <= 1) return [0];
    const desired = Math.min(6, n);
    const indices = new Set<number>();
    for (let i = 0; i < desired; i += 1) {
      indices.add(Math.round((i * (n - 1)) / (desired - 1)));
    }
    return Array.from(indices);
  }, [visiblePoints.length]);

  const maxCoords = visiblePoints.map((p, i) => ({ x: toX(i), y: toY(p.maxTempC) }));
  const minCoords = visiblePoints.map((p, i) => ({ x: toX(i), y: toY(p.minTempC) }));
  const hourlyCoords = visiblePoints.map((p, i) => ({ x: toX(i), y: toY(pointHourlyTemp(p)) }));

  const maxPath = buildPath(maxCoords);
  const minPath = buildPath(minCoords);
  const hourlyPath = buildPath(hourlyCoords);

  const areaPath = useMemo(() => {
    if (isHourlyMode) {
      if (hourlyCoords.length < 2) return '';
      const baseY = pad.top + plotH;
      const forward = hourlyCoords
        .map((pt, i) => `${i === 0 ? 'M' : 'L'} ${pt.x.toFixed(1)} ${pt.y.toFixed(1)}`)
        .join(' ');
      const lastX = hourlyCoords[hourlyCoords.length - 1].x.toFixed(1);
      const firstX = hourlyCoords[0].x.toFixed(1);
      return `${forward} L ${lastX} ${baseY} L ${firstX} ${baseY} Z`;
    }
    if (maxCoords.length < 2) return '';
    const forward = maxCoords.map((pt, i) => `${i === 0 ? 'M' : 'L'} ${pt.x.toFixed(1)} ${pt.y.toFixed(1)}`).join(' ');
    const backward = [...minCoords]
      .reverse()
      .map((pt) => `L ${pt.x.toFixed(1)} ${pt.y.toFixed(1)}`)
      .join(' ');
    return `${forward} ${backward} Z`;
  }, [isHourlyMode, hourlyCoords, maxCoords, minCoords, pad.top, plotH]);

  const showFrostLine = yDomain.yMin < 0 && yDomain.yMax > 0;
  const frostY = toY(0);

  const handlePointerMove = (event: React.MouseEvent<SVGSVGElement>) => {
    if (!svgRef.current || visiblePoints.length === 0) return;
    const rect = svgRef.current.getBoundingClientRect();
    const relX = ((event.clientX - rect.left) / rect.width) * width;
    const clampedX = Math.max(pad.left, Math.min(pad.left + plotW, relX));
    const ratio = (clampedX - pad.left) / plotW;
    const idx = Math.round(ratio * (visiblePoints.length - 1));
    setHoverIndex(Math.max(0, Math.min(visiblePoints.length - 1, idx)));
  };

  const hoveredPoint = hoverIndex !== null ? visiblePoints[hoverIndex] : null;
  const hoveredX = hoverIndex !== null ? toX(hoverIndex) : 0;
  const cardTitle = isHourlyMode ? t.temperature.titleHourly : t.temperature.title;

  return (
    <section className="card chart-card">
      <div className="card-header">
        <div className="card-title-row">
          <div className="card-icon">
            <Thermometer size={18} strokeWidth={1.9} />
          </div>
          <h2 className="card-title">{cardTitle}</h2>
        </div>

        <div className="time-scale-controls">
          <div className="segmented-control" role="group" aria-label={t.temperature.timeScale}>
            {TIME_RANGES.map((item) => (
              <button
                key={item}
                type="button"
                className={`segmented-btn${range === item ? ' is-active' : ''}`}
                onClick={() => {
                  setRange(item);
                  setWindowPercent(100);
                }}
              >
                {t.temperature.ranges[item]}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="temp-meta-bar">
        <div className="temp-stats">
          {isHourlyMode ? (
            <>
              <div className="stat-chip">
                <span className="stat-dot stat-dot-hourly" />
                <span className="stat-label">{t.temperature.latestLabel}:</span>
                <strong className="stat-value">{stats.latestTemp.toFixed(1)}°C</strong>
              </div>
              <div className="stat-chip">
                <span className="stat-label">{t.temperature.avgLabel}:</span>
                <strong className="stat-value">{stats.avgTemp.toFixed(1)}°C</strong>
              </div>
            </>
          ) : (
            <>
              <div className="stat-chip">
                <span className="stat-dot stat-dot-min" />
                <span className="stat-label">{t.temperature.periodMin}:</span>
                <strong className="stat-value">{stats.min.toFixed(1)}°C</strong>
              </div>
              <div className="stat-chip">
                <span className="stat-dot stat-dot-max" />
                <span className="stat-label">{t.temperature.periodMax}:</span>
                <strong className="stat-value">{stats.max.toFixed(1)}°C</strong>
              </div>
              <div className="stat-chip">
                <span className="stat-label">{t.temperature.avgSpread}:</span>
                <strong className="stat-value">{stats.avgSpread.toFixed(1)}°C</strong>
              </div>
            </>
          )}
        </div>

        <label className="zoom-slider-control">
          <span className="zoom-slider-label">
            {t.temperature.windowAdjust}: <strong>{windowPercent}%</strong>
          </span>
          <input
            type="range"
            min={25}
            max={100}
            step={5}
            value={windowPercent}
            onChange={(e) => setWindowPercent(Number(e.target.value))}
            className="zoom-slider"
            aria-label={t.temperature.windowAdjust}
          />
        </label>
      </div>

      <div className="chart-canvas-wrap">
        {visiblePoints.length === 0 ? (
          <div className="empty-rows-state" style={{ marginTop: 48 }}>
            {t.temperature.noData}
          </div>
        ) : (
          <>
            <svg
              ref={svgRef}
              viewBox={`0 0 ${width} ${height}`}
              className="temp-svg"
              role="img"
              aria-label={cardTitle}
              onMouseMove={handlePointerMove}
              onMouseLeave={() => setHoverIndex(null)}
            >
              <defs>
                <linearGradient id="tempBandGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="var(--temp-max)" stopOpacity="0.22" />
                  <stop offset="100%" stopColor="var(--temp-min)" stopOpacity="0.16" />
                </linearGradient>
                <linearGradient id="tempHourlyGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.24" />
                  <stop offset="100%" stopColor="var(--accent)" stopOpacity="0.02" />
                </linearGradient>
              </defs>

              {/* Horizontal gridlines & Y ticks */}
              {yTicks.map((tick) => {
                const y = toY(tick);
                return (
                  <g key={tick}>
                    <line x1={pad.left} y1={y} x2={pad.left + plotW} y2={y} className="chart-grid-line" />
                    <text x={pad.left - 10} y={y + 4} textAnchor="end" className="chart-axis-text">
                      {tick}°
                    </text>
                  </g>
                );
              })}

              {/* 0°C frost reference line */}
              {showFrostLine && (
                <g>
                  <line
                    x1={pad.left}
                    y1={frostY}
                    x2={pad.left + plotW}
                    y2={frostY}
                    className="chart-frost-line"
                    strokeDasharray="4 4"
                  />
                  <text x={pad.left + plotW - 4} y={frostY - 6} textAnchor="end" className="chart-frost-label">
                    0°C
                  </text>
                </g>
              )}

              {/* Shaded area */}
              {areaPath && (
                <path d={areaPath} fill={isHourlyMode ? 'url(#tempHourlyGrad)' : 'url(#tempBandGrad)'} />
              )}

              {/* Single hourly curve (24h) OR Min/Max dual lines (7d/30d/90d) */}
              {isHourlyMode ? (
                hourlyPath && (
                  <path
                    d={hourlyPath}
                    fill="none"
                    className="temp-line-hourly"
                    strokeWidth={2.4}
                    strokeLinejoin="round"
                  />
                )
              ) : (
                <>
                  {minPath && (
                    <path
                      d={minPath}
                      fill="none"
                      className="temp-line-min"
                      strokeWidth={2.2}
                      strokeLinejoin="round"
                    />
                  )}
                  {maxPath && (
                    <path
                      d={maxPath}
                      fill="none"
                      className="temp-line-max"
                      strokeWidth={2.2}
                      strokeLinejoin="round"
                    />
                  )}
                </>
              )}

              {/* X-axis ticks */}
              {xTickIndices.map((idx) => {
                const pt = visiblePoints[idx];
                if (!pt) return null;
                return (
                  <text key={idx} x={toX(idx)} y={height - 10} textAnchor="middle" className="chart-axis-text">
                    {pt.label}
                  </text>
                );
              })}

              {/* Hover vertical guide & active markers */}
              {hoverIndex !== null && hoveredPoint && (
                <g>
                  <line x1={hoveredX} y1={pad.top} x2={hoveredX} y2={pad.top + plotH} className="chart-hover-guide" />
                  {isHourlyMode ? (
                    <circle cx={hoveredX} cy={toY(pointHourlyTemp(hoveredPoint))} r={4.5} className="temp-dot-hourly" />
                  ) : (
                    <>
                      <circle cx={hoveredX} cy={toY(hoveredPoint.maxTempC)} r={4.5} className="temp-dot-max" />
                      <circle cx={hoveredX} cy={toY(hoveredPoint.minTempC)} r={4.5} className="temp-dot-min" />
                    </>
                  )}
                </g>
              )}
            </svg>

            {hoveredPoint && hoverIndex !== null && (
              <div
                className="chart-tooltip"
                style={{
                  left: `${Math.min(76, Math.max(6, (hoveredX / width) * 100))}%`,
                }}
              >
                <div className="chart-tooltip-date">{hoveredPoint.label}</div>
                {isHourlyMode ? (
                  <div className="chart-tooltip-row">
                    <span className="stat-dot stat-dot-hourly" />
                    <span>{t.temperature.hourlyLabel}:</span>
                    <strong>{pointHourlyTemp(hoveredPoint).toFixed(1)}°C</strong>
                  </div>
                ) : (
                  <>
                    <div className="chart-tooltip-row">
                      <span className="stat-dot stat-dot-max" />
                      <span>{t.temperature.maxLabel}:</span>
                      <strong>{hoveredPoint.maxTempC.toFixed(1)}°C</strong>
                    </div>
                    <div className="chart-tooltip-row">
                      <span className="stat-dot stat-dot-min" />
                      <span>{t.temperature.minLabel}:</span>
                      <strong>{hoveredPoint.minTempC.toFixed(1)}°C</strong>
                    </div>
                  </>
                )}
              </div>
            )}
          </>
        )}
      </div>

      <div className="card-footer-meta">
        <div className="legend-inline">
          {isHourlyMode ? (
            <span className="legend-item">
              <span className="legend-line legend-line-hourly" />
              {t.temperature.hourlyLabel}
            </span>
          ) : (
            <>
              <span className="legend-item">
                <span className="legend-line legend-line-max" />
                {t.temperature.maxLabel}
              </span>
              <span className="legend-item">
                <span className="legend-line legend-line-min" />
                {t.temperature.minLabel}
              </span>
            </>
          )}
          {showFrostLine && (
            <span className="legend-item">
              <span className="legend-line legend-line-frost" />
              {t.temperature.frostLine}
            </span>
          )}
        </div>
      </div>
    </section>
  );
}
