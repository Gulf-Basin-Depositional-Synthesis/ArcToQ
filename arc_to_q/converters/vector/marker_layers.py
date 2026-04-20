import logging
import base64
import math
from typing import Optional, Dict, Any, Tuple, List

from qgis.core import (
    QgsSimpleMarkerSymbolLayer,
    QgsFontMarkerSymbolLayer,
    QgsRasterMarkerSymbolLayer,
    QgsUnitTypes,
    QgsSvgMarkerSymbolLayer,
    QgsSymbolLayer,
    QgsMarkerSymbol,
)
from qgis.PyQt.QtCore import Qt, QPointF
from qgis.PyQt.QtGui import QColor

from arc_to_q.converters.utils import parse_color

logger = logging.getLogger(__name__)

PT_TO_MM = 0.352777778

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


def bake_geometry_to_svg(
    geometry: Dict,
    frame: Dict,
    base_size_pt: float,
    anchor: Dict,
    anchor_units: str,
    rotation: float,
    offset_x_pt: float,
    offset_y_pt: float,
    color_hex: str,
    stroke_color_hex: str,
    stroke_width: float,
    is_line: bool
) -> Tuple[Optional[str], float]:
    """
    Bakes ArcGIS anchor, scale, rotation, and offset directly into the SVG coordinates.
    Creates a symmetrical ViewBox so QGIS places (0,0) exactly on the line.
    """
    if not geometry:
        return None, 0.0

    shapes = geometry.get("rings") or geometry.get("paths")
    if not shapes:
        return None, 0.0

    # 1. Parse Frame
    xmin = frame.get("xmin", -5.0)
    xmax = frame.get("xmax", 5.0)
    ymin = frame.get("ymin", -5.0)
    ymax = frame.get("ymax", 5.0)
    
    width = xmax - xmin
    height = ymax - ymin
    frame_size = max(width, height)
    if frame_size <= 0: 
        frame_size = 1.0

    # 2. Scale Factor
    scale = base_size_pt / frame_size

    # 3. Resolve Anchor Point Absolute Coordinates
    if anchor_units == "Relative":
        # In ArcGIS, Relative (0,0) is the center of the frame.
        anchor_x = ((xmin + xmax) / 2.0) + (anchor.get("x", 0.0) * width)
        anchor_y = ((ymin + ymax) / 2.0) + (anchor.get("y", 0.0) * height)
    else:
        anchor_x = anchor.get("x", 0.0)
        anchor_y = anchor.get("y", 0.0)

    # 4. Transform Points
    transformed_shapes = []
    all_x, all_y = [], []

    rad = math.radians(rotation)
    cos_r = math.cos(rad)
    sin_r = math.sin(rad)

    for shape in shapes:
        new_shape = []
        for pt in shape:
            x, y = pt[0], pt[1]

            # Shift geometry to the anchor point origin
            x_anch = x - anchor_x
            y_anch = y - anchor_y

            # Scale to final point size
            x_sc = x_anch * scale
            y_sc = y_anch * scale

            # Rotate (ArcGIS defines rotation as CCW around the anchor)
            x_rot = (x_sc * cos_r) - (y_sc * sin_r)
            y_rot = (x_sc * sin_r) + (y_sc * cos_r)

            # Apply visual offsets
            x_fin = x_rot + offset_x_pt
            y_fin = y_rot + offset_y_pt

            # Map to SVG coordinate space (Flip Y axis)
            svg_x = x_fin
            svg_y = -y_fin

            new_shape.append((svg_x, svg_y))
            all_x.append(svg_x)
            all_y.append(svg_y)
            
        transformed_shapes.append(new_shape)

    if not all_x:
        return None, 0.0

    # 5. Symmetric ViewBox calculation to guarantee exact center alignment
    max_abs_x = max(abs(x) for x in all_x)
    max_abs_y = max(abs(y) for y in all_y)
    
    # Add padding to prevent clipping of thick strokes
    padding = (stroke_width * scale) + 1.0
    limit = max(max_abs_x, max_abs_y) + padding
    limit = max(limit, 2.0)

    vb_size = limit * 2
    vb_min = -limit

    # 6. Construct SVG
    path_parts = []
    for shape in transformed_shapes:
        if not shape: continue
        path_parts.append(f"M {shape[0][0]:.3f} {shape[0][1]:.3f}")
        for pt in shape[1:]:
            path_parts.append(f"L {pt[0]:.3f} {pt[1]:.3f}")
        if not is_line:
            path_parts.append("Z")

    path_str = " ".join(path_parts)

    if is_line:
        fill_str = "none"
        stroke_str = color_hex
    else:
        fill_str = color_hex
        stroke_str = stroke_color_hex if stroke_width > 0 else "none"

    style = f'fill="param(fill) {fill_str}" stroke="param(outline) {stroke_str}" stroke-width="param(outline-width) 1.0"'

    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb_min:.3f} {vb_min:.3f} {vb_size:.3f} {vb_size:.3f}">'
    svg += f'<path d="{path_str}" {style} stroke-linecap="round" stroke-linejoin="round"/>'
    svg += '</svg>'

    return base64.b64encode(svg.encode("utf-8")).decode("utf-8"), vb_size


