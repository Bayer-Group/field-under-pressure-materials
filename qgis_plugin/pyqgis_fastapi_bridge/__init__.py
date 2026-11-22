# -*- coding: utf-8 -*-
"""
PyQGIS FastAPI Bridge - Asynchroniczna wtyczka QGIS.
"""

def classFactory(iface):
    from .plugin import PyQgisFastApiBridgePlugin
    return PyQgisFastApiBridgePlugin(iface)
