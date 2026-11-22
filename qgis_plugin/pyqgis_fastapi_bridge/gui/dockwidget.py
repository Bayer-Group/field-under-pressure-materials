# -*- coding: utf-8 -*-
"""
Side panel of the PyQGIS FastAPI Bridge plugin.
Uses QgsTask to query the API asynchronously in the background
without blocking or freezing the QGIS user interface.
"""

import os
import tempfile
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
    QgsApplication,
    QgsGeometry,
)

from qgis.core import Qgis, QgsMessageLog
from PyQt5.QtCore import Qt, QDate, QTimer

from ..core import farmer_fields, serve_api
from ..core.serve_layers import LAYER_PROPERTY, add_crop_area_layer, add_grid_layer, add_history_table
from ..core.farmer_layers import add_farmer_layers

LOG_TAG = "Field Under Pressure"
UI_PATH = os.path.join(os.path.dirname(__file__), "dockwidget.ui")
FORM_CLASS, _ = uic.loadUiType(UI_PATH)


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


def _intersects(area):
    """Predicate on a GeoJSON geometry: does it intersect the area (QgsGeometry, EPSG:4326)?"""
    engine = QgsGeometry.createGeometryEngine(area.constGet())
    engine.prepareGeometry()
    box = area.boundingBox()

    def test(geojson):
        if geojson["type"] == "Point":
            x, y = geojson["coordinates"][:2]
            geometry = QgsGeometry.fromWkt(f"POINT({x} {y})")
        else:
            geometry = QgsGeometry.fromWkt(farmer_fields.geojson_to_wkt(geojson))
        if geometry.isEmpty() or not box.intersects(geometry.boundingBox()):
            return False
        return engine.intersects(geometry.constGet())

    return test


class ServeTask(QgsTask):
    """Background task: read crop areas or the grid (read contract) from the API or a file.

    For crop areas from the API it also reads GET /crop-areas/{id} of each area, so the
    attribute table carries the soil and crop-map context (issue #49).
    """

    def __init__(self, description, kind, base_url, file_path, date, token, on_done, limit=None):
        super().__init__(description, QgsTask.CanCancel)
        self.limit = limit        # None or (QgsGeometry in EPSG:4326, bbox tuple, label)
        self.kind = kind          # "crop_areas" or "grid"
        self.base_url = base_url
        self.file_path = file_path
        self.date = date
        self.token = token
        self.on_done = on_done
        self.data = None
        self.error = None
        self.grid_options = {}
        self.surface_path = None      # the heatmap of the API (ASC), when it was asked for and read
        self.surface_error = None

    def run(self):
        try:
            if self.file_path:
                payload = serve_api.load_file(self.file_path)
            else:
                bbox = serve_api.bbox_param(self.limit[1]) if self.limit else None
                if self.kind == "crop_areas":
                    payload = serve_api.fetch(self.base_url, serve_api.CROP_AREA_PATH, {"bbox": bbox},
                                              token=self.token)
                else:
                    payload = serve_api.fetch(self.base_url, serve_api.GRID_RISK_PATH,
                                              {"date": self.date, "bbox": bbox}, token=self.token, timeout=60)
            parse = serve_api.parse_crop_areas if self.kind == "crop_areas" else serve_api.parse_grid_risk
            self.data = parse(payload)
            if self.limit:
                serve_api.keep_rows(self.data, _intersects(self.limit[0]), self.limit[2])
            if self.kind == "crop_areas" and not self.file_path and self.data.rows:
                serve_api.add_details(self.data, self.base_url, self.token)
            if self.kind == "grid" and not self.file_path and self.grid_options.get("surface"):
                try:
                    self.surface_path = serve_api.fetch_surface_asc(
                        self.base_url, self.token, self.date, tempfile.gettempdir())
                except farmer_fields.FarmerDataError as exc:       # the cells are still shown
                    self.surface_error = exc
            return True
        except farmer_fields.FarmerDataError as exc:
            self.error = exc
            return False
        except Exception as exc:
            self.error = farmer_fields.FarmerDataError("UNEXPECTED_ERROR", str(exc))
            return False

    def finished(self, result):
        self.on_done(self)


