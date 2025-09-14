"""
Coordinate system conversion module for ArcGIS to QGIS conversion.
"""
from qgis.core import QgsCoordinateReferenceSystem


def create_gbds_albers_crs():
    """
    Creates a custom CRS for GBDS_Albers_Full_ft based on typical Albers projections.
    This is a best guess - you should get the exact parameters from your organization.
    
    Returns:
        QgsCoordinateReferenceSystem or None: The created CRS if successful, None otherwise.
    """
    # This is a template - you'll need the exact parameters
    # Common Albers Equal Area parameters for US data in feet:
    proj4_string = '+proj=aea +lat_0=16.5 +lon_0=-92 +lat_1=16.5 +lat_2=34.5 +x_0=0 +y_0=0 +datum=WGS84 +units=ft +no_defs'
    
    custom_crs = QgsCoordinateReferenceSystem()
    success = custom_crs.createFromProj(proj4_string)
    
    if success:
        print(f"Created custom CRS: {custom_crs.description()}")
        return custom_crs
    else:
        print("Failed to create custom CRS")
        return None


def get_fallback_crs_candidates():
    """
    Returns a list of candidate CRS codes to try as fallbacks.
    
    Returns:
        list: List of EPSG codes to try in order of preference.
    """
    return [
        "EPSG:2163",    # US National Atlas Equal Area (meters)
        "EPSG:5070",    # NAD83 Conus Albers (meters)
        "EPSG:3081",    # NAD83 / Texas Centric Albers Equal Area (feet)
        "EPSG:2780",    # NAD83(HARN) / Texas State Mapping System (feet)
        "EPSG:3857",    # Web Mercator (meters) - last resort
    ]


def try_fallback_crs(qgis_layer):
    """
    Try to set a fallback CRS from a list of candidates.
    
    Args:
        qgis_layer: The QGIS layer to set the CRS on.
        
    Returns:
        bool: True if a fallback CRS was successfully set, False otherwise.
    """
    print("Trying standard projections as fallback...")
    
    for crs_code in get_fallback_crs_candidates():
        test_crs = QgsCoordinateReferenceSystem(crs_code)
        if test_crs.isValid():
            print(f"Trying CRS: {crs_code} - {test_crs.description()}")
            qgis_layer.setCrs(test_crs)
            print(f"Set CRS to: {test_crs.authid()} - {test_crs.description()}")
            return True
    
    print("No fallback CRS could be set")
    return False


def set_crs_from_arcgis_info(qgis_layer, spatial_reference):
    """
    Set the CRS on a QGIS layer based on ArcGIS spatial reference information.
    
    Args:
        qgis_layer: The QGIS layer to set the CRS on.
        spatial_reference (dict): The spatialReference dictionary from the LYRX file.
        
    Returns:
        bool: True if CRS was successfully set, False otherwise.
    """
    if not spatial_reference:
        return False
    
    wkid = spatial_reference.get('wkid')
    latest_wkid = spatial_reference.get('latestWkid')
    wkt = spatial_reference.get('wkt')
    
    print(f"Found ArcGIS CRS info - WKID: {wkid}, Latest WKID: {latest_wkid}")
    
    # Try to set the correct CRS from ArcGIS info
    target_crs = None
    
    if latest_wkid:
        target_crs = QgsCoordinateReferenceSystem(f"EPSG:{latest_wkid}")
        if target_crs.isValid():
            print(f"Setting CRS from latest WKID: {target_crs.authid()} - {target_crs.description()}")
    
    if not target_crs or not target_crs.isValid():
        if wkid:
            target_crs = QgsCoordinateReferenceSystem(f"EPSG:{wkid}")
            if target_crs.isValid():
                print(f"Setting CRS from WKID: {target_crs.authid()} - {target_crs.description()}")
    
    if not target_crs or not target_crs.isValid():
        if wkt:
            target_crs = QgsCoordinateReferenceSystem()
            success = target_crs.createFromWkt(wkt)
            if success and target_crs.isValid():
                print(f"Setting CRS from WKT: {target_crs.authid()} - {target_crs.description()}")
    
    if target_crs and target_crs.isValid():
        qgis_layer.setCrs(target_crs)
        return True
    
    return False


def handle_custom_or_invalid_crs(qgis_layer, current_crs):
    """
    Handle cases where the current CRS is invalid or custom (like GBDS_Albers_Full_ft).
    
    Args:
        qgis_layer: The QGIS layer to fix the CRS for.
        current_crs: The current CRS of the layer.
        
    Returns:
        bool: True if CRS was successfully handled, False otherwise.
    """
    if current_crs.isValid() and current_crs.description() != "GBDS_Albers_Full_ft":
        # CRS is valid and not our problematic custom one
        return True
    
    print("Detected custom/invalid CRS. Attempting to create GBDS Albers projection...")
    
    # Try to create the custom CRS
    custom_crs = create_gbds_albers_crs()
    if custom_crs and custom_crs.isValid():
        print(f"Setting custom CRS: {custom_crs.description()}")
        qgis_layer.setCrs(custom_crs)
        return True
    else:
        print("Custom CRS creation failed, trying fallback CRS...")
        return try_fallback_crs(qgis_layer)


def process_layer_crs(qgis_layer, layer_def):
    """
    Main function to process and set the appropriate CRS for a layer.
    
    Args:
        qgis_layer: The QGIS layer to process.
        layer_def (dict): The layer definition from the LYRX file.
        
    Returns:
        bool: True if CRS processing was successful, False otherwise.
    """
    # Check current CRS
    current_crs = qgis_layer.crs()
    print(f"Current CRS: {current_crs.authid()} - {current_crs.description()}")
    
    # First, try to use spatial reference info from the layer definition
    spatial_reference = layer_def.get('spatialReference')
    if spatial_reference and set_crs_from_arcgis_info(qgis_layer, spatial_reference):
        return True
    
    # If that didn't work, handle custom or invalid CRS
    return handle_custom_or_invalid_crs(qgis_layer, current_crs)


def create_custom_crs_from_proj4(proj4_string, description="Custom CRS"):
    """
    Create a custom CRS from a PROJ4 string.
    
    Args:
        proj4_string (str): The PROJ4 definition string.
        description (str): Optional description for the CRS.
        
    Returns:
        QgsCoordinateReferenceSystem or None: The created CRS if successful, None otherwise.
    """
    custom_crs = QgsCoordinateReferenceSystem()
    success = custom_crs.createFromProj(proj4_string)
    
    if success and custom_crs.isValid():
        print(f"Created custom CRS: {description}")
        return custom_crs
    else:
        print(f"Failed to create custom CRS: {description}")
        return None


def create_custom_crs_from_wkt(wkt_string, description="Custom CRS from WKT"):
    """
    Create a custom CRS from a WKT string.
    
    Args:
        wkt_string (str): The WKT definition string.
        description (str): Optional description for the CRS.
        
    Returns:
        QgsCoordinateReferenceSystem or None: The created CRS if successful, None otherwise.
    """
    custom_crs = QgsCoordinateReferenceSystem()
    success = custom_crs.createFromWkt(wkt_string)
    
    if success and custom_crs.isValid():
        print(f"Created custom CRS from WKT: {description}")
        return custom_crs
    else:
        print(f"Failed to create custom CRS from WKT: {description}")
        return None