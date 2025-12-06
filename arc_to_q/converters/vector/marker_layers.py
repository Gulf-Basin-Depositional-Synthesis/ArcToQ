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

def _create_svg_from_geometry(geometry, frame, color_hex, stroke_width=0):
    """
    Converts ArcGIS geometry (Rings or Paths) into a base64 encoded SVG string.
    """
    if not geometry:
        return None

    # Handle both Rings (Polygons) and Paths (Lines)
    shapes = geometry.get("rings") or geometry.get("paths")
    is_line = "paths" in geometry
    
    if not shapes:
        return None

    # Calculate bounds from frame
    xmin = frame.get("xmin", 0)
    ymin = frame.get("ymin", 0)
    xmax = frame.get("xmax", 0)
    ymax = frame.get("ymax", 0)
    
    width = abs(xmax - xmin)
    height = abs(ymax - ymin)
    
    # Avoid division by zero for flat lines
    width = max(width, 0.1)
    height = max(height, 0.1)
    
    path_data = []
    for shape in shapes:
        if not shape: continue
        
        # SVG Coordinate Transform:
        # X: x - xmin (Shift to 0)
        # Y: ymax - y (Flip Axis so Up is Up)
        def to_svg(pt):
            px = pt[0] - xmin
            py = ymax - pt[1] 
            return f"{px} {py}"

        start = to_svg(shape[0])
        path_data.append(f"M {start}")
        
        for p in shape[1:]:
            path_data.append(f"L {to_svg(p)}")
        
        # Close path only for polygons
        if not is_line:
            path_data.append("Z")
    
    path_str = " ".join(path_data)
    
    # Attributes: Lines need Stroke; Polygons need Fill
    if is_line:
        # Stroke width in SVG is relative to the ViewBox. 
        # We set it to a reasonable relative thickness (e.g. 5% of height) 
        # or 1 unit, as QGIS will scale the whole image.
        rel_stroke = max(stroke_width, 1.0) 
        style_attr = f'fill="none" stroke="{color_hex}" stroke-width="{rel_stroke}"'
    else:
        style_attr = f'fill="{color_hex}" stroke="none"'

    svg_content = (
        f'<svg width="100%" height="100%" viewBox="0 0 {width} {height}" '
        f'xmlns="http://www.w3.org/2000/svg">'
        f'<path d="{path_str}" {style_attr} stroke-linecap="round" stroke-linejoin="round"/>'
        f'</svg>'
    )
    
    return base64.b64encode(svg_content.encode('utf-8')).decode('utf-8')