class SessionTask(QgsTask):
    """Background task: POST /sandbox or POST /login, then GET /clock for the shown today."""

    def __init__(self, description, base_url, on_done, login_name=None, password=None):
        super().__init__(description, QgsTask.CanCancel)
        self.base_url = base_url
        self.login_name = login_name
        self._password = password
        self.on_done = on_done
        self.session = None
        self.clock = None
        self.error = None

    def run(self):
        try:
            if self.login_name:
                self.session = serve_api.login(self.base_url, self.login_name, self._password)
            else:
                self.session = serve_api.start_sandbox(self.base_url, "mock")
            try:
                self.clock = serve_api.get_clock(self.base_url)
            except farmer_fields.FarmerDataError:
                self.clock = None
            return True
        except farmer_fields.FarmerDataError as exc:
            self.error = exc
            return False
        except Exception as exc:
            self.error = farmer_fields.FarmerDataError("UNEXPECTED_ERROR", str(exc))
            return False
        finally:
            self._password = None   # never kept after the request

    def finished(self, result):
        self.on_done(self)


class HistoryTask(QgsTask):
    """Background task: GET /crop-areas/{id}/risk and /changes for one crop area."""

    def __init__(self, description, base_url, token, crop_area_id, on_done):
        super().__init__(description, QgsTask.CanCancel)
        self.base_url = base_url
        self.token = token
        self.crop_area_id = crop_area_id
        self.on_done = on_done
        self.rows = None
        self.changes = None
        self.error = None

    def run(self):
        try:
            self.rows, self.changes = serve_api.fetch_history(self.base_url, self.token, self.crop_area_id)
            return True
        except farmer_fields.FarmerDataError as exc:
            self.error = exc
            return False
        except Exception as exc:
            self.error = farmer_fields.FarmerDataError("UNEXPECTED_ERROR", str(exc))
            return False

    def finished(self, result):
        self.on_done(self)


