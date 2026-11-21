export type Language = 'pl' | 'en';

export interface Translations {
  app: {
    name: string;
    subtitle: string;
    placeholderBadge: string;
    placeholderTooltip: string;
  };
  nav: {
    dashboard: string;
    rowEditor: string;
    analytics: string;
    layers: string;
    settings: string;
    placeholderHint: string;
  };
  topbar: {
    themeLabel: string;
    themeSystem: string;
    themeLight: string;
    themeDark: string;
    languageLabel: string;
  };
  dashboard: {
    sectionTitle: string;
    sectionSubtitle: string;
    moreChartsHint: string;
  };
  temperature: {
    title: string;
    subtitle: string;
    minLabel: string;
    maxLabel: string;
    frostLine: string;
    timeScale: string;
    windowAdjust: string;
    periodMin: string;
    periodMax: string;
    avgSpread: string;
    ranges: {
      '24h': string;
      '7d': string;
      '30d': string;
      '90d': string;
      '1y': string;
    };
  };
  health: {
    title: string;
    subtitle: string;
    averageIndex: string;
    totalTrees: string;
    overallLabel: string;
    scaleTitle: string;
    statuses: {
      dead: string;
      poor: string;
      moderate: string;
      healthy: string;
    };
  };
  orchard3d: {
    title: string;
    subtitle: string;
    pointCloudLayer: string;
    treesLayer: string;
    rowLinesLayer: string;
    viewOrbit: string;
    viewTop: string;
    resetView: string;
    pointsStat: string;
    treesStat: string;
    rowsStat: string;
    controlsHint: string;
    inspectorTitle: string;
    inspectorClose: string;
    inspectorRow: string;
    inspectorHealth: string;
    inspectorHeight: string;
    inspectorCanopy: string;
    inspectorLocalPos: string;
    inspectorGeo: string;
    selectTreePrompt: string;
  };
  placeholderView: {
    title: string;
    description: string;
    rowEditorNote: string;
    backToDashboard: string;
  };
}

