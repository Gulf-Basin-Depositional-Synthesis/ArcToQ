"""
Raster color mapping and renderer creation module for ArcGIS to QGIS.
"""
from qgis.core import (
    QgsRasterLayer,
    QgsSingleBandPseudoColorRenderer,
    QgsColorRampShader,
    QgsRasterShader
)
from qgis.PyQt.QtGui import QColor

# Assumes the parse_color function is in a utils module at this path
from arc_to_q.converters.utils import parse_color

def create_classified_renderer(raster_layer: QgsRasterLayer, colorizer_def: dict) -> QgsSingleBandPseudoColorRenderer:
    """
    Creates a QGIS classified raster renderer from a CIMRasterClassifyColorizer definition.

    Args:
        raster_layer: The QgsRasterLayer to which the renderer will be applied.
        colorizer_def: The 'colorizer' dictionary from the LYRX file.

    Returns:
        A configured QgsSingleBandPseudoColorRenderer.
    """
    class_breaks = colorizer_def.get('classBreaks', [])
    if not class_breaks:
        return None

    # Create a list of QGIS color ramp items from the CIM class breaks
    ramp_items = []
    for c_break in class_breaks:
        upper_bound = c_break.get('upperBound')
        label = c_break.get('label', '')
        color_def = c_break.get('color')

        if upper_bound is None or color_def is None:
            continue

        qgis_color = parse_color(color_def)
        if not qgis_color:
            qgis_color = QColor('black') # Fallback color

        item = QgsColorRampShader.ColorRampItem(upper_bound, qgis_color, label)
        ramp_items.append(item)

    # A discrete ramp ensures each value range gets a single color, like a classified map.
    color_ramp_shader = QgsColorRampShader()
    color_ramp_shader.setColorRampType(QgsColorRampShader.Discrete)
    color_ramp_shader.setColorRampItemList(ramp_items)

    raster_shader = QgsRasterShader()
    raster_shader.setRasterShaderFunction(color_ramp_shader)

    # Create the pseudocolor renderer. This assumes the classification is applied to Band 1.
    renderer = QgsSingleBandPseudoColorRenderer(
        raster_layer.dataProvider(),
        1, # Band number
        raster_shader
    )

    return renderer