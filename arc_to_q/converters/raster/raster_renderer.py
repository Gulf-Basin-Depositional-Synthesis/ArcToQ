"""
Raster renderer and processing module for ArcGIS to QGIS conversion.
"""
import os
from pathlib import Path
from qgis.core import QgsRasterLayer, QgsRasterDataProvider
from arc_to_q.converters.raster.color_mapping import create_classified_renderer
from arc_to_q.converters.raster.resampling import get_resampling_method


def parse_raster_source(in_folder, data_connection, out_file):
    """Build both absolute and relative QGIS-friendly URIs for a raster dataset.
    
    Args:
        in_folder (str): The absolute path to the input folder containing the .lyrx file.
        data_connection (dict): The data connection information from the .lyrx file.
        out_file (str): The output file path for the converted QGIS layer.

    Returns:
        tuple: (absolute path, relative path) where each is a QGIS data source string.
        
    Raises:
        ValueError: If required fields are missing from dataConnection.
        NotImplementedError: If the workspaceFactory is not supported.
    """
    factory = data_connection.get("workspaceFactory")
    conn_str = data_connection.get("workspaceConnectionString", "")
    dataset = data_connection.get("dataset")

    if not factory or not conn_str or not dataset:
        raise ValueError("Missing required fields in dataConnection.")

    # Extract path from ArcGIS-style connection string
    # Example: "DATABASE=G:\\Current_Database\\Database\\tif\\SandGrainVol" → "G:\\Current_Database\\Database\\tif\\SandGrainVol"
    if "=" in conn_str:
        _, raw_path = conn_str.split("=", 1)
    else:
        raw_path = conn_str

    # For raster data, the dataset is the actual filename, not a layer name
    # So we need to join the workspace path with the dataset filename
    lyrx_dir = Path(in_folder)
    workspace_path = (lyrx_dir / raw_path).resolve()
    
    # Build the full raster file path
    if factory == "Raster":
        abs_path = workspace_path / dataset
        abs_uri = abs_path.as_posix()
        
        # Build relative URI for saving in QLR
        out_dir = Path(out_file).parent.resolve()
        rel_path = Path(os.path.relpath(abs_path, start=out_dir))
        rel_uri = rel_path.as_posix()
        
        return abs_uri, rel_uri
    else:
        raise NotImplementedError(f"Unsupported raster workspaceFactory: {factory}")


def create_raster_layer(abs_uri, layer_name):
    """Create and validate a QGIS raster layer.
    
    Args:
        abs_uri (str): Absolute path to the raster file.
        layer_name (str): Name for the QGIS layer.
        
    Returns:
        QgsRasterLayer: The created raster layer.
        
    Raises:
        RuntimeError: If the layer cannot be loaded.
    """
    print(f"Attempting to load raster from: {abs_uri}")
    
    qgis_layer = QgsRasterLayer(abs_uri, layer_name)
    if not qgis_layer.isValid():
        error_msg = f"Failed to load raster layer: {abs_uri}"
        if qgis_layer.error().summary():
            error_msg += f"\nError: {qgis_layer.error().summary()}"
        
        # Additional debugging info
        if os.path.exists(abs_uri):
            error_msg += f"\nFile exists but GDAL cannot read it. Check file format/permissions."
        else:
            error_msg += f"\nFile does not exist at: {abs_uri}"
        
        print(error_msg)
        raise RuntimeError(error_msg)
    
    return qgis_layer


def apply_raster_symbology(qgis_layer, layer_def):
    """Apply symbology and rendering settings to a raster layer.
    
    Args:
        qgis_layer (QgsRasterLayer): The QGIS raster layer to modify.
        layer_def (dict): The layer definition from the LYRX file.
    """
    colorizer_def = layer_def.get('colorizer', {})
    if not colorizer_def:
        return
    
    # Apply color classification if available
    if colorizer_def.get('type') == 'CIMRasterClassifyColorizer':
        renderer = create_classified_renderer(qgis_layer, colorizer_def)
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


def print_raster_debug_info(qgis_layer):
    """Print comprehensive debugging information about a raster layer.
    
    Args:
        qgis_layer (QgsRasterLayer): The raster layer to analyze.
    """
    print("=== RASTER DEBUGGING INFO ===")
    
    data_provider = qgis_layer.dataProvider()
    if not data_provider:
        print("No data provider available")
        return
    
    # Basic raster info
    width = qgis_layer.width()
    height = qgis_layer.height()
    print(f"Raster dimensions: {width} x {height} pixels")
    print(f"Band count: {qgis_layer.bandCount()}")
    
    # Get the raster extent in the CRS units
    extent = qgis_layer.extent()
    extent_width = extent.width()
    extent_height = extent.height()
    print(f"Extent width: {extent_width:.2f}")
    print(f"Extent height: {extent_height:.2f}")
    
    # Calculate pixel size
    if width > 0 and height > 0:
        pixel_width = extent_width / width
        pixel_height = extent_height / height
        print(f"Pixel width: {pixel_width:.6f} units/pixel")
        print(f"Pixel height: {pixel_height:.6f} units/pixel")
        
        # Check pixel aspect ratio
        if pixel_height != 0:
            aspect_ratio = pixel_width / pixel_height
            print(f"Pixel aspect ratio: {aspect_ratio:.6f}")
            
            if abs(aspect_ratio - 1.0) > 0.001:
                print(f"*** WARNING: Non-square pixels detected! ***")
                print(f"This may cause stretching. Pixel aspect ratio should be close to 1.0")
        
        # Calculate overall raster aspect ratio
        if extent_height != 0:
            raster_aspect = extent_width / extent_height
            pixel_grid_aspect = width / height
            print(f"Geographic aspect ratio (extent): {raster_aspect:.4f}")
            print(f"Pixel grid aspect ratio: {pixel_grid_aspect:.4f}")
    
    # CRS info
    crs = qgis_layer.crs()
    print(f"CRS: {crs.authid()} - {crs.description()}")
    print(f"CRS Units: {crs.mapUnits()}")
    
    print("=== END RASTER DEBUGGING INFO ===")


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