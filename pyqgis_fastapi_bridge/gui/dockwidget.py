# -*- coding: utf-8 -*-
"""
Panel boczny wtyczki PyQGIS FastAPI Bridge.
Wykorzystuje QgsTask do asynchronicznego odpytywania API w tle
bez blokowania lub zawieszania interfejsu użytkownika QGIS.
"""

import os
from PyQt5 import uic
from PyQt5.QtWidgets import QDockWidget, QFileDialog, QListWidgetItem
from PyQt5.QtCore import pyqtSignal

from qgis.core import (
    QgsProject,
    QgsVectorLayer,
    QgsWkbTypes,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsTask,
    QgsApplication
)

from qgis.core import Qgis, QgsMessageLog
from PyQt5.QtCore import Qt

from ..core.api_client import BackendApiClient
from ..core import data_catalog, farmer_fields
from ..core.data_layers import add_catalog_layer
from ..core.farmer_layers import add_farmer_layers

LOG_TAG = "Field Under Pressure"
UI_PATH = os.path.join(os.path.dirname(__file__), "dockwidget.ui")
FORM_CLASS, _ = uic.loadUiType(UI_PATH)


class AsyncApiTask(QgsTask):
    """Zadanie w tle (QgsTask) wykonujące zapytanie sieciowe bez blokowania GUI."""

    def __init__(self, description, parcel_id, teryt_id, lat, lon, on_success_callback):
        super().__init__(description, QgsTask.CanCancel)
        self.parcel_id = parcel_id
        self.teryt_id = teryt_id
        self.lat = lat
        self.lon = lon
        self.on_success = on_success_callback
        self.response_data = None
        self.error_msg = None

    def run(self):
        """Metoda wykonywana w osobnym wątku systemowym."""
        try:
            self.response_data = BackendApiClient.analyze_parcel(
                parcel_id=self.parcel_id,
                teryt_id=self.teryt_id,
                lat=self.lat,
                lon=self.lon
            )
            return True
        except Exception as e:
            self.error_msg = str(e)
            return False

    def finished(self, result):
        """Metoda wywoływana w głównym wątku GUI po zakończeniu zadania."""
        if result and self.response_data:
            self.on_success(self.response_data)


class FarmerFieldsTask(QgsTask):
    """Background task: read saved farmer fields from the backend or a JSON file.

    Network and file access happen in run(); QGIS layers are created in
    finished(), which QGIS calls on the main thread.
    """

    def __init__(self, description, base_url, file_path, on_done):
        super().__init__(description, QgsTask.CanCancel)
        self.base_url = base_url
        self.file_path = file_path
        self.on_done = on_done
        self.farmer_data = None
        self.error = None

    def run(self):
        try:
            if self.file_path:
                payload = farmer_fields.load_fields_file(self.file_path)
            else:
                payload = farmer_fields.fetch_fields(self.base_url)
            self.farmer_data = farmer_fields.parse_fields(payload)
            return True
        except farmer_fields.FarmerDataError as exc:
            self.error = exc
            return False
        except Exception as exc:  # unexpected; still reported in the log
            self.error = farmer_fields.FarmerDataError("UNEXPECTED_ERROR", str(exc))
            return False

    def finished(self, result):
        self.on_done(self)


class CatalogTask(QgsTask):
    """Background task: read the layer catalog from the backend or from a file."""

    def __init__(self, description, base_url, file_path, on_done):
        super().__init__(description, QgsTask.CanCancel)
        self.base_url = base_url
        self.file_path = file_path
        self.on_done = on_done
        self.catalog = None
        self.error = None

    def run(self):
        try:
            if self.file_path:
                self.catalog = data_catalog.load_catalog_file(self.file_path)
            else:
                self.catalog = data_catalog.fetch_catalog(self.base_url)
            return True
        except data_catalog.DataSourceError as exc:
            self.error = exc
            return False
        except Exception as exc:
            self.error = data_catalog.DataSourceError("UNEXPECTED_ERROR", str(exc))
            return False

    def finished(self, result):
        self.on_done(self)


