"""
Creates QGIS fill symbol layers from ArcGIS CIM definitions.
Handles solid, hatch, picture, and other fill types.
"""
import logging
import base64
import tempfile
import os
import hashlib
from pathlib import Path
from typing import Optional, Dict, Any

from qgis.core import (
    QgsMarkerSymbol, QgsPointPatternFillSymbolLayer, QgsSimpleFillSymbolLayer,
    QgsRasterFillSymbolLayer, QgsSymbolLayer, QgsUnitTypes
)
from qgis.PyQt.QtCore import Qt, QByteArray, QBuffer, QIODevice
from qgis.PyQt.QtGui import QColor, QImage

from arc_to_q.converters.utils import parse_color
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


def _create_stroke_as_fill_layer(layer_def: Dict[str, Any]) -> Optional[QgsSimpleFillSymbolLayer]:
    """Creates a simple fill layer used only for its stroke properties."""
    if stroke_layer := create_solid_stroke_layer(layer_def):
        simple_stroke = QgsSimpleFillSymbolLayer()
        simple_stroke.setStrokeColor(stroke_layer.color())
        simple_stroke.setStrokeWidth(stroke_layer.width())
        simple_stroke.setStrokeWidthUnit(stroke_layer.widthUnit())
        simple_stroke.setPenJoinStyle(stroke_layer.penJoinStyle())
        simple_stroke.setBrushStyle(Qt.NoBrush)
        return simple_stroke
    return None


def _create_hatch_fill_layer(layer_def: Dict[str, Any]) -> QgsSimpleFillSymbolLayer:
    """Creates a hatch fill layer by mapping rotation to a QGIS BrushStyle."""
    hatch_fill = QgsSimpleFillSymbolLayer()
    
    # 1. Get rotation and normalize it to 0-179 range
    # This handles negative angles (-90 -> 90) and standardizes geometry
    raw_rotation = layer_def.get("rotation", 0.0)
    normalized_rotation = int(raw_rotation) % 180
    
    # 2. Map normalized angles to Qt Patterns
    # 0 = Horizontal, 90 = Vertical, 45 = BDiag (///), 135 = FDiag (\\\)
    style_map = {
        0: Qt.HorPattern, 
        90: Qt.VerPattern,
        45: Qt.BDiagPattern, 
        135: Qt.FDiagPattern
    }
    
    brush_style = style_map.get(normalized_rotation, Qt.SolidPattern)
    
    if brush_style == Qt.SolidPattern and normalized_rotation not in [0, 90, 45, 135]:
        logger.warning(f"Unsupported CIMHatchFill rotation: {raw_rotation} (Norm: {normalized_rotation}). Defaulting to solid.")
    
    hatch_fill.setBrushStyle(brush_style)

    line_def = layer_def.get("lineSymbol", {}).get("symbolLayers", [{}])[0]
    if color_def := line_def.get("color"):
        hatch_fill.setColor(parse_color(color_def) or QColor("black"))

    hatch_fill.setStrokeStyle(Qt.NoPen)
    return hatch_fill


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