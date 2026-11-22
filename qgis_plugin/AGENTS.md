# 🤖 AI Agent Instructions: QGIS Plugin (`qgis_plugin/`)

> Before editing files in this folder, read the parent [`/AGENTS.md`](../AGENTS.md) and [`/CONTRIBUTING.md`](../CONTRIBUTING.md).

---

## 🎯 Module Scope and Role (`Scope`)
The `qgis_plugin/` folder contains the plugin code for the **QGIS 3** workstation (`PyQGIS`). It is responsible for:
1. Registering actions, menus and the toolbar in the QGIS interface (`plugin.py`, `metadata.txt`).
2. Displaying the side docked panel (**QDockWidget**) defined in Qt Designer.
3. **Asynchronous communication with the FastAPI backend** in a separate thread through `QgsTask` (`SessionTask`, `ServeTask`).
4. Safe interaction with the QGIS map (reading objects from layers, transforming coordinates to EPSG:4326/EPSG:2180, presenting results).

---

## 📂 Directory Structure
```text
qgis_plugin/
└── pyqgis_fastapi_bridge/
    ├── __init__.py           # classFactory(iface) - entry point of the QGIS plugin
    ├── metadata.txt          # QGIS Plugin Manager metadata
    ├── plugin.py             # Registration of actions, menu and panel docking
    ├── icon.png              # Plugin icon
    ├── gui/
    │   ├── dockwidget.py     # Panel logic: QgsTask, signal and event handling
    │   └── dockwidget.ui     # Qt Designer layout (XML)
    ├── core/
    │   ├── serve_api.py      # HTTP client of the read contract (sandbox, login, crop areas, grid, heatmap, spray window, history)
    │   ├── serve_layers.py   # builds the QGIS layers from the contract answers
    │   ├── farmer_fields.py  # GET /fields and the farmer-fields file
    │   ├── farmer_layers.py  # farmer crop-area and parcel layers
    │   └── api_client.py     # legacy client of /analysis (not used by the panel; tests/test_qgis_plugin.py imports it)
    └── styles/
        └── categorized_style.qml # QGIS layer style templates
```

---

## 🛑 PyQGIS-Specific Rules (`Hard Rules`)

1. **ABSOLUTE BAN ON BLOCKING THE MAIN GUI THREAD:**
   * No network request (`urllib.request`, `http`) or heavy geometry operation **may** be executed directly in button handler methods (`clicked`).
   * Always use the `QgsTask` multithreading pattern (as in `SessionTask`). The network query is done in the `run()` method and the GUI update in the `finished()` method.
2. **Dynamic loading of UI views (`loadUiType`):**
   * The `dockwidget.ui` view file is edited in Qt Designer (with `open_designer.bat`).
   * **Never compile the `.ui` file to `.py`** with `pyuic5`. The `.ui` file is loaded dynamically on the fly by `PyQt5.uic.loadUiType()`.
3. **Paths and links:**
   * All references to files (e.g. `dockwidget.ui`, `icon.png`) must be built relatively with `os.path.join(os.path.dirname(__file__), ...)`.
   * The plugin is linked into the QGIS profile through a junction/symlink (`deploy.py`). Do not copy files manually into the `%APPDATA%` directory.
4. **Geometry safety:**
   * Always check that the layer is valid (`layer.isValid()`) and that the geometry is not empty (`not geom.isEmpty()`) before trying to compute a centroid or transform the coordinate system.
