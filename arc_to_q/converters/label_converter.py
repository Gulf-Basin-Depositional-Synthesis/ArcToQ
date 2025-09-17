import re

from qgis.core import (
    QgsVectorLayer,
    QgsPalLayerSettings,
    QgsTextFormat,
    QgsTextBufferSettings,
    QgsVectorLayerSimpleLabeling,
    QgsRuleBasedLabeling,
    QgsUnitTypes
)
from PyQt5.QtGui import QFont, QColor

from arc_to_q.converters.utils import parse_color

def _vb_to_qgis(vb_expr: str) -> str:
    """Converts VBScript/ArcGIS label expressions to QGIS syntax."""
    expr = vb_expr.strip()
    expr = re.sub(r"(?i)Function\s+FindLabel\s*\(.*?\)", "", expr)
    expr = re.sub(r"(?i)End Function", "", expr)
    expr = expr.strip()
    expr = re.sub(r'"([^"]*)"', r"'\1'", expr)
    expr = re.sub(r"\[([A-Za-z0-9_]+)\]", r'"\1"', expr)
    expr = expr.replace("&", "||").replace("+", "||")
    # Add more complex regex for If/Case statements if needed
    return expr.strip()

def _parse_expression(expression: str, engine: str) -> (str, bool):
    """Converts an ArcGIS label expression to a QGIS expression."""
    expression = expression.strip()
    is_expression = not (expression.startswith('[') and expression.endswith(']') and expression.count('[') == 1)

    if engine == "Arcade":
        expression = expression.replace("$feature.", "")
        qgis_expr = re.sub(r"(\w+)", r'"\1"', expression)
        return qgis_expr, True
    elif engine == "VBScript":
        return _vb_to_qgis(expression), True
    
    return expression.replace("[", "\"").replace("]", "\""), is_expression

def _make_label_settings(label_class: dict) -> QgsPalLayerSettings:
    """Creates a QgsPalLayerSettings object from an ArcGIS label class definition."""
    expression, is_expression = _parse_expression(
        label_class.get("expression", ""),
        label_class.get("expressionEngine", "Arcade")
    )
    
    text_symbol_ref = label_class.get("textSymbol", {})
    text_symbol = text_symbol_ref.get("symbol", {})
    placement_props = label_class.get("maplexLabelPlacementProperties", {})

    settings = QgsPalLayerSettings()
    settings.fieldName = expression
    settings.isExpression = is_expression
    settings.enabled = True

    # Text Format
    text_format = QgsTextFormat()
    font = QFont(text_symbol.get("fontFamilyName", "Arial"))
    font_size = text_symbol.get("height", 8)
    font.setPointSize(font_size)
    if "Bold" in text_symbol.get("fontStyleName", ""):
        font.setBold(True)
    text_format.setFont(font)
    text_format.setSize(font_size)
    text_format.setSizeUnit(QgsUnitTypes.RenderPoints)
    
    if "symbol" in text_symbol and "symbolLayers" in text_symbol["symbol"]:
        if cim_color := text_symbol["symbol"]["symbolLayers"][0].get("color"):
            text_format.setColor(parse_color(cim_color))

    if halo_size := text_symbol.get("haloSize", 0) > 0:
        buffer_settings = QgsTextBufferSettings()
        buffer_settings.setEnabled(True)
        buffer_settings.setSize(halo_size)
        buffer_settings.setColor(QColor("white")) # Default halo color
        text_format.setBuffer(buffer_settings)

    settings.setFormat(text_format)

    # Placement
    if feature_type := placement_props.get("featureType"):
        if feature_type == "Line":
            settings.placement = QgsPalLayerSettings.Curved
        elif feature_type == "Polygon":
            settings.placement = QgsPalLayerSettings.Horizontal
        else: # Point
            settings.placement = QgsPalLayerSettings.AroundPoint
            
    return settings


def set_labels(layer: QgsVectorLayer, layer_def: dict):
    """Configures and applies labeling to a QGIS layer."""
    label_classes = layer_def.get("labelClasses", [])
    if not label_classes:
        return

    if len(label_classes) > 1:
        root_rule = QgsRuleBasedLabeling.Rule(QgsPalLayerSettings())
        for lc in label_classes:
            settings = _make_label_settings(lc)
            rule = QgsRuleBasedLabeling.Rule(settings)
            if where_clause := lc.get("whereClause"):
                rule.setFilterExpression(where_clause.replace("[", "\"").replace("]", "\""))
            rule.setActive(lc.get("visibility", True))
            root_rule.appendChild(rule)
        labeling = QgsRuleBasedLabeling(root_rule)
        layer.setLabeling(labeling)
    else:
        settings = _make_label_settings(label_classes[0])
        layer.setLabeling(QgsVectorLayerSimpleLabeling(settings))

    layer.setLabelsEnabled(layer_def.get("labelVisibility", False))