class PrepareLayersTask(QgsTask):
    """Background task: check every source (network or disk) and fetch legend styles.

    The layers themselves are created in finished(), on the main thread, so a slow or
    unreachable server never blocks QGIS.
    """

    def __init__(self, description, entries, on_done):
        super().__init__(description, QgsTask.CanCancel)
        self.entries = entries
        self.on_done = on_done
        self.ready = []      # (entry, qml_path)
        self.failures = []   # DataSourceError with the layer title in its message
        self.warnings = []

    def run(self):
        for entry in self.entries:
            if self.isCanceled():
                return False
            try:
                warning = data_catalog.probe_source(entry["source"])
                if warning:
                    self.warnings.append(warning)
                qml = data_catalog.fetch_to_temp(entry["legend_qml"]) if entry.get("legend_qml") else None
                self.ready.append((entry, qml))
            except data_catalog.DataSourceError as exc:
                exc.message = f"{entry['title']}: {exc.message}"
                self.failures.append(exc)
        return True

    def finished(self, result):
        self.on_done(self)


class PyQgisBridgeDockWidget(QDockWidget, FORM_CLASS):
    closingPlugin = pyqtSignal()

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.iface = iface

        self.btnRefresh.clicked.connect(self.populate_layers)
        self.btnRun.clicked.connect(self.run_processing)
        self.btnClear.clicked.connect(self.txtLog.clear)
        self.btnToggleLog.toggled.connect(self._toggle_log)
        self.txtFarmerUrl.setText(farmer_fields.DEFAULT_BASE_URL)
        self.btnLoadFarmer.clicked.connect(self.load_farmer_from_backend)
        self.btnLoadFarmerFile.clicked.connect(self.load_farmer_from_file)
        self._farmer_source = ""
        self.btnLoadCatalog.clicked.connect(self.load_catalog_from_backend)
        self.btnLoadCatalogFile.clicked.connect(self.load_catalog_from_file)
        self.btnAddLayers.clicked.connect(self.add_selected_layers)
        self.btnAddLocalFiles.clicked.connect(self.add_local_files)
        self._bg_tasks = []
        self._farmer_tasks = []  # keep Python references so QgsTask objects are not garbage collected

        self.populate_layers()

    def closeEvent(self, event):
        self.closingPlugin.emit()
        event.accept()

    def log(self, text):
        """Show the line in the panel details and mirror it to the QGIS Log Messages panel."""
        text = str(text)
        self.txtLog.append(text)
        stripped = text.strip()
        if not stripped:
            return
        if stripped.startswith(("ERROR", "BŁĄD")):
            level = Qgis.Critical
        elif stripped.startswith(("WARNING", "INCOMPLETE")):
            level = Qgis.Warning
        else:
            level = Qgis.Info
        QgsMessageLog.logMessage(stripped, LOG_TAG, level)

    def _toggle_log(self, expanded):
        self.logBody.setVisible(expanded)
        self.btnToggleLog.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)

    def populate_layers(self):
        self.cmbLayer.clear()
        found = 0
        for layer in QgsProject.instance().mapLayers().values():
            if isinstance(layer, QgsVectorLayer) and layer.geometryType() == QgsWkbTypes.PolygonGeometry:
                self.cmbLayer.addItem(layer.name(), layer)
                found += 1

        self.log(f"Layer list refreshed. Polygon layers found: {found}")

    def run_processing(self):
        layer = self.cmbLayer.currentData()
        if not layer or not layer.isValid():
            self.log("ERROR: Select a valid polygon layer.")
            return

        input_teryt = self.txtTeryt.text().strip()

        self.log(f"\nStarting analysis (QgsTask) for layer: {layer.name()}")
        if input_teryt:
            self.log(f"Filter TERYT / ID: {input_teryt}")

        src_crs = layer.crs()
        wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        transform = QgsCoordinateTransform(src_crs, wgs84, QgsProject.instance())

        total = layer.featureCount()
        self.progressBar.setMaximum(max(1, total))
        self.progressBar.setValue(0)

        processed = 0
        for feature in layer.getFeatures():
            geom = feature.geometry()
            if not geom or geom.isEmpty():
                continue

            centroid = geom.centroid().asPoint()
            wgs_pt = transform.transform(centroid)
            lat, lon = wgs_pt.y(), wgs_pt.x()

            fid_str = str(feature.id())
            name_attr = feature.attribute("name") if "name" in [f.name() for f in layer.fields()] else f"Obiekt #{fid_str}"

            # Tworzenie zadania asynchronicznego QgsTask
            task_desc = f"Analiza {name_attr} ({lat:.3f}, {lon:.3f})"
            task = AsyncApiTask(
                description=task_desc,
                parcel_id=fid_str,
                teryt_id=input_teryt,
                lat=lat,
                lon=lon,
                on_success_callback=self.on_task_completed
            )

            # Rejestracja w menedżerze zadań QGIS (pasek zadań na dole QGIS)
            QgsApplication.taskManager().addTask(task)
            processed += 1

        self.log(f"Queued {processed} background tasks (QgsTask); QGIS stays responsive.")

    def on_task_completed(self, data):
        """Slot odbierający wyniki z wątku tła i aktualizujący GUI."""
        current_val = self.progressBar.value() + 1
        self.progressBar.setValue(current_val)

        pid = data.get("parcel_id", "N/A")
        status = data.get("status", "N/A")
        metrics = data.get("metrics", {})

        self.log(f"Result for object #{pid} [status: {status}]")
        for k, v in metrics.items():
            self.log(f"   -> {k}: {v}")

    # ----- Farmer input layers (issue #14) -----

    def load_farmer_from_backend(self):
        base_url = self.txtFarmerUrl.text().strip()
        self._start_farmer_task(base_url, None, f"{base_url}/fields")

    def load_farmer_from_file(self):
        path, _filter = QFileDialog.getOpenFileName(
            self, "Farmer fields JSON (same shape as GET /fields)", "", "JSON (*.json)"
        )
        if path:
            self._start_farmer_task(None, path, path)

    def _start_farmer_task(self, base_url, file_path, source_label):
        self._farmer_source = source_label
        self.log(f"\nLoading farmer fields from {source_label} ...")
        self._set_farmer_busy(True)
        self._set_farmer_status("Loading farmer fields...", "info")
        task = FarmerFieldsTask("Load farmer fields", base_url, file_path, self._on_farmer_task_done)
        self._farmer_tasks.append(task)
        QgsApplication.taskManager().addTask(task)

    def _on_farmer_task_done(self, task):
        if task in self._farmer_tasks:
            self._farmer_tasks.remove(task)
        self.on_farmer_loaded(None if task.error else task.farmer_data, task.error)

    def _set_farmer_busy(self, busy):
        for button in (self.btnLoadFarmer, self.btnLoadFarmerFile):
            button.setEnabled(not busy)

    def _set_farmer_status(self, text, kind):
        """Plain status line under the buttons. kind: info, ok, mock (not real data) or error."""
        prefix = {"mock": "MOCK data: ", "error": "Error: "}.get(kind, "")
        self.lblFarmerStatus.setText(prefix + text)

    # ----- Data layers: pick layers from the backend catalog or local files -----

    def _set_data_busy(self, busy):
        for button in (self.btnLoadCatalog, self.btnLoadCatalogFile, self.btnAddLayers, self.btnAddLocalFiles):
            button.setEnabled(not busy)

    def _run_task(self, task):
        self._bg_tasks.append(task)
        self._set_data_busy(True)
        QgsApplication.taskManager().addTask(task)

    def _finish_task(self, task):
        if task in self._bg_tasks:
            self._bg_tasks.remove(task)
        self._set_data_busy(bool(self._bg_tasks))

    def load_catalog_from_backend(self):
        base_url = self.txtFarmerUrl.text().strip()
        self.lblCatalogStatus.setText("Loading catalog...")
        self.log(f"\nLoading catalog from {base_url}/catalog ...")
        self._run_task(CatalogTask("Load data catalog", base_url, None, self.on_catalog_loaded))

    def load_catalog_from_file(self):
        path, _filter = QFileDialog.getOpenFileName(
            self, "Catalog JSON (relative paths resolve against its folder)", "", "JSON (*.json)"
        )
        if path:
            self.lblCatalogStatus.setText("Loading catalog...")
            self.log(f"\nLoading catalog from {path} ...")
            self._run_task(CatalogTask("Load data catalog", None, path, self.on_catalog_loaded))

    def on_catalog_loaded(self, task):
        self._finish_task(task)
        if task.error is not None:
            self.lblCatalogStatus.setText("Error: " + task.error.message)
            self.log("ERROR loading catalog: " + task.error.describe())
            self.iface.messageBar().pushMessage(
                "Data layers", task.error.message, level=Qgis.Critical, duration=8
            )
            return
        catalog = task.catalog
        self.listLayers.clear()
        for entry in catalog.layers:
            item = QListWidgetItem(f"{entry['title']}  [{entry['format'] or entry['kind']}]")
            item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            item.setCheckState(Qt.Checked)
            item.setData(Qt.UserRole, entry)
            tip = [f"Source: {entry['source']}"]
            if entry["provenance"]:
                tip.append(f"Provenance: {entry['provenance']}")
            if entry["note"]:
                tip.append(f"Note: {entry['note']}")
            if entry["known_gaps"]:
                tip.append("Known gaps: " + "; ".join(entry["known_gaps"]))
            item.setToolTip("\n".join(tip))
            self.listLayers.addItem(item)
        self._fit_layer_list()
        for warning in catalog.warnings:
            self.log("WARNING: " + warning)
        text = f"{len(catalog.layers)} layers in the catalog. Untick the ones you do not need."
        if catalog.warnings:
            text += f" {len(catalog.warnings)} entries skipped (see details)."
        self.lblCatalogStatus.setText(text)
        self.log(f"Catalog loaded: {len(catalog.layers)} layers.")
        sim = catalog.simulation
        if sim and sim.get("simulated"):
            self.log(f"NOTE: simulated dates, shifted by {sim.get('shift_days')} days (see sim_date).")
            self.iface.messageBar().pushMessage(
                "Data layers",
                f"Dates are simulated: shifted by {sim.get('shift_days')} days. Use sim_date.",
                level=Qgis.Info, duration=8,
            )

    def _fit_layer_list(self):
        """Make the list exactly as tall as its rows (no empty space)."""
        n = self.listLayers.count()
        if n == 0:
            self.listLayers.setFixedHeight(0)
            self.listLayers.setVisible(False)
            return
        self.listLayers.setVisible(True)
        row = self.listLayers.sizeHintForRow(0)
        rows = min(n, 12)
        self.listLayers.setFixedHeight(row * rows + 2 * self.listLayers.frameWidth() + 2)

    def add_selected_layers(self):
        entries = []
        for row in range(self.listLayers.count()):
            item = self.listLayers.item(row)
            if item.checkState() == Qt.Checked:
                entries.append(item.data(Qt.UserRole))
        if not entries:
            self.lblCatalogStatus.setText("Nothing ticked. Load a catalog and tick at least one layer.")
            return
        self._start_prepare(entries)

    def add_local_files(self):
        paths, _filter = QFileDialog.getOpenFileNames(
            self, "Add files", "",
            "Data files (*.tif *.tiff *.geojson *.json *.gpkg *.shp *.csv);;All files (*)",
        )
        entries = []
        for path in paths:
            try:
                entries.append(data_catalog.entry_from_local_file(path))
            except data_catalog.DataSourceError as exc:
                self.log("ERROR: " + exc.message)
        if entries:
            self._start_prepare(entries)

    def _start_prepare(self, entries):
        self.lblCatalogStatus.setText(f"Checking {len(entries)} sources...")
        self.log(f"\nChecking {len(entries)} sources ...")
        self._run_task(PrepareLayersTask("Check data sources", entries, self.on_layers_prepared))

    def on_layers_prepared(self, task):
        """Main thread: create the layers that passed the checks and report the rest."""
        self._finish_task(task)
        for warning in task.warnings:
            self.log("WARNING: " + warning)
        for failure in task.failures:
            self.log("ERROR: " + failure.describe())
        added, last = 0, None
        for entry, qml in task.ready:
            try:
                last, notes = add_catalog_layer(entry, qml)
                added += 1
                self.log(f"Added: {entry['title']}")
                for note in notes:
                    self.log("WARNING: " + note)
            except data_catalog.DataSourceError as exc:
                self.log("ERROR: " + exc.describe())
                task.failures.append(exc)
        text = f"Added {added} of {len(task.entries)} layers."
        if task.failures:
            text += f" {len(task.failures)} failed (see details)."
            self.iface.messageBar().pushMessage(
                "Data layers", f"{len(task.failures)} layers could not be added.",
                level=Qgis.Warning, duration=8,
            )
        self.lblCatalogStatus.setText(text)
        if last is not None:
            self.iface.setActiveLayer(last)
            self.iface.zoomToActiveLayer()

    def on_farmer_loaded(self, farmer_data, error):
        """Runs on the main thread. An outage, an error and an empty result are reported separately."""
        bar = self.iface.messageBar()
        self._set_farmer_busy(False)
        if error is not None:
            self._set_farmer_status(error.message, "error")
            self.log("ERROR loading farmer fields: " + error.describe())
            bar.pushMessage("Farmer fields", error.message, level=Qgis.Critical, duration=8)
            return

        status = farmer_data.data_status or "unlabelled"
        self.log(
            f"Backend data_status: {status}. Fields: {farmer_data.field_count}, "
            f"parcels: {len(farmer_data.parcels)}, crop areas: {len(farmer_data.crop_areas)}."
        )
        for warning in farmer_data.warnings:
            self.log("WARNING: " + warning)
        incomplete = [r for r in farmer_data.crop_areas if r["attributes"]["data_issues"]]
        for row in incomplete:
            a = row["attributes"]
            self.log(f"INCOMPLETE {a['crop_area_id']}: {a['data_issues']}")

        if not farmer_data.crop_areas:
            self._set_farmer_status("Loaded, but the source returned no crop areas.", "info")
            self.log("The backend returned no crop areas to display (this is not an error).")
            bar.pushMessage("Farmer fields", "No saved crop areas to display.", level=Qgis.Info, duration=6)
            return

        _parcels, areas = add_farmer_layers(farmer_data, self._farmer_source)
        summary = (
            f"{farmer_data.field_count} fields, {len(farmer_data.crop_areas)} crop areas"
            f" - data_status: {status}"
        )
        if incomplete or farmer_data.warnings:
            summary += f"\n{len(incomplete)} incomplete, {len(farmer_data.warnings)} warnings (see log)"
        self._set_farmer_status(summary, "mock" if farmer_data.data_status == "mock" else "ok")
        self.iface.mapCanvas().setExtent(areas.extent())
        self.iface.mapCanvas().refresh()
        if farmer_data.data_status == "mock":
            bar.pushMessage(
                "Farmer fields", "These are MOCK fixtures, not real farmer data.",
                level=Qgis.Warning, duration=10,
            )
