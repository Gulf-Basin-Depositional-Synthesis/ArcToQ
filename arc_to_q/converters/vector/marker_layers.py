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
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor

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
        marker_layer.setSize(size)
        marker_layer.setSizeUnit(QgsUnitTypes.RenderPoints)
        marker_layer.setShape(shape)
        marker_layer.setAngle(rotation)

        graphic = layer_def.get("markerGraphics", [{}])[0]
        graphic_symbol_layers = graphic.get("symbol", {}).get("symbolLayers", [])
        fill_def = next((sl for sl in graphic_symbol_layers if sl.get("type") == "CIMSolidFill"), None)
        stroke_def = next((sl for sl in graphic_symbol_layers if sl.get("type") == "CIMSolidStroke"), None)

        if fill_def and (fill_color := parse_color(fill_def.get("color"))) and fill_color.alpha() > 0:
            marker_layer.setColor(fill_color)
        else:
            marker_layer.setColor(QColor(0, 0, 0, 0))  # Transparent

        if stroke_def and (stroke_color := parse_color(stroke_def.get("color"))) and (stroke_width := stroke_def.get("width", 0.26)) > 0:
            marker_layer.setStrokeStyle(Qt.SolidLine)
            marker_layer.setStrokeColor(stroke_color)
            marker_layer.setStrokeWidth(stroke_width)
            marker_layer.setStrokeWidthUnit(QgsUnitTypes.RenderPoints)
        else:
            marker_layer.setStrokeStyle(Qt.NoPen)

        return marker_layer
    except Exception as e:
        logger.error(f"Failed to create simple marker from vector: {e}")
        return None


def create_font_marker_from_character(layer_def: Dict[str, Any]) -> Optional[QgsFontMarkerSymbolLayer]:
    """Creates a QGIS Font Marker layer from a CIMCharacterMarker definition."""
    try:
        font_layer = QgsFontMarkerSymbolLayer()
        font_family = layer_def.get("fontFamilyName", "Arial")
        character_code = layer_def.get("characterIndex", 32)  # Default to space
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


def _determine_marker_shape(layer_def: Dict[str, Any]) -> QgsSimpleMarkerSymbolLayer.Shape:
    """Determine the QGIS marker shape from ArcGIS marker definition."""
    if not (marker_graphics := layer_def.get("markerGraphics", [])):
        return QgsSimpleMarkerSymbolLayer.Circle

    graphic = marker_graphics[0]
    if (shape_name := graphic.get("primitiveName")) and shape_name in MARKER_SHAPE_MAP:
        return MARKER_SHAPE_MAP[shape_name]

    geometry = graphic.get("geometry", {})
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