def create_simple_marker_from_vector(layer_def: Dict[str, Any]) -> Optional[QgsSymbolLayer]:
    """Creates a QGIS Marker from an ArcGIS CIMVectorMarker."""
    try:
        # 1. Extract Properties (Digging Deep)
        base_size = layer_def.get("size", 6.0)
        rotation = _get_nested_rotation(layer_def)
        
        # Offsets
        raw_off_x = layer_def.get("offsetX", 0.0)
        raw_off_y = layer_def.get("offsetY", 0.0)

        # Colors & Geometry
        fill_color = QColor("black")
        stroke_color = QColor("black")
        stroke_width = 1.0
        
        deepest_layer = _get_deepest_layer_def(layer_def) or layer_def
        
        # Dig for colors in the deepest layer
        graphic_layers = deepest_layer.get("markerGraphics", [])[0].get("symbol", {}).get("symbolLayers", []) if deepest_layer.get("markerGraphics") else []
        
        for sl in graphic_layers:
            if sl.get("type") == "CIMSolidFill":
                if c := parse_color(sl.get("color")):
                    fill_color = c
            elif sl.get("type") == "CIMSolidStroke":
                if c := parse_color(sl.get("color")):
                    stroke_color = c
                if w := sl.get("width"):
                    stroke_width = w

        # 2. Get Geometry & Frame
        graphics = deepest_layer.get("markerGraphics", [])
        geometry = graphics[0].get("geometry", {}) if graphics else {}
        frame = _get_deepest_frame(layer_def)

        # 3. GENERATE SVG MARKER (Universal Fix)
        # We prioritize SVG for everything unless it's a known Primitive like 'Circle'
        primitive_name = graphics[0].get("primitiveName") if graphics else None
        
        # Determine Color to use (Stroke for Lines, Fill for Polygons)
        is_line = "paths" in geometry
        main_color = stroke_color if is_line else fill_color
        
        if ("rings" in geometry or "paths" in geometry) and not primitive_name:
            svg_base64 = _create_svg_from_geometry(geometry, frame, main_color.name(), stroke_width)
            
            if svg_base64:
                marker_layer = QgsSvgMarkerSymbolLayer(f"base64:{svg_base64}")
                marker_layer.setColor(main_color) # QGIS Tint
                marker_layer.setStrokeWidth(0)    # Handled inside SVG
                
                # --- Aspect Ratio / Size Correction ---
                frame_height = abs(frame.get("ymax", 0) - frame.get("ymin", 0))
                
                # Calculate geometry height
                shapes = geometry.get("rings") or geometry.get("paths")
                all_y = [pt[1] for shape in shapes for pt in shape] if shapes else []
                geo_height = max(all_y) - min(all_y) if all_y else frame_height
                
                final_size = base_size
                dominant_axis = layer_def.get("dominantSizeAxis3D", "Y")
                
                if dominant_axis == "Y" and frame_height > 0 and geo_height > 0:
                     frame_width = abs(frame.get("xmax", 0) - frame.get("xmin", 0))
                     max_frame_dim = max(frame_width, frame_height)
                     # Boost size so visual geometry height matches base_size
                     final_size = base_size * (max_frame_dim / geo_height)

                marker_layer.setSize(final_size)
            else:
                # Fallback if SVG gen failed
                marker_layer = QgsSimpleMarkerSymbolLayer()
                marker_layer.setColor(QColor("red"))
                marker_layer.setSize(base_size)
        
        else:
            # 4. Fallback for Primitives (Circle, etc.)
            # If no geometry found, or it's a primitive, use standard marker
            marker_layer = QgsSimpleMarkerSymbolLayer()
            marker_layer.setColor(fill_color)
            marker_layer.setStrokeColor(stroke_color)
            marker_layer.setSize(base_size)

        # 5. Final Settings (Offsets & Rotation)
        marker_layer.setSizeUnit(QgsUnitTypes.RenderPoints)
        
        # Apply Rotation
        marker_layer.setAngle(rotation)

        # Apply Rotated Offset
        if raw_off_x != 0 or raw_off_y != 0:
            rad = math.radians(rotation)
            rot_x = raw_off_x * math.cos(rad) - raw_off_y * math.sin(rad)
            rot_y = raw_off_x * math.sin(rad) + raw_off_y * math.cos(rad)
            
            # Invert Y for QGIS Screen Coordinates
            marker_layer.setOffset(QPointF(rot_x, -rot_y))
            marker_layer.setOffsetUnit(QgsUnitTypes.RenderPoints)

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
    """
    Determine the QGIS marker shape.
    Recursively digs into nested symbols if the top-level graphic is just a container.
    """
    if not (marker_graphics := layer_def.get("markerGraphics", [])):
        return QgsSimpleMarkerSymbolLayer.Circle, False

    graphic = marker_graphics[0]

    # 1. Check for primitive name (Standard shapes like 'Circle', 'Square')
    if (shape_name := graphic.get("primitiveName")) and shape_name in MARKER_SHAPE_MAP:
        return MARKER_SHAPE_MAP[shape_name], False

    geometry = graphic.get("geometry", {})

    # 2. Check for Direct Geometry (Paths/Rings at this level)
    if "paths" in geometry:
        paths = geometry["paths"]
        if paths and len(paths) > 0:
            path = paths[0]
            if len(path) == 2:
                p1, p2 = path[0], path[1]
                # Check if it's horizontal (y values are effectively equal)
                is_horizontal = abs(p1[1] - p2[1]) < 1e-6
                return QgsSimpleMarkerSymbolLayer.Line, is_horizontal
        return QgsSimpleMarkerSymbolLayer.Line, False

    elif "rings" in geometry:
        points = geometry["rings"][0]
        point_count = len(points)
        
        # Distinguish Square vs Diamond based on unique coordinates
        if point_count == 5:
            unique_x = {p[0] for p in points}
            unique_y = {p[1] for p in points}
            return (QgsSimpleMarkerSymbolLayer.Diamond if len(unique_x) == 3 and len(unique_y) == 3 else QgsSimpleMarkerSymbolLayer.Square), False
            
        shape_map = {
            4: QgsSimpleMarkerSymbolLayer.Triangle, 
            6: QgsSimpleMarkerSymbolLayer.Pentagon,
            7: QgsSimpleMarkerSymbolLayer.Hexagon, 
            11: QgsSimpleMarkerSymbolLayer.Star,
            13: QgsSimpleMarkerSymbolLayer.Cross
        }
        return shape_map.get(point_count, QgsSimpleMarkerSymbolLayer.Circle), False

    # 3. RECURSIVE DIG (Critical for your 'Arch' symbol)
    # If geometry is missing or just a point (x,y), check for a nested symbol
    nested_symbol = graphic.get("symbol", {})
    if nested_symbol and nested_symbol.get("type") == "CIMPointSymbol":
        nested_layers = nested_symbol.get("symbolLayers", [])
        # Recurse into the first symbol layer of the nested symbol to find the real shape
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

