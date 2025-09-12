"""
Vector symbol creation module for ArcGIS to QGIS conversion.

This module provides factories for creating QGIS symbols from ArcGIS CIM symbol definitions.
It consolidates symbol creation logic that was previously scattered across multiple files.
"""

from typing import Optional, List, Dict, Any
import logging

from qgis.core import (
    QgsMarkerSymbol,
    QgsLineSymbol,
    QgsFillSymbol,
    QgsSimpleMarkerSymbolLayer,
    QgsSimpleLineSymbolLayer,
    QgsSimpleFillSymbolLayer,
    QgsSymbolLayer,
    QgsUnitTypes,
    QgsFontMarkerSymbolLayer,
    QgsMarkerLineSymbolLayer,
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor

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
            rotation = layer_def.get("rotation", 0.0) # --- ADD THIS LINE ---
            marker_layer.setSize(size)
            marker_layer.setSizeUnit(QgsUnitTypes.RenderPoints)
            marker_layer.setShape(shape)
            marker_layer.setAngle(rotation) # --- ADD THIS LINE ---

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
        """Creates a QGIS Font Marker layer from a CIMCharacterMarker definition."""
        try:
            font_layer = QgsFontMarkerSymbolLayer()
            font_family = layer_def.get("fontFamilyName", "Arial")
            character_code = layer_def.get("characterIndex", 32) # Default to space
            character = chr(character_code)

            # The color/size info is in a nested symbol definition
            nested_symbol_def = layer_def.get("symbol", {}).get("symbolLayers", [{}])[0]
            color = parse_color(nested_symbol_def.get("color"))
            size = nested_symbol_def.get("size", 6.0)

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
        
        # Process layers in reverse order to match ArcGIS rendering order
        # (ArcGIS renders from bottom to top, QGIS from top to bottom)
        for layer_def in reversed(symbol_layers):
            if not layer_def.get("enable", True):
                continue
                
            layer_type = layer_def.get("type")
            
            if layer_type == "CIMSolidStroke":
                symbol_layer = SymbolFactory._create_solid_stroke_layer(layer_def)
                if symbol_layer:
                    line_symbol.appendSymbolLayer(symbol_layer)
            elif layer_type == "CIMCharacterMarker":
                symbol_layer = SymbolFactory._create_character_marker_line_layer(layer_def)
                if symbol_layer:
                    line_symbol.appendSymbolLayer(symbol_layer)
            elif layer_type == "CIMVectorMarker":
                symbol_layer = SymbolFactory._create_vector_marker_line_layer(layer_def)
                if symbol_layer:
                    line_symbol.appendSymbolLayer(symbol_layer)
            else:
                logger.warning(f"Unsupported line layer type: {layer_type}")
        
        # If no valid layers were created, add a default one
        if line_symbol.symbolLayerCount() == 0:
            default_layer = SymbolFactory._create_default_line_layer()
            line_symbol.appendSymbolLayer(default_layer)
            
        return line_symbol
    
    @staticmethod
    def _create_character_marker_line_layer(layer_def: Dict[str, Any]) -> Optional[QgsMarkerLineSymbolLayer]:
        """Creates a QGIS Marker Line from an ArcGIS CIMCharacterMarker definition."""
        try:
            # 1. Create the font marker that will be placed on the line
            font_symbol_layer = QgsFontMarkerSymbolLayer()
            
            # Extract properties from the CIM definition
            font_family = layer_def.get("fontFamilyName", "Arial")
            # The characterIndex is the Unicode value of the character
            character_code = layer_def.get("characterIndex", 32) # Default to space
            character = chr(character_code)
            
            # Find the nested symbol to get the color and size
            nested_symbol_def = layer_def.get("symbol", {}).get("symbolLayers", [{}])[0]
            color = parse_color(nested_symbol_def.get("color"))
            size = nested_symbol_def.get("size", 6.0)

            font_symbol_layer.setFontFamily(font_family)
            font_symbol_layer.setCharacter(character)
            font_symbol_layer.setColor(color if color else QColor("black"))
            font_symbol_layer.setSize(size)
            font_symbol_layer.setSizeUnit(QgsUnitTypes.RenderPoints)

            # Wrap the font marker layer in a full marker symbol
            marker_symbol = QgsMarkerSymbol()
            marker_symbol.changeSymbolLayer(0, font_symbol_layer)

            # 2. Create the marker line and set our font marker as its symbol
            marker_line_layer = QgsMarkerLineSymbolLayer()
            marker_line_layer.setSubSymbol(marker_symbol)

            # 3. Configure placement (how often the character repeats)
            placement = layer_def.get("markerPlacement", {})
            if placement.get("type") == "CIMMarkerPlacementAlongLineSameSize":
                interval = placement.get("placementTemplate", [10])[0]
                marker_line_layer.setInterval(interval)
                marker_line_layer.setIntervalUnit(QgsUnitTypes.RenderPoints)

            return marker_line_layer

        except Exception as e:
            logger.error(f"Failed to create character marker line layer: {e}")
            return None

    @staticmethod
    def _create_vector_marker_line_layer(layer_def: Dict[str, Any]) -> Optional[QgsMarkerLineSymbolLayer]:
        """
        Creates a QGIS Marker Line from an ArcGIS CIMVectorMarker definition.
        Improved to handle various marker types and placement patterns.
        """
        try:
            # Extract key properties
            size = layer_def.get("size", 4.0)
            rotation = layer_def.get("rotation", 0.0)
            
            # Analyze the marker graphics to determine what type of marker this is
            marker_graphics = layer_def.get("markerGraphics", [])
            if not marker_graphics:
                return None
            
            graphic = marker_graphics[0]
            geometry = graphic.get("geometry", {})
            
            # Create appropriate marker based on geometry type
            marker_symbol = QgsMarkerSymbol()
            marker_symbol.deleteSymbolLayer(0)
            
            if "paths" in geometry:
                # Line-based marker (like tick marks)
                line_marker = QgsSimpleMarkerSymbolLayer()
                line_marker.setShape(QgsSimpleMarkerSymbolLayer.Line)
                
                # Calculate appropriate size
                frame = layer_def.get("frame", {})
                if frame:
                    frame_width = abs(frame.get("xmax", 1) - frame.get("xmin", -1))
                    frame_height = abs(frame.get("ymax", 1) - frame.get("ymin", -1))
                    marker_size = max(frame_width, frame_height) * size / 2
                else:
                    marker_size = size
                
                # Ensure reasonable size
                marker_size = max(marker_size, 2.0)
                marker_size = min(marker_size, 20.0)  # Prevent overly large markers
                
                line_marker.setSize(marker_size)
                line_marker.setSizeUnit(QgsUnitTypes.RenderPoints)
                line_marker.setAngle(rotation)
                
                # Set color from nested symbol
                symbol_def = graphic.get("symbol", {})
                if symbol_def:
                    symbol_layers = symbol_def.get("symbolLayers", [])
                    if symbol_layers:
                        stroke_color = parse_color(symbol_layers[0].get("color"))
                        if stroke_color:
                            line_marker.setColor(stroke_color)
                
                marker_symbol.appendSymbolLayer(line_marker)
                
            else:
                # For other marker types, use existing logic
                marker_symbol = SymbolFactory.create_marker_symbol(layer_def)
                if not marker_symbol:
                    return None

            # Create the marker line layer
            marker_line_layer = QgsMarkerLineSymbolLayer()
            marker_line_layer.setSubSymbol(marker_symbol)

            # Configure placement
            placement = layer_def.get("markerPlacement", {})
            placement_type = placement.get("type", "")
            
            if "AlongLineSameSize" in placement_type:
                template = placement.get("placementTemplate", [10])
                interval = template[0] if template else 10
                
                # Ensure reasonable interval
                interval = max(interval, 2.0)
                interval = min(interval, 100.0)
                
                marker_line_layer.setInterval(interval)
                marker_line_layer.setIntervalUnit(QgsUnitTypes.RenderPoints)
                
                # Handle offset
                offset = placement.get("offset", 0)
                if offset != 0:
                    marker_line_layer.setOffset(offset)
                    marker_line_layer.setOffsetUnit(QgsUnitTypes.RenderPoints)
                    
                # Handle offset along line
                offset_along = placement.get("offsetAlongLine", 0)
                if offset_along != 0:
                    marker_line_layer.setOffsetAlongLine(offset_along)
                    marker_line_layer.setOffsetAlongLineUnit(QgsUnitTypes.RenderPoints)
            
            elif "AtRatioPositions" in placement_type:
                # Handle ratio-based placement
                positions = placement.get("positionArray", [0.5])
                if positions:
                    # For now, convert to interval-based placement
                    # This is a simplification but should work for most cases
                    marker_line_layer.setPlacement(QgsMarkerLineSymbolLayer.CentralPoint)
            
            return marker_line_layer

        except Exception as e:
            logger.error(f"Failed to create vector marker line layer: {e}")
            return None
    
    @staticmethod
    def create_fill_symbol(symbol_def: Dict[str, Any]) -> QgsFillSymbol:
        """
        Create a QGIS fill symbol from an ArcGIS polygon/fill symbol definition.
        This version correctly handles symbols with no fill (hollow).
        """
        fill_symbol = QgsFillSymbol()
        fill_symbol.deleteSymbolLayer(0)  # Remove default layer

        symbol_layers = symbol_def.get("symbolLayers", [])
        if not symbol_layers:
            # Create a default simple fill if no layers are defined at all
            fill_symbol.appendSymbolLayer(SymbolFactory._create_default_fill_layer())
            return fill_symbol

        # Explicitly find the fill and stroke definitions from the symbol layers
        fill_def = next((layer for layer in symbol_layers if layer.get("type") == "CIMSolidFill" and layer.get("enable", True)), None)
        stroke_def = next((layer for layer in symbol_layers if layer.get("type") == "CIMSolidStroke" and layer.get("enable", True)), None)

        fill_layer = QgsSimpleFillSymbolLayer()

        # 1. Configure the FILL (Interior)
        if fill_def:
            fill_color = parse_color(fill_def.get("color"))
            if fill_color:
                fill_layer.setFillColor(fill_color)
        else:
            # THIS IS THE FIX: If no fill is defined, set the style to NoBrush.
            fill_layer.setBrushStyle(Qt.NoBrush)

        # 2. Configure the STROKE (Outline)
        if stroke_def:
            stroke_color = parse_color(stroke_def.get("color"))
            stroke_width = stroke_def.get("width", 0.26)
            if stroke_color:
                fill_layer.setStrokeColor(stroke_color)
            fill_layer.setStrokeWidth(stroke_width)
            fill_layer.setStrokeWidthUnit(QgsUnitTypes.RenderPoints)
            # The default stroke style is Qt.SolidLine, which is what we want.
        else:
            # If no stroke is defined either, explicitly set style to NoPen.
            fill_layer.setStrokeStyle(Qt.NoPen)

        fill_symbol.appendSymbolLayer(fill_layer)
        return fill_symbol
    
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
            if width > 0:
                width = max(width, 0.1)
            
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