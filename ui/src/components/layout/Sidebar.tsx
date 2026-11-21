import { ChartNoAxesCombined, Layers, LayoutDashboard, Route, Settings } from 'lucide-react';
import { useLanguage } from '../../contexts/LanguageContext';

export type NavSectionId = 'dashboard' | 'row-editor' | 'analytics' | 'layers' | 'settings';

interface SidebarProps {
  activeSection: NavSectionId;
  onSelectSection: (section: NavSectionId) => void;
}

export function Sidebar({ activeSection, onSelectSection }: SidebarProps) {
  const { t } = useLanguage();

  // Minimalist placeholder navigation items — icons and final routes will be refined later
  const primaryItems: Array<{ id: NavSectionId; label: string; icon: typeof LayoutDashboard }> = [
    { id: 'dashboard', label: t.nav.dashboard, icon: LayoutDashboard },
    { id: 'row-editor', label: t.nav.rowEditor, icon: Route },
    { id: 'analytics', label: t.nav.analytics, icon: ChartNoAxesCombined },
    { id: 'layers', label: t.nav.layers, icon: Layers },
  ];

  return (
    <aside className="sidebar" aria-label="Main navigation">
      <div className="sidebar-brand" title={t.app.name}>
        <span className="sidebar-brand-mark" aria-hidden="true">
          FP
        </span>
      </div>

      <nav className="sidebar-nav">
        {primaryItems.map((item) => {
          const Icon = item.icon;
          const isActive = activeSection === item.id;
          return (
            <button
              key={item.id}
              type="button"
              className={`sidebar-btn${isActive ? ' is-active' : ''}`}
              onClick={() => onSelectSection(item.id)}
              title={item.label}
              aria-label={item.label}
              aria-current={isActive ? 'page' : undefined}
            >
              <Icon size={20} strokeWidth={1.75} />
            </button>
          );
        })}
      </nav>

      <div className="sidebar-footer">
        <button
          type="button"
          className={`sidebar-btn${activeSection === 'settings' ? ' is-active' : ''}`}
          onClick={() => onSelectSection('settings')}
          title={t.nav.settings}
          aria-label={t.nav.settings}
          aria-current={activeSection === 'settings' ? 'page' : undefined}
        >
          <Settings size={20} strokeWidth={1.75} />
        </button>
      </div>
    </aside>
  );
}
