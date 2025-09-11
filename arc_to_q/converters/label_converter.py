from qgis.core import (
    QgsVectorLayer,
    QgsPalLayerSettings,
    QgsTextFormat,
    QgsTextBufferSettings,
    QgsVectorLayerSimpleLabeling,
    QgsTextRenderer,
    QgsRuleBasedLabeling,
    QgsProperty
)
from PyQt5.QtGui import QFont

from arc_to_q.converters.utils import parse_color


def _parse_vbscript_expression(expression: str) -> str:
    """Convert a simple VBScript expression to QGIS expression.
    
    E.g., [Transect_Name] to Transect_Name
    
    Args:
        expression (str): The VBScript expression from ArcGIS Pro.

    Returns:
        str: The converted expression for QGIS.
    """
    # Remove brackets used in VBScript for field names
    expression = expression.replace("[", "").replace("]", "")
    # If "." in expression, it might be a table.field reference; remove table prefix
    if "." in expression:
        expression = expression.split(".")[-1]
    return expression


def _parse_arcade_expression(expression: str) -> str:
    """Convert a simple Arcade expression to QGIS expression.
    
    Examples:
        $feature.CommonName
        $feature['CommonName']
    
    Args:
        expression (str): The Arcade expression from ArcGIS Pro.

    Returns:
        str: The converted expression for QGIS.
    """
    # Remove $feature['field'] prefix used in Arcade for field names
    if expression.startswith("$feature['") and expression.endswith("']"):
        expression = expression[len("$feature['"):-len("']")]
    elif expression.startswith("$feature."):
        expression = expression[len("$feature."):]

    return expression


def _parse_expression(expression: str, express_engine: str) -> str:
    """Convert ArcGIS label expression to QGIS expression.
    
    Args:
        expression (str): The label expression from ArcGIS Pro.
        express_engine (str): The expression engine used (e.g., "Arcade", "VBScript", "Python").

    Returns:
        str: The converted expression for QGIS.
    """
    expression = expression.strip()

    if express_engine == "Arcade":
        return _parse_arcade_expression(expression)
    elif express_engine == "VBScript":
        return _parse_vbscript_expression(expression)
    else:
        # Default behavior: remove ArcGIS-specific characters
        return expression.replace("[", "").replace("]", "")


def _color_from_symbol_layers(symbol_layers):
    # Loop until we find a layer with type=CIMSolidFill
    for layer in symbol_layers:
        if layer.get("type") == "CIMSolidFill":
            color = layer.get("color", {})
            return parse_color(color)

    return parse_color(None)


def _make_label_settings(label_class: dict) -> QgsPalLayerSettings:
    expression = _parse_expression(label_class.get("expression", ""), label_class.get("expressionEngine", "Arcade"))
    text_symbol = label_class.get("textSymbol", {}).get("symbol", {})
    placement_props = label_class.get("maplexLabelPlacementProperties", {})
    underline = text_symbol.get("underline", False)
    strikeout = text_symbol.get("strikethrough", False)

    # --- Text Format ---
    text_format = QgsTextFormat()

    # Font
    font = QFont()
    font.setFamily(text_symbol.get("fontFamilyName", "Arial"))
    font.setPointSize(text_symbol.get("height", 8))

    # Font style
    font_style = text_symbol.get("fontStyleName", "").lower()
    if "bold" in font_style:
        font.setBold(True)
    if "italic" in font_style:
        font.setItalic(True)
    if underline:
        font.setUnderline(True)
    if strikeout:
        font.setStrikeOut(True)

    # Apply font to text format
    text_format.setFont(font)
    text_format.setSize(text_symbol.get("height", 8))

    # Text color
    color = _color_from_symbol_layers(text_symbol["symbol"]["symbolLayers"])
    text_format.setColor(color)

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
    can_overrun_feature = placement_props.get("canOverrunFeature", True)

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
            labeling.placement = QgsPalLayerSettings.Placement.Horizontal
        else:
            labeling.placement = QgsPalLayerSettings.FreePolygon

    elif feature_type == "Line":
        if line_method == "OffsetCurvedFromLine":
            labeling.placement = QgsPalLayerSettings.Curved
        elif line_method == "OffsetStraightFromLine":
            labeling.placement = QgsPalLayerSettings.Parallel
        elif line_method == "CenteredStraightOnLine":
            labeling.placement = QgsPalLayerSettings.Line
            labeling.placementFlags = QgsPalLayerSettings.OnLine | QgsPalLayerSettings.MapOrientation
        else:
            labeling.placement = QgsPalLayerSettings.Line

    if not can_overrun_feature:
        labeling.priority = 4

    return labeling


def _parse_where_clause(where: str) -> str:
    """Convert ArcGIS where clause to QGIS expression.
    
    Example:
    "\"WellData_GeoSetting\" NOT in (1,2)"
    to
    "\"WellData_GeoSetting\" NOT IN (1,2)"
    """
    return where


def set_labels(layer: QgsVectorLayer, layer_def: dict):
    label_classes = layer_def.get("labelClasses", [])
    layer_name = layer_def.get('name', 'Unknown Layer')

    if not label_classes:
        print(f"No label classes found for layer: {layer_name}")
        return

    if len(label_classes) > 1:
        root_rule = QgsRuleBasedLabeling.Rule(QgsPalLayerSettings())
        for label_class in label_classes:
            where = _parse_where_clause(label_class.get("whereClause", ""))
            labeling = _make_label_settings(label_class)
            rule = QgsRuleBasedLabeling.Rule(labeling)
            if where:
                rule.setFilterExpression(where)
            visibility = label_class.get("visibility", False)
            rule.setActive(visibility)
            root_rule.appendChild(rule)

        labeling = QgsRuleBasedLabeling(root_rule)
        layer.setLabeling(labeling)
    else:
        labeling = _make_label_settings(label_classes[0])
        layer.setLabeling(QgsVectorLayerSimpleLabeling(labeling))

    visibility = layer_def.get("labelVisibility", False)
    layer.setLabelsEnabled(visibility)

