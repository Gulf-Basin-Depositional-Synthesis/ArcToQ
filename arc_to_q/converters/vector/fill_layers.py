"""
Creates QGIS fill symbol layers from ArcGIS CIM definitions.
Handles solid, hatch, picture, and other fill types.
"""
import logging
import base64
import math
import tempfile
import os
import hashlib
from pathlib import Path
import json
from typing import Optional, Dict, Any

from qgis.core import (
    QgsMarkerSymbol, QgsPointPatternFillSymbolLayer, QgsSimpleFillSymbolLayer,
    QgsRasterFillSymbolLayer, QgsSymbolLayer, QgsUnitTypes, 
    QgsGradientFillSymbolLayer, QgsGradientStop, QgsGradientColorRamp,
    QgsLinePatternFillSymbolLayer, QgsSymbolLayerUtils, QgsSimpleLineSymbolLayer, QgsFillSymbol
)

from qgis.PyQt.QtCore import Qt, QByteArray, QBuffer, QIODevice, QPointF
from qgis.PyQt.QtGui import QColor, QImage

from arc_to_q.converters.utils import parse_color, extract_colors_from_ramp
from .line_layers import create_solid_stroke_layer
from .marker_layers import create_font_marker_from_character

logger = logging.getLogger(__name__)


def create_fill_layer_from_def(layer_def: Dict[str, Any]) -> Optional[QgsSymbolLayer]:
    """
    Creates a QGIS symbol layer from a single ArcGIS fill layer definition.
    Acts as a dispatcher for different fill types.
    """
    layer_type = layer_def.get("type")

    if layer_type == "CIMSolidFill":
        return _create_solid_fill_layer(layer_def)
    elif layer_type == "CIMSolidStroke":
        return _create_stroke_as_fill_layer(layer_def)
    elif layer_type == "CIMHatchFill":
        return _create_hatch_fill_layer(layer_def)
    elif layer_type == "CIMGradientFill":        
        return _create_gradient_fill_layer(layer_def)
    elif layer_type == "CIMPictureFill":
        return _create_picture_fill_layer(layer_def)
    elif layer_type == "CIMCharacterMarker":
        return _create_point_pattern_fill_layer(layer_def)
    else:
        logger.warning(f"Unsupported fill layer type: {layer_type}")
        return None


def _create_solid_fill_layer(layer_def: Dict[str, Any]) -> Optional[QgsSimpleFillSymbolLayer]:
    """Creates a simple fill layer for a solid color."""
    if fill_color := parse_color(layer_def.get("color")):
        simple_fill = QgsSimpleFillSymbolLayer()
        simple_fill.setFillColor(fill_color)
        simple_fill.setStrokeStyle(Qt.NoPen)
        return simple_fill
    return None


def _create_stroke_as_fill_layer(layer_def: Dict[str, Any]) -> Optional[QgsSymbolLayer]:
    """
    Creates an outline for a fill symbol. 
    
    NOTE: We return a QgsSimpleLineSymbolLayer (not a FillLayer). 
    QGIS Fill Symbols accept line layers, which act as the polygon outline.
    This is required because QgsSimpleFillSymbolLayer does NOT support custom dash vectors.
    """
    # create_solid_stroke_layer returns a fully configured QgsSimpleLineSymbolLayer
    # (including custom dashes, caps, joins, and colors)
    return create_solid_stroke_layer(layer_def)


