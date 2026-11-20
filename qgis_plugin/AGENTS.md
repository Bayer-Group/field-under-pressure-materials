# 🤖 Instrukcje dla Agenta AI: Wtyczka QGIS (`qgis_plugin/`)

> Przed edycją plików w tym folderze zapoznaj się z nadrzędnym plikiem [`/AGENTS.md`](../AGENTS.md) oraz [`/CONTRIBUTING.md`](../CONTRIBUTING.md).

---

## 🎯 Zakres i Rola Modułu (`Scope`)
Folder `qgis_plugin/` zawiera kod wtyczki dla stacji roboczej **QGIS 3** (`PyQGIS`). Odpowiada za:
1. Rejestrację akcji, menu i paska narzędzi w interfejsie QGIS (`plugin.py`, `metadata.txt`).
2. Wyświetlanie bocznego panelu dokowanego (**QDockWidget**) zdefiniowanego w Qt Designerze.
3. **Asynchroniczną komunikację z backendem FastAPI** w osobnym wątku za pośrednictwem `QgsTask` (`AsyncApiTask`).
4. Bezpieczną interakcję z mapą QGIS (odczyt obiektów z warstw, transformacja współrzędnych do EPSG:4326/EPSG:2180, prezentacja wyników).

---

## 📂 Struktura Katalogu
```text
qgis_plugin/
└── pyqgis_fastapi_bridge/
    ├── __init__.py           # classFactory(iface) - punkt startowy wtyczki QGIS
    ├── metadata.txt          # Metadane QGIS Plugin Manager
    ├── plugin.py             # Rejestracja akcji, menu i dokowania panelu
    ├── icon.png              # Ikonka wtyczki
    ├── gui/
    │   ├── dockwidget.py     # Logika panelu: QgsTask, obsługa sygnałów i zdarzeń
    │   └── dockwidget.ui     # Layout z Qt Designera (XML)
    ├── core/
    │   └── api_client.py     # Klient HTTP odpytujący backend z trybem offline fallback
    └── styles/
        └── categorized_style.qml # Szablony stylów warstw QGIS
```

---

## 🛑 Zasady Specyficzne dla PyQGIS (`Twarde Reguły`)

1. **BEZWZGLĘDNY ZAKAZ BLOKOWANIA WĄTKU GŁÓWNEGO GUI:**
   * Żadne zapytanie sieciowe (`urllib.request`, `http`) ani ciężka operacja na geometrii **nie może** być wykonywana bezpośrednio w metodach obsługi przycisków (`clicked`).
   * Zawsze używaj wzorca wielowątkowości `QgsTask` (tak jak w `AsyncApiTask`). Odpytanie sieciowe wykonuje się w metodzie `run()`, a aktualizacja GUI w metodzie `finished()`.
2. **Dynamiczne ładowanie widoków UI (`loadUiType`):**
   * Plik widoku `dockwidget.ui` edytujemy w Qt Designerze (za pomocą `open_designer.bat`).
   * **Nigdy nie kompiluj pliku `.ui` do `.py`** za pomocą `pyuic5`. Plik `.ui` jest ładowany dynamicznie w locie przez `PyQt5.uic.loadUiType()`.
3. **Ścieżki i powiązania:**
   * Wszelkie odwołania do plików (np. `dockwidget.ui`, `icon.png`) muszą być budowane relatywnie za pomocą `os.path.join(os.path.dirname(__file__), ...)`.
   * Wtyczka jest linkowana do profilu QGIS przez junction/symlink (`deploy.py`). Nie kopiuj plików ręcznie do katalogu `%APPDATA%`.
4. **Bezpieczeństwo geometrii:**
   * Zawsze sprawdzaj, czy warstwa jest poprawna (`layer.isValid()`) i czy geometria nie jest pusta (`not geom.isEmpty()`) przed próbą wyznaczenia centroidu lub transformacji układu.
