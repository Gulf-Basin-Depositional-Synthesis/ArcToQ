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
    
    REWRITE LOGIC:
    1. PARITY: Removed arbitrary multipliers (2.0x, 0.8x) and caps.
    2. UNITS: Converts all input (Points) to Millimeters (0.352778 scaling).
    3. ENGINE: Sets QGIS render units to Millimeters to match physical output.
    """
    hatch_fill = QgsLinePatternFillSymbolLayer()
    
    # ArcGIS uses PostScript Points (1/72 inch). QGIS works best in Millimeters.
    # 1 Point = 0.352777778 mm
    PT_TO_MM = 0.352777778

    # ------------------------------------------------------------------
    # 1. Angle (Rotation)
    # ------------------------------------------------------------------
    # ArcGIS and QGIS both use CCW rotation from East (0 degrees).
    # No conversion needed usually, but normalization is good practice.
    rotation = layer_def.get("rotation")
    if rotation is None:
        rotation = layer_def.get("Angle") or layer_def.get("angle") or 0.0

    try:
        rotation = float(rotation) % 360
    except (ValueError, TypeError):
        rotation = 0.0

    hatch_fill.setLineAngle(rotation)

    # ------------------------------------------------------------------
    # 2. Extract Raw Properties (in Points)
    # ------------------------------------------------------------------
    
    # --- GET STROKE WIDTH (Points) ---
    line_symbol_def = layer_def.get("lineSymbol") or layer_def.get("LineSymbol") or {}
    symbol_layers = line_symbol_def.get("symbolLayers") or []

    stroke_def = None
    for sl in symbol_layers:
        # We look for the stroke definition to get width and color
        if sl.get("type") in ["CIMSolidStroke", "SolidStroke"]:
            stroke_def = sl
            break
    
    raw_width_pt = 0.7 # Default ArcGIS width
    if stroke_def:
        w_val = stroke_def.get("width")
        try:
            raw_width_pt = float(w_val) if w_val is not None else 0.7
        except (ValueError, TypeError):
            raw_width_pt = 0.7

    # --- GET SPACING / SEPARATION (Points) ---
    # ArcGIS 'Separation' is center-to-center, same as QGIS 'Distance' [1, 2]
    raw_spacing_val = layer_def.get("separation") or layer_def.get("Separation") or layer_def.get("spacing")
    raw_spacing_pt = 5.0 # Default
    try:
        if raw_spacing_val is not None:
            raw_spacing_pt = float(raw_spacing_val)
    except (ValueError, TypeError):
        raw_spacing_pt = 5.0

    # --- GET OFFSET (Points) ---
    raw_offset_val = layer_def.get("offset") or layer_def.get("Offset")
    raw_offset_pt = 0.0
    try:
        if raw_offset_val is not None:
            raw_offset_pt = float(raw_offset_val)
    except (ValueError, TypeError):
        raw_offset_pt = 0.0

    # ------------------------------------------------------------------
    # 3. Apply Parity Conversion (Points -> Millimeters)
    # ------------------------------------------------------------------
    
    # We strip the "Work Arounds". If parity is correct, 
    # the visual weight will match without artificial thinning.
    
    final_width_mm = raw_width_pt * PT_TO_MM
    final_spacing_mm = raw_spacing_pt * PT_TO_MM
    final_offset_mm = raw_offset_pt * PT_TO_MM

    # ------------------------------------------------------------------
    # 4. Apply Properties to QGIS Layer
    # ------------------------------------------------------------------
    
    # Color Parsing
    color = QColor(0, 0, 0)
    if stroke_def:
        color_def = stroke_def.get("color")
        if color_def:
            try:
                # Assuming parse_color is a helper function you have defined elsewhere
                parsed_c = parse_color(color_def) 
                if isinstance(parsed_c, QColor):
                    color = parsed_c
            except Exception:
                pass

    # Apply Configuration with explicit Millimeter units
    hatch_fill.setLineWidth(final_width_mm)
    hatch_fill.setLineWidthUnit(QgsUnitTypes.RenderMillimeters) # CHANGED from RenderPoints
    hatch_fill.setColor(color)

    hatch_fill.setDistance(final_spacing_mm)
    hatch_fill.setDistanceUnit(QgsUnitTypes.RenderMillimeters) # CHANGED from RenderPoints
    
    hatch_fill.setOffset(final_offset_mm)
    hatch_fill.setOffsetUnit(QgsUnitTypes.RenderMillimeters)

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