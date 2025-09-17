# In arc_to_q/converters/custom_crs_registry.py

from qgis.core import QgsCoordinateReferenceSystem

# This dictionary stores all your custom CRS definitions.
CUSTOM_CRS_DEFINITIONS = {
    "GBDS_Albers_Full_ft": (
    "+proj=aea +lat_1=16.5 +lat_2=34.5 +lat_0=16.5 +lon_0=-92.0 "
    "+x_0=0 +y_0=0 +a=6378137.0 +b=6356752.314245179 +to_meter=0.3048006096012192 +no_defs"
),
}

def get_custom_crs_from_name(crs_name: str) -> QgsCoordinateReferenceSystem:
    """
    Looks up a custom CRS name and returns a QGIS CRS object.
    (This function remains the same but is included for completeness).
    """
    proj_string = CUSTOM_CRS_DEFINITIONS.get(crs_name)
    
    if not proj_string:
        return None
        
    custom_crs = QgsCoordinateReferenceSystem()
    custom_crs.createFromProj(proj_string)
    
    if custom_crs.isValid():
        print(f"Found and created valid custom CRS for '{crs_name}'.")
        return custom_crs
    
    return None

def save_custom_crs_to_database(crs_name: str, proj_string: str) -> bool:
    """
    Saves a custom projection to the QGIS user CRS database.
    This version is compatible with the QGIS 3.4 API.
    """
    custom_crs = QgsCoordinateReferenceSystem()
    if not custom_crs.createFromProj(proj_string):
        print(f"!!! ERROR: Failed to create CRS object for '{crs_name}' from PROJ string.")
        return False

    # In QGIS 3.4, you save the CRS using the saveAsUserCrs() method
    # on the QgsCoordinateReferenceSystem object itself.
    result, message = custom_crs.saveAsUserCrs(crs_name)
    
    if result == 0: # 0 means success
        print(f"Successfully saved '{crs_name}' to the QGIS user CRS database.")
        return True
    elif "already exists" in message:
        print(f"CRS '{crs_name}' already exists in the database. No action needed.")
        return True
    else:
        print(f"!!! ERROR: Failed to save '{crs_name}' to database. Reason: {message}")
        return False