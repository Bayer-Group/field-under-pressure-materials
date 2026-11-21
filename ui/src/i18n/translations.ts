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
    orchardLabel: string;
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
    boundaryLayer: string;
    colorModeLabel: string;
    colorRgb: string;
    colorElevation: string;
    colorClass: string;
    reliefTooltip: string;
    viewOrbit: string;
    viewTop: string;
    focusTrees: string;
    resetView: string;
    geometricFallbackLabel: string;
    loadingLas: string;
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
  rowEditor: {
    title: string;
    subtitle: string;
    backdropLabel: string;
    backdropBlank: string;
    backdropSatellite: string;
    previewPayload: string;
    saveLayout: string;
    saving: string;
    saveSuccessTitle: string;
    saveBackendNote: string;
    toolsLabel: string;
    toolDraw: string;
    toolSelect: string;
    toolPaint: string;
    angleSnap: string;
    angleSnapHint: string;
    parallelRow: string;
    parallelRowHint: string;
    undo: string;
    clearAll: string;
    fitView: string;
    emptyOrchardBadge: string;
    emptyOrchardGuide: string;
    hintDrawMode: string;
    hintFinishLine: string;
    hintSelectMode: string;
    hintPaintMode: string;
    rowsCountLabel: string;
    treesCountLabel: string;
    activeSpeciesLabel: string;
    rowsUnit: string;
    treesUnit: string;
    speciesTitle: string;
    speciesHint: string;
    useRecommendedSpacing: string;
    spacingTitle: string;
    treeSpacingLabel: string;
    applySpacingAll: string;
    rowOffsetLabel: string;
    edgeMarginLabel: string;
    selectedTreeTitle: string;
    computedByBackend: string;
    changeTreeSpecies: string;
    rowsListTitle: string;
    emptyRowsList: string;
    deleteRow: string;
    rowSpeciesShort: string;
    rowSpacingShort: string;
    payloadPreviewTitle: string;
    payloadPreviewSubtitle: string;
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
      rowEditor: 'Edytor linii rzędów',
      analytics: 'Analityka (placeholder)',
      layers: 'Warstwy i skany (placeholder)',
      settings: 'Ustawienia (placeholder)',
      placeholderHint: 'Ikony tymczasowe',
    },
    topbar: {
      orchardLabel: 'Wyświetlany sad',
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
      pointCloudLayer: 'Chmura .las',
      treesLayer: 'Drzewa 3D',
      rowLinesLayer: 'Linie rzędów',
      boundaryLayer: 'Granica pola',
      colorModeLabel: 'Kolorowanie chmury punktów',
      colorRgb: 'RGB',
      colorElevation: 'Wysokość',
      colorClass: 'Klasy',
      reliefTooltip: 'Przełącz skalę wysokości Z (×1 / ×1.8 / ×2.8)',
      viewOrbit: 'Widok 3D',
      viewTop: 'Z góry',
      focusTrees: 'Drzewa',
      resetView: 'Resetuj kamerę',
      geometricFallbackLabel: 'Widok geometryczny (brak pliku .las)',
      loadingLas: 'Ładowanie chmury punktów .las…',
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
    rowEditor: {
      title: 'Edytor Linii Rzędów Sadu',
      subtitle: 'Narysuj proste linie rzędów w granicach sadu, aby wyliczyć współrzędne pojedynczych drzew.',
      backdropLabel: 'Tryb podkładu',
      backdropBlank: 'Pusty kształt',
      backdropSatellite: 'Zdjęcie satelitarne',
      previewPayload: 'Podgląd MongoDB',
      saveLayout: 'Zapisz układ',
      saving: 'Zapisywanie...',
      saveSuccessTitle: 'Wysłano układ do endpointu',
      saveBackendNote: 'healthIndex zostanie obliczony po stronie backendu',
      toolsLabel: 'Narzędzia rysowania',
      toolDraw: 'Rysuj rząd',
      toolSelect: 'Zaznacz / Edytuj',
      toolPaint: 'Maluj gatunek',
      angleSnap: 'Przyciągaj kąt',
      angleSnapHint: 'Wyrównuje linię równolegle do ostatniego rzędu lub co 15° (lub przytrzymaj Shift)',
      parallelRow: 'Równoległy rząd',
      parallelRowHint: 'Dodaje równoległy rząd przesunięty o odstęp między rzędami i przycięty do kształtu pola',
      undo: 'Cofnij',
      clearAll: 'Wyczyść sad',
      fitView: 'Dopasuj widok do sadu',
      emptyOrchardBadge: 'Pusty sad — brak rzędów',
      emptyOrchardGuide: 'Wybierz gatunek po prawej i kliknij dwa punkty (początek i koniec), aby narysować pierwszy rząd.',
      hintDrawMode: 'Kliknij punkt początkowy rzędu · Scroll: zoom · PPM: przesuwanie',
      hintFinishLine: 'Kliknij punkt końcowy rzędu · Esc lub PPM: anuluj · Shift: przyciąganie kąta',
      hintSelectMode: 'Kliknij rząd, aby przesuwać punkty A/B, lub kliknij drzewo, aby zmienić jego gatunek',
      hintPaintMode: 'Kliknij rząd albo przeciągnij po drzewach, aby przypisać aktywny gatunek (CropPref)',
      rowsCountLabel: 'Rzędy',
      treesCountLabel: 'Wyliczone drzewa',
      activeSpeciesLabel: 'Aktywny gatunek',
      rowsUnit: 'rzędów',
      treesUnit: 'drzew',
      speciesTitle: 'Gatunek drzewa',
      speciesHint: 'Wybierz gatunek z kolekcji CropPref dla nowych rzędów lub narzędzia malowania.',
      useRecommendedSpacing: 'Użyj zalecanego odstępu',
      spacingTitle: 'Parametry rozmieszczenia',
      treeSpacingLabel: 'Średni odstęp między drzewami',
      applySpacingAll: 'Zastosuj odstęp do wszystkich rzędów',
      rowOffsetLabel: 'Odstęp rzędów',
      edgeMarginLabel: 'Margines granicy',
      selectedTreeTitle: 'Wybrane drzewo',
      computedByBackend: 'liczy backend',
      changeTreeSpecies: 'Zmień gatunek (CropPref ObjectId)',
      rowsListTitle: 'Narysowane rzędy',
      emptyRowsList: 'Brak rzędów. Narysuj pierwszą prostą linię na obszarze sadu, aby automatycznie wyliczyć drzewa.',
      deleteRow: 'Usuń rząd',
      rowSpeciesShort: 'Gatunek',
      rowSpacingShort: 'Odstęp (m)',
      payloadPreviewTitle: 'Podgląd dokumentów do zapisu w MongoDB',
      payloadPreviewSubtitle:
        'Orchard.rows przechowuje punkty start/end oraz uporządkowane ObjectId drzew; Tree zawiera coordinates, healthIndex: null oraz species (CropPref ObjectId).',
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
      rowEditor: 'Row Line Editor',
      analytics: 'Analytics (placeholder)',
      layers: 'Layers & Scans (placeholder)',
      settings: 'Settings (placeholder)',
      placeholderHint: 'Placeholder icons',
    },
    topbar: {
      orchardLabel: 'Active orchard',
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
      pointCloudLayer: '.las Cloud',
      treesLayer: '3D Trees',
      rowLinesLayer: 'Row lines',
      boundaryLayer: 'Boundary',
      colorModeLabel: 'Point cloud color mode',
      colorRgb: 'RGB',
      colorElevation: 'Elevation',
      colorClass: 'Class',
      reliefTooltip: 'Cycle vertical relief scale Z (×1 / ×1.8 / ×2.8)',
      viewOrbit: '3D Orbit',
      viewTop: 'Top Map',
      focusTrees: 'Trees',
      resetView: 'Reset Camera',
      geometricFallbackLabel: 'Geometric view (no .las file)',
      loadingLas: 'Loading .las point cloud…',
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
    rowEditor: {
      title: 'Orchard Row Line Editor',
      subtitle: 'Draw straight row lines across the orchard polygon to calculate individual tree coordinates.',
      backdropLabel: 'Canvas backdrop',
      backdropBlank: 'Empty shape',
      backdropSatellite: 'Satellite map',
      previewPayload: 'MongoDB Payload',
      saveLayout: 'Save layout',
      saving: 'Saving...',
      saveSuccessTitle: 'Layout sent to endpoint',
      saveBackendNote: 'healthIndex will be computed by the backend',
      toolsLabel: 'Drawing tools',
      toolDraw: 'Draw row',
      toolSelect: 'Select / Edit',
      toolPaint: 'Paint species',
      angleSnap: 'Angle snap',
      angleSnapHint: 'Snaps parallel to the last row or 15° steps (or hold Shift)',
      parallelRow: 'Parallel row',
      parallelRowHint: 'Duplicates a parallel row shifted by row spacing and clipped to field geometry',
      undo: 'Undo',
      clearAll: 'Clear orchard',
      fitView: 'Fit orchard parcel',
      emptyOrchardBadge: 'Empty orchard — no rows yet',
      emptyOrchardGuide: 'Pick a tree species on the right and click two points (start & end) to draw the first row.',
      hintDrawMode: 'Click row start point · Scroll: zoom · Right-drag: pan',
      hintFinishLine: 'Click row end point · Esc or right-click: cancel · Shift: angle snap',
      hintSelectMode: 'Click a row to drag A/B handles, or click a tree to change its species',
      hintPaintMode: 'Click a row or drag across trees to assign the active species (CropPref)',
      rowsCountLabel: 'Rows',
      treesCountLabel: 'Calculated trees',
      activeSpeciesLabel: 'Active species',
      rowsUnit: 'rows',
      treesUnit: 'trees',
      speciesTitle: 'Tree Species',
      speciesHint: 'Choose a CropPref species for newly drawn rows or the species brush.',
      useRecommendedSpacing: 'Use recommended spacing',
      spacingTitle: 'Placement Parameters',
      treeSpacingLabel: 'Average spacing between trees',
      applySpacingAll: 'Apply spacing to all rows',
      rowOffsetLabel: 'Row offset',
      edgeMarginLabel: 'Border margin',
      selectedTreeTitle: 'Selected Tree',
      computedByBackend: 'backend computed',
      changeTreeSpecies: 'Change species (CropPref ObjectId)',
      rowsListTitle: 'Drawn Rows',
      emptyRowsList: 'No rows yet. Draw a straight line across the orchard shape to generate tree coordinates.',
      deleteRow: 'Delete row',
      rowSpeciesShort: 'Species',
      rowSpacingShort: 'Spacing (m)',
      payloadPreviewTitle: 'MongoDB Persistence Payload Preview',
      payloadPreviewSubtitle:
        'Orchard.rows stores start/end coordinates and ordered Tree ObjectIds; Tree stores coordinates, healthIndex: null, and species (CropPref ObjectId).',
    },
  },
};
