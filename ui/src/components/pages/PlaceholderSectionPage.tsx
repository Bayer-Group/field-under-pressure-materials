import { ArrowLeft, Construction } from 'lucide-react';
import { useLanguage } from '../../contexts/LanguageContext';
import type { NavSectionId } from '../layout/Sidebar';

interface PlaceholderSectionPageProps {
  section: Exclude<NavSectionId, 'dashboard'>;
  onBackToDashboard: () => void;
}

export function PlaceholderSectionPage({ section, onBackToDashboard }: PlaceholderSectionPageProps) {
  const { t } = useLanguage();

  const titles: Record<Exclude<NavSectionId, 'dashboard'>, string> = {
    'row-editor': t.nav.rowEditor,
    analytics: t.nav.analytics,
    layers: t.nav.layers,
    settings: t.nav.settings,
  };

  return (
    <div className="placeholder-section-wrap">
      <div className="card placeholder-section-card">
        <div className="placeholder-icon-ring">
          <Construction size={28} strokeWidth={1.7} />
        </div>
        <h1 className="placeholder-section-title">{titles[section]}</h1>
        <p className="placeholder-section-desc">
          {section === 'row-editor' ? t.placeholderView.rowEditorNote : t.placeholderView.description}
        </p>
        <button type="button" className="primary-btn" onClick={onBackToDashboard}>
          <ArrowLeft size={16} />
          <span>{t.placeholderView.backToDashboard}</span>
        </button>
      </div>
    </div>
  );
}
