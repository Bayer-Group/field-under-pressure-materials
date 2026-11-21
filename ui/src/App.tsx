import { useState } from 'react';
import { Sidebar, type NavSectionId } from './components/layout/Sidebar';
import { TopBar } from './components/layout/TopBar';
import { DashboardPage } from './components/pages/DashboardPage';
import { PlaceholderSectionPage } from './components/pages/PlaceholderSectionPage';
import { SoilMoisturePage } from './components/pages/SoilMoisturePage';
import { LanguageProvider } from './contexts/LanguageContext';
import { ThemeProvider } from './contexts/ThemeContext';

function AppShell() {
  const [activeSection, setActiveSection] = useState<NavSectionId>('dashboard');

  return (
    <div className="app-shell">
      <Sidebar activeSection={activeSection} onSelectSection={setActiveSection} />
      <div className="app-main-column">
        <TopBar activeSection={activeSection} />
        <main className="app-content">
          {activeSection === 'dashboard' ? (
            <DashboardPage />
          ) : activeSection !== 'analytics' ? (
            <PlaceholderSectionPage
              section={activeSection}
              onBackToDashboard={() => setActiveSection('dashboard')}
            />
          ) : null}
          <div hidden={activeSection !== 'analytics'}>
            <SoilMoisturePage />
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
        <AppShell />
      </LanguageProvider>
    </ThemeProvider>
  );
}

export default App;
