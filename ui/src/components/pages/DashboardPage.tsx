import { useLanguage } from '../../contexts/LanguageContext';
import { Orchard3DViewerCard } from '../dashboard/Orchard3DViewerCard';
import { OrchardHealthCard } from '../dashboard/OrchardHealthCard';
import { TemperatureChartCard } from '../dashboard/TemperatureChartCard';

export function DashboardPage() {
  const { t } = useLanguage();

  return (
    <div className="dashboard-page">
      <div className="page-intro">
        <div>
          <h1 className="page-title">{t.dashboard.sectionTitle}</h1>
          <p className="page-subtitle">{t.dashboard.sectionSubtitle}</p>
        </div>
        <span className="page-meta-hint">{t.dashboard.moreChartsHint}</span>
      </div>

      {/* Top extensible dashboard charts grid */}
      <div className="dashboard-charts-grid">
        <TemperatureChartCard />
        <OrchardHealthCard />
      </div>

      {/* Bottom 3D orchard point-cloud & individual trees render */}
      <div className="dashboard-3d-section">
        <Orchard3DViewerCard />
      </div>
    </div>
  );
}