class PyQgisBridgeDockWidget(QDockWidget, FORM_CLASS):
    closingPlugin = pyqtSignal()

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.iface = iface

        self.btnClear.clicked.connect(self.txtLog.clear)
        self.btnToggleLog.toggled.connect(self._toggle_log)
        self.txtFarmerUrl.setText(farmer_fields.DEFAULT_BASE_URL)
        self.btnLoadFarmer.clicked.connect(self.load_farmer_from_backend)
        self.btnLoadFarmerFile.clicked.connect(self.load_farmer_from_file)
        self._farmer_source = ""
        self.dateGrid.setDate(QDate.currentDate())
        self.btnSandbox.clicked.connect(self._start_sandbox)
        self.btnLogin.clicked.connect(self._login)
        self.txtPassword.returnPressed.connect(self._login)
        self.btnHistory.clicked.connect(self._load_history)
        self.btnRefreshLimit.clicked.connect(self._populate_limit_layers)
        QgsProject.instance().layersAdded.connect(lambda *_: self._populate_limit_layers())
        QgsProject.instance().layersRemoved.connect(lambda *_: self._populate_limit_layers())
        self._populate_limit_layers()
        self._session_role = None
        self.btnDisconnect.clicked.connect(self._disconnect)
        self.btnOffline.clicked.connect(self._work_offline)
        self.btnLoadApiLayers.clicked.connect(self._load_checked_layers)
        self._risk_running = 0
        self._fill_api_layers()
        self.btnLoadCropAreasFile.clicked.connect(lambda: self._start_serve("crop_areas", True))
        self.btnLoadGridFile.clicked.connect(lambda: self._start_serve("grid", True))
        self._bg_tasks = []
        self._farmer_tasks = []  # keep Python references so QgsTask objects are not garbage collected

        self.lblRiskStatus.setVisible(False)
        self.lblFarmerStatus.setVisible(False)
        self.txtToken.setVisible(False)     # filled by the sign-in; no need to paste a token
        self._set_stage(False)              # step 1 first: backend and sign-in

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
        if stripped.startswith("ERROR"):
            level = Qgis.Critical
        elif stripped.startswith(("WARNING", "INCOMPLETE")):
            level = Qgis.Warning
        else:
            level = Qgis.Info
        QgsMessageLog.logMessage(stripped, LOG_TAG, level)

    def _toggle_log(self, expanded):
        self.logBody.setVisible(expanded)
        self.btnToggleLog.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)

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
        """Status line under the buttons, shown only for an error. kind: info, ok, mock or error.

        The rest (counts, the MOCK warning) is in the log and the message bar.
        """
        self.lblFarmerStatus.setText("Error: " + text if kind == "error" else "")
        self.lblFarmerStatus.setVisible(kind == "error")

    def _risk_msg(self, text):
        """Hint or error under the layer buttons; an empty text hides the label."""
        self.lblRiskStatus.setText(text)
        self.lblRiskStatus.setVisible(bool(text))

    # ----- Septoria risk: crop areas and grid from the read contract (issue #49) -----

    def _risk_buttons(self):
        return (self.btnSandbox, self.btnLogin, self.btnLoadApiLayers, self.btnLoadCropAreasFile,
                self.btnLoadGridFile, self.btnHistory)

    def _set_risk_busy(self, busy):
        """Counts running tasks, so two layers loading at once keep the buttons off until both end."""
        self._risk_running = max(0, getattr(self, "_risk_running", 0) + (1 if busy else -1))
        for button in self._risk_buttons():
            button.setEnabled(self._risk_running == 0)

    def _fill_api_layers(self):
        """The checklist of API layers; a layer needing another role or not served yet is greyed out."""
        checked = {self.listApiLayers.item(i).data(Qt.UserRole)
                   for i in range(self.listApiLayers.count())
                   if self.listApiLayers.item(i).checkState() == Qt.Checked}
        if not checked and self.listApiLayers.count() == 0:
            checked = set(serve_api.DEFAULT_LAYERS)
        self.listApiLayers.clear()
        role = getattr(self, "_session_role", None)
        for layer_id, title, request, needs_role, available in serve_api.API_LAYERS:
            item = QListWidgetItem(title)
            item.setData(Qt.UserRole, layer_id)
            usable = available and (needs_role is None or role in (None, needs_role))
            tip = request
            if needs_role and role not in (None, needs_role):
                tip += f" - needs the {needs_role} role (now: {role})"
            if not available:
                item.setText(f"{title} - not in the API yet")
            item.setToolTip(tip)
            flags = Qt.ItemIsUserCheckable | (Qt.ItemIsEnabled if usable else Qt.NoItemFlags)
            item.setFlags(flags)
            item.setCheckState(Qt.Checked if (usable and layer_id in checked) else Qt.Unchecked)
            self.listApiLayers.addItem(item)
        row = self.listApiLayers.sizeHintForRow(0)
        self.listApiLayers.setFixedHeight(row * self.listApiLayers.count() + 2 * self.listApiLayers.frameWidth() + 2)

    def _load_checked_layers(self):
        ids = [self.listApiLayers.item(i).data(Qt.UserRole) for i in range(self.listApiLayers.count())
               if self.listApiLayers.item(i).checkState() == Qt.Checked]
        if not ids:
            self._risk_msg("Tick at least one layer to load.")
            return
        if "crop_areas" in ids:
            self._start_serve("crop_areas", False)
        surface, cells = "grid_surface" in ids, "grid_cells" in ids
        if surface or cells:
            self._start_serve("grid", False, surface=surface, cells=cells)

    def _base_url(self):
        return self.txtFarmerUrl.text().strip() or serve_api.DEFAULT_BASE_URL

    def _set_stage(self, connected, text=None):
        """Two steps: 1 = backend + sign-in, 2 = everything else (after a successful sign-in)."""
        for box in (self.grpBackend, self.grpSession):
            box.setVisible(not connected)
        for box in (self.grpConnection, self.grpFarmer, self.grpRisk):
            box.setVisible(connected)
        if connected:
            self.lblConnection.setText((text or "Connected.") + f"\nBackend: {self._base_url()}")

    def _disconnect(self):
        """Back to step 1: the token is forgotten; layers already on the map stay."""
        self.txtToken.clear()
        self.txtPassword.clear()
        self._session_role = None
        self.lblSession.setText("Not connected.")
        self._fill_api_layers()
        self._set_stage(False)
        self.log("Logged out.")

    def _work_offline(self):
        """Step 2 without a session: only the buttons that read files work."""
        self._session_role = None
        self._fill_api_layers()
        self._set_stage(True, "Offline: files only (no token).")

    def _start_sandbox(self):
        """POST /sandbox {"mode": "mock"}: no password, farmer role, a copy of a ready farm for 8 hours."""
        self._start_session(SessionTask("Start sandbox", self._base_url(), self._on_session_done), "sandbox")

    def _login(self):
        """POST /login: the analyst (or a development farmer) account. The password is not kept."""
        login_name = self.txtLogin.text().strip()
        password = self.txtPassword.text()
        self.txtPassword.clear()
        if not login_name or not password:
            self.lblSession.setText("Enter the login and the password.")
            return
        task = SessionTask("Log in", self._base_url(), self._on_session_done, login_name, password)
        self._start_session(task, f"login as {login_name}")

    def _start_session(self, task, label):
        self.log(f"\nConnecting to {self._base_url()} ({label}) ...")
        self.lblSession.setText("Connecting...")
        self._set_risk_busy(True)
        self._bg_tasks.append(task)
        QgsApplication.taskManager().addTask(task)

    def _on_session_done(self, task):
        if task in self._bg_tasks:
            self._bg_tasks.remove(task)
        self._set_risk_busy(False)
        if task.error is not None:
            self.lblSession.setText("Error: " + task.error.message)
            self.log("ERROR connecting: " + task.error.describe())
            self.iface.messageBar().pushMessage("Session", task.error.message, level=Qgis.Critical, duration=8)
            return
        session = task.session
        self.txtToken.setText(session["token"])
        self._session_role = session.get("role")
        who = task.login_name or "sandbox"
        hours = round((session.get("expires_in") or 0) / 3600, 1)
        text = f"Connected: {who}, role {self._session_role}"
        if session.get("mode"):
            text += f", mode {session['mode']}"
        if hours:
            text += f", token valid {hours:g} h"
        if task.clock:
            today = QDate.fromString(task.clock["today"], Qt.ISODate)
            if today.isValid():
                self.dateGrid.setDate(today)
            text += f". Today (shown): {task.clock['today']}"
        self.lblSession.setText(text + ".")
        self.log(text + ".")
        self._fill_api_layers()
        self._set_stage(True, text + ".")

    def _populate_limit_layers(self):
        """Polygon layers that can limit the loading (not the grid layers this panel makes)."""
        try:
            current = self.cmbLimitLayer.currentData()
        except RuntimeError:            # the panel was closed
            return
        self.cmbLimitLayer.blockSignals(True)
        self.cmbLimitLayer.clear()
        self.cmbLimitLayer.addItem("(no limit: everything the API returns)", None)
        for layer in QgsProject.instance().mapLayers().values():
            if not isinstance(layer, QgsVectorLayer) or layer.geometryType() != QgsWkbTypes.PolygonGeometry:
                continue
            if layer.customProperty(LAYER_PROPERTY) == "grid":
                continue
            self.cmbLimitLayer.addItem(layer.name(), layer.id())
        index = self.cmbLimitLayer.findData(current)
        self.cmbLimitLayer.setCurrentIndex(max(index, 0))
        self.cmbLimitLayer.blockSignals(False)

    def _limit_area(self):
        """(geometry in EPSG:4326, bbox, label), None for no limit, or a str with the reason it failed."""
        layer_id = self.cmbLimitLayer.currentData()
        if not layer_id:
            return None
        layer = QgsProject.instance().mapLayer(layer_id)
        if layer is None:
            return "The limit layer is no longer in the project."
        only_selected = self.chkLimitSelected.isChecked()
        features = layer.selectedFeatures() if only_selected else list(layer.getFeatures())
        if not features:
            return ("Select at least one polygon in " if only_selected else "No polygons in ") + layer.name() + "."
        parts = [f.geometry() for f in features if f.hasGeometry()]
        area = QgsGeometry.unaryUnion(parts)
        if area.isEmpty():
            return f"The polygons of {layer.name()} have no usable geometry."
        transform = QgsCoordinateTransform(layer.crs(), QgsCoordinateReferenceSystem("EPSG:4326"),
                                           QgsProject.instance())
        area.transform(transform)
        box = area.boundingBox()
        label = layer.name() + (f" ({len(features)} selected)" if only_selected else "")
        return area, (box.xMinimum(), box.yMinimum(), box.xMaximum(), box.yMaximum()), label

    def _start_serve(self, kind, from_file, surface=True, cells=True):
        label = "crop areas" if kind == "crop_areas" else "voivodeship grid"
        base_url = self._base_url()
        token = self.txtToken.text().strip()
        path = None
        if from_file:
            title = "GeoJSON like GET /me/crop-areas" if kind == "crop_areas" else "GeoJSON like GET /grid/risk"
            path, _filter = QFileDialog.getOpenFileName(self, title, "", "GeoJSON / JSON (*.json *.geojson)")
            if not path:
                return
        elif not token:
            self._risk_msg("Start a sandbox or log in first (the API needs a token).")
            return
        date = self.dateGrid.date().toString("yyyy-MM-dd")
        source = path or base_url + (serve_api.CROP_AREA_PATH if kind == "crop_areas"
                                     else f"{serve_api.GRID_RISK_PATH}?date={date}")
        self._serve_source = source
        self.log(f"\nLoading {label} from {source} ...")
        self._set_risk_busy(True)
        self._risk_msg(f"Loading {label}...")
        limit = self._limit_area()
        if isinstance(limit, str):
            self._risk_msg(limit)
            self._set_risk_busy(False)
            return
        if limit:
            self.log(f"Limited to {limit[2]}; bbox {serve_api.bbox_param(limit[1])}")
        task = ServeTask(f"Load {label}", kind, base_url, path, date, token, self._on_serve_done, limit)
        task.grid_options = {"surface": surface, "cells": cells}
        task.source = source
        self._bg_tasks.append(task)
        QgsApplication.taskManager().addTask(task)

    def _on_serve_done(self, task):
        if task in self._bg_tasks:
            self._bg_tasks.remove(task)
        self._set_risk_busy(False)
        bar = self.iface.messageBar()
        label = "Crop areas" if task.kind == "crop_areas" else "Voivodeship grid"
        if task.error is not None:
            self._risk_msg("Error: " + task.error.message)
            self.log(f"ERROR loading {label.lower()}: " + task.error.describe())
            bar.pushMessage(label, task.error.message, level=Qgis.Critical, duration=8)
            return
        data = task.data
        for warning in data.warnings[:20]:
            self.log("WARNING: " + warning)
        if len(data.warnings) > 20:
            self.log(f"WARNING: ... and {len(data.warnings) - 20} more.")
        if not data.rows:
            text = ("Nothing intersects the limit area." if data.limited
                    else "The source returned no features.")
            if task.kind == "grid":
                text += " There may be no data for this date; try the shown today."
            self._risk_msg(text)
            bar.pushMessage(label, text, level=Qgis.Info, duration=6)
            return
        if task.kind == "crop_areas":
            layer = add_crop_area_layer(data, getattr(task, "source", self._serve_source))
        else:
            options = task.grid_options
            layer = add_grid_layer(data, getattr(task, "source", self._serve_source),
                                   surface_path=task.surface_path, cells=options.get("cells", True))
            if task.surface_error is not None:
                self.log("WARNING: the heatmap was not loaded: " + task.surface_error.describe())
                bar.pushMessage(label, "Heatmap not loaded: " + task.surface_error.message,
                                level=Qgis.Warning, duration=8)
        counts = {}
        for row in data.rows:
            attrs = row["attributes"]
            if task.kind == "crop_areas" and attrs.get("status") not in ("ok", "uncertain"):
                key = attrs.get("status") or "no assessment today"
            else:
                key = attrs.get("risk_class") or "not assessed"
            counts[key] = counts.get(key, 0) + 1
        order = ["high", "medium", "low"]
        parts = [f"{counts[k]} {k}" for k in order if k in counts]
        parts += [f"{v} {k}" for k, v in sorted(counts.items()) if k not in order]
        text = f"{label}: {len(data.rows)} features ({', '.join(parts)})"
        if task.kind == "crop_areas" and not task.file_path:
            with_soil = len(data.rows) - data.details_missing
            text += f"; soil context for {with_soil}"
        if data.limited:
            area, kept, received = data.limited
            text += f"; limited to {area}: {kept} of {received}"
            if task.surface_path:
                text += " (the heatmap covers the whole voivodeship)"
        if task.kind == "grid" and task.surface_error is not None:
            text += "; heatmap not loaded"
        if data.data_status == "mock":
            text = "MOCK data. " + text
        if data.warnings:
            text += f"; {len(data.warnings)} warnings (see details)"
        self._risk_msg("")                      # a success is only in the log; the label is for errors and hints
        self.log(text + ".")
        # QGIS gives an empty project the CRS of its first layer a moment later (EPSG:4326 here), so the
        # switch to the metric national CRS runs after that: 4 km cells look square, distances in metres.
        QTimer.singleShot(300, lambda: self._show_in_2180(layer))
        if data.data_status == "mock":
            bar.pushMessage(label, "Mock data (a demo farm), not real fields.", level=Qgis.Warning, duration=8)

    def _show_in_2180(self, layer):
        project = QgsProject.instance()
        if project.crs().authid() in ("", "EPSG:4326"):
            project.setCrs(QgsCoordinateReferenceSystem("EPSG:2180"))
            self.log("Project CRS set to EPSG:2180 (the layers stay EPSG:4326).")
        canvas = self.iface.mapCanvas()
        try:
            extent = canvas.mapSettings().layerExtentToOutputExtent(layer, layer.extent())
        except RuntimeError:        # the layer was removed meanwhile
            return
        extent.scale(1.05)
        canvas.setExtent(extent)
        canvas.refresh()

    def _load_history(self):
        layer = next((l for l in QgsProject.instance().mapLayers().values()
                      if l.customProperty(LAYER_PROPERTY) == "crop_areas"), None)
        if layer is None or layer.selectedFeatureCount() != 1:
            self._risk_msg("Load the crop areas and select exactly one on the map.")
            return
        token = self.txtToken.text().strip()
        if not token:
            self._risk_msg("Start a sandbox or log in first (the API needs a token).")
            return
        crop_area_id = layer.selectedFeatures()[0]["crop_area_id"]
        self.log(f"\nLoading the risk history of {crop_area_id} ...")
        self._set_risk_busy(True)
        self._risk_msg(f"Loading the risk history of {crop_area_id}...")
        task = HistoryTask(f"Risk history {crop_area_id}", self._base_url(), token, crop_area_id,
                           self._on_history_done)
        self._bg_tasks.append(task)
        QgsApplication.taskManager().addTask(task)

    def _on_history_done(self, task):
        if task in self._bg_tasks:
            self._bg_tasks.remove(task)
        self._set_risk_busy(False)
        if task.error is not None:
            self._risk_msg("Error: " + task.error.message)
            self.log("ERROR loading the risk history: " + task.error.describe())
            return
        source = self._base_url() + serve_api.CROP_AREA_RISK_PATH.format(id=task.crop_area_id)
        layer = add_history_table(task.crop_area_id, task.rows, serve_api.RISK_DAY_FIELDS, source)
        self.log(f"Risk history of {task.crop_area_id}: {len(task.rows)} days, {len(task.changes)} changes.")
        for change in task.changes[:15]:
            self.log(
                f"  {change.get('date')}: class {change.get('old_class')} -> {change.get('new_class')}, "
                f"status {change.get('old_status')} -> {change.get('new_status')} ({change.get('reason')})"
            )
        self._risk_msg("")
        self.iface.showAttributeTable(layer)

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
