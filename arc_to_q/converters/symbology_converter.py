from qgis.core import (
    QgsVectorLayer,
    QgsSingleSymbolRenderer,
    QgsMarkerSymbol,
    QgsSimpleMarkerSymbolLayer
)
from qgis.PyQt.QtGui import QColor

from arc_to_q.converters.utils import parse_color


def _convert_simple_renderer(layer: QgsVectorLayer, renderer_def: dict):
    """
    Converts a CIMSimpleRenderer from ArcGIS Pro to a QgsSingleSymbolRenderer in QGIS.
    This function specifically handles simple point symbols (CIMVectorMarker).
    """
    symbol_ref = renderer_def.get("symbol", {})
    symbol_def = symbol_ref.get("symbol", {})
    
    if not symbol_def or not symbol_def.get("symbolLayers"):
        print("[WARNING] Simple renderer found, but its symbol definition is missing symbolLayers.")
        return

    symbol_layer_def = symbol_def["symbolLayers"][0]

    if symbol_layer_def.get("type") == "CIMVectorMarker":
        
        shape_map = {
            "Circle": QgsSimpleMarkerSymbolLayer.Circle,
            "Square": QgsSimpleMarkerSymbolLayer.Square,
            "Cross": QgsSimpleMarkerSymbolLayer.Cross,
            "X": QgsSimpleMarkerSymbolLayer.Cross2,
            "Diamond": QgsSimpleMarkerSymbolLayer.Diamond,
            "Triangle": QgsSimpleMarkerSymbolLayer.Triangle,
            "Pentagon": QgsSimpleMarkerSymbolLayer.Pentagon,
            "Hexagon": QgsSimpleMarkerSymbolLayer.Hexagon,
            "Star": QgsSimpleMarkerSymbolLayer.Star
        }
        
        arc_shape_graphic = symbol_layer_def.get("markerGraphics", [{}])[0]
        
        arc_shape = arc_shape_graphic.get("primitiveName")
        
        if not arc_shape:
            arc_geometry = arc_shape_graphic.get("geometry", {})
            if "rings" in arc_geometry:
                points = arc_geometry["rings"][0]
                point_count = len(points)
                
                if point_count == 4:
                    arc_shape = "Triangle"
                elif point_count == 5:
                    unique_x = set(p[0] for p in points)
                    unique_y = set(p[1] for p in points)
                    if len(unique_x) == 3 and len(unique_y) == 3:
                        arc_shape = "Diamond"
                    else:
                        arc_shape = "Square"
                elif point_count == 6:
                    arc_shape = "Pentagon"
                elif point_count == 7:
                    arc_shape = "Hexagon"
                elif point_count == 11:
                    arc_shape = "Star"
                elif point_count == 13:
                    arc_shape = "Cross"
                else:
                    print(f"[WARNING] A complex polygon symbol with {len(points) - 1} vertices was found. This shape cannot be converted directly. Defaulting to a circle.")
                    arc_shape = "Circle"
            elif "curveRings" in arc_geometry:
                points_in_curve = [p for p in arc_geometry["curveRings"][0] if isinstance(p, list)]
                if len(points_in_curve) == 13:
                    arc_shape = "X"
                else:
                    arc_shape = "Circle"
            else:
                arc_shape = "Circle"

        qgis_shape_constant = shape_map.get(arc_shape, QgsSimpleMarkerSymbolLayer.Circle)

        size = symbol_layer_def.get("size", 6)

        marker_graphic = symbol_layer_def.get("markerGraphics", [{}])[0]
        graphic_symbol = marker_graphic.get("symbol", {})
        graphic_symbol_layers = graphic_symbol.get("symbolLayers", [])

        fill_color_list = [128, 128, 128, 100]
        stroke_color_list = [0, 0, 0, 100]
        stroke_width = 0

        for graphic_layer in graphic_symbol_layers:
            if graphic_layer.get("type") == "CIMSolidFill":
                color_obj = graphic_layer.get("color", {})
                fill_color_list = color_obj.get("values", fill_color_list)
            elif graphic_layer.get("type") == "CIMSolidStroke":
                color_obj = graphic_layer.get("color", {})
                stroke_color_list = color_obj.get("values", stroke_color_list)
                stroke_width = graphic_layer.get("width", 0)

        symbol_layer = QgsSimpleMarkerSymbolLayer()
        
        #separates line-based and polygon-based shapes.
        is_line_shape = qgis_shape_constant in [
            QgsSimpleMarkerSymbolLayer.Cross,  
            QgsSimpleMarkerSymbolLayer.Cross2
        ]

        if is_line_shape:
            # For line shapes, the main color is the "fill" from Arc.
            # We apply this color to the QGIS stroke and make the fill transparent.
            main_color = parse_color(fill_color_list)
            main_color.setAlpha(0) # Set fill to transparent
            symbol_layer.setColor(main_color)
            symbol_layer.setStrokeColor(parse_color(fill_color_list))
        else:
            # For polygon shapes, we use both fill and stroke from Arc.
            symbol_layer.setColor(parse_color(fill_color_list))
            symbol_layer.setStrokeColor(parse_color(stroke_color_list))

        symbol_layer.setStrokeWidth(stroke_width)
        symbol_layer.setSize(size)
        symbol_layer.setShape(qgis_shape_constant)
        
        marker_symbol = QgsMarkerSymbol()
        marker_symbol.changeSymbolLayer(0, symbol_layer)

        renderer = QgsSingleSymbolRenderer(marker_symbol)
        layer.setRenderer(renderer)
        
        print(f"[INFO] Converted simple marker for layer '{layer.name()}'.")
    else:
        print(f"[WARNING] Unhandled symbol layer type: {symbol_layer_def.get('type')}")


def set_symbology(layer: QgsVectorLayer, layer_def: dict):
    """
    Main function to set the symbology for a QGIS layer from an ArcGIS layer definition.
    """
    renderer_def = layer_def.get("renderer", {})
    renderer_type = renderer_def.get("type")

    if renderer_type == "CIMSimpleRenderer":
        _convert_simple_renderer(layer, renderer_def)
    else:
        print(f"[WARNING] Unhandled renderer type: '{renderer_type}'. Layer will have default symbology.")

