
"""
Vector symbol creation module for ArcGIS to QGIS conversion.

This module provides factories for creating QGIS symbols from ArcGIS CIM symbol definitions.
It consolidates symbol creation logic that was previously scattered across multiple files.
"""

from typing import Optional, List, Dict, Any, Union
import logging
import base64
import tempfile
import os

from qgis.core import (
    QgsMarkerSymbol,
    QgsLineSymbol,
    QgsFillSymbol,
    QgsSimpleMarkerSymbolLayer,
    QgsSimpleLineSymbolLayer,
    QgsSimpleFillSymbolLayer,
    QgsPointPatternFillSymbolLayer,
    QgsSymbolLayer,
    QgsUnitTypes,
    QgsFontMarkerSymbolLayer,
    QgsMarkerLineSymbolLayer,
    QgsLinePatternFillSymbolLayer,
    QgsRasterFillSymbolLayer,
)
from qgis.PyQt.QtCore import Qt, QPointF
from qgis.PyQt.QtGui import QColor, QImage

from arc_to_q.converters.utils import parse_color

logger = logging.getLogger(__name__)


class SymbolCreationError(Exception):
    """Raised when symbol creation fails."""
    pass


class SymbolFactory:
    """Factory class for creating QGIS symbols from ArcGIS CIM definitions."""
    
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
    
    # Mapping ArcGIS line styles to Qt pen styles
    LINE_STYLE_MAP = {
        "Solid": Qt.SolidLine,
        "Dash": Qt.DashLine,
        "Dot": Qt.DotLine,
        "DashDot": Qt.DashDotLine,
        "DashDotDot": Qt.DashDotDotLine
    }
    
    @staticmethod
    def create_symbol(symbol_def: Dict[str, Any]) -> Optional[QgsSymbolLayer]:
        """
        Create a QGIS symbol from an ArcGIS CIM symbol definition.
        
        Args:
            symbol_def: The ArcGIS CIM symbol definition dictionary
            
        Returns:
            QgsSymbolLayer: The created QGIS symbol, or None if creation failed
            
        Raises:
            SymbolCreationError: If the symbol definition is invalid or unsupported
        """
        if not symbol_def or not isinstance(symbol_def, dict):
            raise SymbolCreationError("Symbol definition is required and must be a dictionary")
        
        # Handle symbol reference wrapper
        if symbol_def.get("type") == "CIMSymbolReference":
            symbol_def = symbol_def.get("symbol", {})
        
        symbol_type = symbol_def.get("type", "").lower()
        
        try:
            if "point" in symbol_type or "marker" in symbol_type:
                return SymbolFactory.create_marker_symbol(symbol_def)
            elif "line" in symbol_type:
                return SymbolFactory.create_line_symbol(symbol_def)
            elif "polygon" in symbol_type or "fill" in symbol_type:
                return SymbolFactory.create_fill_symbol(symbol_def)
            else:
                raise SymbolCreationError(f"Unsupported symbol type: {symbol_type}")
                
        except Exception as e:
            logger.error(f"Failed to create symbol from definition: {e}")
            raise SymbolCreationError(f"Symbol creation failed: {str(e)}")
    
    @staticmethod
    def create_marker_symbol(symbol_def: Dict[str, Any]) -> QgsMarkerSymbol:
        """
        Create a QGIS marker symbol from an ArcGIS CIM definition, handling both
        CIMVectorMarker (shapes) and CIMCharacterMarker (fonts).
        """
        marker_symbol = QgsMarkerSymbol()
        marker_symbol.deleteSymbolLayer(0)  # Start with a blank symbol

        # The definition can be a composite symbol with layers, or a direct marker definition
        arc_layers = symbol_def.get("symbolLayers", [])
        if not arc_layers and "type" in symbol_def:
            arc_layers = [symbol_def]

        if not arc_layers:
            marker_symbol.appendSymbolLayer(SymbolFactory._create_default_marker_layer())
            return marker_symbol

        # Look for the primary marker type within the definition's layers
        vector_def = next((l for l in arc_layers if l.get("type") == "CIMVectorMarker"), None)
        char_def = next((l for l in arc_layers if l.get("type") == "CIMCharacterMarker"), None)

        qgis_layer = None
        if vector_def:
            qgis_layer = SymbolFactory._create_simple_marker_from_vector(vector_def)
        elif char_def:
            qgis_layer = SymbolFactory._create_font_marker_from_character(char_def)

        if qgis_layer:
            marker_symbol.appendSymbolLayer(qgis_layer)
        else:
            # Fallback if parsing failed or type not found
            logger.warning(f"Could not create a specific marker layer for symbol; using default.")
            marker_symbol.appendSymbolLayer(SymbolFactory._create_default_marker_layer())

        return marker_symbol
    
    @staticmethod
    def _create_simple_marker_from_vector(layer_def: Dict[str, Any]) -> Optional[QgsSimpleMarkerSymbolLayer]:
        """Creates a QGIS Simple Marker from an ArcGIS CIMVectorMarker definition."""
        try:
            marker_layer = QgsSimpleMarkerSymbolLayer()

            # Set basic properties: size, shape, and rotation
            size = layer_def.get("size", 6.0)
            shape = SymbolFactory._determine_marker_shape(layer_def)
            rotation = layer_def.get("rotation", 0.0)
            marker_layer.setSize(size)
            marker_layer.setSizeUnit(QgsUnitTypes.RenderPoints)
            marker_layer.setShape(shape)
            marker_layer.setAngle(rotation)

            # Find the nested fill and stroke definitions from the JSON
            graphic = layer_def.get("markerGraphics", [{}])[0]
            graphic_symbol_layers = graphic.get("symbol", {}).get("symbolLayers", [])
            fill_def = next((sl for sl in graphic_symbol_layers if sl.get("type") == "CIMSolidFill"), None)
            stroke_def = next((sl for sl in graphic_symbol_layers if sl.get("type") == "CIMSolidStroke"), None)

            # Configure the FILL
            if fill_def:
                fill_color = parse_color(fill_def.get("color"))
                if fill_color and fill_color.alpha() > 0:
                    marker_layer.setColor(fill_color)
                else:
                    marker_layer.setColor(QColor(0, 0, 0, 0)) # Transparent
            else:
                marker_layer.setColor(QColor(0, 0, 0, 0)) # Transparent

            # Configure the STROKE
            if stroke_def:
                stroke_color = parse_color(stroke_def.get("color"))
                stroke_width = stroke_def.get("width", 0.26)
                if stroke_color and stroke_width > 0:
                    marker_layer.setStrokeStyle(Qt.SolidLine)
                    marker_layer.setStrokeColor(stroke_color)
                    marker_layer.setStrokeWidth(stroke_width)
                    marker_layer.setStrokeWidthUnit(QgsUnitTypes.RenderPoints)
                else:
                    marker_layer.setStrokeStyle(Qt.NoPen)
            else:
                marker_layer.setStrokeStyle(Qt.NoPen)
            
            return marker_layer
        except Exception as e:
            logger.error(f"Failed to create simple marker from vector: {e}")
            return None
    
    @staticmethod
    def _create_font_marker_from_character(layer_def: Dict[str, Any]) -> Optional[QgsFontMarkerSymbolLayer]:
        """
        Creates a QGIS Font Marker layer from a CIMCharacterMarker definition.
        NOTE: This function relies on a correct mapping from ESRI font characterIndex to
        a Unicode character. For custom/non-Unicode ESRI fonts, this may produce
        incorrect glyphs. Prefer CIMVectorMarker with embedded geometry where possible.
        """
        try:
            font_layer = QgsFontMarkerSymbolLayer()
            font_family = layer_def.get("fontFamilyName", "Arial")
            character_code = layer_def.get("characterIndex", 32) # Default to space
            character = chr(character_code)

            # The color/size info is in a nested symbol definition
            color = QColor("black") # Default color
            nested_symbol_def = layer_def.get("symbol", {})
            if nested_symbol_def:
                symbol_layers = nested_symbol_def.get("symbolLayers", [])
                # Find the solid fill layer which defines the character's color
                fill_layer_def = next((l for l in symbol_layers if l.get("type") == "CIMSolidFill"), None)
                if fill_layer_def and "color" in fill_layer_def:
                    parsed_color = parse_color(fill_layer_def["color"])
                    if parsed_color:
                        color = parsed_color
            size = layer_def.get("size", 6.0)

            font_layer.setFontFamily(font_family)
            font_layer.setCharacter(character)
            font_layer.setColor(color if color else QColor("black"))
            font_layer.setSize(size)
            font_layer.setSizeUnit(QgsUnitTypes.RenderPoints)

            return font_layer
        except Exception as e:
            logger.error(f"Failed to create font marker from character: {e}")
            return None
            
    @staticmethod
    def create_line_symbol(symbol_def: Dict[str, Any]) -> QgsLineSymbol:
        """
        Create a QGIS line symbol from an ArcGIS line symbol definition.
        Handles complex multi-layer symbols properly.
        """
        line_symbol = QgsLineSymbol()
        line_symbol.deleteSymbolLayer(0)  # Remove default layer
        
        symbol_layers = symbol_def.get("symbolLayers", [])
        if not symbol_layers:
            # Create a default simple line if no layers defined
            default_layer = SymbolFactory._create_default_line_layer()
            line_symbol.appendSymbolLayer(default_layer)
            return line_symbol
        
        for layer_def in reversed(symbol_layers):
            if not layer_def.get("enable", True):
                continue
                
            layer_type = layer_def.get("type")
            
            qgis_layers: List[QgsSymbolLayer] = []
            if layer_type == "CIMSolidStroke":
                layer = SymbolFactory._create_solid_stroke_layer(layer_def)
                if layer:
                    qgis_layers.append(layer)
            elif layer_type == "CIMCharacterMarker":
                qgis_layers = SymbolFactory._create_character_marker_line_layers(layer_def)
            elif layer_type == "CIMVectorMarker":
                qgis_layers = SymbolFactory._create_vector_marker_line_layers(layer_def)
            else:
                logger.warning(f"Unsupported line layer type: {layer_type}")

            for layer in qgis_layers:
                line_symbol.appendSymbolLayer(layer)
        
        if line_symbol.symbolLayerCount() == 0:
            default_layer = SymbolFactory._create_default_line_layer()
            line_symbol.appendSymbolLayer(default_layer)
            
        return line_symbol

    @staticmethod
    def _configure_basic_placement(marker_line_layer: QgsMarkerLineSymbolLayer, layer_def: Dict[str, Any]):
        """Configures properties common to all placement types."""
        placement = layer_def.get("markerPlacement", {})
        if not placement:
            return

        if placement.get("angleToLine", False):
            marker_line_layer.setRotateMarker(True)

        if placement.get("placePerPart", False):
        # This handles rendering on each part of a multipart line feature.
            marker_line_layer.setPlaceOnEveryPart(True)

    @staticmethod
    def _create_character_marker_line_layers(layer_def: Dict[str, Any]) -> List[QgsMarkerLineSymbolLayer]:
        """Creates one or more QGIS Marker Line layers from an ArcGIS CIMCharacterMarker definition."""
        try:
            sub_symbol_layer = SymbolFactory._create_font_marker_from_character(layer_def)
            if not sub_symbol_layer:
                return []
            marker_symbol = QgsMarkerSymbol([sub_symbol_layer])
            return SymbolFactory._create_marker_line_layers_from_sub_symbol(marker_symbol, layer_def)
        except Exception as e:
            logger.error(f"Failed to create character marker line layers: {e}")
            return []

    @staticmethod
    def _create_vector_marker_line_layers(layer_def: Dict[str, Any]) -> List[QgsMarkerLineSymbolLayer]:
        """Creates one or more QGIS Marker Line layers from an ArcGIS CIMVectorMarker definition."""
        try:
            marker_symbol = SymbolFactory.create_marker_symbol(layer_def)
            if not marker_symbol or marker_symbol.symbolLayerCount() == 0:
                logger.warning("Failed to create a valid sub-symbol for vector marker line.")
                return []
            return SymbolFactory._create_marker_line_layers_from_sub_symbol(marker_symbol, layer_def)
        except Exception as e:
            logger.error(f"Failed to create vector marker line layers: {e}")
            return []

    @staticmethod
    def _create_marker_line_layers_from_sub_symbol(sub_symbol: QgsMarkerSymbol, layer_def: Dict[str, Any]) -> List[QgsMarkerLineSymbolLayer]:
        """Creates marker line layers for a given sub-symbol based on placement rules."""
        placement = layer_def.get("markerPlacement", {})
        placement_type = placement.get("type", "")

        if "AlongLineSameSize" in placement_type:
            # For repeating markers that need their base on the line,
            symbol_layer = sub_symbol.symbolLayer(0)
            if symbol_layer and "offset" in placement:
                size = layer_def.get("size", 6.0)
                offset_y = -size/1.4
                symbol_layer.setOffset(QPointF(0, offset_y))
                symbol_layer.setOffsetUnit(QgsUnitTypes.RenderPoints)

            elif symbol_layer:
                size = layer_def.get("size", 6.0)
                offset_y = -size*0.15
                symbol_layer.setOffset(QPointF(0, offset_y))
                symbol_layer.setOffsetUnit(QgsUnitTypes.RenderPoints)

        qgis_layers = []

        if "AtRatioPositions" in placement_type:
            positions = placement.get("positionArray", [0.5])
            
            # Handle the case that requires two separate layers for start and end vertices
            if 0.0 in positions and 1.0 in positions:
                # Layer 1: First Vertex
                start_layer = QgsMarkerLineSymbolLayer()
                start_layer.setSubSymbol(sub_symbol.clone())
                SymbolFactory._configure_basic_placement(start_layer, layer_def)
                start_layer.setPlacement(QgsMarkerLineSymbolLayer.Placement.FirstVertex)
                qgis_layers.append(start_layer)
                
                # Layer 2: Last Vertex
                end_layer = QgsMarkerLineSymbolLayer()
                end_layer.setSubSymbol(sub_symbol.clone())
                SymbolFactory._configure_basic_placement(end_layer, layer_def)
                end_layer.setPlacement(QgsMarkerLineSymbolLayer.Placement.LastVertex)
                qgis_layers.append(end_layer)
                
                # Handle any other positions if they exist
                other_positions = [p for p in positions if p not in [0.0, 1.0]]
                if other_positions:
                     logger.warning(f"Combined start/end and other ratio positions ({other_positions}) are not fully supported.")

            else: # Handle single position cases
                marker_layer = QgsMarkerLineSymbolLayer()
                marker_layer.setSubSymbol(sub_symbol.clone())
                SymbolFactory._configure_basic_placement(marker_layer, layer_def)
                if positions == [0.5]:
                    marker_layer.setPlacement(QgsMarkerLineSymbolLayer.Placement.CentralPoint)
                elif positions == [0.0]:
                     marker_layer.setPlacement(QgsMarkerLineSymbolLayer.Placement.FirstVertex)
                elif positions == [1.0]:
                     marker_layer.setPlacement(QgsMarkerLineSymbolLayer.Placement.LastVertex)
                else:
                    logger.warning(f"Complex AtRatioPositions {positions} not fully supported; falling back to CentralPoint.")
                    marker_layer.setPlacement(QgsMarkerLineSymbolLayer.Placement.CentralPoint)
                qgis_layers.append(marker_layer)

        elif "AlongLineSameSize" in placement_type:
            marker_layer = QgsMarkerLineSymbolLayer()
            marker_layer.setSubSymbol(sub_symbol.clone())
            SymbolFactory._configure_basic_placement(marker_layer, layer_def)
            
            use_map_units = layer_def.get("scaleSymbolsProportionally", False) or layer_def.get("respectFrame", False)
            qgis_unit = QgsUnitTypes.RenderMapUnits if use_map_units else QgsUnitTypes.RenderPoints

            template = placement.get("placementTemplate", [10])
            interval = template[0] if template else 10
            marker_layer.setInterval(interval)
            marker_layer.setIntervalUnit(QgsUnitTypes.RenderPoints)
            
            offset = placement.get("offset", 0)
            if offset != 0:
                marker_layer.setOffset(offset)
                marker_layer.setOffsetUnit(QgsUnitTypes.RenderPoints)
            
                
            qgis_layers.append(marker_layer)
        
        else: # Default or unknown placement
            marker_layer = QgsMarkerLineSymbolLayer()
            marker_layer.setSubSymbol(sub_symbol.clone())
            SymbolFactory._configure_basic_placement(marker_layer, layer_def)
            qgis_layers.append(marker_layer)

        return qgis_layers
    
    @staticmethod
    def create_fill_symbol(symbol_def: Dict[str, Any]) -> QgsFillSymbol:
        """
        Create a QGIS fill symbol from an ArcGIS polygon/fill symbol definition.
        Handles multi-layer fills including solid, hatch, and picture fills.
        """
        fill_symbol = QgsFillSymbol()
        fill_symbol.deleteSymbolLayer(0)  # Remove default layer

        symbol_layers = symbol_def.get("symbolLayers", [])
        if not symbol_layers:
            fill_symbol.appendSymbolLayer(SymbolFactory._create_default_fill_layer())
            return fill_symbol

        # Process layers in reverse to match ArcGIS rendering order
        for layer_def in reversed(symbol_layers):
            if not layer_def.get("enable", True):
                continue

            layer_type = layer_def.get("type")
            qgis_layer = None

            if layer_type == "CIMSolidFill":
                # Create a simple fill layer for the solid color
                fill_color = parse_color(layer_def.get("color"))
                if fill_color:
                    simple_fill = QgsSimpleFillSymbolLayer()
                    simple_fill.setFillColor(fill_color)
                    simple_fill.setStrokeStyle(Qt.NoPen) # Fill layers have no stroke
                    qgis_layer = simple_fill

            elif layer_type == "CIMSolidStroke":
                # Create a simple fill layer and use it only for the stroke
                stroke_layer = SymbolFactory._create_solid_stroke_layer(layer_def)
                if stroke_layer:
                    simple_stroke = QgsSimpleFillSymbolLayer()
                    simple_stroke.setStrokeColor(stroke_layer.color())
                    simple_stroke.setStrokeWidth(stroke_layer.width())
                    simple_stroke.setStrokeWidthUnit(stroke_layer.widthUnit())
                    simple_stroke.setPenJoinStyle(stroke_layer.penJoinStyle())
                    simple_stroke.setBrushStyle(Qt.NoBrush) # Stroke layers have no fill
                    qgis_layer = simple_stroke
            
            elif layer_type == "CIMCharacterMarker":
                try:
                    # 1. Create the font marker with the correct color logic
                    font_marker_layer = SymbolFactory._create_font_marker_from_character(layer_def)
                    if not font_marker_layer:
                        continue

                    # 2. Create a marker symbol to hold the font marker layer
                    sub_symbol = QgsMarkerSymbol([font_marker_layer])

                    # 3. Create the point pattern fill layer
                    point_pattern_layer = QgsPointPatternFillSymbolLayer()
                    point_pattern_layer.setSubSymbol(sub_symbol)

                    # 4. Get placement properties to set the pattern spacing
                    placement = layer_def.get("markerPlacement", {})
                    step_x = placement.get("stepX", 5.0)
                    step_y = placement.get("stepY", 5.0)

                    point_pattern_layer.setDistanceX(step_x)
                    point_pattern_layer.setDistanceY(step_y)

                    # --- API FIX FOR QGIS 3.4 ---
                    # Use setDistanceXUnit and setDistanceYUnit instead of setDistanceUnit
                    point_pattern_layer.setDistanceXUnit(QgsUnitTypes.RenderPoints)
                    point_pattern_layer.setDistanceYUnit(QgsUnitTypes.RenderPoints)
                    # --- END OF API FIX ---

                    qgis_layer = point_pattern_layer
                except Exception as e:
                    logger.error(f"Failed to create point pattern fill layer: {e}")

            elif layer_type == "CIMHatchFill":
                # Create a simple fill and map the CIM rotation to a QGIS BrushStyle.
                hatch_fill = QgsSimpleFillSymbolLayer()
                rotation = layer_def.get("rotation", 0.0)
                
                brush_style = Qt.NoBrush
                if rotation == 90:
                    brush_style = Qt.VerPattern      # Vertical |
                elif rotation == 0 or rotation == 180:
                    brush_style = Qt.HorPattern      # Horizontal -
                elif rotation == 45:
                    brush_style = Qt.BDiagPattern    # Backward Diagonal \
                elif rotation == 135:
                    brush_style = Qt.FDiagPattern    # Forward Diagonal /
                else:
                    logger.warning(f"Unsupported CIMHatchFill rotation: {rotation}. Defaulting to solid.")
                    brush_style = Qt.SolidPattern

                hatch_fill.setBrushStyle(brush_style)

                # Get the color for the hash lines from the CIM definition.
                line_layer_def = layer_def.get("lineSymbol", {}).get("symbolLayers", [{}])[0]
                if line_layer_def:
                    color_def = line_layer_def.get("color")
                    line_color = parse_color(color_def) if color_def else QColor("black")
                    # For a hash fill, the main color is used for the pattern lines.
                    hatch_fill.setColor(line_color)

                hatch_fill.setStrokeStyle(Qt.NoPen) # Ensure no border is drawn by this layer.
                qgis_layer = hatch_fill

            elif layer_type == "CIMPictureFill":
                qgis_layer = SymbolFactory._create_picture_fill_layer(layer_def)

            else:
                logger.warning(f"Unsupported fill layer type: {layer_type}")

            if qgis_layer:
                fill_symbol.appendSymbolLayer(qgis_layer)

        if fill_symbol.symbolLayerCount() == 0:
            fill_symbol.appendSymbolLayer(SymbolFactory._create_default_fill_layer())

        return fill_symbol

    @staticmethod
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
            image.loadFromData(image_data, 'BMP')

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

            # Save the (potentially modified) image to a temporary PNG file to preserve transparency
            temp_dir = tempfile.gettempdir()
            file_path = os.path.join(temp_dir, "temp_arc_symbol.png") # Use PNG for transparency
            image.save(file_path, "PNG")

            # Instantiate the raster fill layer with the path to our new PNG
            picture_layer = QgsRasterFillSymbolLayer(file_path)

            # Set image size properties from the CIM definition
            image_width = layer_def.get("height", 32.0)
            picture_layer.setWidth(image_width)
            picture_layer.setWidthUnit(QgsUnitTypes.RenderPoints)

            return picture_layer
        except Exception as e:
            logger.error(f"Failed to create picture fill layer: {e}")
            return None
    
    @staticmethod
    def _create_solid_stroke_layer(layer_def: Dict[str, Any]) -> Optional[QgsSimpleLineSymbolLayer]:
        """
        Create a QGIS line symbol layer from a CIMSolidStroke definition.
        Improved to handle offsets, dash patterns, and ensure visibility.
        """
        try:
            line_layer = QgsSimpleLineSymbolLayer()
            
            # Set color and width
            color = parse_color(layer_def.get("color"))
            width = layer_def.get("width", 0.5)
            
            # Ensure minimum width for visibility, but don't alter intended thin lines too much
            #if width > 0:
               # width = max(width, 0.1)
            
            if color:
                line_layer.setColor(color)
            line_layer.setWidth(width)
            line_layer.setWidthUnit(QgsUnitTypes.RenderPoints)
            
            # Set cap and join styles from ArcGIS definition
            cap_style = layer_def.get("capStyle", "Round")
            if cap_style == "Round":
                line_layer.setPenCapStyle(Qt.RoundCap)
            elif cap_style == "Butt":
                line_layer.setPenCapStyle(Qt.FlatCap)
            elif cap_style == "Square":
                line_layer.setPenCapStyle(Qt.SquareCap)
                
            join_style = layer_def.get("joinStyle", "Round")
            if join_style == "Round":
                line_layer.setPenJoinStyle(Qt.RoundJoin)
            elif join_style == "Miter":
                line_layer.setPenJoinStyle(Qt.MiterJoin)
            elif join_style == "Bevel":
                line_layer.setPenJoinStyle(Qt.BevelJoin)
            
            # Process effects
            effects = layer_def.get("effects", [])
            for effect in effects:
                effect_type = effect.get("type")

                if effect_type == "CIMGeometricEffectOffset":
                    offset = effect.get("offset", 0.0)
                    line_layer.setOffset(offset)
                    line_layer.setOffsetUnit(QgsUnitTypes.RenderPoints)

                elif effect_type == "CIMGeometricEffectDashes":
                    dash_template = effect.get("dashTemplate", [])
                    
                    if dash_template:
                        # Clean the dash template more carefully
                        cleaned_template = []
                        for value in dash_template:
                            if isinstance(value, (int, float)) and value >= 0:
                                cleaned_template.append(float(value))
                        
                        # Remove leading and trailing zeros
                        while cleaned_template and cleaned_template[0] == 0:
                            cleaned_template.pop(0)
                        while cleaned_template and cleaned_template[-1] == 0:
                            cleaned_template.pop()
                        
                        # Only apply if we have a valid pattern
                        if len(cleaned_template) >= 2:
                            # Ensure minimum dash/gap sizes for visibility
                            min_size = 0.5
                            cleaned_template = [max(x, min_size) if x > 0 else min_size for x in cleaned_template]
                            
                            line_layer.setCustomDashVector(cleaned_template)
                            line_layer.setCustomDashPatternUnit(QgsUnitTypes.RenderPoints)
                            line_layer.setUseCustomDashPattern(True)
            
            return line_layer
            
        except Exception as e:
            logger.error(f"Failed to create solid stroke layer: {e}")
            return None

    @staticmethod
    def _determine_marker_shape(layer_def: Dict[str, Any]) -> QgsSimpleMarkerSymbolLayer.Shape:
        """Determine the QGIS marker shape from ArcGIS marker definition."""
        marker_graphics = layer_def.get("markerGraphics", [])
        if not marker_graphics:
            return QgsSimpleMarkerSymbolLayer.Circle
        
        graphic = marker_graphics[0]
        
        # Check if there's an explicit shape name
        shape_name = graphic.get("primitiveName")
        if shape_name and shape_name in SymbolFactory.MARKER_SHAPE_MAP:
            return SymbolFactory.MARKER_SHAPE_MAP[shape_name]
        
        # Analyze geometry to determine shape
        geometry = graphic.get("geometry", {})

        if "paths" in geometry:
            return QgsSimpleMarkerSymbolLayer.Line
        
        if "rings" in geometry:
            points = geometry["rings"][0]
            point_count = len(points)
            
            # Determine shape based on point count and geometry
            if point_count == 4:
                return QgsSimpleMarkerSymbolLayer.Triangle
            elif point_count == 5:
                # Check if it's a diamond or square
                unique_x = set(p[0] for p in points)
                unique_y = set(p[1] for p in points)
                if len(unique_x) == 3 and len(unique_y) == 3:
                    return QgsSimpleMarkerSymbolLayer.Diamond
                else:
                    return QgsSimpleMarkerSymbolLayer.Square
            elif point_count == 6:
                return QgsSimpleMarkerSymbolLayer.Pentagon
            elif point_count == 7:
                return QgsSimpleMarkerSymbolLayer.Hexagon
            elif point_count == 11:
                return QgsSimpleMarkerSymbolLayer.Star
            elif point_count == 13:
                return QgsSimpleMarkerSymbolLayer.Cross
                
        elif "curveRings" in geometry:
            curve_points = [p for p in geometry["curveRings"][0] if isinstance(p, list)]
            if len(curve_points) == 13:
                return QgsSimpleMarkerSymbolLayer.Cross2
            else:
                return QgsSimpleMarkerSymbolLayer.Circle
        
        # Default to circle for unknown shapes
        logger.warning(f"Unknown marker shape, defaulting to circle")
        return QgsSimpleMarkerSymbolLayer.Circle
    
    @staticmethod
    def _create_default_marker_layer() -> QgsSimpleMarkerSymbolLayer:
        """Create a default marker symbol layer."""
        layer = QgsSimpleMarkerSymbolLayer()
        layer.setShape(QgsSimpleMarkerSymbolLayer.Circle)
        layer.setSize(6.0)
        layer.setColor(QColor(255, 0, 0))  # Red
        layer.setStrokeColor(QColor(0, 0, 0))  # Black outline
        return layer
    
    @staticmethod
    def _create_default_line_layer() -> QgsSimpleLineSymbolLayer:
        """Create a default line symbol layer."""
        layer = QgsSimpleLineSymbolLayer()
        layer.setColor(QColor(0, 0, 255))  # Blue
        layer.setWidth(0.5)
        return layer
    
    @staticmethod
    def _create_default_fill_layer() -> QgsSimpleFillSymbolLayer:
        """Create a default fill symbol layer."""
        layer = QgsSimpleFillSymbolLayer()
        layer.setFillColor(QColor(0, 255, 0, 100))  # Semi-transparent green
        layer.setStrokeColor(QColor(0, 0, 0))  # Black outline
        layer.setStrokeWidth(0.5)
        return layer


