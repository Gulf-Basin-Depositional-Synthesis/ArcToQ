import logging
from typing import List, Dict, Any, Optional

import qgis.core
from qgis.core import (
    QgsMarkerSymbol,
    QgsMarkerLineSymbolLayer,
    QgsSimpleLineSymbolLayer,
    QgsSymbolLayer,
    QgsUnitTypes,
    QgsLineSymbol,
    Qgis,
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor

from arc_to_q.converters.utils import parse_color
from .marker_layers import create_font_marker_from_character, create_simple_marker_from_vector

logger = logging.getLogger(__name__)

PT_TO_MM = 0.352777778


# ---------------------------------------------------------------------------
# Enum compatibility helper
# ---------------------------------------------------------------------------

def _get_placement_enum(name: str):
    """
    Resolves a QgsMarkerLineSymbolLayer placement enum by name, handling the
    API change between QGIS 3.x versions where the enum moved to Qgis.MarkerLinePlacement.
    """
    if hasattr(qgis.core.Qgis, "MarkerLinePlacement"):
        return getattr(qgis.core.Qgis.MarkerLinePlacement, name)
    return getattr(QgsMarkerLineSymbolLayer, name)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Solid stroke
# ---------------------------------------------------------------------------

def create_solid_stroke_line_layers(layer_def: Dict[str, Any]) -> List[QgsSymbolLayer]:
    """
    Creates QGIS line symbol layers from a CIMSolidStroke definition.

    If the stroke carries a markerPlacement rule (e.g. a stem/arch), the stroke
    is treated as a stamped marker.  Because QGIS cannot place a
    QgsSimpleLineSymbolLayer inside a QgsMarkerLineSymbolLayer directly, we fall
    back to drawing it as a continuous line — this is visually acceptable for
    straight stems and avoids a QGIS API mismatch.
    """
    stroke_layer = create_solid_stroke_layer(layer_def)
    if not stroke_layer:
        return []

    placement = layer_def.get("markerPlacement")
    if not placement:
        # Standard continuous line — most common case
        return [stroke_layer]

    # Placed stroke (stem): return as a continuous line.
    # A true stamped-stroke would require an SVG round-trip; the continuous
    # line is a reasonable approximation and avoids broken symbol trees.
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
                # Negate: ArcGIS positive offset is left-of-line; QGIS is right-of-line
                offset_mm = -effect.get("offset", 0.0) * PT_TO_MM
                line_layer.setOffset(offset_mm)
                line_layer.setOffsetUnit(QgsUnitTypes.RenderMillimeters)

            elif effect.get("type") == "CIMGeometricEffectDashes":
                if dash_template := effect.get("dashTemplate", []):
                    scaled_dash = [d * PT_TO_MM for d in dash_template]
                    line_layer.setCustomDashVector(scaled_dash)
                    line_layer.setCustomDashPatternUnit(QgsUnitTypes.RenderMillimeters)
                    line_layer.setUseCustomDashPattern(True)

        return line_layer
    except Exception as e:
        logger.error(f"Failed to create solid stroke layer: {e}")
        return None


# ---------------------------------------------------------------------------
# Character marker on a line
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Vector marker on a line
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Placement routing
# ---------------------------------------------------------------------------

def _create_marker_line_layers_from_sub_symbol(
    sub_symbol: QgsMarkerSymbol,
    layer_def: Dict[str, Any],
) -> List[QgsMarkerLineSymbolLayer]:
    """
    Creates one or more QgsMarkerLineSymbolLayers for a sub-symbol based on the
    CIM markerPlacement rules attached to layer_def.
    """
    placement = layer_def.get("markerPlacement", {})
    placement_type = placement.get("type", "")
    qgis_layers: List[QgsMarkerLineSymbolLayer] = []

    if "AtExtremities" in placement_type:
        pos = placement.get("extremityPlacement", "Both")
        # offsetAlongLine is in points; convert to mm
        offset_along = placement.get("offsetAlongLine", 0.0)

        if pos in ("JustBegin", "Both"):
            qgis_layers.append(
                _create_single_marker_line(
                    sub_symbol, layer_def, _get_placement_enum("FirstVertex"), offset_along
                )
            )
        if pos in ("JustEnd", "Both"):
            # Negate so the end marker pushes inward symmetrically
            qgis_layers.append(
                _create_single_marker_line(
                    sub_symbol, layer_def, _get_placement_enum("LastVertex"), -offset_along
                )
            )

    elif "AlongLineSameSize" in placement_type:
        marker_layer = _create_single_marker_line(
            sub_symbol, layer_def, _get_placement_enum("Interval")
        )

        template = placement.get("placementTemplate", [10])
        interval = template[0] if template else 10
        marker_layer.setInterval(interval * PT_TO_MM)
        marker_layer.setIntervalUnit(QgsUnitTypes.RenderMillimeters)

        if "offset" in placement:
            # Perpendicular offset — restore original sign (no inversion needed here)
            marker_layer.setOffset(placement["offset"] * PT_TO_MM)
            marker_layer.setOffsetUnit(QgsUnitTypes.RenderMillimeters)

        if "offsetAlongLine" in placement:
            marker_layer.setOffsetAlongLine(placement["offsetAlongLine"] * PT_TO_MM)
            marker_layer.setOffsetAlongLineUnit(QgsUnitTypes.RenderMillimeters)

        qgis_layers.append(marker_layer)

        # Force markers at endpoints for symbols like flexures / escarpments
        if placement.get("endings") == "WithMarkers":
            qgis_layers.append(
                _create_single_marker_line(sub_symbol, layer_def, _get_placement_enum("FirstVertex"))
            )
            qgis_layers.append(
                _create_single_marker_line(sub_symbol, layer_def, _get_placement_enum("LastVertex"))
            )

    elif "OnLine" in placement_type:
        offset_along = placement.get("startPointOffset", 0.0)
        qgis_layers.append(
            _create_single_marker_line(
                sub_symbol, layer_def, _get_placement_enum("CentralPoint"), offset_along
            )
        )

    else:
        # Unknown placement type — fall back to central point
        qgis_layers.append(
            _create_single_marker_line(sub_symbol, layer_def, _get_placement_enum("CentralPoint"))
        )

    return qgis_layers


def _create_single_marker_line(
    sub_symbol: QgsMarkerSymbol,
    layer_def: Dict[str, Any],
    placement_enum,
    offset_along: float = 0.0,
) -> QgsMarkerLineSymbolLayer:
    """
    Creates and configures a single QgsMarkerLineSymbolLayer.

    offset_along is expected in ArcGIS points; it is converted to mm here.
    """
    marker_layer = QgsMarkerLineSymbolLayer()
    marker_layer.setSubSymbol(sub_symbol.clone())
    marker_layer.setPlacement(placement_enum)

    placement_rules = layer_def.get("markerPlacement", {})

    # Tangent rotation: marker follows the line direction
    if placement_rules.get("angleToLine", False):
        if hasattr(marker_layer, "setRotateMarker"):
            marker_layer.setRotateMarker(True)
        elif hasattr(marker_layer, "setRotateSymbols"):
            marker_layer.setRotateSymbols(True)

    if placement_rules.get("placePerPart", False):
        if hasattr(marker_layer, "setPlaceOnEveryPart"):
            marker_layer.setPlaceOnEveryPart(True)

    if offset_along != 0.0:
        marker_layer.setOffsetAlongLine(offset_along * PT_TO_MM)
        marker_layer.setOffsetAlongLineUnit(QgsUnitTypes.RenderMillimeters)

    # flipFirst: rotate the first-vertex marker 180° for double-plunge symbols
    if (
        placement_rules.get("flipFirst")
        and placement_enum == _get_placement_enum("FirstVertex")
    ):
        cloned = marker_layer.subSymbol().clone()
        if cloned.symbolLayerCount() > 0:
            first_layer = cloned.symbolLayer(0)
            first_layer.setAngle(first_layer.angle() + 180)
        marker_layer.setSubSymbol(cloned)

    return marker_layer


# ---------------------------------------------------------------------------
# Fallback
# ---------------------------------------------------------------------------

def create_default_line_layer() -> QgsSimpleLineSymbolLayer:
    """Creates a default blue line symbol layer as a last-resort fallback."""
    layer = QgsSimpleLineSymbolLayer()
    layer.setColor(QColor(0, 0, 255))
    layer.setWidth(0.5)
    return layer