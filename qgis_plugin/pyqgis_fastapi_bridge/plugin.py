# -*- coding: utf-8 -*-
"""
Rejestracja wtyczki PyQGIS FastAPI Bridge w interfejsie QGIS.
"""

import os
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QAction
from PyQt5.QtGui import QIcon
from .gui.dockwidget import PyQgisBridgeDockWidget

class PyQgisFastApiBridgePlugin:
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.action = None
        self.dockwidget = None

    def initGui(self):
        icon_path = os.path.join(self.plugin_dir, "icon.png")
        icon = QIcon(icon_path)

        self.action = QAction(icon, "PyQGIS FastAPI Bridge", self.iface.mainWindow())
        self.action.setStatusTip("Otwórz panel asynchronicznej komunikacji z FastAPI")
        self.action.triggered.connect(self.run)

        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu("&PyQGIS FastAPI Bridge", self.action)

        self.dockwidget = PyQgisBridgeDockWidget(self.iface, self.iface.mainWindow())
        self.dockwidget.closingPlugin.connect(self.on_dock_closed)
        self.iface.addDockWidget(Qt.RightDockWidgetArea, self.dockwidget)
        self.dockwidget.hide()

    def unload(self):
        if self.action:
            self.iface.removePluginMenu("&PyQGIS FastAPI Bridge", self.action)
            self.iface.removeToolBarIcon(self.action)

        if self.dockwidget:
            self.iface.removeDockWidget(self.dockwidget)
            self.dockwidget.deleteLater()

    def run(self):
        if not self.dockwidget:
            self.dockwidget = PyQgisBridgeDockWidget(self.iface, self.iface.mainWindow())
            self.iface.addDockWidget(Qt.RightDockWidgetArea, self.dockwidget)

        if self.dockwidget.isVisible():
            self.dockwidget.hide()
        else:
            self.dockwidget.show()
            self.dockwidget.raise_()

    def on_dock_closed(self):
        pass
