import { useCallback, useEffect, useState } from 'react';
import { Sidebar, type NavSectionId } from './components/layout/Sidebar';
import { TopBar } from './components/layout/TopBar';
import { DashboardPage } from './components/pages/DashboardPage';
import { RowLineEditorPage } from './components/pages/RowLineEditorPage';
import { AnalyticsPage } from './components/pages/AnalyticsPage';
import { CalendarPage } from './components/pages/CalendarPage';
import { LanguageProvider } from './contexts/LanguageContext';
import { OrchardProvider } from './contexts/OrchardContext';
import { ThemeProvider } from './contexts/ThemeContext';
import { UserPreferencesSync } from './contexts/UserPreferencesSync';
import { pathForSection, sectionFromPathname } from './utils/pagePrefs';

function resolveInitialSection(): NavSectionId {
  const matched = sectionFromPathname(window.location.pathname);
  if (matched) return matched;
  window.history.replaceState(null, '', pathForSection('dashboard'));
  return 'dashboard';
}

function AppShell() {
  const [activeSection, setActiveSection] = useState<NavSectionId>(resolveInitialSection);

  const navigateToSection = useCallback((section: NavSectionId) => {
    setActiveSection(section);
    const targetPath = pathForSection(section);
    if (window.location.pathname !== targetPath) {
      window.history.pushState(null, '', targetPath);
    }
  }, []);

  useEffect(() => {
    const onPopState = () => {
      const matched = sectionFromPathname(window.location.pathname);
      if (matched) {
        setActiveSection(matched);
      } else {
        window.history.replaceState(null, '', pathForSection('dashboard'));
        setActiveSection('dashboard');
      }
    };
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, []);

  return (
    <div className="app-shell">
      <Sidebar activeSection={activeSection} onSelectSection={navigateToSection} />
      <div className="app-main-column">
        <TopBar activeSection={activeSection} />
        <main className="app-content">
          {activeSection === 'dashboard' ? (
            <DashboardPage />
          ) : activeSection === 'row-editor' ? (
            <RowLineEditorPage />
          ) : activeSection === 'calendar' ? (
            <CalendarPage />
          ) : null}
          <div hidden={activeSection !== 'analytics'}>
            <AnalyticsPage active={activeSection === 'analytics'} />
          </div>
        </main>
      </div>
    </div>
  );
}

export function App() {
  return (
    <ThemeProvider>
      <LanguageProvider>
        <OrchardProvider>
          <UserPreferencesSync />
          <AppShell />
        </OrchardProvider>
      </LanguageProvider>
    </ThemeProvider>
  );
}

export default App;
