# -*- coding: utf-8 -*-
"""
Builds the QGIS layers for farmer input (issue #14) from parsed FarmerData.

Two memory layers in EPSG:4326: parcels (outline) and crop areas (filled,
categorized). Farmer-provided crop and crop-map crop are separate attributes.
Call ``add_farmer_layers`` from the GUI thread only (QgsTask.finished).
"""

from PyQt5.QtCore import QDate, QVariant, Qt
from qgis.core import (
    QgsCategorizedSymbolRenderer,
    QgsFeature,
    QgsField,
    QgsFillSymbol,
    QgsGeometry,
    QgsPalLayerSettings,
    QgsProject,
    QgsRendererCategory,
    QgsVectorLayer,
    QgsVectorLayerSimpleLabeling,
)

from .farmer_fields import geojson_to_wkt

LAYER_PROPERTY = "pyqgis_bridge/farmer_layer"

CATEGORY_INCOMPLETE = "incomplete or invalid data"
CATEGORY_DIFFERS = "farmer crop differs from crop map"
CATEGORY_NO_MAP = "farmer crop, no crop-map value"
CATEGORY_SAME = "farmer crop matches crop map"

STYLE_EXPRESSION = (
    "CASE "
    "WHEN \"data_issues\" IS NOT NULL AND \"data_issues\" <> '' THEN '%s' "
    "WHEN \"crop_differs\" THEN '%s' "
    "WHEN \"map_crop_id\" IS NULL THEN '%s' "
    "ELSE '%s' END"
) % (CATEGORY_INCOMPLETE, CATEGORY_DIFFERS, CATEGORY_NO_MAP, CATEGORY_SAME)

CROP_AREA_FIELDS = [
    ("field_id", QVariant.String),
    ("crop_area_id", QVariant.String),
    ("parcel_id", QVariant.String),
    ("parcel_number", QVariant.String),
    ("farmer_crop_id", QVariant.String),
    ("map_crop_id", QVariant.String),
    ("crop_differs", QVariant.Bool),
    ("sowing_date", QVariant.Date),
    ("spray_count", QVariant.Int),
    ("last_spray_date", QVariant.Date),
    ("past_sprays", QVariant.String),
    ("data_issues", QVariant.String),
    ("data_status", QVariant.String),
]

PARCEL_FIELDS = [
    ("parcel_id", QVariant.String),
    ("parcel_number", QVariant.String),
    ("field_id", QVariant.String),
    ("data_status", QVariant.String),
]

DATE_FIELDS = {"sowing_date", "last_spray_date"}


def remove_farmer_layers():
    """Remove layers added by an earlier load so a reload does not stack copies."""
    project = QgsProject.instance()
    for layer_id, layer in list(project.mapLayers().items()):
        if layer.customProperty(LAYER_PROPERTY):
            project.removeMapLayer(layer_id)


def add_farmer_layers(farmer_data, source_label):
    """Create and add the layers. Returns (parcel_layer, crop_area_layer)."""
    remove_farmer_layers()
    mock = (farmer_data.data_status == "mock")
    suffix = " (MOCK)" if mock else ""
    status_text = farmer_data.data_status or "unlabelled"

    parcels = _build_layer(
        f"Farmer parcels{suffix}", PARCEL_FIELDS, farmer_data.parcels, source_label, status_text
    )
    areas = _build_layer(
        f"Farmer crop areas{suffix}", CROP_AREA_FIELDS, farmer_data.crop_areas, source_label, status_text
    )
    _style_parcels(parcels)
    _style_crop_areas(areas)

    project = QgsProject.instance()
    project.addMapLayer(parcels)   # outline below
    project.addMapLayer(areas)
    return parcels, areas


def _build_layer(name, fields, rows, source_label, status_text):
    layer = QgsVectorLayer("Polygon?crs=EPSG:4326", name, "memory")
    provider = layer.dataProvider()
    provider.addAttributes([QgsField(n, t) for n, t in fields])
    layer.updateFields()

    features = []
    for row in rows:
        geometry = QgsGeometry.fromWkt(geojson_to_wkt(row["geometry"]))
        if geometry.isNull() or geometry.isEmpty():
            continue
        feature = QgsFeature(layer.fields())
        feature.setGeometry(geometry)
        for field_name, _type in fields:
            value = row["attributes"].get(field_name)
            if field_name in DATE_FIELDS and value:
                value = QDate.fromString(value, Qt.ISODate)
            feature.setAttribute(field_name, value)
        features.append(feature)
    provider.addFeatures(features)
    layer.updateExtents()

    layer.setCustomProperty(LAYER_PROPERTY, True)
    layer.setAbstract(f"Source: {source_label}. data_status: {status_text}.")
    return layer


def _style_parcels(layer):
    symbol = QgsFillSymbol.createSimple({
        "style": "no",
        "outline_color": "#176544",
        "outline_width": "0.7",
        "outline_style": "dash",
    })
    layer.renderer().setSymbol(symbol)


def _style_crop_areas(layer):
    def symbol(color):
        return QgsFillSymbol.createSimple(
            {"color": color, "outline_color": "#333333", "outline_width": "0.4"}
        )

    categories = [
        QgsRendererCategory(CATEGORY_DIFFERS, symbol("#e9a23b"), CATEGORY_DIFFERS),
        QgsRendererCategory(CATEGORY_NO_MAP, symbol("#a9c7b4"), CATEGORY_NO_MAP),
        QgsRendererCategory(CATEGORY_SAME, symbol("#4f9a76"), CATEGORY_SAME),
        QgsRendererCategory(CATEGORY_INCOMPLETE, symbol("#d4dad6"), CATEGORY_INCOMPLETE),
    ]
    layer.setRenderer(QgsCategorizedSymbolRenderer(STYLE_EXPRESSION, categories))

    settings = QgsPalLayerSettings()
    settings.fieldName = "coalesce(\"farmer_crop_id\", '?') || ' ' || coalesce(to_string(\"sowing_date\"), 'no sowing date')"
    settings.isExpression = True
    layer.setLabeling(QgsVectorLayerSimpleLabeling(settings))
    layer.setLabelsEnabled(True)
