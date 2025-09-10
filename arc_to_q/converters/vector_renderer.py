from colorsys import hsv_to_rgb

# --- QGIS imports ---
from qgis.core import (
    QgsVectorLayer,
    QgsSingleSymbolRenderer,
    QgsCategorizedSymbolRenderer,
    QgsRendererCategory,
    QgsGraduatedSymbolRenderer,
    QgsRendererRange,
    QgsMarkerSymbol,
    QgsLineSymbol,
    QgsFillSymbol,
    QgsSimpleMarkerSymbolLayer,
    QgsSimpleLineSymbolLayer,
    QgsSimpleFillSymbolLayer
)
from qgis.PyQt.QtGui import QColor

from arc_to_q.converters.utils import parse_color

# --- Mapping tables ---

# ArcGIS marker shape → QGIS 'name' property
MARKER_SHAPE_MAP = {
    "circle": "circle",
    "square": "square",
    "cross": "cross",
    "x": "x",
    "diamond": "diamond",
    "triangle": "triangle",
    "triangle-up": "triangle",
    "triangle-down": "triangle",
    "triangle-left": "triangle",
    "triangle-right": "triangle",
    "star": "star",
    "pentagon": "pentagon"
}

# ArcGIS line style → QGIS 'line_style' property
LINE_STYLE_MAP = {
    "solid": "solid",
    "dash": "dash",
    "dot": "dot",
    "dash-dot": "dash dot",
    "dash-dot-dot": "dash dot dot"
}

# ArcGIS fill style → QGIS 'style' property
FILL_STYLE_MAP = {
    "solid": "solid",
    "null": "no",
    "horizontal": "horizontal",
    "vertical": "vertical",
    "cross": "cross",
    "diagonal-cross": "diagonal cross",
    "forward-diagonal": "forward diagonal",
    "backward-diagonal": "backward diagonal"
}

# --- Utility functions ---



def _create_symbol(symbol_def):
    """
    Create a QGIS symbol from an ArcGIS CIM symbol definition, including symbolLayers.
    """
    if not symbol_def or not isinstance(symbol_def, dict):
        return None
    if symbol_def.get("type") != "CIMSymbolReference":
        return None

    symbol_def = symbol_def.get("symbol", {})
    if not symbol_def or not isinstance(symbol_def, dict):
        return None

    s_type = symbol_def.get("type", "").lower()

    # --- Handle point symbols with symbolLayers ---
    if "point" in s_type:
        size = symbol_def.get("size", 2.0)
        base_symbol = QgsMarkerSymbol()
        base_symbol.deleteSymbolLayer(0)  # remove default layer

        for layer in symbol_def.get("symbolLayers", []):
            if not layer.get("enable", True):
                continue
            if layer.get("type") == "CIMVectorMarker":
                for mg in layer.get("markerGraphics", []):
                    mg_symbol = mg.get("symbol", {})
                    mg_type = mg_symbol.get("type", "").lower()
                    if "polygon" in mg_type:
                        # Extract fill/outline from polygon symbolLayers
                        fill_color = None
                        outline_color = None
                        outline_width = 0.26
                        for sublayer in mg_symbol.get("symbolLayers", []):
                            stype = sublayer.get("type", "")
                            if stype == "CIMSolidFill":
                                fill_color = parse_color(sublayer.get("color"))
                            elif stype == "CIMSolidStroke":
                                outline_color = parse_color(sublayer.get("color"))
                                outline_width = sublayer.get("width", outline_width)

                        # Defaults if missing
                        if fill_color is None:
                            fill_color = QColor(0, 0, 0, 0)
                        if outline_color is None:
                            outline_color = QColor(0, 0, 0, 0)

                        # Create marker layer and set properties
                        marker_layer = QgsSimpleMarkerSymbolLayer()
                        marker_layer.setShape(QgsSimpleMarkerSymbolLayer.Circle)
                        marker_layer.setColor(fill_color)
                        marker_layer.setSize(size)
                        marker_layer.setOutlineColor(outline_color)
                        marker_layer.setOutlineWidth(outline_width)

                        base_symbol.appendSymbolLayer(marker_layer)

        return base_symbol

    # --- Handle line symbols ---
    elif "line" in s_type:
        base_symbol = QgsLineSymbol()
        base_symbol.deleteSymbolLayer(0)
        for layer in symbol_def.get("symbolLayers", []):
            if layer.get("type") == "CIMSolidStroke":
                color = parse_color(layer.get("color"))
                width = layer.get("width", 0.5)
                line_layer = QgsSimpleLineSymbolLayer()
                line_layer.setColor(color)
                line_layer.setWidth(width)
                base_symbol.appendSymbolLayer(line_layer)
        return base_symbol

    # --- Handle polygon/fill symbols ---
    elif "polygon" in s_type or "fill" in s_type:
        base_symbol = QgsFillSymbol()
        base_symbol.deleteSymbolLayer(0)
        fill_color = None
        outline_color = None
        outline_width = 0.26
        for layer in symbol_def.get("symbolLayers", []):
            if layer.get("type") == "CIMSolidFill":
                fill_color = parse_color(layer.get("color"))
            elif layer.get("type") == "CIMSolidStroke":
                outline_color = parse_color(layer.get("color"))
                outline_width = layer.get("width", outline_width)

        if fill_color is None:
            fill_color = QColor(0, 0, 0, 0)
        if outline_color is None:
            outline_color = QColor(0, 0, 0, 0)

        fill_layer = QgsSimpleFillSymbolLayer()
        fill_layer.setFillColor(fill_color)
        fill_layer.setStrokeColor(outline_color)
        fill_layer.setStrokeWidth(outline_width)

        base_symbol.appendSymbolLayer(fill_layer)
        return base_symbol

    return None


