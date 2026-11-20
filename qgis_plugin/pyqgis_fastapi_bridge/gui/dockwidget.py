# -*- coding: utf-8 -*-
"""
Panel boczny wtyczki PyQGIS FastAPI Bridge.
Wykorzystuje QgsTask do asynchronicznego odpytywania API w tle
bez blokowania lub zawieszania interfejsu użytkownika QGIS.
"""

import os
from PyQt5 import uic
from PyQt5.QtWidgets import QDockWidget
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

from ..core.api_client import BackendApiClient

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


class PyQgisBridgeDockWidget(QDockWidget, FORM_CLASS):
    closingPlugin = pyqtSignal()

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.iface = iface

        self.btnRefresh.clicked.connect(self.populate_layers)
        self.btnRun.clicked.connect(self.run_processing)
        self.btnClear.clicked.connect(self.txtLog.clear)

        self.populate_layers()

    def closeEvent(self, event):
        self.closingPlugin.emit()
        event.accept()

    def log(self, text):
        self.txtLog.append(str(text))

    def populate_layers(self):
        self.cmbLayer.clear()
        found = 0
        for layer in QgsProject.instance().mapLayers().values():
            if isinstance(layer, QgsVectorLayer) and layer.geometryType() == QgsWkbTypes.PolygonGeometry:
                self.cmbLayer.addItem(layer.name(), layer)
                found += 1

        self.log(f"Wczytano warstwy. Znaleziono poligonów: {found}")

    def run_processing(self):
        layer = self.cmbLayer.currentData()
        if not layer or not layer.isValid():
            self.log("BŁĄD: Wybierz poprawną warstwę wektorową!")
            return

        input_teryt = self.txtTeryt.text().strip()

        self.log(f"\n==================================================")
        self.log(f" Start asynchronicznej analizy (QgsTask): {layer.name()}")
        if input_teryt:
            self.log(f" Filtr TERYT / ID: {input_teryt}")
        self.log(f"==================================================")

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

        self.log(f"Zlecono {processed} zadań w tle (QgsTask). Interfejs QGIS pozostaje w pełni responsywny!")

    def on_task_completed(self, data):
        """Slot odbierający wyniki z wątku tła i aktualizujący GUI."""
        current_val = self.progressBar.value() + 1
        self.progressBar.setValue(current_val)

        pid = data.get("parcel_id", "N/A")
        status = data.get("status", "N/A")
        metrics = data.get("metrics", {})

        self.log(f"✓ Wynik dla obiektu #{pid} [Status: {status}]")
        for k, v in metrics.items():
            self.log(f"   -> {k}: {v}")
