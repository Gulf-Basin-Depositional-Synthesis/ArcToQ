"""
Creates QGIS marker symbol layers from ArcGIS CIM definitions.
"""
import logging
from typing import Optional, Dict, Any

from qgis.core import (
    QgsSimpleMarkerSymbolLayer,
    QgsFontMarkerSymbolLayer,
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
        shape = _determine_marker_shape(layer_def)
        rotation = layer_def.get("rotation", 0.0)
        
        # Check if this is a line-based marker (like escarpment ticks)
        graphic = layer_def.get("markerGraphics", [{}])[0]
        geometry = graphic.get("geometry", {})
        is_line_marker = "paths" in geometry
        
        print(f"Vector marker: shape={shape}, size={size}, rotation={rotation}, is_line={is_line_marker}")
        
        # CRITICAL FIX: For line markers with angleToLine, rotation needs adjustment
        marker_placement = layer_def.get("markerPlacement", {})
        angle_to_line = marker_placement.get("angleToLine", False)
        
        if is_line_marker and angle_to_line:
            # CRITICAL: When angleToLine is true, QGIS will rotate the marker to align with the line
            # The built-in rotation (90°) would then make it parallel instead of perpendicular
            # Solution: Set rotation to 0° here, let angleToLine handle it, which naturally makes it perpendicular
            print(f"Line marker with angleToLine - changing rotation from {rotation}° to 0° (angleToLine will make it perpendicular)")
            rotation = 0
        
        marker_layer.setSize(size)
        marker_layer.setSizeUnit(QgsUnitTypes.RenderPoints)
        marker_layer.setShape(shape)
        marker_layer.setAngle(rotation)
        
        print(f"Set marker: shape={shape}, size={size}, angle={rotation}°")

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
            # CRITICAL FIX: For Line or Cross shape markers representing lines, use fill color
            if shape in (QgsSimpleMarkerSymbolLayer.Line, QgsSimpleMarkerSymbolLayer.Cross):
                marker_layer.setColor(stroke_color)
                marker_layer.setStrokeStyle(Qt.NoPen)  # No outline
                print(f"Line/Cross shape: using stroke color {stroke_color.name()} as fill")
                has_fill = True
            else:
                marker_layer.setStrokeStyle(Qt.SolidLine)
                marker_layer.setStrokeColor(stroke_color)
                marker_layer.setStrokeWidth(stroke_width)
                marker_layer.setStrokeWidthUnit(QgsUnitTypes.RenderPoints)
                print(f"Normal shape stroke: color={stroke_color.name()}, width={stroke_width}")
            has_stroke = True
        
        if not has_fill and not has_stroke:
            # Fallback to a default visible marker
            marker_layer.setColor(QColor("red"))
            marker_layer.setStrokeColor(QColor("black"))
            marker_layer.setStrokeWidth(0.2)
            marker_layer.setStrokeStyle(Qt.SolidLine)
            print(f"Applied fallback colors")
        elif not has_fill:
            marker_layer.setColor(QColor(0, 0, 0, 0)) # transparent fill
        elif not has_stroke:
            marker_layer.setStrokeStyle(Qt.NoPen)

        return marker_layer
    except Exception as e:
        print(f"ERROR in create_simple_marker_from_vector: {e}")
        logger.error(f"Failed to create simple marker from vector: {e}")
        return None


def create_font_marker_from_character(layer_def: Dict[str, Any]) -> Optional[QgsFontMarkerSymbolLayer]:
    """
    Creates a QGIS Font Marker layer from a CIMCharacterMarker definition.
    """
    try:
        font_layer = QgsFontMarkerSymbolLayer()
        font_family = layer_def.get("fontFamilyName", "Arial")
        character_code = layer_def.get("characterIndex", 63)
        character = chr(character_code)

        print(f"\n*** Creating font marker ***")
        print(f"Font: {font_family}, Char code: {character_code}, Char: '{character}'")

        color = QColor("black")
        nested_symbol_def = layer_def.get("symbol", {})
        if nested_symbol_def:
            symbol_layers = nested_symbol_def.get("symbolLayers", [])
            fill_layer_def = next((l for l in symbol_layers if l.get("type") == "CIMSolidFill"), None)
            if fill_layer_def and "color" in fill_layer_def:
                if parsed_color := parse_color(fill_layer_def["color"]):
                    color = parsed_color

        size = layer_def.get("size", 6.0)
        print(f"Size: {size}, Color: {color.name()}")

        font_layer.setFontFamily(font_family)
        font_layer.setCharacter(character)
        font_layer.setColor(color)
        font_layer.setSize(size)
        font_layer.setSizeUnit(QgsUnitTypes.RenderPoints)

        # Check for explicit anchor point
        anchor_point = layer_def.get("anchorPoint")
        anchor_point_units = layer_def.get("anchorPointUnits", "Relative")
        
        print(f"Anchor point: {anchor_point}")
        print(f"Anchor point units: {anchor_point_units}")
        
        if anchor_point:
            anchor_x = anchor_point.get("x", 0.0)
            anchor_y = anchor_point.get("y", 0.0)
            
            offset_x = 0.0
            offset_y = 0.0
            
            if anchor_point_units == "Absolute":
                offset_x = -anchor_x
                offset_y = anchor_y
                print(f"Absolute anchor -> offset=({offset_x}, {offset_y})")
            elif anchor_point_units == "Relative":
                offset_x = -anchor_x * size
                offset_y = anchor_y * size
                print(f"Relative anchor -> offset=({offset_x}, {offset_y})")
            
            font_layer.setOffset(QPointF(offset_x, offset_y))
            font_layer.setOffsetUnit(QgsUnitTypes.RenderPoints)
        else:
            print(f"No anchor point - using default centering")

        return font_layer
    except Exception as e:
        print(f"ERROR creating font marker: {e}")
        logger.error(f"Failed to create font marker from character: {e}")
        return None


def _determine_marker_shape(layer_def: Dict[str, Any]) -> QgsSimpleMarkerSymbolLayer.Shape:
    """Determine the QGIS marker shape from ArcGIS marker definition."""
    if not (marker_graphics := layer_def.get("markerGraphics", [])):
        return QgsSimpleMarkerSymbolLayer.Circle

    graphic = marker_graphics[0]
    if (shape_name := graphic.get("primitiveName")) and shape_name in MARKER_SHAPE_MAP:
        return MARKER_SHAPE_MAP[shape_name]

    geometry = graphic.get("geometry", {})
    
    # CRITICAL FIX: For line/path geometry (like escarpment ticks), try Cross instead of Line
    # The Line shape may not render properly in QGIS 3.4
    if "paths" in geometry:
        paths = geometry["paths"]
        if paths and len(paths) > 0:
            path = paths[0]
            # Check if it's a simple horizontal or vertical line
            if len(path) == 2:
                p1, p2 = path[0], path[1]
                # If it's horizontal or vertical, it should work as a line marker
                is_horizontal = p1[1] == p2[1]
                is_vertical = p1[0] == p2[0]
                if is_horizontal or is_vertical:
                    print(f"Detected simple line marker - using Cross shape as workaround")
                    return QgsSimpleMarkerSymbolLayer.Cross  # Use Cross, we'll rotate it
        print(f"Detected line marker (paths geometry) - using Line shape")
        return QgsSimpleMarkerSymbolLayer.Line
    
    if "rings" in geometry:
        points = geometry["rings"][0]
        point_count = len(points)
        if point_count == 5:
            unique_x = {p[0] for p in points}
            unique_y = {p[1] for p in points}
            return QgsSimpleMarkerSymbolLayer.Diamond if len(unique_x) == 3 and len(unique_y) == 3 else QgsSimpleMarkerSymbolLayer.Square
        shape_map = {4: QgsSimpleMarkerSymbolLayer.Triangle, 6: QgsSimpleMarkerSymbolLayer.Pentagon, 7: QgsSimpleMarkerSymbolLayer.Hexagon, 11: QgsSimpleMarkerSymbolLayer.Star, 13: QgsSimpleMarkerSymbolLayer.Cross}
        return shape_map.get(point_count, QgsSimpleMarkerSymbolLayer.Circle)
    elif "curveRings" in geometry:
        curve_points = [p for p in geometry["curveRings"][0] if isinstance(p, list)]
        return QgsSimpleMarkerSymbolLayer.Cross2 if len(curve_points) == 13 else QgsSimpleMarkerSymbolLayer.Circle

    return QgsSimpleMarkerSymbolLayer.Circle


def create_default_marker_layer() -> QgsSimpleMarkerSymbolLayer:
    """Create a default marker symbol layer."""
    layer = QgsSimpleMarkerSymbolLayer()
    layer.setShape(QgsSimpleMarkerSymbolLayer.Circle)
    layer.setSize(6.0)
    layer.setColor(QColor(255, 0, 0))  # Red
    layer.setStrokeColor(QColor(0, 0, 0))  # Black outline
    return layer