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
from qgis.PyQt.QtCore import Qt, QPointF
from qgis.PyQt.QtGui import QColor

from arc_to_q.converters.utils import parse_color
from .marker_layers import create_font_marker_from_character, create_simple_marker_from_vector, _get_effective_props

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

def _create_grouped_vector_marker_line(
    layer_defs: List[Dict[str, Any]],
) -> List[QgsMarkerLineSymbolLayer]:
    """
    Combines multiple CIMVectorMarkers that share the same placement into a
    single QgsMarkerLineSymbolLayer with a multi-layer QgsMarkerSymbol.
    This keeps composite markers (stem + arrowhead, paired ticks, etc.)
    in phase along the line.

    For AlongLine placements, CIM offsetY is a perpendicular offset from the
    line and must be promoted to the QgsMarkerLineSymbolLayer rather than baked
    into each sub-symbol, so that all sub-layers shift together.  offsetX is an
    along-line nudge and is kept as a per-sub-layer local offset.
    """
    try:
        sub_symbol = QgsMarkerSymbol()
        sub_symbol.deleteSymbolLayer(0)

        placement_type = layer_defs[0].get("markerPlacement", {}).get("type", "")
        is_along_line = "AlongLine" in placement_type

        # For AlongLine placements, collect the perpendicular (Y) offsets from
        # all grouped layers.  We use the average so that a tick+arrow pair
        # (e.g. offsetY 1 and offsetY -4) sit symmetrically about the line.
        perp_offsets_pt: List[float] = []

        for layer_def in layer_defs:
            sub_layer = create_simple_marker_from_vector(layer_def, bake_offset=False)
            if sub_layer is None:
                continue

            props = _get_effective_props(layer_def)
            offset_x_pt = props.get("offsetX", 0.0)
            offset_y_pt = props.get("offsetY", 0.0)

            if is_along_line:
                # offsetY → perpendicular; promote to marker-line level (handled below)
                perp_offsets_pt.append(offset_y_pt)
                # offsetX → along-line nudge; keep as local sub-layer offset
                if offset_x_pt != 0.0:
                    sub_layer.setOffset(QPointF(offset_x_pt * PT_TO_MM, 0.0))
                    sub_layer.setOffsetUnit(QgsUnitTypes.RenderMillimeters)
            else:
                if offset_x_pt != 0.0 or offset_y_pt != 0.0:
                    sub_layer.setOffset(QPointF(offset_x_pt * PT_TO_MM, -offset_y_pt * PT_TO_MM))
                    sub_layer.setOffsetUnit(QgsUnitTypes.RenderMillimeters)

            sub_symbol.appendSymbolLayer(sub_layer)

        if sub_symbol.symbolLayerCount() == 0:
            return []

        # All layer_defs in the group share the same placement — use the first.
        qgis_layers = _create_marker_line_layers_from_sub_symbol(sub_symbol, layer_defs[0])

        # Apply the averaged perpendicular offset at the marker-line level.
        if is_along_line and perp_offsets_pt:
            avg_perp_mm = (sum(perp_offsets_pt) / len(perp_offsets_pt)) * PT_TO_MM
            for ml in qgis_layers:
                ml.setOffset(avg_perp_mm)
                ml.setOffsetUnit(QgsUnitTypes.RenderMillimeters)

        return qgis_layers
    except Exception as e:
        logger.error(f"Failed to create grouped vector marker line: {e}")
        return []

# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def create_line_layers_from_symbol_layers(symbol_layers: List[Dict[str, Any]]) -> List[QgsSymbolLayer]:
    """
    Entry point that processes the full CIMLineSymbol.symbolLayers list.
    Groups CIMVectorMarkers sharing identical placement specs into single
    QgsMarkerLineSymbolLayers so that composite markers (e.g. stem + arrowhead)
    stay in phase along the line.  Non-vector-marker layers are passed through
    individually.
    """
    result: List[QgsSymbolLayer] = []
    pending_vector_markers: List[Dict[str, Any]] = []

    def _flush_group():
        if not pending_vector_markers:
            return
        if len(pending_vector_markers) == 1:
            result.extend(create_line_layers_from_def(pending_vector_markers))
        else:
            result.extend(_create_grouped_vector_marker_line(pending_vector_markers))
        pending_vector_markers.clear()

    def _placement_key(layer_def: Dict[str, Any]):
        p = layer_def.get("markerPlacement", {})
        return (
            p.get("type", ""),
            tuple(p.get("placementTemplate", [])),
            p.get("endings", ""),
            p.get("offset", 0.0),
            p.get("offsetAlongLine", 0.0),
            p.get("extremityPlacement", ""),
            p.get("relativeTo", ""),
        )

    prev_key = None
    for layer_def in symbol_layers:
        if layer_def.get("type") != "CIMVectorMarker":
            _flush_group()
            result.extend(create_line_layers_from_def(layer_def))
            prev_key = None
            continue

        key = _placement_key(layer_def)
        if key != prev_key and pending_vector_markers:
            _flush_group()
        pending_vector_markers.append(layer_def)
        prev_key = key

    _flush_group()
    return result

