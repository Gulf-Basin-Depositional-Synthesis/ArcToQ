"""
Creates QGIS stretched raster renderers from ArcGIS CIM definitions.
"""
import logging
from typing import Dict, Any

from qgis.core import (
    QgsRasterLayer, 
    QgsSingleBandPseudoColorRenderer, 
    QgsColorRampShader,
    QgsRasterShader, 
    QgsGradientColorRamp, 
    QgsRasterBandStats,
    QgsGradientStop,
)
from arc_to_q.converters.utils import extract_colors_from_ramp

logger = logging.getLogger(__name__)

def create_stretched_renderer(raster_layer: QgsRasterLayer, colorizer_def: Dict[str, Any]) -> QgsSingleBandPseudoColorRenderer:
    """
    Creates a QGIS single-band pseudocolor renderer that correctly applies the
    stretch method (e.g., Standard Deviation, Min-Max) from the ArcGIS definition.
    """
    stretch_type = colorizer_def.get('stretchType')
    stats = raster_layer.dataProvider().bandStatistics(1, QgsRasterBandStats.All)
    min_val, max_val = stats.minimumValue, stats.maximumValue # Default to full range

    #  Implement stretch-type specific logic 
    if stretch_type == 'StandardDeviations':
        n = colorizer_def.get('standardDeviationParam', 2.0)
        mean, std_dev = stats.mean, stats.stdDev
        min_val = mean - (n * std_dev)
        max_val = mean + (n * std_dev)
        logger.info(f"Applying 'Standard Deviation' stretch: {min_val:.2f} to {max_val:.2f}")
    elif stretch_type == 'PercentClip':
        # This is a placeholder; a full implementation requires a histogram.
        logger.warning("PercentClip is approximated using Min/Max.")
        min_val, max_val = stats.minimumValue, stats.maximumValue
    elif stretch_type == 'MinimumMaximum':
        min_val, max_val = stats.minimumValue, stats.maximumValue
        logger.info(f"Applying 'MinimumMaximum' stretch: {min_val:.2f} to {max_val:.2f}")
    else:
        # Fallback for custom or unspecified types, using explicit values if they exist.
        min_val = colorizer_def.get('customStretchMin', min_val)
        max_val = colorizer_def.get('customStretchMax', max_val)

    stretch_classes = colorizer_def.get('stretchClasses', [])
    low_label = next((c.get('label', f"{min_val:.2f}") for c in stretch_classes if 'Low' in c.get('label', '')), f"{min_val:.2f}")
    high_label = next((c.get('label', f"{max_val:.2f}") for c in stretch_classes if 'High' in c.get('label', '')), f"{max_val:.2f}")

    arc_color_ramp = colorizer_def.get('colorRamp', {})
    colors = extract_colors_from_ramp(arc_color_ramp)
    if not colors:
        return None

    if colorizer_def.get("invert", False):
        colors.reverse()

    shader = QgsColorRampShader()
    shader.setMinimumValue(min_val)
    shader.setMaximumValue(max_val)
    shader.setColorRampType(QgsColorRampShader.Interpolated)
    shader.setClassificationMode(QgsColorRampShader.Continuous)

    color_ramp_items = []
    num_colors = len(colors)
    if num_colors > 0:
        color_ramp_items.append(QgsColorRampShader.ColorRampItem(min_val, colors[0], low_label))
        for i in range(1, num_colors - 1):
            value = min_val + (i / (num_colors - 1)) * (max_val - min_val)
            color_ramp_items.append(QgsColorRampShader.ColorRampItem(value, colors[i]))
        if num_colors > 1:
            color_ramp_items.append(QgsColorRampShader.ColorRampItem(max_val, colors[-1], high_label))

    shader.setColorRampItemList(color_ramp_items)
    
    raster_shader = QgsRasterShader()
    raster_shader.setRasterShaderFunction(shader)

    renderer = QgsSingleBandPseudoColorRenderer(raster_layer.dataProvider(), 1, raster_shader)
    renderer.setClassificationMin(min_val)
    renderer.setClassificationMax(max_val)

    return renderer