def set_vector_renderer(layer, renderer_def):
    """
    Set the QGIS vector layer renderer based on the ArcGIS renderer definition.

    Args:
        layer (QgsVectorLayer): The QGIS vector layer to set the renderer for.
        renderer_def (dict): The ArcGIS renderer definition.
    """
    if not isinstance(layer, QgsVectorLayer):
        raise TypeError("layer must be a QgsVectorLayer")

    if not isinstance(renderer_def, dict):
        raise TypeError("renderer_def must be a dict")

    r_type = renderer_def.get("type")
    if not r_type:
        raise ValueError(f"Renderer type missing for layer: {layer.name()}")

    if r_type == "CIMSimpleRenderer":
        symbol_def = renderer_def.get("symbol", {})
        symbol = _create_symbol(symbol_def)
        if symbol:
            layer.setRenderer(QgsSingleSymbolRenderer(symbol))
        else:
            raise ValueError(f"Failed to create symbol for simple renderer: {layer.name()}")

    elif r_type == "CIMUniqueValueRenderer":
        field_names = renderer_def.get("fieldNames", [])
        if len(field_names) != 1:
            raise NotImplementedError(
                f"Unhandled: Unique value renderer with multiple fields: {field_names}"
            )
        field_name = field_names[0]
        categories = []
        for uv in renderer_def.get("uniqueValues", []):
            value = uv.get("value")
            label = uv.get("label", str(value))
            symbol_def = uv.get("symbol", {})
            symbol = _create_symbol(symbol_def)
            if symbol:
                categories.append(QgsRendererCategory(value, symbol, label))
            else:
                raise ValueError(
                    f"Failed to create symbol for unique value: {value} in layer: {layer.name()}"
                )
        if categories:
            layer.setRenderer(QgsCategorizedSymbolRenderer(field_name, categories))
        else:
            raise ValueError(
                f"No valid categories found for unique value renderer in layer: {layer.name()}"
            )

    elif r_type == "CIMClassBreaksRenderer":
        field_name = renderer_def.get("field")
        if not field_name:
            raise ValueError(
                f"Field name missing for class breaks renderer in layer: {layer.name()}"
            )

        breaks = renderer_def.get("breaks", [])
        if not breaks:
            raise ValueError(f"No breaks found for class breaks renderer in layer: {layer.name()}")

        # Sort by upperBound just in case
        breaks = sorted(breaks, key=lambda b: b.get("upperBound", float("inf")))

        classes = []
        lower = renderer_def.get("minValue")  # optional: ArcGIS sometimes stores this
        if lower is None:
            lower = float("-inf")

        for cb in breaks:
            upper = cb.get("upperBound")
            if upper is None:
                raise ValueError(f"upperBound missing in class break for layer: {layer.name()}")

            label = cb.get("label", f"{lower} - {upper}")
            symbol_def = cb.get("symbol", {})
            symbol = _create_symbol(symbol_def)
            if symbol:
                classes.append(QgsRendererRange(lower, upper, symbol, label))
            else:
                raise ValueError(
                    f"Failed to create symbol for class break: {label} in layer: {layer.name()}"
                )

            # Next lower bound starts at this upper bound
            lower = upper

        if classes:
            layer.setRenderer(QgsGraduatedSymbolRenderer(field_name, classes))
        else:
            raise ValueError(
                f"No valid classes found for class breaks renderer in layer: {layer.name()}"
            )

    else:
        raise NotImplementedError(
            f"Unhandled renderer type: {r_type} in layer: {layer.name()}"
        )
