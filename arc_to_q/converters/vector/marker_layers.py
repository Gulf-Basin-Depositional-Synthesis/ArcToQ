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
from qgis.PyQt.QtGui import QColor, QFontMetrics, QFont

from arc_to_q.converters.utils import parse_color

logger = logging.getLogger(__name__)

# ArcGIS uses PostScript Points (1/72 inch). QGIS works best in Millimeters.
# 1 Point = 0.352777778 mm
PT_TO_MM = 0.352777778

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


def _create_clean_svg_with_offset(
    geometry: Dict,
    color_hex: str,
    stroke_width: float,
    is_line: bool,
    offset_x: float,
    offset_y: float
) -> Tuple[Optional[str], float, float]:
    """
    Creates an SVG from geometry with offsets baked in.
    
    KEY PRINCIPLES:
    1. ArcGIS coordinate system: (0,0) at center, Y+ up, X+ right
    2. SVG coordinate system: (0,0) at top-left, Y+ down, X+ right
    3. ViewBox centered at (0,0) to maintain anchor point
    4. Offsets shift the ENTIRE geometry relative to the anchor point
    
    Returns: (base64_svg, viewbox_size, geometry_visual_height)
    """
    if not geometry:
        return None, 0, 0

    shapes = geometry.get("rings") or geometry.get("paths")
    if not shapes:
        return None, 0, 0

    # -----------------------------------------------
    # 1. First pass: Calculate geometry bounds WITHOUT offset
    # -----------------------------------------------
    geo_min_x = float('inf')
    geo_max_x = float('-inf')
    geo_min_y = float('inf')
    geo_max_y = float('-inf')
    
    for shape in shapes:
        for pt in shape:
            geo_min_x = min(geo_min_x, pt[0])
            geo_max_x = max(geo_max_x, pt[0])
            geo_min_y = min(geo_min_y, pt[1])
            geo_max_y = max(geo_max_y, pt[1])
    
    # Calculate geometry dimensions (for sizing)
    geometry_width = max((geo_max_x - geo_min_x), 0.1)
    geometry_height = max((geo_max_y - geo_min_y), 0.1)
    geometry_visual_size = max(geometry_width, geometry_height)
    
    # -----------------------------------------------
    # 2. Transform Points: Apply offset then flip Y for SVG
    # -----------------------------------------------
    transformed_points = []
    all_x = []
    all_y = []

    for shape in shapes:
        new_shape = []
        for pt in shape:
            # Step 1: Apply offset in ArcGIS coordinate space
            x_arcgis = pt[0] + offset_x
            y_arcgis = pt[1] + offset_y
            
            # Step 2: Convert to SVG coordinate space (flip Y)
            svg_x = x_arcgis
            svg_y = -y_arcgis  # SVG Y increases downward
            
            new_shape.append((svg_x, svg_y))
            all_x.append(svg_x)
            all_y.append(svg_y)
            
        transformed_points.append(new_shape)

    if not all_x:
        return None, 0, 0

    # -----------------------------------------------
    # 2. Calculate Symmetric ViewBox Centered at (0,0)
    # -----------------------------------------------
    # Find maximum absolute coordinate in SVG space (AFTER offset applied)
    max_abs_x = max(abs(x) for x in all_x)
    max_abs_y = max(abs(y) for y in all_y)
    
    # Add padding for stroke and safety margin
    padding = (stroke_width * 2.0) + 2.0
    limit = max(max_abs_x, max_abs_y) + padding
    
    # Ensure minimum viewbox size for very small geometries
    limit = max(limit, 5.0)
    
    # ViewBox: from -limit to +limit (centered at origin)
    vb_min = -limit
    vb_size = limit * 2

    print(f"[VIEWBOX DEBUG] Geometry size: {geometry_visual_size:.2f}, Max offset coord: ({max_abs_x:.2f}, {max_abs_y:.2f}), ViewBox: {vb_size:.2f}")

    # -----------------------------------------------
    # 3. Build SVG Path
    # -----------------------------------------------
    path_parts = []
    for shape in transformed_points:
        if not shape:
            continue
        
        # Move to first point
        path_parts.append(f"M {shape[0][0]:.3f} {shape[0][1]:.3f}")
        
        # Line to subsequent points
        for pt in shape[1:]:
            path_parts.append(f"L {pt[0]:.3f} {pt[1]:.3f}")
        
        # Close path for filled shapes
        if not is_line:
            path_parts.append("Z")

    path_str = " ".join(path_parts)

    # Set appropriate style based on shape type
    if is_line:
        style = f'fill="none" stroke="{color_hex}" stroke-width="{max(stroke_width, 0.5)}"'
    else:
        style = f'fill="{color_hex}" stroke="none"'

    # -----------------------------------------------
    # 4. Generate SVG with Explicit Namespace and Clean Formatting
    # -----------------------------------------------
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb_min:.3f} {vb_min:.3f} {vb_size:.3f} {vb_size:.3f}">
<path d="{path_str}" {style} stroke-linecap="round" stroke-linejoin="round"/>
</svg>"""

    # Debug: print FULL SVG for first marker
    if abs(offset_y + 7.0) < 0.1:  # First marker with offset -7
        print(f"[FULL SVG]\n{svg}\n")

    svg_base64 = base64.b64encode(svg.encode("utf-8")).decode("utf-8")

    print(f"[SVG DEBUG] ViewBox: {vb_size:.2f}, Geometry: {geometry_visual_size:.2f}, Offset applied: ({offset_x:.2f}, {offset_y:.2f})")

    return svg_base64, vb_size, geometry_visual_size


def _get_cumulative_props(layer_def: Dict[str, Any]) -> Dict[str, float]:
    """Recursively sums rotation and offsets from nested marker definitions."""
    props = {"rotation": 0.0, "offsetX": 0.0, "offsetY": 0.0, "angleToLine": False}
    
    # Check for angle-to-line placement
    placement = layer_def.get("markerPlacement", {})
    if placement.get("angleToLine"):
        props["angleToLine"] = True
    
    # Add current layer's properties
    props["rotation"] += layer_def.get("rotation", 0.0)
    props["offsetX"] += layer_def.get("offsetX", 0.0)
    props["offsetY"] += layer_def.get("offsetY", 0.0)
    
    # Recurse into nested marker graphics
    graphics = layer_def.get("markerGraphics", [])
    if graphics:
        graphic = graphics[0]
        
        # Add graphic-level angle
        if "angle" in graphic:
            props["rotation"] += graphic["angle"]
        
        # Check symbol definition
        symbol = graphic.get("symbol", {})
        if "angle" in symbol:
            props["rotation"] += symbol["angle"]
        
        # Recurse into nested vector markers
        nested = symbol.get("symbolLayers", [])
        if nested and nested[0].get("type") == "CIMVectorMarker":
            child_props = _get_cumulative_props(nested[0])
            props["rotation"] += child_props["rotation"]
            props["offsetX"] += child_props["offsetX"]
            props["offsetY"] += child_props["offsetY"]
            if child_props["angleToLine"]:
                props["angleToLine"] = True
    
    return props


def _get_deepest_layer_def(layer_def: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Recursively finds the deepest nested vector marker layer containing actual geometry."""
    graphics = layer_def.get("markerGraphics", [])
    if not graphics:
        return None
    
    symbol = graphics[0].get("symbol", {})
    nested = symbol.get("symbolLayers", [])
    
    # Recurse if there's a nested vector marker
    if nested and nested[0].get("type") == "CIMVectorMarker":
        deeper = _get_deepest_layer_def(nested[0])
        return deeper if deeper else layer_def
    
    return layer_def


