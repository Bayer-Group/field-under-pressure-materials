import { useEffect, useState } from 'react';
import { HeartPulse } from 'lucide-react';
import { fetchOrchardHealth } from '../../api/orchardApi';
import { HEALTH_PALETTE, HEALTH_STATUS_ORDER, UNRATED_HEALTH_TOKEN } from '../../constants/healthPalette';
import { useLanguage } from '../../contexts/LanguageContext';
import { useOrchard } from '../../contexts/OrchardContext';
import { useTheme } from '../../contexts/ThemeContext';
import type { OrchardHealthSummary } from '../../types/orchard';

export function OrchardHealthCard() {
  const { t, language } = useLanguage();
  const { resolvedTheme } = useTheme();
  const { selectedOrchardId } = useOrchard();
  const [summary, setSummary] = useState<OrchardHealthSummary | null>(null);
  const [endpoint, setEndpoint] = useState<string>('');

  useEffect(() => {
    const controller = new AbortController();
    setSummary(null);
    setEndpoint('');
    fetchOrchardHealth(selectedOrchardId, controller.signal)
      .then((res) => {
        if (controller.signal.aborted) return;
        setSummary(res.data);
        setEndpoint(res.endpoint);
      })
      .catch((err) => {
        if ((err as Error).name !== 'AbortError') {
          console.error('Failed to fetch orchard health summary:', err);
        }
      });

    return () => controller.abort();
  }, [selectedOrchardId]);

  const score = summary?.averageScore ?? null;
  const overallStatus = summary?.overallStatus ?? null;
  const totalTrees = summary?.totalTrees ?? 0;
  const unratedTrees = summary?.distribution.unrated ?? 0;
  const statusToken = overallStatus ? HEALTH_PALETTE[overallStatus] : UNRATED_HEALTH_TOKEN;
  const statusLabel = overallStatus ? t.health.statuses[overallStatus] : t.health.statuses.unrated;

  // Semi-circular radial gauge geometry
  const radius = 78;
  const circumference = Math.PI * radius;
  const clampedScore = score !== null ? Math.max(0, Math.min(100, score)) : 0;
  const strokeDashoffset = circumference * (1 - clampedScore / 100);

  const badgeBg = resolvedTheme === 'dark' ? statusToken.softBgDark : statusToken.softBgLight;
  const badgeBorder = resolvedTheme === 'dark' ? statusToken.borderDark : statusToken.borderLight;

  return (
    <section className="card health-card">
      <div className="card-header">
        <div className="card-title-row">
          <div className="card-icon">
            <HeartPulse size={18} strokeWidth={1.9} />
          </div>
          <h2 className="card-title">{t.health.title}</h2>
        </div>
      </div>

      <div className="health-gauge-wrap">
        <svg viewBox="0 0 200 118" className="health-gauge-svg" role="img" aria-label={t.health.title}>
          {/* 4-tier reference track segments: black -> red -> orange -> green */}
          <path
            d="M 22 102 A 78 78 0 0 1 178 102"
            fill="none"
            stroke="var(--border-subtle)"
            strokeWidth={14}
            strokeLinecap="round"
          />

          {/* Active averaged score arc */}
          <path
            d="M 22 102 A 78 78 0 0 1 178 102"
            fill="none"
            stroke={statusToken.hex}
            strokeWidth={14}
            strokeLinecap="round"
            strokeDasharray={circumference}
            strokeDashoffset={strokeDashoffset}
            className="health-gauge-progress"
          />

          <text x="100" y="76" textAnchor="middle" className="health-score-value">
            {score !== null ? score : '—'}
          </text>
          <text x="100" y="96" textAnchor="middle" className="health-score-caption">
            {score !== null ? `/ 100 · ${t.health.averageIndex}` : t.health.statuses.unrated}
          </text>
        </svg>

        <div className="health-status-row">
          <span
            className="health-status-badge"
            style={{
              backgroundColor: badgeBg,
              borderColor: badgeBorder,
            }}
          >
            <span
              className="health-swatch"
              style={{
                backgroundColor: statusToken.hex,
                borderColor: overallStatus === 'dead' && resolvedTheme === 'dark' ? '#71717a' : 'transparent',
              }}
            />
            {statusLabel}
          </span>
          <span className="health-total-label">
            {t.health.totalTrees}: <strong>{totalTrees}</strong>
          </span>
        </div>
      </div>

      <div className="health-distribution">
        <div className="health-dist-title">{t.health.scaleTitle}</div>
        {unratedTrees > 0 && (
          <div className="muted-caption">{t.health.statuses.unrated}: {unratedTrees}</div>
        )}
        {!!summary?.estimatedTrees && (
          <div className="muted-caption">{language === 'pl' ? 'Szacunek ML' : 'ML estimate'} · {summary.estimatedTrees}/{totalTrees}</div>
        )}

        {/* Stacked horizontal bar */}
        <div className="health-stacked-bar" aria-label={t.health.scaleTitle}>
          {HEALTH_STATUS_ORDER.map((status) => {
            const count = summary?.distribution[status] ?? 0;
            const pct = totalTrees > 0 ? (count / totalTrees) * 100 : 0;
            if (pct <= 0) return null;
            return (
              <div
                key={status}
                className="health-stacked-segment"
                style={{
                  width: `${pct}%`,
                  backgroundColor: HEALTH_PALETTE[status].hex,
                }}
                title={`${t.health.statuses[status]}: ${count} (${pct.toFixed(1)}%)`}
              />
            );
          })}
        </div>

        {/* 4-tier legend breakdown */}
        <div className="health-breakdown-list">
          {HEALTH_STATUS_ORDER.map((status) => {
            const count = summary?.distribution[status] ?? 0;
            const pct = totalTrees > 0 ? Math.round((count / totalTrees) * 100) : 0;
            const token = HEALTH_PALETTE[status];
            return (
              <div key={status} className="health-breakdown-item">
                <span className="health-breakdown-left">
                  <span
                    className="health-swatch"
                    style={{
                      backgroundColor: token.hex,
                      borderColor: status === 'dead' && resolvedTheme === 'dark' ? '#71717a' : 'transparent',
                    }}
                  />
                  <span className="health-breakdown-label">{t.health.statuses[status]}</span>
                </span>
                <span className="health-breakdown-right">
                  <strong>{count}</strong>
                  <span className="health-breakdown-pct">{pct}%</span>
                </span>
              </div>
            );
          })}
        </div>
      </div>

      <div className="card-footer-meta">
        <span className="muted-caption">{t.health.overallLabel}</span>
        <code className="endpoint-tag">GET {endpoint}</code>
      </div>
    </section>
  );
}