export const TRANSLATIONS: Record<Language, Translations> = {
  pl: {
    app: {
      name: 'Field Under Pressure',
      subtitle: 'Monitoring Sadu 3D',
      placeholderBadge: 'Tryb Placeholderów',
      placeholderTooltip: 'Brak aktywnego backendu — wyświetlane są dane testowe z src/placeholders/.',
    },
    nav: {
      dashboard: 'Dashboard',
      rowEditor: 'Edytor linii rzędów (wkrótce)',
      analytics: 'Analityka (placeholder)',
      layers: 'Warstwy i skany (placeholder)',
      settings: 'Ustawienia (placeholder)',
      placeholderHint: 'Ikony tymczasowe',
    },
    topbar: {
      themeLabel: 'Motyw',
      themeSystem: 'System',
      themeLight: 'Jasny',
      themeDark: 'Ciemny',
      languageLabel: 'Język',
    },
    dashboard: {
      sectionTitle: 'Panel Główny Sadu',
      sectionSubtitle: 'Monitorowanie mikroklimatu, uśrednionej kondycji drzew oraz wizualizacja 3D chmury punktów.',
      moreChartsHint: 'Siatka przygotowana pod kolejne wykresy',
    },
    temperature: {
      title: 'Temperatura Min / Max',
      subtitle: 'Wykres liniowy z dostrajaniem skali czasu',
      minLabel: 'Temp. min',
      maxLabel: 'Temp. max',
      frostLine: 'Próg przymrozku (0°C)',
      timeScale: 'Skala czasu',
      windowAdjust: 'Dostrajanie okna',
      periodMin: 'Min w oknie',
      periodMax: 'Max w oknie',
      avgSpread: 'Śr. amplituda',
      ranges: {
        '24h': '24h',
        '7d': '7 dni',
        '30d': '30 dni',
        '90d': '90 dni',
        '1y': '1 rok',
      },
    },
    health: {
      title: 'Zdrowie Drzew w Sadzie',
      subtitle: 'Ogólny uśredniony wskaźnik kondycji',
      averageIndex: 'Średni indeks',
      totalTrees: 'Drzewa',
      overallLabel: 'Stan ogólny',
      scaleTitle: 'Rozkład kondycji drzew',
      statuses: {
        dead: 'Martwe',
        poor: 'Zły stan',
        moderate: 'Średni',
        healthy: 'Poprawny',
      },
    },
    orchard3d: {
      title: 'Render 3D Sadu — Chmura Punktów i Drzewa',
      subtitle: 'Pojedyncze obiekty 3D wyliczone z linii rzędów nałożone na chmurę punktów terenu',
      pointCloudLayer: 'Chmura punktów',
      treesLayer: 'Drzewa 3D',
      rowLinesLayer: 'Linie rzędów',
      viewOrbit: 'Widok 3D',
      viewTop: 'Widok z góry',
      resetView: 'Resetuj kamerę',
      pointsStat: 'Punktów',
      treesStat: 'Drzew 3D',
      rowsStat: 'Rzędów',
      controlsHint: 'LPM: obrót · PPM: przesuwanie · Scroll: zoom · Kliknij drzewo: szczegóły',
      inspectorTitle: 'Wybrane drzewo',
      inspectorClose: 'Zamknij',
      inspectorRow: 'Rząd / Pozycja',
      inspectorHealth: 'Kondycja',
      inspectorHeight: 'Wysokość',
      inspectorCanopy: 'Promień korony',
      inspectorLocalPos: 'Pozycja 3D (m)',
      inspectorGeo: 'Współrzędne GPS',
      selectTreePrompt: 'Kliknij dowolne drzewo 3D, aby podejrzeć jego parametry',
    },
    placeholderView: {
      title: 'Ekran w przygotowaniu',
      description: 'Ten widok jest obecnie placeholderem w nawigacji i zostanie rozbudowany w kolejnych krokach.',
      rowEditorNote:
        'Tutaj znajdzie się ekran rysowania linii rzędów na mapie, na podstawie których backend wyliczy dokładne pozycje pojedynczych drzew 3D (POST /api/v1/orchard/row-lines).',
      backToDashboard: 'Wróć do Dashboardu',
    },
  },
  en: {
    app: {
      name: 'Field Under Pressure',
      subtitle: '3D Orchard Intelligence',
      placeholderBadge: 'Placeholder Mode',
      placeholderTooltip: 'No live backend connected yet — rendering placeholder data from src/placeholders/.',
    },
    nav: {
      dashboard: 'Dashboard',
      rowEditor: 'Row Line Editor (coming next)',
      analytics: 'Analytics (placeholder)',
      layers: 'Layers & Scans (placeholder)',
      settings: 'Settings (placeholder)',
      placeholderHint: 'Placeholder icons',
    },
    topbar: {
      themeLabel: 'Theme',
      themeSystem: 'System',
      themeLight: 'Light',
      themeDark: 'Dark',
      languageLabel: 'Language',
    },
    dashboard: {
      sectionTitle: 'Orchard Overview Dashboard',
      sectionSubtitle: 'Microclimate tracking, averaged tree health diagnostics, and 3D point-cloud orchard visualization.',
      moreChartsHint: 'Extensible grid ready for additional charts',
    },
    temperature: {
      title: 'Min / Max Temperature',
      subtitle: 'Line chart with interactive time-scale tuning',
      minLabel: 'Min temp',
      maxLabel: 'Max temp',
      frostLine: 'Frost threshold (0°C)',
      timeScale: 'Time scale',
      windowAdjust: 'Window zoom',
      periodMin: 'Window min',
      periodMax: 'Window max',
      avgSpread: 'Avg spread',
      ranges: {
        '24h': '24h',
        '7d': '7D',
        '30d': '30D',
        '90d': '90D',
        '1y': '1Y',
      },
    },
    health: {
      title: 'Orchard Tree Health',
      subtitle: 'Overall averaged orchard condition index',
      averageIndex: 'Avg score',
      totalTrees: 'Trees',
      overallLabel: 'Overall status',
      scaleTitle: 'Tree health distribution',
      statuses: {
        dead: 'Dead',
        poor: 'Poor',
        moderate: 'Moderate',
        healthy: 'Healthy',
      },
    },
    orchard3d: {
      title: '3D Orchard Render — Point Cloud & Trees',
      subtitle: 'Individual 3D tree objects placed from user-drawn row lines over the terrain point cloud',
      pointCloudLayer: 'Point cloud',
      treesLayer: '3D Trees',
      rowLinesLayer: 'Row lines',
      viewOrbit: '3D Orbit',
      viewTop: 'Top Map',
      resetView: 'Reset Camera',
      pointsStat: 'Points',
      treesStat: '3D Trees',
      rowsStat: 'Rows',
      controlsHint: 'Left-drag: rotate · Right-drag: pan · Scroll: zoom · Click tree: inspect',
      inspectorTitle: 'Selected Tree',
      inspectorClose: 'Close',
      inspectorRow: 'Row / Slot',
      inspectorHealth: 'Health',
      inspectorHeight: 'Height',
      inspectorCanopy: 'Canopy radius',
      inspectorLocalPos: 'Local 3D (m)',
      inspectorGeo: 'GPS Coords',
      selectTreePrompt: 'Click any 3D tree in the orchard to inspect its details',
    },
    placeholderView: {
      title: 'Screen Under Construction',
      description: 'This route is currently a navigation placeholder and will be implemented in upcoming iterations.',
      rowEditorNote:
        'This screen will allow drawing orchard row lines on the map so individual 3D tree positions are calculated and submitted via POST /api/v1/orchard/row-lines.',
      backToDashboard: 'Back to Dashboard',
    },
  },
};