def create_simple_marker_from_vector(symbol_def: Dict[str, Any],
                                     baked_svg_path: Optional[str] = None,
                                     angle_to_line: Optional[bool] = None) -> QgsSymbolLayer:
    """
    Builds a QGIS marker symbol layer from an ArcGIS CIM vector marker.
    
    OFFSET HANDLING STRATEGY:
    - angle_to_line=True: Bake offsets into SVG (rotate with marker)
    - angle_to_line=False: Use QGIS offset property (screen-aligned)
    
    COORDINATE SYSTEM CONVERSIONS:
    - ArcGIS: Y+ up, rotation CCW+
    - QGIS: Y+ down, rotation CW-
    """

    # ----------------------------------------------------------------------
    # 1. Extract All Properties (Rotation & Offsets)
    # ----------------------------------------------------------------------
    props = _get_cumulative_props(symbol_def)
    rotation = props["rotation"]
    offset_x_pt = props["offsetX"]
    offset_y_pt = props["offsetY"]
    
    # Auto-detect angle_to_line if not provided
    if angle_to_line is None:
        angle_to_line = props.get("angleToLine", False)

    base_size_pt = symbol_def.get("size", 6.0)
    
    print(f"\n[INPUT] Rotation: {rotation}°, Offset: ({offset_x_pt:.2f}, {offset_y_pt:.2f})pt, AngleToLine: {angle_to_line}, Size: {base_size_pt}pt")
    
    # Get deepest layer for actual geometry
    deepest_layer = _get_deepest_layer_def(symbol_def) or symbol_def
    graphics = deepest_layer.get("markerGraphics", [])
    geometry = graphics[0].get("geometry", {}) if graphics else {}
    primitive_name = graphics[0].get("primitiveName") if graphics else None
    
    # ----------------------------------------------------------------------
    # 2. Extract Colors and Styles
    # ----------------------------------------------------------------------
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

    # ----------------------------------------------------------------------
    # 3. Generate SVG for Custom Geometry
    # ----------------------------------------------------------------------
    if ("rings" in geometry or "paths" in geometry) and not primitive_name:
        
        # DON'T bake offsets into SVG - use QGIS offsets with rotation instead!
        bake_x = 0.0
        bake_y = 0.0
        qgis_offset_x = offset_x_pt
        qgis_offset_y = offset_y_pt
        
        print(f"[OFFSET DECISION] NOT baking offsets - will use QGIS rotated offset instead")
        
        # Generate SVG with NO offset baked in
        svg_b64, viewbox_size, geo_size = _create_clean_svg_with_offset(
            geometry, main_color.name(), stroke_width, is_line, bake_x, bake_y
        )
        
        if svg_b64:
            svg_path = f"base64:{svg_b64}"
            marker_layer = QgsSvgMarkerSymbolLayer(svg_path)
            
            if not marker_layer:
                print(f"[ERROR] Failed to create QgsSvgMarkerSymbolLayer!")
                return create_default_marker_layer()
            
            marker_layer.setColor(main_color)
            marker_layer.setStrokeWidth(0)  # Stroke handled in SVG

            # --- SIZE CALCULATION ---
            # Goal: Make the geometry appear at base_size_pt (4pt) on screen.
            # 
            # The geometry is geo_size (17) units tall in the SVG.
            # QGIS setSize() controls how big the ViewBox appears.
            # 
            # If we set QGIS size = X:
            #   ViewBox (61 units) appears as X on screen
            #   Geometry (17 units) appears as: X * (17/61) on screen
            #   
            # We want: X * (17/61) = 4pt
            # So: X = 4pt * (61/17) = 14.35pt
            #
            # This is what we calculated! But the problem is the geometry
            # was designed to be 12pt, not 4pt. We're shrinking it.
            #
            # ACTUALLY: Ignore frame_display_size! Just use base_size_pt!
            
            if geo_size > 0:
                # Make geometry appear at exactly base_size_pt
                scale_ratio = viewbox_size / geo_size
                final_size_pt = base_size_pt * scale_ratio
            else:
                scale_ratio = 1.0
                final_size_pt = base_size_pt
            
            final_size_mm = final_size_pt * PT_TO_MM
            
            print(f"[SIZE DEBUG] Geometry={geo_size:.2f} units should appear as {base_size_pt}pt")
            print(f"[SIZE DEBUG] ViewBox={viewbox_size:.2f} units, so QGIS size={final_size_pt:.2f}pt ({final_size_mm:.2f}mm)")
            print(f"[SIZE DEBUG] Verification: {viewbox_size:.2f} * ({base_size_pt}/{viewbox_size:.2f}) = {final_size_pt * geo_size / viewbox_size:.2f}pt (should be {base_size_pt}pt)")
            
            marker_layer.setSize(final_size_mm)
            marker_layer.setSizeUnit(QgsUnitTypes.RenderMillimeters)

            # --- ROTATION & OFFSET HANDLING ---
            if angle_to_line:
                # For angle-to-line: Apply rotation AND rotate the offset vector
                
                # First handle the perpendicular rotation adjustment
                if abs(abs(rotation) - 180) < 10:
                    if offset_y_pt > 0:
                        final_rotation = 90
                        print(f"[ROTATION DEBUG] Adjusted {rotation}° to +90° (perpendicular, offset_y > 0)")
                    elif offset_y_pt < 0:
                        final_rotation = -90
                        print(f"[ROTATION DEBUG] Adjusted {rotation}° to -90° (perpendicular, offset_y < 0)")
                    else:
                        final_rotation = rotation
                else:
                    final_rotation = rotation
                
                # QGIS uses CW-negative rotation (opposite of ArcGIS)
                marker_layer.setAngle(-final_rotation)
                
                # Now rotate the offset vector so it rotates with the marker
                if offset_x_pt != 0 or offset_y_pt != 0:
                    rad = math.radians(-final_rotation)  # Use QGIS rotation
                    rot_x = offset_x_pt * math.cos(rad) - offset_y_pt * math.sin(rad)
                    rot_y = offset_x_pt * math.sin(rad) + offset_y_pt * math.cos(rad)
                    
                    # Convert to mm and invert Y
                    off_x_mm = rot_x * PT_TO_MM
                    off_y_mm = -rot_y * PT_TO_MM
                    
                    marker_layer.setOffset(QPointF(off_x_mm, off_y_mm))
                    marker_layer.setOffsetUnit(QgsUnitTypes.RenderMillimeters)
                    print(f"[OFFSET] Rotated offset: ({off_x_mm:.2f}, {off_y_mm:.2f})mm")
                else:
                    marker_layer.setOffset(QPointF(0, 0))
                    marker_layer.setOffsetUnit(QgsUnitTypes.RenderMillimeters)
                
            else:
                # Standard fixed rotation
                print(f"[ROTATION] Fixed rotation: {rotation}°")
                marker_layer.setAngle(-rotation)
                
                # Apply QGIS screen-aligned offsets
                # Convert to mm and flip Y (QGIS Y+ down, ArcGIS Y+ up)
                off_x_mm = qgis_offset_x * PT_TO_MM
                off_y_mm = -qgis_offset_y * PT_TO_MM  # Flip Y axis
                
                marker_layer.setOffset(QPointF(off_x_mm, off_y_mm))
                marker_layer.setOffsetUnit(QgsUnitTypes.RenderMillimeters)
                print(f"[ROTATION] QGIS angle: {-rotation}°, QGIS offset: ({off_x_mm:.2f}, {off_y_mm:.2f})mm")

            print(f"[MARKER FINAL] Size: {final_size_pt:.2f}pt ({final_size_pt * PT_TO_MM:.2f}mm), Scale ratio: {scale_ratio:.2f}\n")
            return marker_layer

    # ----------------------------------------------------------------------
    # 4. Fallback to Simple Marker (Primitives / Failed SVG)
    # ----------------------------------------------------------------------
    print(f"[FALLBACK DEBUG] Using simple marker for: {primitive_name or 'custom geometry'}")
    
    fallback = QgsSimpleMarkerSymbolLayer()
    
    # Attempt to match shape
    if primitive_name and primitive_name in MARKER_SHAPE_MAP:
        fallback.setShape(MARKER_SHAPE_MAP[primitive_name])
    else:
        shape, _ = _determine_marker_shape(symbol_def)
        fallback.setShape(shape)
        
    fallback.setColor(fill_color)
    fallback.setStrokeColor(stroke_color)
    fallback.setSize(base_size_pt * PT_TO_MM)
    fallback.setSizeUnit(QgsUnitTypes.RenderMillimeters)
    
    # Apply standard rotation/offset (ArcGIS -> QGIS conversion)
    fallback.setAngle(-rotation)
    off_x_mm = offset_x_pt * PT_TO_MM
    off_y_mm = -offset_y_pt * PT_TO_MM  # Flip Y axis
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
        
        # Handle rotation and offset with coordinate system conversion
        rotation = layer_def.get("rotation", 0.0)
        offset_x_pt = layer_def.get("offsetX", 0.0)
        offset_y_pt = layer_def.get("offsetY", 0.0)
        
        offset_x_mm = offset_x_pt * PT_TO_MM
        offset_y_mm = -offset_y_pt * PT_TO_MM  # Flip Y axis
        
        font_layer.setAngle(-rotation)
        font_layer.setOffset(QPointF(offset_x_mm, offset_y_mm))
        font_layer.setOffsetUnit(QgsUnitTypes.RenderMillimeters)
        
        return font_layer
    except Exception as e:
        logger.error(f"ERROR creating font marker: {e}")
        return None


