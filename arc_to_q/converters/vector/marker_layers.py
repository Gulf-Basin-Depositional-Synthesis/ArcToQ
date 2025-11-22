import logging
from typing import Optional, Dict, Any

from qgis.core import (
    QgsSimpleMarkerSymbolLayer,
    QgsFontMarkerSymbolLayer,
    QgsRasterMarkerSymbolLayer,
    QgsUnitTypes,
)
from qgis.PyQt.QtCore import Qt, QPointF
from qgis.PyQt.QtGui import QColor, QFontMetrics, QFont

from arc_to_q.converters.utils import parse_color

logger = logging.getLogger(__name__)

# Mapping ArcGIS marker shapes to QGIS shapes
MARKER_SHAPE_MAP = {
    "Circle": QgsSimpleMarkerSymbolLayer.Circle,
    "Square": QgsSimpleMarkerSymbolLayer.Square,
    "Cross": QgsSimpleMarkerSymbolLayer.Cross,
    "X": QgsSimpleMarkerSymbolLayer.Cross2,
    "Diamond": QgsSimpleMarkerSymbolLayer.Diamond,
    "Triangle": QgsSimpleMarkerSymbolLayer.Triangle,
    "Pentagon": QgsSimpleMarkerSymbolLayer.Pentagon,
    "Hexagon": QgsSimpleMarkerSymbolLayer.Hexagon,
    "Star": QgsSimpleMarkerSymbolLayer.Star,
    "Arrow": QgsSimpleMarkerSymbolLayer.ArrowHead,
    "Line": QgsSimpleMarkerSymbolLayer.Line
}


def create_simple_marker_from_vector(layer_def: Dict[str, Any]) -> Optional[QgsSimpleMarkerSymbolLayer]:
    """Creates a QGIS Simple Marker from an ArcGIS CIMVectorMarker definition."""
    try:
        marker_layer = QgsSimpleMarkerSymbolLayer()

        size = layer_def.get("size", 6.0)
        shape, is_horizontal_path = _determine_marker_shape(layer_def)
        rotation = layer_def.get("rotation", 0.0)
        
        # Check if this is a line-based marker (like escarpment ticks)
        graphic = layer_def.get("markerGraphics", [{}])[0]
        geometry = graphic.get("geometry", {})
        is_line_marker = "paths" in geometry
        
        # Fix rotation for line markers
        # If we mapped a Horizontal path (ArcGIS) to a Vertical Line Shape (QGIS), we need +90 deg
        if is_horizontal_path and shape == QgsSimpleMarkerSymbolLayer.Line:
             rotation += 90

        marker_layer.setSize(size)
        marker_layer.setSizeUnit(QgsUnitTypes.RenderPoints)
        marker_layer.setShape(shape)
        marker_layer.setAngle(rotation)
        
        graphic_symbol_layers = graphic.get("symbol", {}).get("symbolLayers", [])
        fill_def = next((sl for sl in graphic_symbol_layers if sl.get("type") == "CIMSolidFill"), None)
        stroke_def = next((sl for sl in graphic_symbol_layers if sl.get("type") == "CIMSolidStroke"), None)

        has_fill = False
        if fill_def and (fill_color := parse_color(fill_def.get("color"))):
            if fill_color.alpha() > 0:
                marker_layer.setColor(fill_color)
                has_fill = True

        has_stroke = False
        if stroke_def and (stroke_color := parse_color(stroke_def.get("color"))) and (stroke_width := stroke_def.get("width", 0.26)) > 0:
            # FIXED: For Line and Cross shapes, we MUST use stroke properties (setStrokeStyle)
            # and MUST NOT disable the pen (Qt.NoPen), otherwise they are invisible.
            if shape in (QgsSimpleMarkerSymbolLayer.Line, QgsSimpleMarkerSymbolLayer.Cross):
                marker_layer.setColor(stroke_color) # Set fill color match just in case
                marker_layer.setStrokeColor(stroke_color)
                marker_layer.setStrokeWidth(stroke_width)
                marker_layer.setStrokeWidthUnit(QgsUnitTypes.RenderPoints)
                marker_layer.setStrokeStyle(Qt.SolidLine)
                has_fill = True # Considered 'filled' because it's visible
            else:
                marker_layer.setStrokeStyle(Qt.SolidLine)
                marker_layer.setStrokeColor(stroke_color)
                marker_layer.setStrokeWidth(stroke_width)
                marker_layer.setStrokeWidthUnit(QgsUnitTypes.RenderPoints)
            has_stroke = True
        
        if not has_fill and not has_stroke:
            # Fallback to a default visible marker
            marker_layer.setColor(QColor("red"))
            marker_layer.setStrokeColor(QColor("black"))
            marker_layer.setStrokeWidth(0.2)
            marker_layer.setStrokeStyle(Qt.SolidLine)
        elif not has_fill:
            # Only set transparent fill if it's not a Line/Cross (which don't have fill)
            if shape not in (QgsSimpleMarkerSymbolLayer.Line, QgsSimpleMarkerSymbolLayer.Cross):
                marker_layer.setColor(QColor(0, 0, 0, 0))
        elif not has_stroke:
            marker_layer.setStrokeStyle(Qt.NoPen)

        return marker_layer
    except Exception as e:
        print(f"ERROR in create_simple_marker_from_vector: {e}")
        logger.error(f"Failed to create simple marker from vector: {e}")
        return None


