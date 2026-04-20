import logging
from typing import List, Dict, Any, Optional, Tuple

from qgis.core import (
    QgsMarkerSymbol, QgsMarkerLineSymbolLayer, QgsSimpleLineSymbolLayer,
    QgsSymbolLayer, QgsUnitTypes, QgsLineSymbol
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor

from arc_to_q.converters.utils import parse_color
from .marker_layers import create_font_marker_from_character, create_simple_marker_from_vector

logger = logging.getLogger(__name__)

PT_TO_MM = 0.352777778

def create_line_layers_from_def(layer_def: Dict[str, Any]) -> List[QgsSymbolLayer]:
    """Creates one or more QGIS symbol layers from a single ArcGIS symbol layer definition."""
    layer_type = layer_def.get("type")
    
    if layer_type == "CIMSolidStroke":
        return create_solid_stroke_line_layers(layer_def)
    elif layer_type == "CIMCharacterMarker":
        return create_character_marker_line_layers(layer_def)
    elif layer_type == "CIMVectorMarker":
        return create_vector_marker_line_layers(layer_def)
    else:
        logger.warning(f"Unsupported line layer type: {layer_type}")
    
    return []


def create_solid_stroke_line_layers(layer_def: Dict[str, Any]) -> List[QgsSymbolLayer]:
    """
    Creates QGIS line symbol layers from a CIMSolidStroke definition.
    Handles the case where a stroke is used as a 'marker' (e.g., the stem of an arch/flexure).
    """
    stroke_layer = create_solid_stroke_layer(layer_def)
    if not stroke_layer:
        return []

    # Check if this stroke has a marker placement rule
    placement = layer_def.get("markerPlacement")
    if not placement:
        # Standard continuous line
        return [stroke_layer]
    
    # This stroke is acting as a stamped marker (like a stem)
    # We must wrap it in a QgsMarkerSymbol and then a QgsMarkerLineSymbolLayer
    try:
        sub_symbol = QgsMarkerSymbol()
        sub_symbol.deleteSymbolLayer(0)
        
        # A MarkerSymbol cannot hold a SimpleLineSymbolLayer directly. 
        # We must create a LineSymbol, put the stroke in it, and then...
        # Wait, QGIS handles this differently. A stroke marker is just a VectorMarker
        # in ArcGIS that happens to only contain a stroke.
        
        # Let's pass it to the sub-symbol generator
        return _create_marker_line_layers_from_sub_symbol(sub_symbol, layer_def, inject_stroke=stroke_layer)
        
    except Exception as e:
        logger.error(f"Failed to create placed stroke layer: {e}")
        return [stroke_layer]


def create_solid_stroke_layer(layer_def: Dict[str, Any]) -> Optional[QgsSimpleLineSymbolLayer]:
    """Creates a base QGIS line symbol layer from a CIMSolidStroke definition."""
    try:
        line_layer = QgsSimpleLineSymbolLayer()
        
        if color := parse_color(layer_def.get("color")):
            line_layer.setColor(color)
            
        line_layer.setWidth(layer_def.get("width", 0.5) * PT_TO_MM)
        line_layer.setWidthUnit(QgsUnitTypes.RenderMillimeters)
        
        cap_map = {"Round": Qt.RoundCap, "Butt": Qt.FlatCap, "Square": Qt.SquareCap}
        join_map = {"Round": Qt.RoundJoin, "Miter": Qt.MiterJoin, "Bevel": Qt.BevelJoin}
        line_layer.setPenCapStyle(cap_map.get(layer_def.get("capStyle", "Round"), Qt.RoundCap))
        line_layer.setPenJoinStyle(join_map.get(layer_def.get("joinStyle", "Round"), Qt.RoundJoin))

        for effect in layer_def.get("effects", []):
            if effect.get("type") == "CIMGeometricEffectOffset":
                # Convert points to MM and flip the offset direction to match QGIS coordinates
                offset_pt = effect.get("offset", 0.0)
                offset_mm = -offset_pt * PT_TO_MM
                line_layer.setOffset(offset_mm)
                line_layer.setOffsetUnit(QgsUnitTypes.RenderMillimeters)
            elif effect.get("type") == "CIMGeometricEffectDashes":
                if dash_template := effect.get("dashTemplate", []):
                    # Scale dash template to MM
                    scaled_dash = [d * PT_TO_MM for d in dash_template]
                    line_layer.setCustomDashVector(scaled_dash)
                    line_layer.setCustomDashPatternUnit(QgsUnitTypes.RenderMillimeters)
                    line_layer.setUseCustomDashPattern(True)
        return line_layer
    except Exception as e:
        logger.error(f"Failed to create solid stroke layer: {e}")
        return None


def create_character_marker_line_layers(layer_def: Dict[str, Any]) -> List[QgsMarkerLineSymbolLayer]:
    """Creates QGIS Marker Line layers from an ArcGIS CIMCharacterMarker on a line."""
    try:
        sub_symbol_layer = create_font_marker_from_character(layer_def)
        if not sub_symbol_layer:
            return []
        
        marker_symbol = QgsMarkerSymbol([sub_symbol_layer])
        return _create_marker_line_layers_from_sub_symbol(marker_symbol, layer_def)
    except Exception as e:
        logger.error(f"Failed to create character marker line layers: {e}")
        return []


def create_vector_marker_line_layers(layer_def: Dict[str, Any]) -> List[QgsMarkerLineSymbolLayer]:
    """Creates QGIS Marker Line layers from an ArcGIS CIMVectorMarker on a line."""
    try:
        sub_symbol = QgsMarkerSymbol()
        sub_symbol.deleteSymbolLayer(0)
        
        if sub_layer := create_simple_marker_from_vector(layer_def):
            sub_symbol.appendSymbolLayer(sub_layer)
        else:
            return []
            
        return _create_marker_line_layers_from_sub_symbol(sub_symbol, layer_def)
    except Exception as e:
        logger.error(f"Failed to create vector marker line layers: {e}")
        return []


def _create_marker_line_layers_from_sub_symbol(
    sub_symbol: QgsMarkerSymbol, 
    layer_def: Dict[str, Any],
    inject_stroke: Optional[QgsSimpleLineSymbolLayer] = None
) -> List[QgsMarkerLineSymbolLayer]:
    """Creates marker line layers for a given sub-symbol based on placement rules."""
    
    # If we are injecting a stroke (like a stem), we need a different approach
    # QGIS doesn't let us put a LineSymbol inside a MarkerLineSymbol directly easily.
    # The best way to handle "stems" is to let the main drawing pipeline handle them
    # as standard lines with dash effects if possible, but if they have strict placements...
    if inject_stroke:
        # Fallback: Just return the stroke. It's often better to draw the stem continuously
        # than to try to stamp it if we lack the exact SVG geometry for it.
        return [inject_stroke]

    placement = layer_def.get("markerPlacement", {})
    placement_type = placement.get("type", "")
    qgis_layers = []

    if "AtRatioPositions" in placement_type:
        pass

    elif "AtExtremities" in placement_type:
        pos = placement.get("extremityPlacement", "Both")
        offset_along = placement.get("offsetAlongLine", 0.0) * PT_TO_MM

        if pos == "JustBegin":
            qgis_layers.append(_create_single_marker_line(sub_symbol, layer_def, QgsMarkerLineSymbolLayer.FirstVertex, offset_along))
        elif pos == "JustEnd":
            # Invert offset for the end vertex so it pushes inward symmetrically
            qgis_layers.append(_create_single_marker_line(sub_symbol, layer_def, QgsMarkerLineSymbolLayer.LastVertex, -offset_along))
        elif pos == "Both":
            qgis_layers.append(_create_single_marker_line(sub_symbol, layer_def, QgsMarkerLineSymbolLayer.FirstVertex, offset_along))
            qgis_layers.append(_create_single_marker_line(sub_symbol, layer_def, QgsMarkerLineSymbolLayer.LastVertex, -offset_along))

    elif "AlongLineSameSize" in placement_type:
        marker_layer = _create_single_marker_line(sub_symbol, layer_def, QgsMarkerLineSymbolLayer.Interval)
        
        template = placement.get("placementTemplate", [10])
        interval = template[0] if template else 10
        marker_layer.setInterval(interval * PT_TO_MM)
        marker_layer.setIntervalUnit(QgsUnitTypes.RenderMillimeters)
        
        if "offset" in placement:
            offset_value = placement.get("offset", 0.0)
            marker_layer.setOffset(-offset_value * PT_TO_MM)
            marker_layer.setOffsetUnit(QgsUnitTypes.RenderMillimeters)
        
        if "offsetAlongLine" in placement:
            offset_along = placement.get("offsetAlongLine", 0.0)
            marker_layer.setOffsetAlongLine(offset_along * PT_TO_MM)
            marker_layer.setOffsetAlongLineUnit(QgsUnitTypes.RenderMillimeters)
            
        # Check endings constraint
        endings = placement.get("endings", "WithMarkers")
        if endings == "WithMarkers":
            # Add explicit markers at the ends if requested
            qgis_layers.append(_create_single_marker_line(sub_symbol, layer_def, QgsMarkerLineSymbolLayer.FirstVertex))
            qgis_layers.append(_create_single_marker_line(sub_symbol, layer_def, QgsMarkerLineSymbolLayer.LastVertex))
        
        qgis_layers.append(marker_layer)

    elif "OnLine" in placement_type:
        marker_layer = _create_single_marker_line(sub_symbol, layer_def, QgsMarkerLineSymbolLayer.CentralPoint)
        
        # Check if it's placed relative to extremities
        relative_to = placement.get("relativeTo", "LineMiddle")
        if relative_to == "LineMiddle":
            pass # Default behavior is fine
            
        qgis_layers.append(marker_layer)
        
    else:
        qgis_layers.append(_create_single_marker_line(sub_symbol, layer_def, QgsMarkerLineSymbolLayer.CentralPoint))

    return qgis_layers


def _create_single_marker_line(sub_symbol: QgsMarkerSymbol, layer_def: Dict[str, Any], placement_enum, offset_along: float = 0.0) -> QgsMarkerLineSymbolLayer:
    """Helper to create and configure a single QgsMarkerLineSymbolLayer."""
    marker_layer = QgsMarkerLineSymbolLayer()
    marker_layer.setSubSymbol(sub_symbol.clone())
    marker_layer.setPlacement(placement_enum)
    
    placement_rules = layer_def.get("markerPlacement", {})
    
    if placement_rules.get("angleToLine", False):
        marker_layer.setRotateMarker(True)
    
    if placement_rules.get("placePerPart", False):
        marker_layer.setPlaceOnEveryPart(True)
        
    if offset_along != 0.0:
        marker_layer.setOffsetAlongLine(offset_along)
        marker_layer.setOffsetAlongLineUnit(QgsUnitTypes.RenderMillimeters)
    
    # Handle flipFirst for double-plunge symbols
    if placement_rules.get("flipFirst") and placement_enum == QgsMarkerLineSymbolLayer.FirstVertex:
        cloned_sub_symbol = marker_layer.subSymbol().clone()
        if cloned_sub_symbol.symbolLayerCount() > 0:
            first_layer = cloned_sub_symbol.symbolLayer(0)
            first_layer.setAngle(first_layer.angle() + 180)
        marker_layer.setSubSymbol(cloned_sub_symbol)

    return marker_layer


def create_default_line_layer() -> QgsSimpleLineSymbolLayer:
    """Create a default line symbol layer."""
    layer = QgsSimpleLineSymbolLayer()
    layer.setColor(QColor(0, 0, 255))
    layer.setWidth(0.5)
    return layer