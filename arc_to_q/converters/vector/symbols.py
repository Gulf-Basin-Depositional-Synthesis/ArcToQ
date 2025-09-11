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
    QgsUnitTypes
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
        Create a QGIS marker symbol from an ArcGIS point/marker symbol definition.
        
        Args:
            symbol_def: ArcGIS CIM marker symbol definition
            
        Returns:
            QgsMarkerSymbol: The created marker symbol
        """
        marker_symbol = QgsMarkerSymbol()
        marker_symbol.deleteSymbolLayer(0)  # Remove default layer
        
        symbol_layers = symbol_def.get("symbolLayers", [])
        if not symbol_layers:
            # Create a default simple marker if no layers defined
            default_layer = SymbolFactory._create_default_marker_layer()
            marker_symbol.appendSymbolLayer(default_layer)
            return marker_symbol
        
        # Process each symbol layer
        for layer_def in symbol_layers:
            if not layer_def.get("enable", True):
                continue
                
            layer_type = layer_def.get("type")
            
            if layer_type == "CIMVectorMarker":
                symbol_layer = SymbolFactory._create_vector_marker_layer(layer_def)
                if symbol_layer:
                    marker_symbol.appendSymbolLayer(symbol_layer)
            else:
                logger.warning(f"Unsupported marker layer type: {layer_type}")
        
        # If no valid layers were created, add a default one
        if marker_symbol.symbolLayerCount() == 0:
            default_layer = SymbolFactory._create_default_marker_layer()
            marker_symbol.appendSymbolLayer(default_layer)
            
        return marker_symbol
    
    @staticmethod
    def create_line_symbol(symbol_def: Dict[str, Any]) -> QgsLineSymbol:
        """
        Create a QGIS line symbol from an ArcGIS line symbol definition.
        
        Args:
            symbol_def: ArcGIS CIM line symbol definition
            
        Returns:
            QgsLineSymbol: The created line symbol
        """
        line_symbol = QgsLineSymbol()
        line_symbol.deleteSymbolLayer(0)  # Remove default layer
        
        symbol_layers = symbol_def.get("symbolLayers", [])
        if not symbol_layers:
            # Create a default simple line if no layers defined
            default_layer = SymbolFactory._create_default_line_layer()
            line_symbol.appendSymbolLayer(default_layer)
            return line_symbol
        
        # Process each symbol layer
        for layer_def in symbol_layers:
            if not layer_def.get("enable", True):
                continue
                
            layer_type = layer_def.get("type")
            
            if layer_type == "CIMSolidStroke":
                symbol_layer = SymbolFactory._create_solid_stroke_layer(layer_def)
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
    def create_fill_symbol(symbol_def: Dict[str, Any]) -> QgsFillSymbol:
        """
        Create a QGIS fill symbol from an ArcGIS polygon/fill symbol definition.
        
        Args:
            symbol_def: ArcGIS CIM fill symbol definition
            
        Returns:
            QgsFillSymbol: The created fill symbol
        """
        fill_symbol = QgsFillSymbol()
        fill_symbol.deleteSymbolLayer(0)  # Remove default layer
        
        symbol_layers = symbol_def.get("symbolLayers", [])
        if not symbol_layers:
            # Create a default simple fill if no layers defined
            default_layer = SymbolFactory._create_default_fill_layer()
            fill_symbol.appendSymbolLayer(default_layer)
            return fill_symbol
        
        # Extract fill and stroke properties from all layers
        fill_color = None
        stroke_color = None
        stroke_width = 0.26
        
        for layer_def in symbol_layers:
            if not layer_def.get("enable", True):
                continue
                
            layer_type = layer_def.get("type")
            
            if layer_type == "CIMSolidFill":
                fill_color = parse_color(layer_def.get("color"))
            elif layer_type == "CIMSolidStroke":
                stroke_color = parse_color(layer_def.get("color"))
                stroke_width = layer_def.get("width", stroke_width)
        
        # Create the fill layer with extracted properties
        fill_layer = QgsSimpleFillSymbolLayer()
        
        if fill_color:
            fill_layer.setFillColor(fill_color)
        else:
            fill_layer.setFillColor(QColor(128, 128, 128, 100))  # Default gray fill
            
        if stroke_color:
            fill_layer.setStrokeColor(stroke_color)
            fill_layer.setStrokeWidth(stroke_width)
        else:
            fill_layer.setStrokeColor(QColor(0, 0, 0, 100))  # Default black stroke
        
        fill_symbol.appendSymbolLayer(fill_layer)
        return fill_symbol
    
    @staticmethod
    def _create_vector_marker_layer(layer_def: Dict[str, Any]) -> Optional[QgsSimpleMarkerSymbolLayer]:
        """Create a QGIS marker symbol layer from a CIMVectorMarker definition."""
        try:
            marker_layer = QgsSimpleMarkerSymbolLayer()
            
            # Set size
            size = layer_def.get("size", 6.0)
            marker_layer.setSize(size)
            
            # Determine shape from markerGraphics
            shape = SymbolFactory._determine_marker_shape(layer_def)
            marker_layer.setShape(shape)
            
            # Extract colors from marker graphics
            fill_color, stroke_color, stroke_width = SymbolFactory._extract_marker_colors(layer_def)
            
            # Handle line-based vs polygon-based shapes differently
            is_line_shape = shape in [
                QgsSimpleMarkerSymbolLayer.Cross,
                QgsSimpleMarkerSymbolLayer.Cross2,
                QgsSimpleMarkerSymbolLayer.Line
            ]
            
            if is_line_shape:
                # For line shapes, use fill color as stroke and make fill transparent
                marker_layer.setColor(QColor(0, 0, 0, 0))  # Transparent fill
                marker_layer.setStrokeColor(fill_color or QColor(0, 0, 0))
            else:
                # For polygon shapes, use both fill and stroke
                marker_layer.setColor(fill_color or QColor(128, 128, 128, 100))
                marker_layer.setStrokeColor(stroke_color or QColor(0, 0, 0, 100))
            
            marker_layer.setStrokeWidth(stroke_width)
            
            return marker_layer
            
        except Exception as e:
            logger.error(f"Failed to create vector marker layer: {e}")
            return None
    
    @staticmethod
    def _create_solid_stroke_layer(layer_def: Dict[str, Any]) -> Optional[QgsSimpleLineSymbolLayer]:
        """Create a QGIS line symbol layer from a CIMSolidStroke definition."""
        try:
            line_layer = QgsSimpleLineSymbolLayer()
            
            # Set color
            color = parse_color(layer_def.get("color"))
            line_layer.setColor(color)
            
            # Set width
            width = layer_def.get("width", 0.5)
            line_layer.setWidth(width)
            
            # Set line style (if available in the future)
            # line_style = layer_def.get("lineStyle", "Solid")
            # qt_style = SymbolFactory.LINE_STYLE_MAP.get(line_style, Qt.SolidLine)
            # line_layer.setPenStyle(qt_style)
            
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
    def _extract_marker_colors(layer_def: Dict[str, Any]) -> tuple:
        """Extract fill and stroke colors from marker graphics."""
        fill_color = QColor(128, 128, 128, 100)  # Default gray
        stroke_color = QColor(0, 0, 0, 100)      # Default black
        stroke_width = 0.0
        
        marker_graphics = layer_def.get("markerGraphics", [])
        if not marker_graphics:
            return fill_color, stroke_color, stroke_width
        
        graphic = marker_graphics[0]
        symbol = graphic.get("symbol", {})
        symbol_layers = symbol.get("symbolLayers", [])
        
        for sublayer in symbol_layers:
            layer_type = sublayer.get("type")
            
            if layer_type == "CIMSolidFill":
                fill_color = parse_color(sublayer.get("color"))
            elif layer_type == "CIMSolidStroke":
                stroke_color = parse_color(sublayer.get("color"))
                stroke_width = sublayer.get("width", 0.0)
        
        return fill_color, stroke_color, stroke_width
    
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