import logging
import base64
import math
from typing import Optional, Dict, Any

from qgis.core import (
    QgsSimpleMarkerSymbolLayer,
    QgsFontMarkerSymbolLayer,
    QgsRasterMarkerSymbolLayer,
    QgsUnitTypes,
    QgsSvgMarkerSymbolLayer,
    QgsSymbolLayer,
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

def _transform_point(pt, angle_deg, off_x, off_y):
    """
    Rotates and offsets a point in ArcGIS space (Y-Up), then returns it.
    """
    rad = math.radians(angle_deg)
    x, y = pt[0], pt[1]
    
    # Standard Rotation (CCW)
    rx = x * math.cos(rad) - y * math.sin(rad)
    ry = x * math.sin(rad) + y * math.cos(rad)
    
    # Apply Offset (in Rotated/Model Space)
    # Note: ArcGIS documentation implies offsets are applied BEFORE rotation for symbols?
    # Actually, empirical evidence from "Flexure" suggests offsets rotate with the symbol.
    # So we simply add offset to the rotated point? 
    # Or rotate the offset?
    # Let's assume the Offset vector is defined in the Object Space (aligned with symbol axes).
    # So we apply offset first, then rotate.
    # Re-evaluating based on "Flexure" (Y=-4, Rot=-90, Result=Right).
    # If Y=-4 (Down) is applied first -> (0, -4).
    # Rotate -90 -> (-4, 0) Left.
    # User said Left was "Opposite" (Wrong).
    # So user wants Right (4, 0).
    # This implies Offset was (0, -4) in PAGE space, then rotated? No.
    # It implies Offset was (0, -4) relative to the symbol, and sin(-90) flip happened.
    # Let's try: Rotate Point, Then Add Rotated Offset.
    
    # Rotated Offset Vector
    off_rx = off_x * math.cos(rad) - off_y * math.sin(rad)
    off_ry = off_x * math.sin(rad) + off_y * math.cos(rad)
    
    return [rx + off_rx, ry + off_ry]

def _create_baked_svg(geometry, color_hex, stroke_width, rotation, off_x, off_y, force_perpendicular=False):
    """
    Generates an SVG with rotation and offsets baked into the path coordinates.
    The ViewBox is centered on (0,0) to ensure perfect alignment in QGIS.
    """
    if not geometry:
        return None, 0

    shapes = geometry.get("rings") or geometry.get("paths")
    is_line = "paths" in geometry
    if not shapes:
        return None, 0

    # Apply specialized rotation logic
    # If "AtExtremities" logic requested perpendicularity (force_perpendicular)
    # We add -90 degrees. (0 -> -90 = Down/Right relative to tangent).
    final_rotation = rotation
    if force_perpendicular:
        final_rotation -= 90.0

    # 1. Transform all points
    all_points = []
    trans_shapes = []
    
    max_dist = 0.0
    
    for shape in shapes:
        new_shape = []
        for pt in shape:
            # Transform (Rotation + Offset)
            tp = _transform_point(pt, final_rotation, off_x, off_y)
            
            # Convert to SVG Coordinate System (Flip Y) for the path data string
            # We will calculate bounds in logic, but SVG path needs Y-down.
            # However, since we center the ViewBox later, we just need consistecy.
            # Let's keep math in Cartesian (Y-Up) and flip Y during path string generation.
            new_shape.append(tp)
            
            dist = math.sqrt(tp[0]**2 + tp[1]**2)
            if dist > max_dist:
                max_dist = dist
        trans_shapes.append(new_shape)

    # 2. Define ViewBox centered on (0,0)
    # We need a square box big enough to hold the rotated/offset shape spinning around origin.
    # Size = 2 * max_dist (plus a little padding)
    limit = max(max_dist, 0.5) * 2.1 # 5% padding
    
    # SVG ViewBox: min_x min_y width height
    # We want (0,0) cartesian to be the center of the SVG.
    # SVG (0,0) is top-left.
    # So logical (0,0) should be at SVG (limit/2, limit/2).
    # Or simpler: ViewBox from -R to +R.
    viewbox_str = f"{-limit/2} {-limit/2} {limit} {limit}"
    
    # 3. Build Path
    path_data = []
    for shape in trans_shapes:
        if not shape: continue
        
        # To SVG string: Flip Y coordinate (because SVG Y is Down)
        # Cartesian (x, y) -> SVG (x, -y)
        def to_str(p):
            return f"{p[0]} {-p[1]}"

        start = to_str(shape[0])
        path_data.append(f"M {start}")
        for p in shape[1:]:
            path_data.append(f"L {to_str(p)}")
        
        if not is_line:
            path_data.append("Z")
            
    path_str = " ".join(path_data)
    
    # Style
    if is_line:
        rel_stroke = max(stroke_width, 1.0) 
        style_attr = f'fill="none" stroke="{color_hex}" stroke-width="{rel_stroke}"'
    else:
        style_attr = f'fill="{color_hex}" stroke="none"'

    svg_content = (
        f'<svg width="100%" height="100%" viewBox="{viewbox_str}" '
        f'xmlns="http://www.w3.org/2000/svg">'
        f'<path d="{path_str}" {style_attr} stroke-linecap="round" stroke-linejoin="round"/>'
        f'</svg>'
    )
    
    # Return SVG and the physical height of the ViewBox (for scaling)
    return base64.b64encode(svg_content.encode('utf-8')).decode('utf-8'), limit

def _get_cumulative_props(layer_def):
    """
    Recursively sums rotation and offsets.
    """
    props = {"rotation": 0.0, "offsetX": 0.0, "offsetY": 0.0}
    
    # Current layer
    props["rotation"] += layer_def.get("rotation", 0.0)
    props["offsetX"] += layer_def.get("offsetX", 0.0)
    props["offsetY"] += layer_def.get("offsetY", 0.0)
    
    # Recursion
    graphics = layer_def.get("markerGraphics", [])
    if graphics:
        graphic = graphics[0]
        if "angle" in graphic:
            props["rotation"] += graphic["angle"]
        
        symbol = graphic.get("symbol", {})
        if "angle" in symbol:
            props["rotation"] += symbol["angle"]
            
        nested = symbol.get("symbolLayers", [])
        if nested and nested[0].get("type") == "CIMVectorMarker":
            child_props = _get_cumulative_props(nested[0])
            props["rotation"] += child_props["rotation"]
            props["offsetX"] += child_props["offsetX"]
            props["offsetY"] += child_props["offsetY"]
            
    return props

def create_simple_marker_from_vector(layer_def: Dict[str, Any]) -> Optional[QgsSymbolLayer]:
    try:
        # 1. Gather Cumulative Properties
        props = _get_cumulative_props(layer_def)
        rotation = props["rotation"]
        off_x = props["offsetX"]
        off_y = props["offsetY"]
        
        base_size = layer_def.get("size", 6.0)
        
        # 2. Check logic for Arch/Perpendicularity
        force_perpendicular = False
        placement = layer_def.get("markerPlacement", {})
        # If placed at extremities and no explicit rotation, assume it needs to point Away (90 deg shift)
        if placement.get("type") == "CIMMarkerPlacementAtExtremities" and abs(rotation) < 0.1:
            force_perpendicular = True

        # 3. Get Geometry & Colors
        deepest_layer = _get_deepest_layer_def(layer_def) or layer_def
        graphics = deepest_layer.get("markerGraphics", [])
        geometry = graphics[0].get("geometry", {}) if graphics else {}
        
        fill_color = QColor("black")
        stroke_color = QColor("black")
        stroke_width = 1.0
        
        sym_layers = graphics[0].get("symbol", {}).get("symbolLayers", []) if graphics else []
        for sl in sym_layers:
            if sl.get("type") == "CIMSolidFill":
                if c := parse_color(sl.get("color")): fill_color = c
            elif sl.get("type") == "CIMSolidStroke":
                if c := parse_color(sl.get("color")): stroke_color = c
                if w := sl.get("width"): stroke_width = w

        primitive_name = graphics[0].get("primitiveName") if graphics else None
        is_line = "paths" in geometry
        main_color = stroke_color if is_line else fill_color
        
        # 4. Generate Baked SVG
        if ("rings" in geometry or "paths" in geometry) and not primitive_name:
            svg_base64, viewbox_height = _create_baked_svg(
                geometry, main_color.name(), stroke_width, 
                rotation, off_x, off_y, force_perpendicular
            )
            
            if svg_base64:
                marker_layer = QgsSvgMarkerSymbolLayer(f"base64:{svg_base64}")
                marker_layer.setColor(main_color)
                marker_layer.setStrokeWidth(0)
                
                # --- Accurate Sizing ---
                # QGIS setSize sets the width/height of the SVG viewport.
                # ArcGIS 'size' usually refers to the visual height of the symbol geometry.
                # Our SVG ViewBox height is 'viewbox_height' (2 * max_dist).
                # We need to find the visual height of the geometry inside that box to scale correctly.
                # For simplicity, we scale based on the ViewBox height ratio.
                # If the geometry was 10 units high, and base_size is 10.
                # And ViewBox is 20 units high.
                # QGIS Size should be 20.
                
                # Calculate raw geometry height (unrotated) to get a scale factor
                shapes = geometry.get("rings") or geometry.get("paths")
                all_y = [pt[1] for shape in shapes for pt in shape] if shapes else []
                geo_height = (max(all_y) - min(all_y)) if all_y else 1.0
                geo_height = max(geo_height, 0.1)
                
                # Scale Factor: How much bigger is the ViewBox than the actual geometry?
                scale_ratio = viewbox_height / geo_height
                
                # Final Size
                final_size = base_size * scale_ratio
                
                marker_layer.setSize(final_size)
                
                # 5. Reset QGIS properties (Baked into SVG)
                marker_layer.setAngle(0)
                marker_layer.setOffset(QPointF(0, 0))
                marker_layer.setSizeUnit(QgsUnitTypes.RenderPoints)
                
                return marker_layer

        # Fallback for primitives
        marker_layer = QgsSimpleMarkerSymbolLayer()
        marker_layer.setColor(fill_color)
        marker_layer.setStrokeColor(stroke_color)
        marker_layer.setSize(base_size)
        marker_layer.setSizeUnit(QgsUnitTypes.RenderPoints)
        return marker_layer

    except Exception as e:
        logger.error(f"Failed to create marker from vector: {e}")
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
    if not (marker_graphics := layer_def.get("markerGraphics", [])):
        return QgsSimpleMarkerSymbolLayer.Circle, False
    graphic = marker_graphics[0]
    if (shape_name := graphic.get("primitiveName")) and shape_name in MARKER_SHAPE_MAP:
        return MARKER_SHAPE_MAP[shape_name], False
    geometry = graphic.get("geometry", {})
    if "paths" in geometry:
        return QgsSimpleMarkerSymbolLayer.Line, False
    elif "rings" in geometry:
        points = geometry["rings"][0]
        point_count = len(points)
        if point_count == 5:
            unique_x = {p[0] for p in points}
            unique_y = {p[1] for p in points}
            return (QgsSimpleMarkerSymbolLayer.Diamond if len(unique_x) == 3 and len(unique_y) == 3 else QgsSimpleMarkerSymbolLayer.Square), False
        shape_map = {4: QgsSimpleMarkerSymbolLayer.Triangle, 6: QgsSimpleMarkerSymbolLayer.Pentagon, 7: QgsSimpleMarkerSymbolLayer.Hexagon, 11: QgsSimpleMarkerSymbolLayer.Star, 13: QgsSimpleMarkerSymbolLayer.Cross}
        return shape_map.get(point_count, QgsSimpleMarkerSymbolLayer.Circle), False
    nested_symbol = graphic.get("symbol", {})
    if nested_symbol and nested_symbol.get("type") == "CIMPointSymbol":
        nested_layers = nested_symbol.get("symbolLayers", [])
        if nested_layers:
            return _determine_marker_shape(nested_layers[0])
    return QgsSimpleMarkerSymbolLayer.Circle, False


def create_default_marker_layer() -> QgsSimpleMarkerSymbolLayer:
    """Create a default marker symbol layer."""
    layer = QgsSimpleMarkerSymbolLayer()
    layer.setShape(QgsSimpleMarkerSymbolLayer.Circle)
    layer.setSize(6.0)
    layer.setColor(QColor(255, 0, 0))  # Red
    layer.setStrokeColor(QColor(0, 0, 0))  # Black outline
    return layer

def create_default_marker_layer() -> QgsSimpleMarkerSymbolLayer:
    layer = QgsSimpleMarkerSymbolLayer()
    layer.setShape(QgsSimpleMarkerSymbolLayer.Circle)
    layer.setSize(6.0)
    layer.setColor(QColor(255, 0, 0)) 
    layer.setStrokeColor(QColor(0, 0, 0)) 
    return layer

def _get_deepest_layer_def(layer_def):
    graphics = layer_def.get("markerGraphics", [])
    if not graphics: return None
    symbol = graphics[0].get("symbol", {})
    nested = symbol.get("symbolLayers", [])
    if nested and nested[0].get("type") == "CIMVectorMarker":
        return _get_deepest_layer_def(nested[0])
    return layer_def