def create_picture_marker_from_def(layer_def: Dict[str, Any]) -> Optional[QgsRasterMarkerSymbolLayer]:
    """
    Creates a QGIS Raster (Picture) Marker layer from a CIMPictureMarker definition.
    """
    try:
        url = layer_def.get("url", "")
        path = ""
        
        if "base64," in url:
            base64_data = url.split("base64,")[1]
            path = f"base64:{base64_data}"
        else:
            path = url
        
        if not path:
            return None
        
        layer = QgsRasterMarkerSymbolLayer(path)
        if not layer:
            return None
        
        size_pt = layer_def.get("size", 12.0)
        size_mm = size_pt * PT_TO_MM
        
        layer.setSize(size_mm)
        layer.setSizeUnit(QgsUnitTypes.RenderMillimeters)
        
        # Handle rotation and offset with coordinate system conversion
        rotation = layer_def.get("rotation", 0.0)
        offset_x_pt = layer_def.get("offsetX", 0.0)
        offset_y_pt = layer_def.get("offsetY", 0.0)
        
        offset_x_mm = offset_x_pt * PT_TO_MM
        offset_y_mm = -offset_y_pt * PT_TO_MM  # Flip Y axis
        
        layer.setAngle(-rotation)
        layer.setOffset(QPointF(offset_x_mm, offset_y_mm))
        layer.setOffsetUnit(QgsUnitTypes.RenderMillimeters)
        
        return layer
    
    except Exception as e:
        logger.error(f"ERROR creating picture marker: {e}")
        return None


