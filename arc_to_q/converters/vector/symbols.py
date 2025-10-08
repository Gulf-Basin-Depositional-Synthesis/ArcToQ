"""
Vector symbol creation module for ArcGIS to QGIS conversion.
This module provides a factory for creating high-level QGIS symbols by assembling
symbol layers created by specialized factory modules.
"""
from typing import Optional, List, Dict, Any
import logging

from qgis.core import QgsMarkerSymbol, QgsLineSymbol, QgsFillSymbol, QgsSymbol

from .marker_layers import (
    create_simple_marker_from_vector, create_font_marker_from_character,
    create_default_marker_layer
)
from .line_layers import create_line_layers_from_def, create_default_line_layer
from .fill_layers import create_fill_layer_from_def, create_default_fill_layer

logger = logging.getLogger(__name__)

class SymbolCreationError(Exception):
    """Raised when symbol creation fails."""
    pass

class SymbolFactory:
    """Factory for creating QGIS symbols from ArcGIS CIM definitions."""

    @staticmethod
    def create_symbol(symbol_def: Dict[str, Any]) -> Optional[QgsSymbol]:
        """
        Create a QGIS symbol from an ArcGIS CIM symbol definition.
        This is the main entry point that dispatches to geometry-specific methods.
        """
        if not symbol_def or not isinstance(symbol_def, dict):
            raise SymbolCreationError("Symbol definition is required and must be a dictionary")
        
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
        """Assembles a QGIS marker symbol from an ArcGIS CIM definition."""
        marker_symbol = QgsMarkerSymbol()
        marker_symbol.deleteSymbolLayer(0)

        arc_layers = symbol_def.get("symbolLayers", [symbol_def] if "type" in symbol_def else [])
        if not arc_layers:
            marker_symbol.appendSymbolLayer(create_default_marker_layer())
            return marker_symbol

        for layer_def in arc_layers:
            if not layer_def.get("enable", True):
                continue
            
            qgis_layer = None
            layer_type = layer_def.get("type")
            if layer_type == "CIMVectorMarker":
                qgis_layer = create_simple_marker_from_vector(layer_def)
            elif layer_type == "CIMCharacterMarker":
                qgis_layer = create_font_marker_from_character(layer_def)

            if qgis_layer:
                marker_symbol.appendSymbolLayer(qgis_layer)

        if marker_symbol.symbolLayerCount() == 0:
            marker_symbol.appendSymbolLayer(create_default_marker_layer())
            
        return marker_symbol
    
    @staticmethod
    def create_line_symbol(symbol_def: Dict[str, Any]) -> QgsLineSymbol:
        """Assembles a QGIS line symbol from an ArcGIS CIM definition."""
        line_symbol = QgsLineSymbol()
        line_symbol.deleteSymbolLayer(0)
        
        arc_layers = symbol_def.get("symbolLayers", [])
        if not arc_layers:
            line_symbol.appendSymbolLayer(create_default_line_layer())
            return line_symbol
        
        for layer_def in reversed(arc_layers):
            if not layer_def.get("enable", True):
                continue
            for qgis_layer in create_line_layers_from_def(layer_def):
                line_symbol.appendSymbolLayer(qgis_layer)
        
        if line_symbol.symbolLayerCount() == 0:
            line_symbol.appendSymbolLayer(create_default_line_layer())
            
        return line_symbol

    @staticmethod
    def create_fill_symbol(symbol_def: Dict[str, Any]) -> QgsFillSymbol:
        """Assembles a QGIS fill symbol from an ArcGIS CIM definition."""
        fill_symbol = QgsFillSymbol()
        fill_symbol.deleteSymbolLayer(0)

        arc_layers = symbol_def.get("symbolLayers", [])
        if not arc_layers:
            fill_symbol.appendSymbolLayer(create_default_fill_layer())
            return fill_symbol

        for layer_def in reversed(arc_layers):
            if not layer_def.get("enable", True):
                continue
            if qgis_layer := create_fill_layer_from_def(layer_def):
                fill_symbol.appendSymbolLayer(qgis_layer)

        if fill_symbol.symbolLayerCount() == 0:
            fill_symbol.appendSymbolLayer(create_default_fill_layer())

        return fill_symbol