# -*- coding: utf-8 -*-
"""
QGIS layers for the read contract (issue #49): risk-coloured crop areas, the 4 km grid and
the day-by-day risk history of one crop area.

Colours follow docs/serve_read_contract.md: low green, medium amber, high red, any status
other than ``ok`` grey, ``uncertain`` shown as the class with a hatch. Call from the GUI
thread only (QgsTask.finished).
"""

from PyQt5.QtCore import QDate, QVariant, Qt
from PyQt5.QtGui import QColor
from qgis.core import (
    QgsCategorizedSymbolRenderer,
    QgsFeature,
    QgsField,
    QgsFillSymbol,
    QgsGeometry,
    QgsMarkerSymbol,
    QgsPalLayerSettings,
    QgsProject,
    QgsRendererCategory,
    QgsVectorLayer,
    QgsVectorLayerSimpleLabeling,
)

from .farmer_fields import geojson_to_wkt

LAYER_PROPERTY = "pyqgis_bridge/serve_layer"

COLORS = {"low": "#4f9a76", "medium": "#f0a830", "high": "#d73027", "none": "#bdbdbd"}
NOT_ASSESSED = "not assessed"
ABSTRACT_NOTE = "The risk class describes conditions favourable to the disease, never an instruction to spray."
SPRAY_NOTE = ("The spray window is an assessment of the weather, never an instruction or a consent to spray; "
              "the product, its label and its approval are not checked.")

# Spray window statuses (GET /me/spray-window): blue shades are used so they are not read as the disease risk colours.
SPRAY_STATUSES = [
    ("window_now", "#1f78b4", "window now (good weather starts now)", False),
    ("window_later", "#74add1", "window later (within 72 h)", False),
    ("no_window", "#8c6bb1", "no window in the next 72 h", False),
    ("no_forecast", "#d9d9d9", "no forecast for the hours", True),
    ("no_signal", "#bdbdbd", "no signal (no window proposed)", False),
]

_QTYPES = {
    "text": QVariant.String, "date": QVariant.Date, "int": QVariant.Int,
    "real": QVariant.Double, "bool": QVariant.Bool,
}

# One category per class; the (uncertain) variants carry a hatch; any other status is grey.
CROP_AREA_EXPRESSION = (
    "CASE "
    "WHEN \"status\" = 'ok' AND \"risk_class\" IS NOT NULL THEN \"risk_class\" "
    "WHEN \"status\" = 'uncertain' AND \"risk_class\" IS NOT NULL THEN \"risk_class\" || ' (uncertain)' "
    "ELSE '%s' END" % NOT_ASSESSED
)
GRID_EXPRESSION = (
    "CASE WHEN \"risk_class\" IS NULL THEN '%s' "
    "WHEN \"uncertain\" THEN \"risk_class\" || ' (uncertain)' ELSE \"risk_class\" END" % NOT_ASSESSED
)
CROP_AREA_LABEL = (
    "coalesce(\"field_name\", \"crop_area_id\") || '\\n' || "
    "CASE WHEN \"status\" IN ('ok', 'uncertain') THEN coalesce(\"risk_class\", '') "
    "ELSE coalesce(\"status\", 'no assessment today') END"
)


def remove_serve_layers(kind):
    project = QgsProject.instance()
    for layer_id, layer in list(project.mapLayers().items()):
        if layer.customProperty(LAYER_PROPERTY) == kind:
            project.removeMapLayer(layer_id)


def add_crop_area_layer(data, source_label):
    remove_serve_layers("crop_areas")
    layer = _build(data, "MultiPolygon", source_label, _title("Crop areas - septoria assessment", data))
    categories = []
    for cls in ("high", "medium", "low"):
        categories.append(QgsRendererCategory(cls, _fill(COLORS[cls]), cls))
    for cls in ("high", "medium", "low"):
        categories.append(
            QgsRendererCategory(f"{cls} (uncertain)", _fill(COLORS[cls], hatch=True), f"{cls} (uncertain)")
        )
    categories.append(QgsRendererCategory(NOT_ASSESSED, _fill(COLORS["none"]), f"{NOT_ASSESSED} (other status)"))
    layer.setRenderer(QgsCategorizedSymbolRenderer(CROP_AREA_EXPRESSION, categories))

    settings = QgsPalLayerSettings()
    settings.fieldName = CROP_AREA_LABEL
    settings.isExpression = True
    layer.setLabeling(QgsVectorLayerSimpleLabeling(settings))
    layer.setLabelsEnabled(True)
    QgsProject.instance().addMapLayer(layer)
    return layer


