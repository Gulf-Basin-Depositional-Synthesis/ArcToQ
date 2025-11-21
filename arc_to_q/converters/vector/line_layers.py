"""
Manual tuning version - allows per-character rotation and offset adjustments
"""
import logging
from typing import List, Dict, Any, Optional

from qgis.core import (
    QgsMarkerSymbol, QgsMarkerLineSymbolLayer, QgsSimpleLineSymbolLayer,
    QgsSymbolLayer, QgsUnitTypes
)
from qgis.PyQt.QtCore import Qt, QPointF
from qgis.PyQt.QtGui import QColor

from arc_to_q.converters.utils import parse_color
from .marker_layers import create_font_marker_from_character, create_simple_marker_from_vector

logger = logging.getLogger(__name__)

# MANUAL TUNING: Adjust these values for specific character codes
CHAR_ADJUSTMENTS = {
    40: (0, -3),      # Thrust fault teeth (USGS Font)
    (35, "ESRI Default Marker"): (180, -2.5), # Thrust fault triangle (ESRI Default Marker)
    38: (0, -1.7),    # Strike slip
    70: (0, -0.25),   # Anticline F
    77: (0, -0.7),    # Syncline M
    72: (0, 0),       # Arrowhead H
    82: (0, -0.5),    # Symbol R
}


def create_line_layers_from_def(layer_def: Dict[str, Any]) -> List[QgsSymbolLayer]:
    """Creates one or more QGIS symbol layers from a single ArcGIS symbol layer definition."""
    layer_type = layer_def.get("type")
    
    if layer_type == "CIMSolidStroke":
        if layer := create_solid_stroke_layer(layer_def):
            return [layer]
    elif layer_type == "CIMCharacterMarker":
        return create_character_marker_line_layers(layer_def)
    elif layer_type == "CIMVectorMarker":
        return create_vector_marker_line_layers(layer_def)
    else:
        logger.warning(f"Unsupported line layer type: {layer_type}")
    
    return []


def create_solid_stroke_layer(layer_def: Dict[str, Any]) -> Optional[QgsSimpleLineSymbolLayer]:
    """Creates a QGIS line symbol layer from a CIMSolidStroke definition."""
    try:
        line_layer = QgsSimpleLineSymbolLayer()
        
        if color := parse_color(layer_def.get("color")):
            line_layer.setColor(color)
        line_layer.setWidth(layer_def.get("width", 0.5))
        line_layer.setWidthUnit(QgsUnitTypes.RenderPoints)
        
        cap_map = {"Round": Qt.RoundCap, "Butt": Qt.FlatCap, "Square": Qt.SquareCap}
        join_map = {"Round": Qt.RoundJoin, "Miter": Qt.MiterJoin, "Bevel": Qt.BevelJoin}
        line_layer.setPenCapStyle(cap_map.get(layer_def.get("capStyle", "Round"), Qt.RoundCap))
        line_layer.setPenJoinStyle(join_map.get(layer_def.get("joinStyle", "Round"), Qt.RoundJoin))

        for effect in layer_def.get("effects", []):
            if effect.get("type") == "CIMGeometricEffectOffset":
                line_layer.setOffset(effect.get("offset", 0.0))
                line_layer.setOffsetUnit(QgsUnitTypes.RenderPoints)
            elif effect.get("type") == "CIMGeometricEffectDashes":
                if dash_template := effect.get("dashTemplate", []):
                    line_layer.setCustomDashVector(dash_template)
                    line_layer.setCustomDashPatternUnit(QgsUnitTypes.RenderPoints)
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
        
        # Apply manual adjustments based on character code
        char_code = layer_def.get("characterIndex", 0)
        font_family = layer_def.get("fontFamilyName", "")
        
        rot_adj = 0
        y_offset_adj = 0
        
        if (char_code, font_family) in CHAR_ADJUSTMENTS:
             rot_adj, y_offset_adj = CHAR_ADJUSTMENTS[(char_code, font_family)]
        elif char_code in CHAR_ADJUSTMENTS:
             rot_adj, y_offset_adj = CHAR_ADJUSTMENTS[char_code]

        if rot_adj != 0:
            sub_symbol_layer.setAngle(sub_symbol_layer.angle() + rot_adj)
        
        if y_offset_adj != 0:
            current_offset = sub_symbol_layer.offset()
            sub_symbol_layer.setOffset(QPointF(current_offset.x(), current_offset.y() + y_offset_adj))
        
        marker_symbol = QgsMarkerSymbol([sub_symbol_layer])
        return _create_marker_line_layers_from_sub_symbol(marker_symbol, layer_def)
    except Exception as e:
        logger.error(f"Failed to create character marker line layers: {e}")
        return []


