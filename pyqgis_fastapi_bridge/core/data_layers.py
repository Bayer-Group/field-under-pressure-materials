# -*- coding: utf-8 -*-
"""
Adds catalog layers or local files to the QGIS project. Call from the GUI thread only
(QgsTask.finished); network checks happen earlier in the task (data_catalog.probe_source).
"""

from qgis.core import (
    QgsProject,
    QgsRasterLayer,
    QgsVectorLayer,
    QgsVectorLayerTemporalProperties,
)

from .data_catalog import DataSourceError, is_remote

LAYER_ID_PROPERTY = "pyqgis_bridge/catalog_layer_id"
CSV_OPTIONS = "?delimiter=,&detectTypes=yes"


def add_catalog_layer(entry, qml_path=None):
    """Create one layer from a catalog entry and add it. Returns (layer, notes).

    An earlier layer added from the same entry is replaced, so reloading does not stack copies.
    """
    layer = _create_layer(entry)
    if not layer.isValid():
        raise DataSourceError("LAYER_INVALID", f"QGIS could not open {entry['title']} ({entry['source']}).")

    notes = []
    if qml_path:
        _message, loaded = layer.loadNamedStyle(qml_path)
        if not loaded:
            notes.append(f"{entry['title']}: legend style could not be applied.")
    if entry.get("time_field") and isinstance(layer, QgsVectorLayer):
        notes.extend(_enable_time(layer, entry["time_field"], entry["title"]))

    layer.setCustomProperty(LAYER_ID_PROPERTY, entry["id"])
    layer.setAbstract(
        f"Source: {entry['source']}. Provenance: {entry.get('provenance') or 'not stated'}."
        + (" Known gaps: " + "; ".join(entry["known_gaps"]) if entry.get("known_gaps") else "")
    )

    project = QgsProject.instance()
    for layer_id, old in list(project.mapLayers().items()):
        if old.customProperty(LAYER_ID_PROPERTY) == entry["id"]:
            project.removeMapLayer(layer_id)
    project.addMapLayer(layer)
    return layer, notes


def _create_layer(entry):
    source, kind, title = entry["source"], entry["kind"], entry["title"]
    if kind == "raster":
        return QgsRasterLayer(("/vsicurl/" + source) if is_remote(source) else source, title, "gdal")
    if kind == "vector":
        return QgsVectorLayer(("/vsicurl/" + source) if is_remote(source) else source, title, "ogr")
    uri = source if is_remote(source) else "file:///" + source.replace("\\", "/")
    return QgsVectorLayer(uri + CSV_OPTIONS, title, "delimitedtext")


def _enable_time(layer, field, title):
    if layer.fields().indexOf(field) < 0:
        return [f"{title}: time field {field} not found; temporal controller not enabled."]
    properties = layer.temporalProperties()
    properties.setIsActive(True)
    properties.setMode(QgsVectorLayerTemporalProperties.ModeFeatureDateTimeInstantFromField)
    properties.setStartField(field)
    return []
