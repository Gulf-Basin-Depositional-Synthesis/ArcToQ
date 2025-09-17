
from qgis.core import QgsCoordinateReferenceSystem
from arc_to_q.converters.custom_crs_registry import get_custom_crs_from_name

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
    name = spatial_reference.get('name')
    
    print(f"Found ArcGIS CRS info - Name: {name}, WKID: {wkid}, Latest WKID: {latest_wkid}")
    
    target_crs = None
    
    # Priority 1: Check for a custom definition in our registry
    if name:
        target_crs = get_custom_crs_from_name(name)
        if target_crs:
            print(f"Setting CRS from custom registry: {name}")

    # Priority 2: Try standard EPSG codes
    if not target_crs or not target_crs.isValid():
        if latest_wkid:
            target_crs = QgsCoordinateReferenceSystem(f"EPSG:{latest_wkid}")
    
    if not target_crs or not target_crs.isValid():
        if wkid:
            target_crs = QgsCoordinateReferenceSystem(f"EPSG:{wkid}")

    # Priority 3: Try creating from the WKT string provided by ArcGIS
    if not target_crs or not target_crs.isValid():
        if wkt:
            target_crs = QgsCoordinateReferenceSystem()
            target_crs.createFromWkt(wkt)

    # If we found a valid CRS, apply it to the layer
    if target_crs and target_crs.isValid():
        print(f"Successfully set CRS to: {target_crs.authid()} - {target_crs.description()}")
        qgis_layer.setCrs(target_crs)
        return True
    
    print("Could not set a valid CRS from the provided ArcGIS info.")
    return False


def process_layer_crs(qgis_layer, layer_def):
    """
    Main function to process and set the appropriate CRS for a layer.
    
    Args:
        qgis_layer: The QGIS layer to process.
        layer_def (dict): The layer definition from the LYRX file.
        
    Returns:
        bool: True if CRS processing was successful, False otherwise.
    """
    # If the layer already has a valid CRS, we might not need to do anything.
    if qgis_layer.crs().isValid():
        print(f"Layer already has a valid CRS: {qgis_layer.crs().authid()}")
        # You could add logic here to only override if it's a known problematic one
        # For now, we'll proceed to ensure it matches the LYRX definition
    
    # Try to set the correct CRS using all available info from the LYRX
    spatial_reference = layer_def.get('spatialReference')
    if spatial_reference and set_crs_from_arcgis_info(qgis_layer, spatial_reference):
        return True
    
    # If all attempts fail, you could add a fallback to a default CRS here if needed
    print("!!! WARNING: Failed to set a valid CRS for the layer.")
    return False