def _is_horizontal_vector_tick(layer_def: Dict[str, Any]) -> bool:
    """Detects if a vector marker is a horizontal line segment rotated 90 degrees (Tick)."""
    if layer_def.get("type") != "CIMVectorMarker": return False
    
    # Check rotation (approx 90)
    rotation = layer_def.get("rotation", 0)
    if abs(rotation - 90) > 1e-6: return False
    
    # Check geometry path
    graphics = layer_def.get("markerGraphics", [])
    if not graphics: return False
    geo = graphics[0].get("geometry", {})
    paths = geo.get("paths", [])
    if not paths or len(paths[0]) != 2: return False
    
    p1, p2 = paths[0]
    # Check if y-coordinates are essentially equal (Horizontal)
    return abs(p1[1] - p2[1]) < 1e-6


def create_vector_marker_line_layers(layer_def: Dict[str, Any]) -> List[QgsMarkerLineSymbolLayer]:
    """Creates QGIS Marker Line layers from an ArcGIS CIMVectorMarker on a line."""
    try:
        sub_symbol = QgsMarkerSymbol()
        sub_symbol.deleteSymbolLayer(0)
        if sub_layer := create_simple_marker_from_vector(layer_def):
            sub_symbol.appendSymbolLayer(sub_layer)
        else:
            return []
            
        # Detect if this is a Tick (Limit, Normal Fault) that needs offset inversion
        invert_offset = _is_horizontal_vector_tick(layer_def)
        
        return _create_marker_line_layers_from_sub_symbol(sub_symbol, layer_def, invert_offset=invert_offset)
    except Exception as e:
        logger.error(f"Failed to create vector marker line layers: {e}")
        return []


def _create_marker_line_layers_from_sub_symbol(sub_symbol: QgsMarkerSymbol, layer_def: Dict[str, Any], invert_offset: bool = False) -> List[QgsMarkerLineSymbolLayer]:
    """Creates marker line layers for a given sub-symbol based on placement rules."""
    placement = layer_def.get("markerPlacement", {})
    placement_type = placement.get("type", "")
    qgis_layers = []

    if "AtRatioPositions" in placement_type:
        positions = placement.get("positionArray", [0.5])
        
        if 0.0 in positions:
            qgis_layers.append(_create_single_marker_line(sub_symbol, layer_def, QgsMarkerLineSymbolLayer.FirstVertex))
        if 1.0 in positions:
            qgis_layers.append(_create_single_marker_line(sub_symbol, layer_def, QgsMarkerLineSymbolLayer.LastVertex))
        if 0.5 in positions:
            qgis_layers.append(_create_single_marker_line(sub_symbol, layer_def, QgsMarkerLineSymbolLayer.CentralPoint))

    elif "AlongLineSameSize" in placement_type:
        marker_layer = _create_single_marker_line(sub_symbol, layer_def, QgsMarkerLineSymbolLayer.Interval)
        
        template = placement.get("placementTemplate", [10])
        interval = template[0] if template else 10
        marker_layer.setInterval(interval)
        marker_layer.setIntervalUnit(QgsUnitTypes.RenderPoints)
        
        # Apply the perpendicular offset
        if "offset" in placement:
            offset_value = placement.get("offset", 0.0)
            
            # FIX: Invert offset for ticks that appear on the wrong side
            if invert_offset:
                offset_value = -offset_value
                
            marker_layer.setOffset(offset_value)
            marker_layer.setOffsetUnit(QgsUnitTypes.RenderPoints)
        
        # Apply offset along the line
        if "offsetAlongLine" in placement:
            offset_along = placement.get("offsetAlongLine", 0.0)
            marker_layer.setOffsetAlongLine(offset_along)
            marker_layer.setOffsetAlongLineUnit(QgsUnitTypes.RenderPoints)
        
        qgis_layers.append(marker_layer)
        
    else:
        qgis_layers.append(_create_single_marker_line(sub_symbol, layer_def, QgsMarkerLineSymbolLayer.CentralPoint))

    return qgis_layers


def _create_single_marker_line(sub_symbol: QgsMarkerSymbol, layer_def: Dict[str, Any], placement_enum) -> QgsMarkerLineSymbolLayer:
    """Helper to create and configure a single QgsMarkerLineSymbolLayer."""
    marker_layer = QgsMarkerLineSymbolLayer()
    marker_layer.setSubSymbol(sub_symbol.clone())
    marker_layer.setPlacement(placement_enum)
    
    placement_rules = layer_def.get("markerPlacement", {})
    
    if placement_rules.get("angleToLine", False):
        marker_layer.setRotateMarker(True)
    
    if placement_rules.get("placePerPart", False):
        marker_layer.setPlaceOnEveryPart(True)
    
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