def _get_deepest_symbol_layers(layer_def):
    """Recursively finds the symbol layers inside the matryoshka doll."""
    graphics = layer_def.get("markerGraphics", [])
    if not graphics: return []
    
    symbol = graphics[0].get("symbol", {})
    if symbol.get("type") == "CIMPointSymbol":
        # Check if the first layer is another VectorMarker (recursion)
        nested_layers = symbol.get("symbolLayers", [])
        if nested_layers and nested_layers[0].get("type") == "CIMVectorMarker":
            return _get_deepest_symbol_layers(nested_layers[0])
        return nested_layers
    return []

def _get_deepest_rings(layer_def):
    """Recursively finds the coordinate rings."""
    graphics = layer_def.get("markerGraphics", [])
    if not graphics: return None
    
    geo = graphics[0].get("geometry", {})
    if "rings" in geo: return geo["rings"]
    
    # Recurse
    symbol = graphics[0].get("symbol", {})
    nested_layers = symbol.get("symbolLayers", [])
    if nested_layers and nested_layers[0].get("type") == "CIMVectorMarker":
        return _get_deepest_rings(nested_layers[0])
    return None

def _get_nested_rotation(layer_def):
    if "rotation" in layer_def: return layer_def["rotation"]
    graphics = layer_def.get("markerGraphics", [])
    if graphics:
        symbol = graphics[0].get("symbol", {})
        if "angle" in symbol: return symbol["angle"]
        nested = symbol.get("symbolLayers", [])
        if nested and nested[0].get("type") == "CIMVectorMarker":
            return _get_nested_rotation(nested[0])
    return 0.0

def _get_deepest_layer_def(layer_def):
    graphics = layer_def.get("markerGraphics", [])
    if not graphics: return None
    symbol = graphics[0].get("symbol", {})
    nested = symbol.get("symbolLayers", [])
    if nested and nested[0].get("type") == "CIMVectorMarker":
        return _get_deepest_layer_def(nested[0])
    return layer_def

def _get_deepest_frame(layer_def):
    frame = layer_def.get("frame", {})
    deepest = _get_deepest_layer_def(layer_def)
    if deepest and "frame" in deepest:
        return deepest["frame"]
    return frame