def _determine_marker_shape(layer_def: Dict[str, Any]) -> Tuple[int, bool]:
    """
    Determines the best QGIS marker shape for a given layer definition.
    """
    if not (marker_graphics := layer_def.get("markerGraphics", [])):
        return QgsSimpleMarkerSymbolLayer.Circle, False
    
    graphic = marker_graphics[0]
    
    # Check for primitive name first
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
            if len(unique_x) == 3 and len(unique_y) == 3:
                return QgsSimpleMarkerSymbolLayer.Diamond, False
            return QgsSimpleMarkerSymbolLayer.Square, False
        
        shape_map = {
            4: QgsSimpleMarkerSymbolLayer.Triangle,
            6: QgsSimpleMarkerSymbolLayer.Pentagon,
            7: QgsSimpleMarkerSymbolLayer.Hexagon,
            11: QgsSimpleMarkerSymbolLayer.Star,
            13: QgsSimpleMarkerSymbolLayer.Cross
        }
        return shape_map.get(point_count, QgsSimpleMarkerSymbolLayer.Circle), False
    
    nested_symbol = graphic.get("symbol", {})
    if nested_symbol and nested_symbol.get("type") == "CIMPointSymbol":
        nested_layers = nested_symbol.get("symbolLayers", [])
        if nested_layers:
            return _determine_marker_shape(nested_layers[0])
    
    return QgsSimpleMarkerSymbolLayer.Circle, False


def create_default_marker_layer() -> QgsSimpleMarkerSymbolLayer:
    """Create a default marker symbol layer as fallback."""
    layer = QgsSimpleMarkerSymbolLayer()
    layer.setShape(QgsSimpleMarkerSymbolLayer.Circle)
    layer.setSize(6.0)
    layer.setColor(QColor(255, 0, 0))
    layer.setStrokeColor(QColor(0, 0, 0))
    return layer