def create_font_marker_from_character(layer_def: Dict[str, Any]) -> Optional[QgsFontMarkerSymbolLayer]:
    """Creates a QGIS Font Marker layer from a CIMCharacterMarker definition."""
    try:
        font_layer = QgsFontMarkerSymbolLayer()
        font_family = layer_def.get("fontFamilyName", "Arial")
        character_code = layer_def.get("characterIndex", 63)  # Default to '?'
        character = chr(character_code)

        color = QColor("black")
        nested_symbol_def = layer_def.get("symbol", {})
        if nested_symbol_def:
            symbol_layers = nested_symbol_def.get("symbolLayers", [])
            fill_layer_def = next((l for l in symbol_layers if l.get("type") == "CIMSolidFill"), None)
            if fill_layer_def and "color" in fill_layer_def:
                if parsed_color := parse_color(fill_layer_def["color"]):
                    color = parsed_color

        size = layer_def.get("size", 6.0)

        font_layer.setFontFamily(font_family)
        font_layer.setCharacter(character)
        font_layer.setColor(color)
        font_layer.setSize(size)
        font_layer.setSizeUnit(QgsUnitTypes.RenderPoints)

        return font_layer
    except Exception as e:
        logger.error(f"Failed to create font marker from character: {e}")
        return None

def create_picture_marker_from_def(layer_def: Dict[str, Any]) -> Optional[QgsRasterMarkerSymbolLayer]:
    """
    Creates a QGIS Raster (Picture) Marker layer from a CIMPictureMarker definition.
    """
    try:
        url = layer_def.get("url", "")
        path = ""

        # Handle embedded Base64 images
        if "base64," in url:
            # Extract just the base64 string
            base64_data = url.split("base64,")[1]
            # QGIS format for embedded raster markers
            path = f"base64:{base64_data}"
        else:
            # Assume standard file path or web URL
            path = url

        if not path:
            return None

        layer = QgsRasterMarkerSymbolLayer(path)
        if not layer:
            return None

        size = layer_def.get("size", 12.0)
        layer.setSize(size)
        layer.setSizeUnit(QgsUnitTypes.RenderPoints)
        
        # Handle optional rotation if present in the layer def
        rotation = layer_def.get("rotation", 0.0)
        if rotation:
            layer.setAngle(rotation)

        return layer

    except Exception as e:
        logger.error(f"Failed to create picture marker: {e}")
        return None

def _determine_marker_shape(layer_def: Dict[str, Any]):
    """
    Determine the QGIS marker shape from ArcGIS marker definition.
    Returns: (Shape, is_horizontal_path_flag)
    """
    if not (marker_graphics := layer_def.get("markerGraphics", [])):
        return QgsSimpleMarkerSymbolLayer.Circle, False

    graphic = marker_graphics[0]
    if (shape_name := graphic.get("primitiveName")) and shape_name in MARKER_SHAPE_MAP:
        return MARKER_SHAPE_MAP[shape_name], False

    geometry = graphic.get("geometry", {})
    
    if "paths" in geometry:
        paths = geometry["paths"]
        if paths and len(paths) > 0:
            path = paths[0]
            # Check if it's a simple horizontal or vertical line
            if len(path) == 2:
                p1, p2 = path[0], path[1]
                is_horizontal = p1[1] == p2[1]
                is_vertical = p1[0] == p2[0]
                
                if is_horizontal:
                    # Use Line shape, but flag it as horizontal so we can rotate it +90
                    return QgsSimpleMarkerSymbolLayer.Line, True
                if is_vertical:
                    return QgsSimpleMarkerSymbolLayer.Line, False

        return QgsSimpleMarkerSymbolLayer.Line, False
    
    if "rings" in geometry:
        points = geometry["rings"][0]
        point_count = len(points)
        if point_count == 5:
            unique_x = {p[0] for p in points}
            unique_y = {p[1] for p in points}
            return (QgsSimpleMarkerSymbolLayer.Diamond if len(unique_x) == 3 and len(unique_y) == 3 else QgsSimpleMarkerSymbolLayer.Square), False
        shape_map = {4: QgsSimpleMarkerSymbolLayer.Triangle, 6: QgsSimpleMarkerSymbolLayer.Pentagon, 7: QgsSimpleMarkerSymbolLayer.Hexagon, 11: QgsSimpleMarkerSymbolLayer.Star, 13: QgsSimpleMarkerSymbolLayer.Cross}
        return shape_map.get(point_count, QgsSimpleMarkerSymbolLayer.Circle), False
        
    elif "curveRings" in geometry:
        curve_points = [p for p in geometry["curveRings"][0] if isinstance(p, list)]
        return (QgsSimpleMarkerSymbolLayer.Cross2 if len(curve_points) == 13 else QgsSimpleMarkerSymbolLayer.Circle), False

    return QgsSimpleMarkerSymbolLayer.Circle, False


def create_default_marker_layer() -> QgsSimpleMarkerSymbolLayer:
    """Create a default marker symbol layer."""
    layer = QgsSimpleMarkerSymbolLayer()
    layer.setShape(QgsSimpleMarkerSymbolLayer.Circle)
    layer.setSize(6.0)
    layer.setColor(QColor(255, 0, 0))  # Red
    layer.setStrokeColor(QColor(0, 0, 0))  # Black outline
    return layer