def _create_hatch_fill_layer(layer_def: Dict[str, Any]) -> QgsLinePatternFillSymbolLayer:
    """
    Creates a QgsLinePatternFillSymbolLayer from a CIM definition.
    
    IMPROVEMENT:
    - Implements a 'Width Damper'. ArcGIS often uses thick stroke widths (e.g. 3pt, 4pt)
      that look fine in print but render as solid blocks on QGIS screens.
    - This logic caps the line width to ensure the 'Gap' is always visible.
    """
    hatch_fill = QgsLinePatternFillSymbolLayer()
    layer_name = layer_def.get("name", "Unnamed Layer")
    
    print("\n" + "="*60)
    print(f"[DEBUG] Processing Hatch: '{layer_name}'")

    # ------------------------------------------------------------------
    # 1. Angle (Rotation)
    # ------------------------------------------------------------------
    rotation = layer_def.get("rotation")
    if rotation is None:
        rotation = layer_def.get("Angle") or layer_def.get("angle") or 0.0

    try:
        rotation = float(rotation)
    except (ValueError, TypeError):
        rotation = 0.0

    hatch_fill.setLineAngle(rotation)

    # ------------------------------------------------------------------
    # 2. Extract Raw Width & Spacing First (To Compare Them)
    # ------------------------------------------------------------------
    
    # --- GET WIDTH ---
    line_symbol_def = layer_def.get("lineSymbol") or layer_def.get("LineSymbol") or {}
    symbol_layers = line_symbol_def.get("symbolLayers") or []
    
    stroke_def = None
    for sl in symbol_layers:
        if sl.get("type") == "CIMSolidStroke":
            stroke_def = sl
            break
    
    raw_width = 0.7
    if stroke_def:
        w_val = stroke_def.get("width")
        try:
            raw_width = float(w_val) if w_val is not None else 0.7
        except (ValueError, TypeError):
            raw_width = 0.7

    # --- GET SPACING ---
    raw_spacing_val = layer_def.get("separation") or layer_def.get("Separation") or layer_def.get("spacing")
    raw_spacing = 5.0
    try:
        if raw_spacing_val is not None:
            raw_spacing = float(raw_spacing_val)
    except (ValueError, TypeError):
        raw_spacing = 5.0

    print(f"[DEBUG] Input -> Width: {raw_width} | Spacing: {raw_spacing}")

    # ------------------------------------------------------------------
    # 3. The "Width Damper" & "Gap Safety" Logic
    # ------------------------------------------------------------------
    
    final_width = raw_width
    final_spacing = raw_spacing

    # CHECK: Is the gap too small? (Gap = Spacing - Width)
    gap = raw_spacing - raw_width
    
    # If the gap is tiny (< 2.0) or the width is massive (> 2.0), 
    # the hatch will look like a solid block in QGIS.
    
    if raw_width > 1.5 or gap < 1.5:
        print(f"[DEBUG] DETECTED POOR VISIBILITY (Gap: {gap}, Width: {raw_width})")
        
        # STRATEGY: Reduce Width first.
        # Thick lines (3pt+) are the main culprit. We clamp them to 1.5pt max.
        # This instantly recovers whitespace without changing the pattern density.
        if raw_width > 1.5:
            final_width = 1.5
            print(f"        ACTION: Clamped Line Width {raw_width} -> {final_width}")
        
        # RE-CHECK GAP with new width
        new_gap = final_spacing - final_width
        
        # If gap is STILL too small (e.g. Spacing was 2.0), verify spacing
        if new_gap < 2.0:
            # Enforce a minimum spacing based on the new width
            # We want the spacing to be at least Width + 2.0 (creating a 2pt gap)
            min_spacing = final_width + 2.5 
            if final_spacing < min_spacing:
                final_spacing = min_spacing
                print(f"        ACTION: Increased Spacing {raw_spacing} -> {final_spacing}")
        
    # ------------------------------------------------------------------
    # 4. Apply Properties
    # ------------------------------------------------------------------
    
    # Color
    color = QColor(0, 0, 0)
    if stroke_def:
        color_def = stroke_def.get("color")
        if color_def:
            try:
                parsed_c = parse_color(color_def) # Ensure parse_color is available
                if isinstance(parsed_c, QColor):
                    color = parsed_c
            except Exception:
                pass

    hatch_fill.setLineWidth(final_width)
    hatch_fill.setLineWidthUnit(QgsUnitTypes.RenderPoints)
    hatch_fill.setColor(color)

    hatch_fill.setDistance(final_spacing)
    hatch_fill.setDistanceUnit(QgsUnitTypes.RenderPoints)
    
    print(f"[DEBUG] FINAL -> Width: {final_width} | Spacing: {final_spacing}")
    print("="*60 + "\n")

    return hatch_fill