def add_spray_window_layer(data, source_label):
    """Crop areas coloured by the spray window status now; the best window is in the attribute table."""
    remove_serve_layers("spray_window")
    when = f" {data.assessed_at[:16].replace('T', ' ')}" if data.assessed_at else ""
    mock = " (MOCK)" if data.data_status == "mock" else ""
    layer = _build(data, "MultiPolygon", source_label, f"Spray window (weather assessment){when}{mock}")
    categories = []
    for status, color, label, hatch in SPRAY_STATUSES:
        categories.append(QgsRendererCategory(status, _fill(color, hatch=hatch), label))
    layer.setRenderer(QgsCategorizedSymbolRenderer("spray_window_status", categories))
    layer.setAbstract(f"Source: {source_label}. {SPRAY_NOTE}")
    layer.setLabelsEnabled(False)       # no labels: they make the map unreadable (the details are in the table)
    QgsProject.instance().addMapLayer(layer)
    return layer


def add_grid_layer(data, source_label, surface_path=None, cells=True):
    """Layers of the voivodeship grid: the heatmap of the API and the 4 km cells with the values.

    The heatmap is the ESRI ASCII Grid of GET /grid/risk/surface?format=asc&value=hours (EPSG:4326):
    each pixel is the longest wet run H in the last 72 h, interpolated by the API between the cell
    centres. It is coloured by hours with the thresholds as landmarks (10 h medium, 20 h high). It is a
    view of the same number as the classes, not a new assessment. The cells (Polygon, as the API sends
    them) carry the classes and stay for Identify and the attribute table; they are shown when there
    is no heatmap (a file, or the surface could not be read).
    """
    remove_serve_layers("grid")
    project = QgsProject.instance()
    root = project.layerTreeRoot()
    title = _title("Septoria weather conditions (4 km grid)", data)

    if data.geometry_type == "Point":            # early mock files: cell centres only
        points = _build(data, "Point", source_label, title + " - cells")
        categories = [QgsRendererCategory(cls, _marker(COLORS[cls]), cls) for cls in ("high", "medium", "low")]
        categories.append(QgsRendererCategory(NOT_ASSESSED, _marker(COLORS["none"]), NOT_ASSESSED))
        points.setRenderer(QgsCategorizedSymbolRenderer(GRID_EXPRESSION, categories))
        project.addMapLayer(points, False)
        root.insertLayer(len(root.children()), points)
        return points

    cells_layer = _build(data, "Polygon", source_label, title + " - cells")
    categories = []
    for cls in ("high", "medium", "low"):
        categories.append(QgsRendererCategory(cls, _cell(COLORS[cls]), cls))
    for cls in ("high", "medium", "low"):
        categories.append(
            QgsRendererCategory(f"{cls} (uncertain)", _cell(COLORS[cls], hatch=True), f"{cls} (uncertain)")
        )
    categories.append(QgsRendererCategory(NOT_ASSESSED, _cell(COLORS["none"]), NOT_ASSESSED))
    cells_layer.setRenderer(QgsCategorizedSymbolRenderer(GRID_EXPRESSION, categories))

    surface_layer = None
    if surface_path:
        surface_layer = _surface_layer(surface_path, title + " - heatmap, wet hours H", source_label)
    show_cells = cells or surface_layer is None
    if show_cells:
        project.addMapLayer(cells_layer, False)
        node = root.insertLayer(len(root.children()), cells_layer)
        node.setItemVisibilityChecked(surface_layer is None)
    if surface_layer is not None:
        project.addMapLayer(surface_layer, False)
        root.insertLayer(len(root.children()) - (1 if show_cells else 0), surface_layer)
        return surface_layer
    return cells_layer


# The thresholds are the landmarks of the colour ramp (config/septoria.toml of the backend).
HOURS_MEDIUM = 10.0
HOURS_HIGH = 20.0
HOURS_MAX = 24.0        # the ramp stops here; longer wet runs keep the colour of high


def _surface_layer(path, name, source_label):
    """The ASC of GET /grid/risk/surface as a raster layer: EPSG:4326, coloured by hours."""
    from qgis.core import (
        QgsBilinearRasterResampler, QgsColorRampShader, QgsCoordinateReferenceSystem, QgsRasterLayer,
        QgsRasterShader, QgsSingleBandPseudoColorRenderer,
    )
    layer = QgsRasterLayer(path, name, "gdal")
    if not layer.isValid():
        raise RuntimeError("the heatmap file is not a valid raster")
    layer.setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))       # an ASC has no CRS of its own

    shader = QgsColorRampShader(0.0, HOURS_MAX)
    shader.setColorRampType(QgsColorRampShader.Interpolated)
    shader.setColorRampItemList([
        QgsColorRampShader.ColorRampItem(0.0, QColor(COLORS["low"]), "0 h"),
        QgsColorRampShader.ColorRampItem(HOURS_MEDIUM, QColor(COLORS["medium"]), f"{HOURS_MEDIUM:g} h (medium)"),
        QgsColorRampShader.ColorRampItem(HOURS_HIGH, QColor(COLORS["high"]), f"{HOURS_HIGH:g} h and more (high)"),
    ])
    raster_shader = QgsRasterShader()
    raster_shader.setRasterShaderFunction(shader)
    renderer = QgsSingleBandPseudoColorRenderer(layer.dataProvider(), 1, raster_shader)
    renderer.setClassificationMin(0.0)
    renderer.setClassificationMax(HOURS_MAX)
    layer.setRenderer(renderer)
    layer.resampleFilter().setZoomedInResampler(QgsBilinearRasterResampler())
    layer.resampleFilter().setZoomedOutResampler(QgsBilinearRasterResampler())
    layer.renderer().setOpacity(0.8)
    layer.setCustomProperty(LAYER_PROPERTY, "grid")
    layer.setAbstract(
        f"Source: {source_label}. Hours of continuous leaf wetness in the last 72 h (H), interpolated by the "
        f"API between the 4 km cell centres; amber from {HOURS_MEDIUM:g} h, red from {HOURS_HIGH:g} h. "
        "A pixel is an estimate between two cells, not a new assessment; the exact classes are in the cells layer. "
        + ABSTRACT_NOTE
    )
    return layer


