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
    calendar: string;
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
  soilMoisture: {
    subtitle: string;
    raster: {
      title: string;
      description: string;
      open: string;
      exportPending: string;
      waitingForFile: string;
      downloading: string;
      automaticError: string;
      retry: string;
      choosePart: string;
      part: string;
      loading: string;
      error: string;
      inspect: string;
      noData: string;
      pixelError: string;
      pixelValue: string;
      legend: string;
      reset: string;
    };
    forecastTitle: string;
    forecastDescription: string;
    loadForecast: string;
    loadingForecast: string;
    forecastError: string;
    issuedAt: string;
    sarDate: string;
    nextOverpass: string;
    selectField: string;
    field: string;
    noForecast: string;
    sarMoisture: string;
    forecastTime: string;
    moisture: string;
    rain: string;
    et0: string;
    analysisTitle: string;
    analysisDescription: string;
    start: string;
    testStart: string;
    end: string;
    dateError: string;
    submit: string;
    submitting: string;
    submitError: string;
    submitTimeout: string;
    statusError: string;
    exportLabel: string;
    statusLabel: string;
    taskId: string;
    driveLabel: string;
    states: Record<string, string>;
    taskNames: Record<string, string>;
  };
  temperature: {
    title: string;
    titleHourly: string;
    subtitle: string;
    minLabel: string;
    maxLabel: string;
    hourlyLabel: string;
    latestLabel: string;
    avgLabel: string;
    frostLine: string;
    timeScale: string;
    windowAdjust: string;
    periodMin: string;
    periodMax: string;
    avgSpread: string;
    noData: string;
    ranges: {
      '24h': string;
      '7d': string;
      '30d': string;
      '90d': string;
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
      unrated: string;
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
    colorIntensity: string;
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
    zoomModifierHint: string;
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
  calendar: {
    title: string;
    today: string;
    prevMonth: string;
    nextMonth: string;
    weekdaysShort: [string, string, string, string, string, string, string];
    months: [
      string, string, string, string, string, string,
      string, string, string, string, string, string,
    ];
    loading: string;
    loadError: string;
    saveError: string;
    tasksDotLegend: string;
    notesDotLegend: string;
    developmentTitle: string;
    developmentEmpty: string;
    dayPanelTitle: string;
    tasksTitle: string;
    tasksEmpty: string;
    taskPlaceholder: string;
    addTask: string;
    deleteTask: string;
    notesTitle: string;
    notesEmpty: string;
    notePlaceholder: string;
    addNote: string;
    deleteNote: string;
    suggestionsTitle: string;
    suggestionsEmpty: string;
    assignToDay: string;
    assignedBadge: string;
  };
}

export const TRANSLATIONS: Record<Language, Translations> = {
  pl: {
    app: {
      name: 'S.A.G.E.',
      subtitle: 'Smart Agricultural Guidance Engine',
      placeholderBadge: 'Tryb Placeholderów',
      placeholderTooltip: 'Brak aktywnego backendu — wyświetlane są dane testowe z src/placeholders/.',
    },
    nav: {
      dashboard: 'Dashboard',
      rowEditor: 'Edytor linii rzędów',
      analytics: 'Analityka',
      calendar: 'Kalendarz',
      layers: 'Warstwy i skany',
      settings: 'Ustawienia',
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
    soilMoisture: {
      subtitle: 'Prognoza dla pól i analiza historycznych scen Sentinel‑1.',
      raster: {
        title: 'Mapa wilgotności gleby',
        description: 'Mapa wczyta się automatycznie po zakończeniu analizy.',
        open: 'Otwórz zapisany plik GeoTIFF',
        exportPending: 'Earth Engine przygotowuje raster…',
        waitingForFile: 'Eksport zakończony. Czekam na plik z Dysku Google…',
        downloading: 'Pobieranie rastra…',
        automaticError: 'Nie udało się pobrać rastra. Spróbuj ponownie.',
        retry: 'Ponów pobieranie',
        choosePart: 'Fragment mapy',
        part: 'Fragment',
        loading: 'Wczytywanie mapy…',
        error: 'Nie udało się wyświetlić rastra. Wybierz GeoTIFF wilgotności z eksportu GEE w przeglądarce z obsługą WebGL.',
        inspect: 'Kliknij piksel, aby odczytać oszacowaną wilgotność.',
        noData: 'Brak danych w tym miejscu.',
        pixelError: 'Nie udało się odczytać tego piksela.',
        pixelValue: 'Oszacowana wilgotność w tym pikselu',
        legend: 'Wilgotność objętościowa',
        reset: 'Pokaż cały raster',
      },
      forecastTitle: 'Prognoza do następnego przelotu',
      forecastDescription: 'Oszacowanie z najnowszej sceny SAR, aktualizowane prognozą pogody.',
      loadForecast: 'Pobierz prognozę',
      loadingForecast: 'GEE oblicza prognozę…',
      forecastError: 'Nie udało się pobrać prognozy. Sprawdź połączenie z API.',
      issuedAt: 'Obliczono',
      sarDate: 'Scena Sentinel‑1',
      nextOverpass: 'Szacowany kolejny przelot',
      selectField: 'Wybierz pole',
      field: 'Pole',
      noForecast: 'Brak prognozy dla tego pola w wybranej scenie.',
      sarMoisture: 'Wilgotność ze sceny Sentinel‑1',
      forecastTime: 'Czas prognozy (Warszawa)',
      moisture: 'Wilgotność objętościowa',
      rain: 'Opad w okresie (mm)',
      et0: 'ET₀ (mm)',
      analysisTitle: 'Analiza historyczna',
      analysisDescription: 'Wybierz okres treningu i testu. Data końcowa jest wyłączona z zakresu.',
      start: 'Początek treningu',
      testStart: 'Początek testu',
      end: 'Data końcowa',
      dateError: 'Podaj rosnące daty: początek treningu, początek testu i koniec.',
      submit: 'Uruchom analizę',
      submitting: 'Wysyłanie zadań do GEE…',
      submitError: 'Nie udało się wysłać analizy. Sprawdź połączenie z API.',
      submitTimeout: 'Upłynął czas odpowiedzi. Przed ponowieniem sprawdź zadania w GEE.',
      statusError: 'Nie udało się odświeżyć części statusów. Kolejna próba nastąpi automatycznie.',
      exportLabel: 'Eksport',
      statusLabel: 'Stan',
      taskId: 'Identyfikator GEE',
      driveLabel: 'Znajdź eksporty na Dysku Google',
      states: {
        UNCONFIRMED: 'Sprawdzanie',
        UNKNOWN: 'Nie znaleziono',
        UNSUBMITTED: 'Oczekuje na wysłanie',
        READY: 'W kolejce',
        RUNNING: 'W trakcie',
        COMPLETED: 'Zakończono',
        FAILED: 'Błąd',
        CANCEL_REQUESTED: 'Anulowanie',
        CANCELLED: 'Anulowano',
      },
      taskNames: {
        sentinel1_soil_moisture_metrics: 'Metryki modelu (CSV)',
        sentinel1_soil_moisture: 'Mapa pól (GeoTIFF)',
        sentinel1_soil_moisture_fields: 'Raport pól (CSV)',
        sentinel1_soil_moisture_model: 'Model radarowy (GEE)',
      },
    },
    temperature: {
      title: 'Temperatura Min / Max',
      titleHourly: 'Temperatura (24h)',
      subtitle: 'Wykres liniowy z dostrajaniem skali czasu',
      minLabel: 'Temp. min',
      maxLabel: 'Temp. max',
      hourlyLabel: 'Temperatura',
      latestLabel: 'Ostatnia',
      avgLabel: 'Średnia',
      frostLine: 'Próg przymrozku (0°C)',
      timeScale: 'Skala czasu',
      windowAdjust: 'Dostrajanie okna',
      periodMin: 'Min w oknie',
      periodMax: 'Max w oknie',
      avgSpread: 'Śr. amplituda',
      noData: 'Brak danych temperaturowych dla wybranego zakresu',
      ranges: {
        '24h': '24h',
        '7d': '7 dni',
        '30d': '30 dni',
        '90d': '90 dni',
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
        unrated: 'Brak oceny',
      },
    },
    orchard3d: {
      title: 'Render 3D Sadu — Chmura Punktów i Drzewa',
      subtitle: 'Pojedyncze obiekty 3D wyliczone z linii rzędów nałożone na chmurę punktów terenu',
      pointCloudLayer: 'Teren 3D',
      treesLayer: 'Drzewa 3D',
      rowLinesLayer: 'Linie rzędów',
      boundaryLayer: 'Granica pola',
      colorModeLabel: 'Kolorowanie chmury punktów',
      colorRgb: 'RGB',
      colorElevation: 'Wysokość',
      colorClass: 'Klasy',
      colorIntensity: 'Intensywność',
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
      controlsHint: 'LPM: obrót · PPM: przesuwanie · {mod} + Scroll: zoom · Kliknij drzewo: szczegóły',
      zoomModifierHint: 'Przytrzymaj {mod} + scroll, aby przybliżyć mapę',
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
      saveSuccessTitle: 'Zapisano układ sadu',
      saveBackendNote: 'kondycja drzew zostanie wyliczona automatycznie',
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
      hintDrawMode: 'Kliknij punkt początkowy rzędu · {mod} + Scroll: zoom · PPM: przesuwanie',
      hintFinishLine: 'Kliknij punkt końcowy rzędu · Esc lub PPM: anuluj · Shift: przyciąganie kąta',
      hintSelectMode: 'Kliknij rząd, aby przesuwać punkty A/B, lub kliknij drzewo, aby zmienić jego gatunek',
      hintPaintMode: 'Kliknij rząd albo przeciągnij po drzewach, aby przypisać aktywny gatunek',
      rowsCountLabel: 'Rzędy',
      treesCountLabel: 'Drzewa w rzędach',
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
      changeTreeSpecies: 'Zmień gatunek',
      rowsListTitle: 'Narysowane rzędy',
      emptyRowsList: 'Brak rzędów. Narysuj pierwszą prostą linię na obszarze sadu, aby automatycznie wyliczyć drzewa.',
      deleteRow: 'Usuń rząd',
      rowSpeciesShort: 'Gatunek',
      rowSpacingShort: 'Odstęp (m)',
      payloadPreviewTitle: 'Podgląd dokumentów do zapisu w MongoDB',
      payloadPreviewSubtitle:
        'Orchard.rows przechowuje punkty start/end oraz uporządkowane ObjectId drzew; Tree zawiera coordinates, healthIndex: null oraz species (CropPref ObjectId).',
    },
    calendar: {
      title: 'Kalendarz Sadu',
      today: 'Dzisiaj',
      prevMonth: 'Poprzedni miesiąc',
      nextMonth: 'Następny miesiąc',
      weekdaysShort: ['Pon', 'Wt', 'Śr', 'Czw', 'Pt', 'Sob', 'Nie'],
      months: [
        'Styczeń', 'Luty', 'Marzec', 'Kwiecień', 'Maj', 'Czerwiec',
        'Lipiec', 'Sierpień', 'Wrzesień', 'Październik', 'Listopad', 'Grudzień',
      ],
      loading: 'Wczytywanie kalendarza…',
      loadError: 'Nie udało się wczytać kalendarza.',
      saveError: 'Nie udało się zapisać zmian w kalendarzu.',
      tasksDotLegend: 'Zadania',
      notesDotLegend: 'Notatki',
      developmentTitle: 'Rozwój roślin',
      developmentEmpty: 'Brak aktywnych faz rozwoju w tym miesiącu (okres spoczynku).',
      dayPanelTitle: 'Wybrany dzień',
      tasksTitle: 'Zadania na ten dzień',
      tasksEmpty: 'Brak zadań na wybrany dzień.',
      taskPlaceholder: 'Dodaj zadanie do wykonania…',
      addTask: 'Dodaj',
      deleteTask: 'Usuń zadanie',
      notesTitle: 'Notatki',
      notesEmpty: 'Brak notatek na wybrany dzień.',
      notePlaceholder: 'Zapisz notatkę z sadu…',
      addNote: 'Dodaj notatkę',
      deleteNote: 'Usuń notatkę',
      suggestionsTitle: 'Sugerowane zadania na ten miesiąc',
      suggestionsEmpty: 'Brak sugestii dla tego miesiąca.',
      assignToDay: 'Dodaj na',
      assignedBadge: 'Dodano',
    },
  },
  en: {
    app: {
      name: 'S.A.G.E.',
      subtitle: 'Smart Agricultural Guidance Engine',
      placeholderBadge: 'Placeholder Mode',
      placeholderTooltip: 'No live backend connected yet — rendering placeholder data from src/placeholders/.',
    },
    nav: {
      dashboard: 'Dashboard',
      rowEditor: 'Row Line Editor',
      analytics: 'Analytics',
      calendar: 'Calendar',
      layers: 'Layers & Scans',
      settings: 'Settings',
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
    soilMoisture: {
      subtitle: 'Field forecasts and historical Sentinel‑1 analysis.',
      raster: {
        title: 'Soil moisture map',
        description: 'The map loads automatically when the analysis finishes.',
        open: 'Open a saved GeoTIFF',
        exportPending: 'Earth Engine is preparing the raster…',
        waitingForFile: 'Export complete. Waiting for the file on Google Drive…',
        downloading: 'Downloading raster…',
        automaticError: 'Could not download the raster. Try again.',
        retry: 'Retry download',
        choosePart: 'Map part',
        part: 'Part',
        loading: 'Loading map…',
        error: 'The raster could not be displayed. Choose a soil moisture GeoTIFF from GEE in a browser with WebGL support.',
        inspect: 'Click a pixel to read its estimated moisture.',
        noData: 'No data at this location.',
        pixelError: 'Could not read this pixel.',
        pixelValue: 'Estimated moisture at this pixel',
        legend: 'Volumetric soil moisture',
        reset: 'Fit raster to map',
      },
      forecastTitle: 'Forecast until the next overpass',
      forecastDescription: 'An estimate from the latest SAR scene, updated using the weather forecast.',
      loadForecast: 'Load forecast',
      loadingForecast: 'GEE is calculating the forecast…',
      forecastError: 'Could not load the forecast. Check the API connection.',
      issuedAt: 'Issued at',
      sarDate: 'Sentinel‑1 scene',
      nextOverpass: 'Estimated next overpass',
      selectField: 'Select a field',
      field: 'Field',
      noForecast: 'This scene has no forecast for the selected field.',
      sarMoisture: 'Soil moisture from the Sentinel‑1 scene',
      forecastTime: 'Forecast time (Warsaw)',
      moisture: 'Volumetric soil moisture',
      rain: 'Interval rainfall (mm)',
      et0: 'ET₀ (mm)',
      analysisTitle: 'Historical analysis',
      analysisDescription: 'Choose the training and test periods. The end date is exclusive.',
      start: 'Training start',
      testStart: 'Test start',
      end: 'End date',
      dateError: 'Enter the training start, test start, and end date in chronological order.',
      submit: 'Run analysis',
      submitting: 'Submitting tasks to GEE…',
      submitError: 'Could not submit the analysis. Check the API connection.',
      submitTimeout: 'The request timed out. Check GEE tasks before submitting again.',
      statusError: 'Some task statuses could not be refreshed. Retrying automatically.',
      exportLabel: 'Export',
      statusLabel: 'Status',
      taskId: 'GEE task ID',
      driveLabel: 'Find exports in Google Drive',
      states: {
        UNCONFIRMED: 'Checking',
        UNKNOWN: 'Not found',
        UNSUBMITTED: 'Awaiting submission',
        READY: 'Queued',
        RUNNING: 'Running',
        COMPLETED: 'Completed',
        FAILED: 'Failed',
        CANCEL_REQUESTED: 'Cancelling',
        CANCELLED: 'Cancelled',
      },
      taskNames: {
        sentinel1_soil_moisture_metrics: 'Model metrics (CSV)',
        sentinel1_soil_moisture: 'Field map (GeoTIFF)',
        sentinel1_soil_moisture_fields: 'Field report (CSV)',
        sentinel1_soil_moisture_model: 'Radar model (GEE)',
      },
    },
    temperature: {
      title: 'Min / Max Temperature',
      titleHourly: 'Temperature (24h)',
      subtitle: 'Line chart with interactive time-scale tuning',
      minLabel: 'Min temp',
      maxLabel: 'Max temp',
      hourlyLabel: 'Temperature',
      latestLabel: 'Latest',
      avgLabel: 'Average',
      frostLine: 'Frost threshold (0°C)',
      timeScale: 'Time scale',
      windowAdjust: 'Window zoom',
      periodMin: 'Window min',
      periodMax: 'Window max',
      avgSpread: 'Avg spread',
      noData: 'No temperature history available for this range',
      ranges: {
        '24h': '24h',
        '7d': '7D',
        '30d': '30D',
        '90d': '90D',
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
        unrated: 'Unrated',
      },
    },
    orchard3d: {
      title: '3D Orchard Render — Point Cloud & Trees',
      subtitle: 'Individual 3D tree objects placed from user-drawn row lines over the terrain point cloud',
      pointCloudLayer: '3D Terrain',
      treesLayer: '3D Trees',
      rowLinesLayer: 'Row lines',
      boundaryLayer: 'Boundary',
      colorModeLabel: 'Point cloud color mode',
      colorRgb: 'RGB',
      colorElevation: 'Elevation',
      colorClass: 'Class',
      colorIntensity: 'Intensity',
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
      controlsHint: 'Left-drag: rotate · Right-drag: pan · {mod} + Scroll: zoom · Click tree: inspect',
      zoomModifierHint: 'Hold {mod} + scroll to zoom the map',
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
      saveSuccessTitle: 'Orchard layout saved',
      saveBackendNote: 'tree health will be computed automatically',
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
      hintDrawMode: 'Click row start point · {mod} + Scroll: zoom · Right-drag: pan',
      hintFinishLine: 'Click row end point · Esc or right-click: cancel · Shift: angle snap',
      hintSelectMode: 'Click a row to drag A/B handles, or click a tree to change its species',
      hintPaintMode: 'Click a row or drag across trees to assign the active species',
      rowsCountLabel: 'Rows',
      treesCountLabel: 'Trees in rows',
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
      changeTreeSpecies: 'Change species',
      rowsListTitle: 'Drawn Rows',
      emptyRowsList: 'No rows yet. Draw a straight line across the orchard shape to generate tree coordinates.',
      deleteRow: 'Delete row',
      rowSpeciesShort: 'Species',
      rowSpacingShort: 'Spacing (m)',
      payloadPreviewTitle: 'MongoDB Persistence Payload Preview',
      payloadPreviewSubtitle:
        'Orchard.rows stores start/end coordinates and ordered Tree ObjectIds; Tree stores coordinates, healthIndex: null, and species (CropPref ObjectId).',
    },
    calendar: {
      title: 'Orchard Calendar',
      today: 'Today',
      prevMonth: 'Previous month',
      nextMonth: 'Next month',
      weekdaysShort: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
      months: [
        'January', 'February', 'March', 'April', 'May', 'June',
        'July', 'August', 'September', 'October', 'November', 'December',
      ],
      loading: 'Loading calendar…',
      loadError: 'Could not load the calendar.',
      saveError: 'Could not save calendar changes.',
      tasksDotLegend: 'Tasks',
      notesDotLegend: 'Notes',
      developmentTitle: 'Plant Development',
      developmentEmpty: 'No active plant development phases this month (dormancy period).',
      dayPanelTitle: 'Selected Day',
      tasksTitle: 'Tasks for this day',
      tasksEmpty: 'No tasks scheduled for this day.',
      taskPlaceholder: 'Add a task to complete…',
      addTask: 'Add',
      deleteTask: 'Delete task',
      notesTitle: 'Notes',
      notesEmpty: 'No notes for this day.',
      notePlaceholder: 'Write an orchard note…',
      addNote: 'Add note',
      deleteNote: 'Delete note',
      suggestionsTitle: 'Suggested Tasks for This Month',
      suggestionsEmpty: 'No suggestions for this month.',
      assignToDay: 'Add to',
      assignedBadge: 'Added',
    },
  },
};
