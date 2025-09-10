from qgis.core import (
    QgsVectorLayer,
    QgsPalLayerSettings,
    QgsTextFormat,
    QgsTextBufferSettings,
    QgsVectorLayerSimpleLabeling,
    QgsTextRenderer,
    QgsProperty
)
from PyQt5.QtGui import QFont

from arc_to_q.converters.utils import parse_color


def _parse_expression(expression: str) -> str:
    """Convert ArcGIS label expression to QGIS expression.
    
    Args:
        expression (str): The label expression from ArcGIS Pro.

    Returns:
        str: The converted expression for QGIS.
    """
    if " " in expression:
        raise Exception(f"Complex label expressions with spaces are not supported: {expression}")
    # Remove ArcGIS characters that QGIS does not use
    expression = expression.replace("[", "").replace("]", "")
    return expression


def set_labels(layer: QgsVectorLayer, layer_def: dict):
    label_classes = layer_def.get("labelClasses", [])
    layer_name = layer_def.get('name', 'Unknown Layer')

    if not label_classes:
        print(f"No label classes found for layer: {layer_name}")
        return

    if len(label_classes) > 1:
        raise Exception(f"Multiple label classes found for layer: {layer_name}. Only one is supported.")

    label_class = label_classes[0]
    expression = _parse_expression(label_class.get("expression", ""))
    text_symbol = label_class.get("textSymbol", {}).get("symbol", {})
    placement_props = label_class.get("maplexLabelPlacementProperties", {})

    # --- Text Format ---
    text_format = QgsTextFormat()

    # Font
    font = QFont()
    font.setFamily(text_symbol.get("fontFamilyName", "Arial"))
    font.setPointSize(text_symbol.get("height", 8))
    text_format.setFont(font)

    # Text color
    cim_color = text_symbol["symbol"]["symbolLayers"][0]["color"]
    text_format.setColor(parse_color(cim_color))

    # todo: # Halo / buffer
    # halo_size = text_symbol.get("haloSize")
    # if halo_size and halo_size > 0:
    #     buffer_settings = QgsTextBufferSettings()
    #     buffer_settings.setEnabled(True)
    #     buffer_settings.setSize(halo_size)
    #     buffer_color = text_symbol.get("shadowColor", {}).get("values")
    #     if buffer_color and len(buffer_color) >= 3:
    #         buffer_settings.setColor(QgsTextRenderer.colorFromRgb(*buffer_color[:3]))
    #     text_format.setBuffer(buffer_settings)

    # --- Label Settings ---
    labeling = QgsPalLayerSettings()
    labeling.fieldName = expression
    labeling.setFormat(text_format)
    labeling.enabled = True

    # --- Placement ---
    feature_type = placement_props.get("featureType")
    point_method = placement_props.get("pointPlacementMethod")
    polygon_method = placement_props.get("polygonPlacementMethod")
    line_method = placement_props.get("linePlacementMethod")

    if feature_type == "Point":
        if point_method == "AroundPoint":
            labeling.placement = QgsPalLayerSettings.AroundPoint
        elif point_method == "OnTopPoint":
            labeling.placement = QgsPalLayerSettings.OverPoint
        else:
            labeling.placement = QgsPalLayerSettings.AroundPoint  # default fallback

    elif feature_type == "Polygon":
        if polygon_method == "CurvedInPolygon":
            labeling.placement = QgsPalLayerSettings.CurvedPolygon
        elif polygon_method == "HorizontalInPolygon":
            labeling.placement = QgsPalLayerSettings.HorizontalPolygon
        else:
            labeling.placement = QgsPalLayerSettings.FreePolygon

    elif feature_type == "Line":
        if line_method == "OffsetCurvedFromLine":
            labeling.placement = QgsPalLayerSettings.Curved
        elif line_method == "OffsetStraightFromLine":
            labeling.placement = QgsPalLayerSettings.Parallel
        else:
            labeling.placement = QgsPalLayerSettings.Line

    # Apply labeling
    layer.setLabeling(QgsVectorLayerSimpleLabeling(labeling))
    visibility = layer_def.get("labelVisibility", False)
    layer.setLabelsEnabled(visibility)