def _create_gradient_fill_layer(layer_def: Dict[str, Any]) -> Optional[QgsGradientFillSymbolLayer]:
    """
    Creates a QGIS Gradient Fill layer from a CIMGradientFill definition.
    """
    try:
        gradient_layer = QgsGradientFillSymbolLayer()
        
        # Set Coordinate Mode to 'Feature' so it stretches across the polygon
        gradient_layer.setCoordinateMode(QgsGradientFillSymbolLayer.Feature)
        gradient_layer.setGradientSpread(QgsGradientFillSymbolLayer.Pad)
        
        # 1. Map Gradient Method
        method = layer_def.get("gradientMethod", "Linear")
        
        if method == "Linear":
            gradient_layer.setGradientType(QgsGradientFillSymbolLayer.Linear)
            
            # Initialize standard Left-to-Right vector (0 degrees)
            gradient_layer.setReferencePoint1(QPointF(0, 0))
            gradient_layer.setReferencePoint2(QPointF(1, 0))
            gradient_layer.setReferencePoint1IsCentroid(False)
            gradient_layer.setReferencePoint2IsCentroid(False)
            
            # Add 180 degrees to flip the direction
            # ArcGIS and QGIS often disagree on whether the angle points 
            # to the "Start" or the "End" of the gradient.
            raw_angle = layer_def.get("angle", 0.0)
            corrected_angle = (raw_angle + 180) % 360
            gradient_layer.setAngle(corrected_angle)

        elif method in ["Circular", "Radial", "Rectangular", "Buffered"]:
            gradient_layer.setGradientType(QgsGradientFillSymbolLayer.Radial)
            gradient_layer.setReferencePoint1(QPointF(0.5, 0.5))
            gradient_layer.setReferencePoint1IsCentroid(True)
            gradient_layer.setReferencePoint2(QPointF(1, 0.5))
            gradient_layer.setReferencePoint2IsCentroid(False)
            # Radial gradients usually don't need the 180 flip, but if they appear inverted
            # (inside-out), you might need to swap setColor and setColor2 below.
        
        # 2. Handle Colors 
        color_ramp_def = layer_def.get("colorRamp", {})
        colors = extract_colors_from_ramp(color_ramp_def)
        
        if not colors:
            colors = [QColor("grey"), QColor("white")]

        if method in ["Circular", "Radial", "Rectangular", "Buffered"]:
            colors.reverse()
            
        if len(colors) == 1:
            colors.append(colors[0])

        c1 = colors[0]
        c2 = colors[-1]

        # Create a Ramp Object (This is how 3.4 handles multi-stops)
        ramp = QgsGradientColorRamp(c1, c2)
        stops = []

        # --- GAMMA CORRECTION (Manual Midpoint) ---
        if len(colors) == 2:
            # RMS average for Linear-like blending (Fixes the "Too Blue" issue)
            r_mid = int(math.sqrt((c1.red()**2 + c2.red()**2)/2))
            g_mid = int(math.sqrt((c1.green()**2 + c2.green()**2)/2))
            b_mid = int(math.sqrt((c1.blue()**2 + c2.blue()**2)/2))
            a_mid = int((c1.alpha() + c2.alpha())/2)
            
            mid_color = QColor(r_mid, g_mid, b_mid, a_mid)
            stops.append(QgsGradientStop(0.5, mid_color))

        # --- Explicit Stops from JSON ---
        elif len(colors) > 2:
            num_intervals = len(colors) - 1
            for i, color in enumerate(colors):
                if i == 0 or i == len(colors) - 1:
                    continue
                offset = i / num_intervals
                stops.append(QgsGradientStop(offset, color))
        
        # Apply stops to the RAMP, not the layer
        if stops:
            ramp.setStops(stops)

        # Tell the layer to use the ColorRamp engine
        gradient_layer.setGradientColorType(QgsGradientFillSymbolLayer.ColorRamp)
        gradient_layer.setColorRamp(ramp)

        return gradient_layer

    except Exception as e:
        logger.error(f"Failed to create gradient fill layer: {e}")
        return None


