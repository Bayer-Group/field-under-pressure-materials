import { Globe, Monitor, Moon, Sun } from 'lucide-react';
import { apiConfig } from '../../config/apiConfig';
import { useLanguage } from '../../contexts/LanguageContext';
import { useTheme, type ThemePreference } from '../../contexts/ThemeContext';
import type { Language } from '../../i18n/translations';
import type { NavSectionId } from './Sidebar';

interface TopBarProps {
  activeSection: NavSectionId;
}

export function TopBar({ activeSection }: TopBarProps) {
  const { preference, setPreference } = useTheme();
  const { language, setLanguage, t } = useLanguage();

  const sectionLabels: Record<NavSectionId, string> = {
    dashboard: t.nav.dashboard,
    'row-editor': t.nav.rowEditor,
    analytics: t.nav.analytics,
    layers: t.nav.layers,
    settings: t.nav.settings,
  };

  const themeOptions: Array<{ value: ThemePreference; label: string; icon: typeof Sun }> = [
    { value: 'system', label: t.topbar.themeSystem, icon: Monitor },
    { value: 'light', label: t.topbar.themeLight, icon: Sun },
    { value: 'dark', label: t.topbar.themeDark, icon: Moon },
  ];

  const languages: Language[] = ['pl', 'en'];

  return (
    <header className="topbar">
      <div className="topbar-left">
        <div className="topbar-title-group">
          <span className="topbar-app-name">{t.app.name}</span>
          <span className="topbar-divider" aria-hidden="true">
            /
          </span>
          <span className="topbar-section-name">{sectionLabels[activeSection]}</span>
        </div>

        {apiConfig.usePlaceholders && activeSection !== 'analytics' && (
          <span className="placeholder-pill" title={t.app.placeholderTooltip}>
            <span className="placeholder-pill-dot" aria-hidden="true" />
            {t.app.placeholderBadge}
          </span>
        )}
      </div>

      <div className="topbar-right">
        <div className="segmented-control" role="group" aria-label={t.topbar.themeLabel}>
          {themeOptions.map((option) => {
            const Icon = option.icon;
            const active = preference === option.value;
            return (
              <button
                key={option.value}
                type="button"
                className={`segmented-btn${active ? ' is-active' : ''}`}
                onClick={() => setPreference(option.value)}
                title={`${t.topbar.themeLabel}: ${option.label}`}
                aria-pressed={active}
              >
                <Icon size={14} strokeWidth={1.9} />
                <span className="segmented-btn-text">{option.label}</span>
              </button>
            );
          })}
        </div>

        <div className="segmented-control" role="group" aria-label={t.topbar.languageLabel}>
          <span className="lang-icon" aria-hidden="true">
            <Globe size={14} strokeWidth={1.9} />
          </span>
          {languages.map((lang) => {
            const active = language === lang;
            return (
              <button
                key={lang}
                type="button"
                className={`segmented-btn lang-btn${active ? ' is-active' : ''}`}
                onClick={() => setLanguage(lang)}
                aria-pressed={active}
                title={`${t.topbar.languageLabel}: ${lang.toUpperCase()}`}
              >
                {lang.toUpperCase()}
              </button>
            );
          })}
        </div>
      </div>
    </header>
  );
}
