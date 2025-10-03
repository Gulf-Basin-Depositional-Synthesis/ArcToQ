import re

from qgis.core import (
    QgsVectorLayer,
    QgsPalLayerSettings,
    QgsTextFormat,
    QgsTextBufferSettings,
    QgsVectorLayerSimpleLabeling,
    QgsTextRenderer,
    QgsRuleBasedLabeling,
    QgsProperty,
    QgsUnitTypes
)
from PyQt5.QtGui import QFont

from arc_to_q.converters.utils import parse_color
from arc_to_q.converters.label_vbscript_converter import convert_label_expression
from arc_to_q.converters.label_domain_converter import domain_to_case_expression


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
        tuple: (converted expression for QGIS, is_expression flag)
    """
    expression = expression.strip()
    is_expression = False

    if express_engine == "Arcade":
        return _parse_arcade_expression(expression), is_expression
    elif express_engine == "VBScript":
        return convert_label_expression(expression)
    else:
        # Default behavior: remove ArcGIS-specific characters
        return expression.replace("[", "").replace("]", ""), is_expression


def _color_from_symbol_layers(symbol_layers):
    # Loop until we find a layer with type=CIMSolidFill
    for layer in symbol_layers:
        if layer.get("type") == "CIMSolidFill":
            color = layer.get("color", {})
            return parse_color(color)

    return parse_color(None)


def _make_label_settings(layer: QgsVectorLayer, label_class: dict, layer_def: dict) -> QgsPalLayerSettings:
    expression, is_expression = _parse_expression(label_class.get("expression", ""), label_class.get("expressionEngine", "Arcade"))
    text_symbol = label_class.get("textSymbol", {}).get("symbol", {})
    placement_props = label_class.get("maplexLabelPlacementProperties", {})
    underline = text_symbol.get("underline", False)
    strikeout = text_symbol.get("strikethrough", False)

    # --- Check for coded value domain ---!!!
    if label_class.get("useCodedValue", False) and not is_expression:
        domain_expression = domain_to_case_expression(layer, expression)
        if domain_expression:
            expression = domain_expression
            is_expression = True

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


    # --- Halo ---
    def _get_halo_size():
        hs = text_symbol.get("haloSize", None)
        try:
            return float(hs) if hs is not None else None
        except Exception:
            return None

    halo_size = _get_halo_size()
    halo_symbol = text_symbol.get("haloSymbol", None)
    halo_layers = halo_symbol.get("symbolLayers", []) if halo_symbol else []
    halo_present = (halo_layers) and (halo_size is not None and halo_size > 0)

    if halo_present:
        buffer_settings = QgsTextBufferSettings()
        buffer_settings.setEnabled(True)
        halo_color = _color_from_symbol_layers(halo_layers)
        buffer_settings.setColor(halo_color)
        buffer_settings.setSize(halo_size)
        text_format.setBuffer(buffer_settings)

    # --- Label Settings ---
    labeling = QgsPalLayerSettings()
    labeling.fieldName = expression
    labeling.isExpression = is_expression
    labeling.setFormat(text_format)
    labeling.enabled = True

    # --- Scale dependent rendering ---
    min_scale = label_class.get("minimumScale")
    max_scale = label_class.get("maximumScale")
    if min_scale is not None:
        labeling.minimumScale = float(min_scale)
    if max_scale is not None:
        labeling.maximumScale = float(max_scale)
    if min_scale is not None or max_scale is not None:
        labeling.scaleVisibility = True

    # --- Placement ---
    feature_type = placement_props.get("featureType")
    point_method = placement_props.get("pointPlacementMethod")
    polygon_method = placement_props.get("polygonPlacementMethod")
    line_method = placement_props.get("linePlacementMethod")
    can_overrun_feature = placement_props.get("canOverrunFeature", True)

    if feature_type == "Point":
        if point_method == "AroundPoint":
            labeling.placement = QgsPalLayerSettings.Placement.AroundPoint
        elif point_method == "CenteredOnPoint":
            labeling.placement = QgsPalLayerSettings.Placement.OverPoint
        elif "OfPoint" in point_method:
            labeling.placement = QgsPalLayerSettings.Placement.OverPoint
            offset = placement_props.get("offsetFromPoint", 1)
            offset_unit = placement_props.get("primaryOffsetUnit", "Point")
            unit_map = {
                "Point": QgsUnitTypes.RenderPoints,
                "Map": QgsUnitTypes.RenderMapUnits,
                "MM": QgsUnitTypes.RenderMillimeters,
                "Inch": QgsUnitTypes.RenderInches,
                "Pixel": QgsUnitTypes.RenderPixels,
            }            
            labeling.offsetUnits = unit_map.get(offset_unit, QgsUnitTypes.RenderPoints)
            dx = float(offset)
            dy = float(offset)
            if point_method == "EastOfPoint":
                labeling.quadOffset = QgsPalLayerSettings.QuadrantPosition.Right
                dy = 0
            elif point_method == "WestOfPoint":
                labeling.quadOffset = QgsPalLayerSettings.QuadrantPosition.Left
                dy = 0
                dx = -dx
            elif point_method == "NorthOfPoint":
                labeling.quadOffset = QgsPalLayerSettings.QuadrantPosition.Above
                dx = 0
                dy = -dy
            elif point_method == "SouthOfPoint":
                labeling.quadOffset = QgsPalLayerSettings.QuadrantPosition.Below
                dx = 0
            elif point_method == "NorthEastOfPoint":
                labeling.quadOffset = QgsPalLayerSettings.QuadrantPosition.AboveRight
                dy = -dy
            elif point_method == "NorthWestOfPoint":
                labeling.quadOffset = QgsPalLayerSettings.QuadrantPosition.AboveLeft
                dx = -dx
                dy = -dy
            elif point_method == "SouthEastOfPoint":
                labeling.quadOffset = QgsPalLayerSettings.QuadrantPosition.BelowRight
            elif point_method == "SouthWestOfPoint":
                labeling.quadOffset = QgsPalLayerSettings.QuadrantPosition.BelowLeft
                dx = -dx
            labeling.xOffset = dx
            labeling.yOffset = dy

        else:
            labeling.placement = QgsPalLayerSettings.Placement.AroundPoint  # default fallback

    elif feature_type == "Polygon":
        if polygon_method == "CurvedInPolygon":
            labeling.placement = QgsPalLayerSettings.Placement.Free
        elif polygon_method == "HorizontalInPolygon":
            labeling.placement = QgsPalLayerSettings.Placement.Horizontal
        else:
            labeling.placement = QgsPalLayerSettings.Placement.Horizontal

    elif feature_type == "Line":
        if line_method == "OffsetCurvedFromLine":
            labeling.placement = QgsPalLayerSettings.Placement.Curved
        elif line_method == "OffsetStraightFromLine":
            labeling.placement = QgsPalLayerSettings.Placement.Line
        elif line_method == "CenteredStraightOnLine":
            labeling.placement = QgsPalLayerSettings.Placement.Line
            labeling.placementFlags = QgsPalLayerSettings.OnLine | QgsPalLayerSettings.MapOrientation
        else:
            labeling.placement = QgsPalLayerSettings.Placement.Line

    if not can_overrun_feature:
        labeling.priority = 4  # E.g., keeps labels within polygon boundaries

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
            labeling = _make_label_settings(layer, label_class, layer_def)
            rule = QgsRuleBasedLabeling.Rule(labeling)
            if where:
                rule.setFilterExpression(where)
            visibility = label_class.get("visibility", False)
            rule.setActive(visibility)
            root_rule.appendChild(rule)

        labeling = QgsRuleBasedLabeling(root_rule)
        layer.setLabeling(labeling)
    else:
        labeling = _make_label_settings(layer, label_classes[0], layer_def)
        layer.setLabeling(QgsVectorLayerSimpleLabeling(labeling))

    visibility = layer_def.get("labelVisibility", False)
    layer.setLabelsEnabled(visibility)
