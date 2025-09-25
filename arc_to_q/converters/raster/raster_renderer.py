"""
Raster renderer and processing module for ArcGIS to QGIS conversion.
"""
import os
from pathlib import Path
from qgis.core import QgsRasterLayer, QgsRasterDataProvider
from arc_to_q.converters.raster.color_mapping import create_classified_renderer
from arc_to_q.converters.raster.resampling import get_resampling_method
from arc_to_q.converters.raster.stretch_renderer import create_stretched_renderer


def apply_raster_symbology(qgis_layer, layer_def):
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
    
    # Apply color classification if available
    if colorizer_type == 'CIMRasterClassifyColorizer':
        renderer = create_classified_renderer(qgis_layer, colorizer_def)
    elif colorizer_type == 'CIMRasterStretchColorizer':
        renderer = create_stretched_renderer(qgis_layer, colorizer_def)
    
    if renderer:
        qgis_layer.setRenderer(renderer)
    
    # Set resampling method on the raster layer's data provider
    resampling = get_resampling_method(colorizer_def)
    data_provider = qgis_layer.dataProvider()
    if data_provider:
        # Set resampling for zoomed in (overview) display
        data_provider.setZoomedInResamplingMethod(resampling)
        # Set resampling for zoomed out (overview) display  
        data_provider.setZoomedOutResamplingMethod(resampling)

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