def _create_point_pattern_fill_layer(layer_def: Dict[str, Any]) -> Optional[QgsPointPatternFillSymbolLayer]:
    """Creates a point pattern fill from a CIMCharacterMarker definition."""
    try:
        font_marker_layer = create_font_marker_from_character(layer_def)
        if not font_marker_layer:
            return None

        sub_symbol = QgsMarkerSymbol([font_marker_layer])
        point_pattern_layer = QgsPointPatternFillSymbolLayer()
        point_pattern_layer.setSubSymbol(sub_symbol)

        placement = layer_def.get("markerPlacement", {})
        point_pattern_layer.setDistanceX(placement.get("stepX", 5.0))
        point_pattern_layer.setDistanceY(placement.get("stepY", 5.0))
        point_pattern_layer.setDistanceXUnit(QgsUnitTypes.RenderPoints)
        point_pattern_layer.setDistanceYUnit(QgsUnitTypes.RenderPoints)
        return point_pattern_layer
    except Exception as e:
        logger.error(f"Failed to create point pattern fill layer: {e}")
        return None

def _create_picture_fill_layer(layer_def: Dict[str, Any]) -> Optional[QgsSymbolLayer]:
    """
    Creates a QGIS Picture Fill from a CIMPictureFill definition,
    processing color substitutions to handle custom colors and transparency.
    """
    try:
        url_string = layer_def.get("url", "")
        
        if not url_string.startswith("data:image/bmp;base64,"):
            logger.warning(f"Unsupported picture fill format: {url_string[:30]}")
            return None

        # Decode the base64 data
        base64_data = url_string.split(",")[1]
        image_data = base64.b64decode(base64_data)

        # Load the original image data into a QImage object
        image = QImage()
        if not image.loadFromData(image_data, 'BMP'):
            logger.error("Failed to load BMP image data")
            return None

        # Process color substitutions if they exist
        substitutions = layer_def.get("colorSubstitutions", [])
        
        if substitutions:
            # Create a mapping from old RGB tuples to new QColor objects
            color_map = {}
            for sub in substitutions:
                old_color_vals = sub.get("oldColor", {}).get("values")
                new_color_def = sub.get("newColor", {})
                if old_color_vals and new_color_def:
                    # Use only RGB for the key, as source is likely 24-bit
                    old_color_rgb = tuple(old_color_vals[:3])
                    qgis_new_color = parse_color(new_color_def)
                    if qgis_new_color:
                        color_map[old_color_rgb] = qgis_new_color
            
            if color_map:
                # Convert image to a format that supports an alpha channel for transparency
                image = image.convertToFormat(QImage.Format_ARGB32)

                # Iterate through each pixel and apply the color substitution
                for x in range(image.width()):
                    for y in range(image.height()):
                        pixel_color = QColor(image.pixel(x, y))
                        pixel_rgb = (pixel_color.red(), pixel_color.green(), pixel_color.blue())
                        if pixel_rgb in color_map:
                            image.setPixelColor(x, y, color_map[pixel_rgb])

        # Convert image to PNG in memory and encode as base64
        byte_array = QByteArray()
        buffer = QBuffer(byte_array)
        buffer.open(QIODevice.WriteOnly)
        image.save(buffer, "PNG")
        buffer.close()
        
        # Convert to base64
        png_base64 = byte_array.toBase64().data().decode('utf-8')
        
        # Create data URI for embedding in the layer
        data_uri = f"base64:{png_base64}"

        # Create the raster fill layer with embedded data URI
        picture_layer = QgsRasterFillSymbolLayer(data_uri)

        # Set image size properties from the CIM definition
        image_width = layer_def.get("height", 32.0)
        picture_layer.setWidth(image_width)
        picture_layer.setWidthUnit(QgsUnitTypes.RenderPoints)
        
        return picture_layer
        
    except Exception as e:
        logger.error(f"Failed to create picture fill layer: {e}")
        return None


def create_default_fill_layer() -> QgsSimpleFillSymbolLayer:
    """Create a default fill symbol layer."""
    layer = QgsSimpleFillSymbolLayer()
    layer.setFillColor(QColor(0, 255, 0, 100))
    layer.setStrokeColor(QColor(0, 0, 0))
    layer.setStrokeWidth(0.5)
    return layer