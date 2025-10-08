"""Generates an expression to convert a coded value domain into a label expression."""

import sys
from osgeo import ogr, gdal


def get_domain_name_and_values(layer, field_name):
    """
    Given a QgsVectorLayer and a field name, return the domain name and its coded values if it exists.

    Args:
        layer (QgsVectorLayer): The vector layer to inspect.
        field_name (str): The name of the field to check for a domain.

    Returns:
        tuple: (domain_name (str or None), coded_values (dict or None))
    """
    gdal.UseExceptions()  # Make GDAL raise Python exceptions for easier debugging
    full_path = layer.dataProvider().dataSourceUri()  # Assume geodatabase since domains are Esri-specific
    if "|" not in full_path:
        return None, None  # Not a geodatabase path
    parts = full_path.split("|")
    if len(parts) < 2:
        return None, None  # Not a valid geodatabase path
    gdb = parts[0]
    fc = parts[1]
    if "=" not in fc:
        return None, None  # Not a valid feature class part
    fc = fc.split("=")[1]

    ds = ogr.Open(gdb, 0)  # 0 = read-only
    if ds is None:
        raise RuntimeError(f"Could not open geodatabase: {gdb}")

    lyr = ds.GetLayerByName(fc)
    if lyr is None:
        raise RuntimeError(f"Feature class not found: {fc}")

    defn = lyr.GetLayerDefn()
    field_idx = defn.GetFieldIndex(field_name)
    if field_idx < 0:
        raise RuntimeError(f'Field "{field_name}" not found in "{fc}".')

    fdefn = defn.GetFieldDefn(field_idx)

    domain_name = None
    domain_type = None  # Will hold OGR enum if available

    if hasattr(fdefn, "GetDomainName"):
        domain_name = fdefn.GetDomainName() or None
        dom_obj = None
        if domain_name:
            if hasattr(lyr, "GetFieldDomain"):
                dom_obj = lyr.GetFieldDomain(domain_name)
            if dom_obj is None and hasattr(ds, "GetFieldDomain"):
                dom_obj = ds.GetFieldDomain(domain_name)

        if dom_obj is not None and hasattr(dom_obj, "GetDomainType"):
            domain_type = dom_obj.GetDomainType()

        if dom_obj is not None and hasattr(dom_obj, "GetEnumeration"):
            enum = dom_obj.GetEnumeration()
            return domain_name, enum

    return domain_name, None


def domain_to_case_expression(layer, field_name):    
    """Generate a QGIS expression that maps coded values to their descriptions using a CASE statement.
    
    Example case statement:
        CASE
            WHEN "your_field" = 'A' THEN 'Apple'
            WHEN "your_field" = 'B' THEN 'Banana'
            WHEN "your_field" = 'C' THEN 'Cherry'
        END
    
    """
    domain_name, coded_values = get_domain_name_and_values(layer, field_name)    
    if not coded_values:
        return None
    case_statements = []
    for code, description in coded_values.items():
        case_statements.append(f"WHEN {field_name} = '{code}' THEN '{description}'")
    case_expression = "CASE\n    " + "\n    ".join(case_statements) + "\nEND"
    return case_expression