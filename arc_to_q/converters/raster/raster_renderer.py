"""
Raster renderer and processing module for ArcGIS to QGIS conversion.
"""
import os
from pathlib import Path
from qgis.core import (
    QgsRasterLayer, 
    QgsRasterDataProvider,
    QgsRasterPipe
)
from arc_to_q.converters.raster.color_mapping import create_classified_renderer
from arc_to_q.converters.raster.resampling import get_resampling_method
from arc_to_q.converters.raster.stretch_renderer import create_stretched_renderer


def apply_raster_symbology(qgis_layer: QgsRasterLayer, layer_def: dict):
    """Apply symbology and rendering settings to a raster layer.
    
    Args:
        qgis_layer (QgsRasterLayer): The QGIS raster layer to modify.
        layer_def (dict): The layer definition from the LYRX file.
    """
    colorizer_def = layer_def.get('colorizer', {})
    if not colorizer_def:
        return
    
    renderer = None
    colorizer_type = colorizer_def.get('type')
    is_classified = (colorizer_type == 'CIMRasterClassifyColorizer')
    
    # 1. Create the Renderer
    if is_classified:
        # Classified renderers (Discrete) need interpolated VALUES, not interpolated COLORS.
        renderer = create_classified_renderer(qgis_layer, colorizer_def)
    elif colorizer_type == 'CIMRasterStretchColorizer':
        renderer = create_stretched_renderer(qgis_layer, colorizer_def)

    if renderer:
        qgis_layer.setRenderer(renderer)
    
    # 2. Configure Resampling (The Core Fix)
    # ArcGIS "Bilinear" on classified data means "Interpolate Values, then Classify".
    # QGIS default is "Classify, then Interpolate Colors" (which blurs).
    # Solution: Force the PROVIDER to interpolate values first.
    
    resampling_method = get_resampling_method(colorizer_def)
    
    # Check if the requested method is a "smoothing" type (Bilinear, Cubic)
    is_smooth = resampling_method in (
        QgsRasterDataProvider.ResamplingMethod.Bilinear,
        QgsRasterDataProvider.ResamplingMethod.Cubic
    )

    data_provider = qgis_layer.dataProvider()
    if data_provider:
        # Always set the method on the provider
        data_provider.setZoomedInResamplingMethod(resampling_method)
        data_provider.setZoomedOutResamplingMethod(resampling_method)
        
        # Enable Provider Resampling if we need smoothing. 
        # This forces GDAL to calculate intermediate values (e.g. 10.5) which the 
        # Discrete renderer then draws as a smooth boundary, rather than a blocky square.
        data_provider.enableProviderResampling(is_smooth)

    # 3. Configure Visual Filter
    # We largely disable the visual filter for classified data to prevent "color blurring".
    # We only use it for oversampling to clean up artifacts.
    resample_filter = qgis_layer.resampleFilter()
    if resample_filter:
        if is_classified:
            # For classified data, the Provider handles the interpolation (value smoothing).
            # The Visual Filter must be NEAREST (None) to preserve the sharp class colors.
            resample_filter.setZoomedInResampler(None)
            resample_filter.setZoomedOutResampler(None)
        else:
            # For continuous data (Stretch), visual filtering is acceptable/desired.
            # (Note: Passing None resets to Nearest, passing objects would set specific filters, 
            # but usually Provider resampling + Stretch renderer is sufficient).
            pass 

        # Always apply oversampling (2.0 is standard for high quality) 
        # to ensure the grid is rendered cleanly.
        resample_filter.setMaxOversampling(2.0)

    # 4. Force Pipeline Order
    # Explicitly tell the pipe to prefer the Provider stage if possible
    if qgis_layer.pipe():
        if is_smooth and is_classified:
             qgis_layer.pipe().setResamplingStage(QgsRasterPipe.Provider)


def switch_to_relative_path(qgis_layer, rel_uri):
    """Switch the raster layer to use a relative path.
    
    Args:
        qgis_layer (QgsRasterLayer): The raster layer to modify.
        rel_uri (str): The relative URI to set.
        
    Raises:
        RuntimeError: If the layer becomes invalid after switching paths.
    """
    layer_name = qgis_layer.name()
    qgis_layer.setDataSource(rel_uri, layer_name, qgis_layer.providerType())
    
    if not qgis_layer.isValid():
        error_msg = f"CRITICAL ERROR: Raster layer '{layer_name}' became invalid after setting relative path."
        error_msg += f"\nRelative path: {rel_uri}"
        if qgis_layer.error().summary():
            error_msg += f"\nError: {qgis_layer.error().summary()}"
        
        print(error_msg)
        raise RuntimeError(f"Raster layer became invalid: {layer_name}")