class SymbolStyler:
    """Utility class for applying common styling operations to symbols."""
    
    @staticmethod
    def set_size_from_scale(symbol: QgsMarkerSymbol, size: float, scale_factor: float = 1.0):
        """Set symbol size accounting for map scale."""
        adjusted_size = size * scale_factor
        symbol.setSize(adjusted_size)
        symbol.setSizeUnit(QgsUnitTypes.RenderPoints)
    
    @staticmethod
    def apply_rotation(symbol: QgsMarkerSymbol, angle: float):
        """Apply rotation to a marker symbol."""
        symbol.setAngle(angle)
    
    @staticmethod
    def set_opacity(symbol, opacity: float):
        """Set symbol opacity (0.0 to 1.0)."""
        symbol.setOpacity(opacity)
    
    @staticmethod
    def apply_offset(symbol: QgsMarkerSymbol, x_offset: float, y_offset: float):
        """Apply offset to a marker symbol."""
        symbol.setOffset(x_offset, y_offset)
        symbol.setOffsetUnit(QgsUnitTypes.RenderPoints)


# Convenience functions for common symbol creation patterns
def create_simple_point_symbol(color: QColor = QColor(255, 0, 0), 
                               size: float = 6.0, 
                               shape: str = "Circle") -> QgsMarkerSymbol:
    """Create a simple point symbol with specified properties."""
    symbol = QgsMarkerSymbol()
    layer = symbol.symbolLayer(0)
    
    if isinstance(layer, QgsSimpleMarkerSymbolLayer):
        layer.setColor(color)
        layer.setSize(size)
        if shape in SymbolFactory.MARKER_SHAPE_MAP:
            layer.setShape(SymbolFactory.MARKER_SHAPE_MAP[shape])
    
    return symbol


def create_simple_line_symbol(color: QColor = QColor(0, 0, 255), 
                              width: float = 1.0) -> QgsLineSymbol:
    """Create a simple line symbol with specified properties."""
    symbol = QgsLineSymbol()
    layer = symbol.symbolLayer(0)
    
    if isinstance(layer, QgsSimpleLineSymbolLayer):
        layer.setColor(color)
        layer.setWidth(width)
    
    return symbol


def create_simple_fill_symbol(fill_color: QColor = QColor(0, 255, 0, 100),
                              outline_color: QColor = QColor(0, 0, 0),
                              outline_width: float = 0.5) -> QgsFillSymbol:
    """Create a simple fill symbol with specified properties."""
    symbol = QgsFillSymbol()
    layer = symbol.symbolLayer(0)
    
    if isinstance(layer, QgsSimpleFillSymbolLayer):
        layer.setFillColor(fill_color)
        layer.setStrokeColor(outline_color)
        layer.setStrokeWidth(outline_width)
    
    return symbol
