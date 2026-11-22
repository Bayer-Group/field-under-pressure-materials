import { CalendarDays, ChartNoAxesCombined, LayoutDashboard, Route } from 'lucide-react';
import { useLanguage } from '../../contexts/LanguageContext';

export type NavSectionId = 'dashboard' | 'row-editor' | 'analytics' | 'calendar';

interface SidebarProps {
  activeSection: NavSectionId;
  onSelectSection: (section: NavSectionId) => void;
}

export function Sidebar({ activeSection, onSelectSection }: SidebarProps) {
  const { t } = useLanguage();

  const primaryItems: Array<{ id: NavSectionId; label: string; icon: typeof LayoutDashboard }> = [
    { id: 'dashboard', label: t.nav.dashboard, icon: LayoutDashboard },
    { id: 'row-editor', label: t.nav.rowEditor, icon: Route },
    { id: 'analytics', label: t.nav.analytics, icon: ChartNoAxesCombined },
    { id: 'calendar', label: t.nav.calendar, icon: CalendarDays },
  ];

  return (
    <aside className="sidebar" aria-label="Main navigation">
      <button
        type="button"
        className="sidebar-brand"
        onClick={() => onSelectSection('dashboard')}
        title={`${t.app.name} — ${t.app.subtitle}`}
        aria-label={t.app.name}
      >
        <img
          src="/SAGE_logo_kwadrat.png"
          alt={t.app.name}
          className="sidebar-brand-logo"
        />
      </button>

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
    </aside>
  );
}