def create_vector_marker_line_layers(layer_def: Dict[str, Any]) -> List[QgsMarkerLineSymbolLayer]:
    """Creates QGIS Marker Line layers from an ArcGIS CIMVectorMarker on a line."""
    try:
        sub_symbol = QgsMarkerSymbol()
        sub_symbol.deleteSymbolLayer(0)

        sub_layer = create_simple_marker_from_vector(layer_def, bake_offset=False)
        if not sub_layer:
            return []

        props = _get_effective_props(layer_def)
        offset_x_pt = props.get("offsetX", 0.0)
        offset_y_pt = props.get("offsetY", 0.0)

        placement_type = layer_def.get("markerPlacement", {}).get("type", "")
        is_along_line = "AlongLine" in placement_type

        if is_along_line:
            # offsetY is perpendicular to the line — promote to marker-line level.
            # offsetX is an along-line nudge — keep as local sub-layer offset.
            if offset_x_pt != 0.0:
                sub_layer.setOffset(QPointF(offset_x_pt * PT_TO_MM, 0.0))
                sub_layer.setOffsetUnit(QgsUnitTypes.RenderMillimeters)
        else:
            if offset_x_pt != 0.0 or offset_y_pt != 0.0:
                sub_layer.setOffset(QPointF(offset_x_pt * PT_TO_MM, -offset_y_pt * PT_TO_MM))
                sub_layer.setOffsetUnit(QgsUnitTypes.RenderMillimeters)

        sub_symbol.appendSymbolLayer(sub_layer)
        qgis_layers = _create_marker_line_layers_from_sub_symbol(sub_symbol, layer_def)

        if is_along_line and offset_y_pt != 0.0:
            for ml in qgis_layers:
                ml.setOffset(offset_y_pt * PT_TO_MM)
                ml.setOffsetUnit(QgsUnitTypes.RenderMillimeters)

        return qgis_layers
    except Exception as e:
        logger.error(f"Failed to create vector marker line layers: {e}")
        return []

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
    """
    stroke_layer = create_solid_stroke_layer(layer_def)
    if not stroke_layer:
        return []

    placement = layer_def.get("markerPlacement")
    if not placement:
        return [stroke_layer]

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

        template = placement.get("placementTemplate")
        if isinstance(template, list):
            interval = template[0] if template else 10
        elif isinstance(template, (int, float)):
            interval = template
        else:
            interval = 10
        marker_layer.setInterval(interval * PT_TO_MM)
        marker_layer.setIntervalUnit(QgsUnitTypes.RenderMillimeters)

        if "offset" in placement:
            # Perpendicular offset: ArcGIS positive = left-of-line, QGIS positive = right-of-line.
            # Negate to preserve the intended side.
            marker_layer.setOffset(-placement["offset"] * PT_TO_MM)
            marker_layer.setOffsetUnit(QgsUnitTypes.RenderMillimeters)

        if "offsetAlongLine" in placement:
            marker_layer.setOffsetAlongLine(placement["offsetAlongLine"] * PT_TO_MM)
            marker_layer.setOffsetAlongLineUnit(QgsUnitTypes.RenderMillimeters)

        # CIM endings="WithMarkers" means the interval pattern starts and ends with a
        # marker (i.e. the first/last placements are included in the interval cadence).
        # QGIS QgsMarkerLineSymbolLayer Interval placement already renders at the
        # endpoints when the interval divides evenly, so adding extra FirstVertex /
        # LastVertex layers produces duplicates at the ends.  Do NOT emit extra
        # endpoint layers here.
        qgis_layers.append(marker_layer)

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
    """
    marker_layer = QgsMarkerLineSymbolLayer()
    marker_layer.setSubSymbol(sub_symbol.clone())
    marker_layer.setPlacement(placement_enum)

    placement_rules = layer_def.get("markerPlacement", {})

    # Tangent rotation: marker follows the line direction. Defaults to True for marker lines.
    rotate_marker = placement_rules.get("angleToLine", True)
    if hasattr(marker_layer, "setRotateMarker"):
        marker_layer.setRotateMarker(rotate_marker)
    elif hasattr(marker_layer, "setRotateSymbols"):
        marker_layer.setRotateSymbols(rotate_marker)

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