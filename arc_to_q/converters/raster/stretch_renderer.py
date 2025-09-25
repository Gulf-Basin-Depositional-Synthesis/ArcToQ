"""
Creates QGIS stretched raster renderers from ArcGIS CIM definitions.
"""
import logging
from typing import Dict, Any, List
from qgis.core import (
    QgsRasterLayer, 
    QgsSingleBandPseudoColorRenderer, 
    QgsColorRampShader,
    QgsRasterShader, 
    QgsRasterBandStats,
)
from qgis.PyQt.QtGui import QColor
from arc_to_q.converters.utils import extract_colors_from_ramp

logger = logging.getLogger(__name__)

def create_stretched_renderer(raster_layer: QgsRasterLayer, colorizer_def: Dict[str, Any]) -> QgsSingleBandPseudoColorRenderer:
    """
    Creates a QGIS single-band pseudocolor renderer that correctly applies all
    supported stretch methods by separating the visual rendering values from the
    legend's physical unit labels when necessary.
    """
    stats = raster_layer.dataProvider().bandStatistics(1, QgsRasterBandStats.All)
    stretch_type = colorizer_def.get('stretchType', 'None')

    # Get the precise min/max values and labels stored by ArcGIS for the legend
    arcgis_min_label_val = colorizer_def.get('customStretchMin', stats.minimumValue)
    arcgis_max_label_val = colorizer_def.get('customStretchMax', stats.maximumValue)
    
    stretch_classes = colorizer_def.get('stretchClasses', [])
    low_label = next((c.get('label', f"{arcgis_min_label_val:.2f}") for c in stretch_classes if 'Low' in c.get('label', '')), f"{arcgis_min_label_val:.2f}")
    high_label = next((c.get('label', f"{arcgis_max_label_val:.2f}") for c in stretch_classes if 'High' in c.get('label', '')), f"{arcgis_max_label_val:.2f}")

    color_ramp_items = []
    use_pregenerated_ramp_items = False

    # Determine the values to use for the actual visual color mapping
    if stretch_type == 'StandardDeviations':
        n = colorizer_def.get('standardDeviationParam', 2.0)
        mean, std_dev = stats.mean, stats.stdDev
        visual_min = mean - (n * std_dev)
        visual_max = mean + (n * std_dev)
        
        print(f"[INFO] For layer '{raster_layer.name()}': Applied a '{stretch_type}' stretch for visual contrast.")
        print(f"       The legend has been set to display the original data units: '{low_label}' to '{high_label}'.")

    elif stretch_type == 'PercentMinimumMaximum':
        # Use the histogram pre-calculated by ArcGIS and stored in the LYRX file
        stretch_stats = colorizer_def.get('stretchStats', {})
        histogram = stretch_stats.get('histogram', [])
        
        if not histogram:
            logger.warning("PercentMinimumMaximum stretch type specified, but no histogram found in LYRX. Falling back to Min/Max.")
            visual_min = stats.minimumValue
            visual_max = stats.maximumValue
        else:
            total_pixels = sum(histogram)
            min_percent = colorizer_def.get('minPercent', 0.0) / 100.0
            max_percent = colorizer_def.get('maxPercent', 0.0) / 100.0
            
            # Find the value at the lower percentage cutoff
            count = 0
            for i, h_count in enumerate(histogram):
                count += h_count
                if count / total_pixels >= min_percent:
                    # Interpolate the value based on the histogram bin
                    visual_min = stats.minimumValue + (i / len(histogram)) * (stats.maximumValue - stats.minimumValue)
                    break
            
            # Find the value at the upper percentage cutoff
            count = 0
            for i, h_count in reversed(list(enumerate(histogram))):
                count += h_count
                if count / total_pixels >= max_percent:
                    visual_max = stats.minimumValue + (i / len(histogram)) * (stats.maximumValue - stats.minimumValue)
                    break
            
            print(f"[INFO] For layer '{raster_layer.name()}': Applied a 'Percent Clip' stretch.")
            print(f"       The legend does not display the original data units: '{low_label}' to '{high_label} but they can be found in Labels'.")
    
    elif stretch_type == 'HistogramEqualize':
        stretch_stats = colorizer_def.get('stretchStats', {})
        histogram = stretch_stats.get('histogram', [])

        if not histogram:
            logger.warning("HistogramEqualize stretch specified, but no histogram found in LYRX. Falling back to Min/Max.")
            visual_min = arcgis_min_label_val
            visual_max = arcgis_max_label_val
        else:
            print(f"[INFO] For layer '{raster_layer.name()}': Applying simulated 'Histogram Equalize' stretch.")
            print(f"       The legend does not display the original data units: '{low_label}' to '{high_label} but they can be found in Labels'.")

            # 1. Generate a 256-step color palette from the ArcGIS multipart color ramp
            arc_color_ramp = colorizer_def.get('colorRamp', {})
            base_colors = extract_colors_from_ramp(arc_color_ramp)
            if not base_colors or len(base_colors) < 2:
                logger.error("Could not extract a valid multipart color ramp. Aborting.")
                return None

            if colorizer_def.get("invert", False):
                base_colors.reverse()

            full_palette: List[QColor] = []
            num_palette_entries = 256
            num_segments = len(base_colors) - 1

            for i in range(num_palette_entries):
                # Determine which segment the current palette entry falls into
                p = i / (num_palette_entries - 1)
                segment_float = p * num_segments
                segment_index = int(segment_float)
                if segment_index >= num_segments:
                    segment_index = num_segments - 1

                # Determine the progress within that specific segment (0.0 to 1.0)
                p_segment = segment_float - segment_index

                start_color = base_colors[segment_index]
                end_color = base_colors[segment_index + 1]

                # Interpolate the color for the current entry
                r = int(start_color.red() * (1 - p_segment) + end_color.red() * p_segment)
                g = int(start_color.green() * (1 - p_segment) + end_color.green() * p_segment)
                b = int(start_color.blue() * (1 - p_segment) + end_color.blue() * p_segment)
                full_palette.append(QColor(r, g, b))
            
            # 2. Calculate the Cumulative Distribution Function (CDF) from the histogram
            total_pixels = sum(h for h in histogram if h > 0)
            cdf = [0.0] * len(histogram)
            cumulative_sum = 0
            if total_pixels > 0:
                for i, h_count in enumerate(histogram):
                    cumulative_sum += h_count
                    cdf[i] = cumulative_sum / total_pixels

            # 3. Create discrete color ramp items, applying gamma and ensuring values are monotonically increasing
            data_range = arcgis_max_label_val - arcgis_min_label_val
            last_value = -float('inf')
            epsilon = (data_range / num_palette_entries) * 1e-6 if data_range > 0 else 1e-9

            # Get gamma value, defaulting to 1.0 (no change) if not present
            exponent = 1.0
            if colorizer_def.get("useGammaStretch", False):
                exponent = colorizer_def.get("gammaValue", 1.0)

            for i in range(num_palette_entries):
                target_percentile = i / (num_palette_entries - 1)
                
                # Apply gamma correction to the percentile
                adjusted_percentile = target_percentile ** exponent
                
                bin_index = next((j for j, p in enumerate(cdf) if p >= adjusted_percentile), len(cdf) - 1)
                value = arcgis_min_label_val + (bin_index / (len(histogram) - 1)) * data_range

                # Ensure value is strictly greater than the last to prevent hard breaks
                if value <= last_value:
                    value = last_value + epsilon
                last_value = value

                color_ramp_items.append(QgsColorRampShader.ColorRampItem(value, full_palette[i]))
            
            # Clamp first and last items to exact min/max and set labels
            if color_ramp_items:
                # Get colors from the generated items before replacing them
                first_color = color_ramp_items[0].color
                last_color = color_ramp_items[-1].color
                
                # Replace the first and last items with new, corrected ones
                color_ramp_items[0] = QgsColorRampShader.ColorRampItem(
                    arcgis_min_label_val,
                    first_color,
                    low_label
                )
                color_ramp_items[-1] = QgsColorRampShader.ColorRampItem(
                    arcgis_max_label_val,
                    last_color,
                    high_label
                )

            visual_min = arcgis_min_label_val
            visual_max = arcgis_max_label_val
            use_pregenerated_ramp_items = True
            use_pregenerated_ramp_items = True


    elif stretch_type in ['Custom', 'None']:
        # For these types, ArcGIS uses pre-calculated values which we will honor for a perfect match.
        visual_min = arcgis_min_label_val
        visual_max = arcgis_max_label_val
        
        print(f"[INFO] For layer '{raster_layer.name()}': Applied a '{stretch_type}' stretch.")
        print(f"       The legend does not display the original data units: '{low_label}' to '{high_label} but they can be found in Labels'.")

    else: # This covers 'MinimumMaximum'
        visual_min = stats.minimumValue
        visual_max = stats.maximumValue

    arc_color_ramp = colorizer_def.get('colorRamp', {})
    colors = extract_colors_from_ramp(arc_color_ramp)
    
    if not colors:
        return None
    
    if colorizer_def.get("invert", False):
        colors.reverse()
    
    shader = QgsColorRampShader(minimumValue=visual_min, maximumValue=visual_max)
    shader.setColorRampType(QgsColorRampShader.Interpolated)
    shader.setClassificationMode(QgsColorRampShader.Continuous)

    if not use_pregenerated_ramp_items:
        arc_color_ramp = colorizer_def.get('colorRamp', {})
        colors = extract_colors_from_ramp(arc_color_ramp)
        
        if not colors:
            return None
        
        if colorizer_def.get("invert", False):
            colors.reverse()
        
        num_colors = len(colors)
        if num_colors > 0:
            color_ramp_items.append(QgsColorRampShader.ColorRampItem(visual_min, colors[0], low_label))
            for i in range(1, num_colors - 1):
                value = visual_min + (i / (num_colors - 1)) * (visual_max - visual_min)
                color_ramp_items.append(QgsColorRampShader.ColorRampItem(value, colors[i]))
            if num_colors > 1:
                color_ramp_items.append(QgsColorRampShader.ColorRampItem(visual_max, colors[-1], high_label))

    shader.setColorRampItemList(color_ramp_items)
    
    raster_shader = QgsRasterShader()
    raster_shader.setRasterShaderFunction(shader)
    
    renderer = QgsSingleBandPseudoColorRenderer(raster_layer.dataProvider(), 1, raster_shader)
    renderer.setClassificationMin(visual_min)
    renderer.setClassificationMax(visual_max)
    
    return renderer