def add_history_table(crop_area_id, rows, fields, source_label):
    """Table layer (no geometry): one row per day of GET /crop-areas/{id}/risk."""
    kind = f"history:{crop_area_id}"
    remove_serve_layers(kind)
    layer = QgsVectorLayer("None", f"Risk history - {crop_area_id}", "memory")
    provider = layer.dataProvider()
    provider.addAttributes([QgsField(n, _QTYPES[k]) for n, k in fields])
    layer.updateFields()
    features = []
    for attributes in rows:
        feature = QgsFeature(layer.fields())
        for name, kind_name in fields:
            feature.setAttribute(name, _value(attributes.get(name), kind_name))
        features.append(feature)
    provider.addFeatures(features)
    layer.setCustomProperty(LAYER_PROPERTY, kind)
    layer.setAbstract(f"Source: {source_label}. {ABSTRACT_NOTE}")
    QgsProject.instance().addMapLayer(layer)
    return layer


def _title(base, data):
    dates = sorted(data.dates)
    when = f" {dates[0]}" if len(dates) == 1 else (f" {dates[0]}..{dates[-1]}" if dates else "")
    mock = " (MOCK)" if data.data_status == "mock" else ""
    return f"{base}{when}{mock}"


def _fill(color, hatch=False):
    props = {"color": color, "outline_color": "#333333", "outline_width": "0.4"}
    if hatch:
        props.update({"style": "b_diagonal", "color": "#222222", "outline_color": color, "outline_width": "0.8"})
    return QgsFillSymbol.createSimple(props)


def _cell(color, hatch=False):
    """Grid cell: flat fill with a thin outline so 2,400 squares stay readable."""
    props = {"color": color, "outline_color": "#ffffff", "outline_width": "0.1"}
    if hatch:
        props.update({"style": "b_diagonal", "color": color, "outline_color": color, "outline_width": "0.3"})
    return QgsFillSymbol.createSimple(props)


def _marker(color, ring=False):
    props = {"name": "circle", "size": "3.2", "color": color, "outline_color": "#333333", "outline_width": "0.3"}
    if ring:
        props.update({"color": "#ffffff", "outline_color": color, "outline_width": "0.9"})
    return QgsMarkerSymbol.createSimple(props)


def _value(value, kind):
    if kind == "date" and value:
        return QDate.fromString(value[:10], Qt.ISODate)
    return value


def _build(data, geometry_type, source_label, name, centroids=False):
    layer = QgsVectorLayer(f"{geometry_type}?crs=EPSG:4326", name, "memory")
    provider = layer.dataProvider()
    provider.addAttributes([QgsField(n, _QTYPES[k]) for n, k in data.fields])
    layer.updateFields()

    features = []
    for row in data.rows:
        geometry = _geometry(row["geometry"])
        if geometry.isNull() or geometry.isEmpty():
            continue
        if centroids and geometry.type() != 0:      # 0 = point
            geometry = geometry.centroid()
        if geometry_type.startswith("Multi"):
            geometry.convertToMultiType()
        feature = QgsFeature(layer.fields())
        feature.setGeometry(geometry)
        for name_, kind in data.fields:
            feature.setAttribute(name_, _value(row["attributes"].get(name_), kind))
        features.append(feature)
    provider.addFeatures(features)
    layer.updateExtents()

    layer.setCustomProperty(LAYER_PROPERTY, data.kind)
    layer.setAbstract(
        f"Source: {source_label}. data_status: {data.data_status or 'not given'}. {ABSTRACT_NOTE}"
    )
    return layer


def _geometry(geojson):
    if geojson["type"] == "Point":
        x, y = geojson["coordinates"][:2]
        return QgsGeometry.fromWkt(f"POINT({x} {y})")
    return QgsGeometry.fromWkt(geojson_to_wkt(geojson))