def _get_effective_props(layer_def: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively grabs rotation, offset, and anchor points from nested symbols."""
    props = {
        "rotation": 0.0, "offsetX": 0.0, "offsetY": 0.0, 
        "angleToLine": False,
        "anchorPoint": {"x": 0.0, "y": 0.0, "z": 0.0},
        "anchorPointUnits": "Relative"
    }
    
    current = layer_def
    while current:
        placement = current.get("markerPlacement", {})
        if placement.get("angleToLine"):
            props["angleToLine"] = True
            
        if props["offsetX"] == 0.0: props["offsetX"] = current.get("offsetX", 0.0)
        if props["offsetY"] == 0.0: props["offsetY"] = current.get("offsetY", 0.0)
        if props["rotation"] == 0.0: props["rotation"] = current.get("rotation", 0.0)
        
        # Grab anchor point if we haven't yet
        if "anchorPoint" in current and props["anchorPoint"]["x"] == 0.0 and props["anchorPoint"]["y"] == 0.0:
            props["anchorPoint"] = current["anchorPoint"]
            props["anchorPointUnits"] = current.get("anchorPointUnits", "Relative")
            
        graphics = current.get("markerGraphics", [])
        if not graphics: break
        
        symbol = graphics[0].get("symbol", {})
        if props["rotation"] == 0.0:
            props["rotation"] = symbol.get("angle", 0.0)
            
        nested = symbol.get("symbolLayers", [])
        if not nested: break
        current = nested[0]
        
    return props


def _get_deepest_layer_def(layer_def: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Finds the deepest nested vector marker layer containing geometry/frame."""
    graphics = layer_def.get("markerGraphics", [])
    if not graphics:
        return None
    
    symbol = graphics[0].get("symbol", {})
    nested = symbol.get("symbolLayers", [])
    
    if nested and nested[0].get("type") == "CIMVectorMarker":
        deeper = _get_deepest_layer_def(nested[0])
        return deeper if deeper else layer_def
    
    return layer_def


def create_simple_marker_from_vector(symbol_def: Dict[str, Any],
                                     baked_svg_path: Optional[str] = None,
                                     angle_to_line: Optional[bool] = None) -> QgsSymbolLayer:
    """Builds a fully baked QGIS SVG marker layer from a CIM vector marker."""

    props = _get_effective_props(symbol_def)
    base_size_pt = symbol_def.get("size", 6.0)
    
    deepest_layer = _get_deepest_layer_def(symbol_def) or symbol_def
    graphics = deepest_layer.get("markerGraphics", [])
    geometry = graphics[0].get("geometry", {}) if graphics else {}
    primitive_name = graphics[0].get("primitiveName") if graphics else None
    frame = deepest_layer.get("frame", {"xmin": -5.0, "ymin": -5.0, "xmax": 5.0, "ymax": 5.0})
    
    fill_color = QColor("black")
    stroke_color = QColor("black")
    stroke_width = 0.0
    
    sym_layers = graphics[0].get("symbol", {}).get("symbolLayers", []) if graphics else []
    for sl in sym_layers:
        if sl.get("type") == "CIMSolidFill":
            if c := parse_color(sl.get("color")):
                fill_color = c
        elif sl.get("type") == "CIMSolidStroke":
            if c := parse_color(sl.get("color")):
                stroke_color = c
            if w := sl.get("width"):
                stroke_width = w
            
    is_line = "paths" in geometry
    main_color = stroke_color if is_line else fill_color

    if ("rings" in geometry or "paths" in geometry) and not primitive_name:
        
        svg_b64, vb_size = bake_geometry_to_svg(
            geometry, frame, base_size_pt, 
            props["anchorPoint"], props["anchorPointUnits"],
            props["rotation"], props["offsetX"], props["offsetY"],
            main_color.name(), stroke_color.name(), stroke_width, is_line
        )
        
        if svg_b64:
            marker_layer = QgsSvgMarkerSymbolLayer(f"base64:{svg_b64}")
            
            # Parametrization injection mappings
            if is_line:
                marker_layer.setStrokeColor(main_color)
                marker_layer.setStrokeWidth(max(stroke_width, 0.5) * PT_TO_MM)
                marker_layer.setColor(QColor(0,0,0,0))
            else:
                marker_layer.setColor(main_color)
                marker_layer.setStrokeColor(stroke_color)
                marker_layer.setStrokeWidth(stroke_width * PT_TO_MM)

            marker_layer.setSize(vb_size * PT_TO_MM)
            marker_layer.setSizeUnit(QgsUnitTypes.RenderMillimeters)

            # Center align and neutral angle - let QGIS handle tangent tracking
            marker_layer.setAngle(0)
            marker_layer.setOffset(QPointF(0, 0))
            
            return marker_layer

    # Fallback Primitives
    fallback = QgsSimpleMarkerSymbolLayer()
    if primitive_name and primitive_name in MARKER_SHAPE_MAP:
        fallback.setShape(MARKER_SHAPE_MAP[primitive_name])
    else:
        fallback.setShape(QgsSimpleMarkerSymbolLayer.Circle)
        
    fallback.setColor(fill_color)
    fallback.setStrokeColor(stroke_color)
    fallback.setSize(base_size_pt * PT_TO_MM)
    fallback.setSizeUnit(QgsUnitTypes.RenderMillimeters)
    
    # Primitive offset fallback
    off_x_mm = props["offsetX"] * PT_TO_MM
    off_y_mm = -props["offsetY"] * PT_TO_MM
    fallback.setAngle(-props["rotation"])
    fallback.setOffset(QPointF(off_x_mm, off_y_mm))
    fallback.setOffsetUnit(QgsUnitTypes.RenderMillimeters)
    
    return fallback

def create_font_marker_from_character(layer_def: Dict[str, Any]) -> Optional[QgsFontMarkerSymbolLayer]:
    """Creates a QGIS Font Marker layer from a CIMCharacterMarker definition."""
    try:
        font_layer = QgsFontMarkerSymbolLayer()
        font_family = layer_def.get("fontFamilyName", "Arial")
        character_code = layer_def.get("characterIndex", 63)
        character = chr(character_code)
        
        color = QColor("black")
        nested_symbol_def = layer_def.get("symbol", {})
        if nested_symbol_def:
            symbol_layers = nested_symbol_def.get("symbolLayers", [])
            fill_layer_def = next((l for l in symbol_layers if l.get("type") == "CIMSolidFill"), None)
            if fill_layer_def and "color" in fill_layer_def:
                if parsed_color := parse_color(fill_layer_def["color"]):
                    color = parsed_color
        
        size_pt = layer_def.get("size", 6.0)
        size_mm = size_pt * PT_TO_MM
        
        font_layer.setFontFamily(font_family)
        font_layer.setCharacter(character)
        font_layer.setColor(color)
        font_layer.setSize(size_mm)
        font_layer.setSizeUnit(QgsUnitTypes.RenderMillimeters)
        
        rotation = layer_def.get("rotation", 0.0)
        offset_x_pt = layer_def.get("offsetX", 0.0)
        offset_y_pt = layer_def.get("offsetY", 0.0)
        
        offset_x_mm = offset_x_pt * PT_TO_MM
        offset_y_mm = -offset_y_pt * PT_TO_MM
        
        font_layer.setAngle(-rotation)
        font_layer.setOffset(QPointF(offset_x_mm, offset_y_mm))
        font_layer.setOffsetUnit(QgsUnitTypes.RenderMillimeters)
        
        return font_layer
    except Exception as e:
        logger.error(f"ERROR creating font marker: {e}")
        return None

def create_picture_marker_from_def(layer_def: Dict[str, Any]) -> Optional[QgsRasterMarkerSymbolLayer]:
    """Creates a QGIS Raster (Picture) Marker layer from a CIMPictureMarker definition."""
    try:
        url = layer_def.get("url", "")
        path = ""
        
        if "base64," in url:
            base64_data = url.split("base64,")[1]
            path = f"base64:{base64_data}"
        else:
            path = url
        
        if not path: return None
        
        layer = QgsRasterMarkerSymbolLayer(path)
        if not layer: return None
        
        size_pt = layer_def.get("size", 12.0)
        size_mm = size_pt * PT_TO_MM
        
        layer.setSize(size_mm)
        layer.setSizeUnit(QgsUnitTypes.RenderMillimeters)
        
        rotation = layer_def.get("rotation", 0.0)
        offset_x_pt = layer_def.get("offsetX", 0.0)
        offset_y_pt = layer_def.get("offsetY", 0.0)
        
        offset_x_mm = offset_x_pt * PT_TO_MM
        offset_y_mm = -offset_y_pt * PT_TO_MM
        
        layer.setAngle(-rotation)
        layer.setOffset(QPointF(offset_x_mm, offset_y_mm))
        layer.setOffsetUnit(QgsUnitTypes.RenderMillimeters)
        
        return layer
    
    except Exception as e:
        logger.error(f"ERROR creating picture marker: {e}")
        return None

def create_default_marker_layer() -> QgsSimpleMarkerSymbolLayer:
    layer = QgsSimpleMarkerSymbolLayer()
    layer.setShape(QgsSimpleMarkerSymbolLayer.Circle)
    layer.setSize(6.0)
    layer.setColor(QColor(255, 0, 0))
    layer.setStrokeColor(QColor(0, 0, 0))
    return layer