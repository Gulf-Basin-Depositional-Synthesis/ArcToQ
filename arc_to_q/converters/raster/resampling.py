"""
Raster resampling conversion module for ArcGIS to QGIS.
"""
from qgis.core import QgsRasterDataProvider

# Mapping from CIM resampling types to the corresponding QGIS enum values
RESAMPLING_MAP = {
    'NearestNeighbor': QgsRasterDataProvider.ResamplingMethod.Nearest,
    'Bilinear': QgsRasterDataProvider.ResamplingMethod.Bilinear,
    'Cubic': QgsRasterDataProvider.ResamplingMethod.Cubic,
    'Majority': QgsRasterDataProvider.ResamplingMethod.Average,  # No direct equivalent, using Average
}

def get_resampling_method(colorizer_def: dict) -> QgsRasterDataProvider.ResamplingMethod:
    """
    Parses the colorizer definition to get the QGIS resampling method enum.

    Args:
        colorizer_def: The 'colorizer' dictionary from the LYRX file.

    Returns:
        The corresponding QgsRasterDataProvider.ResamplingMethod enum value.
    """
    # Get the resampling type string from the JSON, defaulting to 'NearestNeighbor'.
    resampling_type_str = colorizer_def.get('resamplingType', 'NearestNeighbor')
    
    # Return the QGIS equivalent enum, or Nearest as a fallback.
    return RESAMPLING_MAP.get(resampling_type_str, QgsRasterDataProvider.ResamplingMethod.Nearest)