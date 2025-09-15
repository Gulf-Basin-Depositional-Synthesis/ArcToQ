from qgis.core import (
    QgsVectorLayer,
    QgsPalLayerSettings,
    QgsTextFormat,
    QgsTextBufferSettings,
    QgsVectorLayerSimpleLabeling,
    QgsTextRenderer,
    QgsProperty,
    QgsUnitTypes
)
from PyQt5.QtGui import QFont, QColor
import re

from arc_to_q.converters.utils import parse_color


def _is_simple_field_expression(expression: str) -> bool:
    """
    Determines if an ArcGIS label expression is a simple field reference.
    e.g., "[FIELD_NAME]" or "[FIELD_NAME] "
    """
    expression = expression.strip()
    # A simple expression should contain exactly one opening and one closing bracket
    return expression.startswith('[') and expression.endswith(']') and expression.count('[') == 1


def set_labels(layer: QgsVectorLayer, layer_def: dict):
    """
    Configures and applies labeling settings to a QGIS layer based on an ArcGIS Pro layer definition.
    """
    label_classes = layer_def.get("labelClasses", [])
    layer_name = layer_def.get('name', 'Unknown Layer')

    if not label_classes:
        print(f"No label classes found for layer: {layer_name}")
        return

    if len(label_classes) > 1:
        # QGIS simple labeling supports only one class. For rule-based, this would need to be different.
        print(f"Warning: Multiple label classes found for layer '{layer_name}'. Only the first will be used.")

    label_class = label_classes[0]
    arc_expression = label_class.get("expression", "")
    
    # Correctly reference the nested symbol definition
    text_symbol_ref = label_class.get("textSymbol", {})
    text_symbol = text_symbol_ref.get("symbol", {})
    
    placement_props = label_class.get("maplexLabelPlacementProperties", {})

    # --- Label Settings (QgsPalLayerSettings) ---
    labeling = QgsPalLayerSettings()

    # 1. Expression vs. FieldName Logic
    if _is_simple_field_expression(arc_expression):
        # It's a simple field. Set fieldName without brackets/quotes.
        labeling.fieldName = arc_expression.strip().strip('[]')
        labeling.isExpression = False
    else:
        # It's a complex expression. Translate and set the isExpression flag.
        # A more robust Arcade->QGIS translator would go here.
        # For now, we'll do basic replacement.
        qgis_expression = arc_expression.replace("[", "\"").replace("]", "\"")
        labeling.fieldName = qgis_expression
        labeling.isExpression = True

    # --- Text Format (QgsTextFormat) ---
    text_format = QgsTextFormat()

    # Font
    font = QFont()
    font.setFamily(text_symbol.get("fontFamilyName", "Arial"))
    font_size = text_symbol.get("height", 8)
    font.setPointSize(font_size)
    
    if text_symbol.get("fontStyleName") == "Bold":
        font.setBold(True)
    
    text_format.setFont(font)
    text_format.setSize(font_size) # Explicitly set size in text_format
    text_format.setSizeUnit(QgsUnitTypes.RenderPoints) # Explicitly set unit

    # Text color
    if "symbol" in text_symbol and "symbolLayers" in text_symbol["symbol"]:
        cim_color = text_symbol["symbol"]["symbolLayers"][0].get("color")
        if cim_color:
            text_format.setColor(parse_color(cim_color))

    # Buffer (Halo)
    halo_size = text_symbol.get("haloSize")
    if halo_size and halo_size > 0:
        buffer_settings = QgsTextBufferSettings()
        buffer_settings.setEnabled(True)
        buffer_settings.setSize(halo_size)
        # Use a contrasting default color (white) if no specific halo symbol is defined
        buffer_settings.setColor(QColor("white"))
        text_format.setBuffer(buffer_settings)

    labeling.setFormat(text_format)
    labeling.enabled = True

    # 2. Placement Logic
    feature_type = placement_props.get("featureType")
    line_method = placement_props.get("linePlacementMethod")
    
    if feature_type == "Line":
        # CRITICAL: For QGIS 3.4+, line labels require .Line or .Curved placement
        if line_method == "CenteredStraightOnLine":
            labeling.placement = QgsPalLayerSettings.Line 
        elif "Curved" in line_method:
            labeling.placement = QgsPalLayerSettings.Curved
        else:
            labeling.placement = QgsPalLayerSettings.Line # Default for all other line types
    else:
        # Placeholder for Point/Polygon logic if needed
        labeling.placement = QgsPalLayerSettings.AroundPoint

    # --- Apply to Layer ---
    layer.setLabeling(QgsVectorLayerSimpleLabeling(labeling))
    visibility = layer_def.get("labelVisibility", False)
    layer.setLabelsEnabled(visibility)