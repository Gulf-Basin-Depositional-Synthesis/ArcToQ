"""Converts ArcGIS Pro layer files (.lyrx) to QGIS layer files (.qlr)."""

import json
import os
from pathlib import Path
import re
import io

from qgis.core import (
    QgsApplication,
    QgsVectorLayer,
    QgsRasterLayer,
    QgsVirtualLayerDefinition,
    QgsLayerDefinition,
    QgsReadWriteContext,
    QgsLayerTreeGroup,
    QgsProject,
    Qgis
)


from arc_to_q.converters.vector.vector_renderer import VectorRenderer
from arc_to_q.converters.label_converter import set_labels
from arc_to_q.converters.raster.raster_renderer import (
    apply_raster_symbology,
    switch_to_relative_path,
)



def _open_lyrx(lyrx):
    with open(lyrx, 'r', encoding='utf-8') as f:
        data = json.load(f)

    layers = data.get("layers", [])
    if len(layers) != 1:
        raise Exception(f"Unexpected number of layers found: {len(layers)}")

    return data


def _parse_definition_query(layer_def: dict):
    """
    Parses the definition query (or "subset string") into a valid one for a QGIS layer.

    Example ArcGIS Pro queries from the LYRX JSON:
        "Unit_Id" = 22
        "WellData_UnitThk" <> -9999 AND "WellData_Unit_Id" = 22
        [FeatureName] = 'LK_Boundary'

    Example QGIS equivalents (including pipe delimiter for source URI):
        |subset=Unit_Id = 22
        |subset="WellData_UnitThk" != -9999 AND "WellData_Unit_Id" = 22
        |subset=FeatureName = 'LK_Boundary'

    Args:
        layer_def (dict): The parsed JSON dictionary of an ArcGIS layer definition.

    Returns:
        str: The QGIS-compatible definition query string, or an empty string if none,
             including the leading "|subset=" part.
    """
    feature_table = layer_def.get("featureTable", {})
    definition_query = feature_table.get("definitionExpression", "").strip()

    if definition_query:
        # Replace ArcGIS-style operators with QGIS-compatible ones
        # ArcGIS uses '<>' for 'not equal', QGIS uses '!='
        qgis_query = definition_query.replace("<>", "!=")

        # Remove any square brackets around field names
        qgis_query = qgis_query.replace("[", "").replace("]", "")
        # Return the query string with the pipe delimiter for QGIS
        return f"|subset={qgis_query}"
    return ""


def _make_uris(in_folder, conn_str, factory, dataset, dataset_type, def_query, out_file):
    """Helper to build absolute and relative URIs for a dataset.
    
    Args:
        in_folder (str): Path to the folder containing the .lyrx file.
        conn_str (str): The workspace connection string from the .lyrx file.
        factory (str): The workspace factory type (e.g. "FileGDB", "Shapefile").
        dataset (str): The dataset name (e.g. feature class or table name).
        dataset_type (str): The dataset type (e.g. "esriDTRasterDataset", "esriDTFeatureClass").
        def_query (str): The definition query string to append to the URI (or empty string).
            The query should already be in QGIS-compatible format, including the leading "|subset=".
        out_file (str): Path to the converted QGIS .qlr file.

    Returns:
        tuple: (abs_uri, rel_uri)
          - abs_uri: Absolute QGIS URI for the dataset
          - rel_uri: Relative QGIS URI for the dataset
    """
    if "=" in conn_str:
        _, raw_path = conn_str.split("=", 1)
    else:
        raw_path = conn_str

    lyrx_dir = Path(in_folder)
    abs_path = (lyrx_dir / raw_path).resolve()

    # Absolute URI
    if factory == "FileGDB":
        if dataset_type == "esriDTFeatureClass":
            abs_uri = f"{abs_path.as_posix()}|layername={dataset}"
        elif dataset_type == "esriDTRasterDataset":
            abs_uri = os.path.join(abs_path.as_posix(), dataset)
        else:
            raise NotImplementedError(f"Unsupported FileGDB dataset type: {dataset_type}")
    else:
        abs_uri = os.path.join(abs_path.as_posix(), dataset)

    # Relative URI
    out_dir = Path(out_file).parent.resolve()
    rel_path = Path(os.path.relpath(abs_path, start=out_dir))
    if factory == "FileGDB":
        if dataset_type == "esriDTFeatureClass":
            rel_uri = f"{rel_path.as_posix()}|layername={dataset}"
        elif dataset_type == "esriDTRasterDataset":
            rel_uri = os.path.join(rel_path.as_posix(), dataset)
        else:
            raise NotImplementedError(f"Unsupported FileGDB dataset type: {dataset_type}")
    else:
        rel_uri = os.path.join(rel_path.as_posix(), dataset)

    if dataset_type == "esriDTFeatureClass":
        if factory == "Shapefile":
            if not rel_uri.lower().endswith(".shp"):
                rel_uri += ".shp"
            if not abs_uri.lower().endswith(".shp"):
                abs_uri += ".shp"

        if def_query:
            abs_uri += def_query
            rel_uri += def_query

    return abs_uri, rel_uri


def _parse_source(in_folder, data_connection, def_query, out_file):
    """Build both absolute and relative QGIS-friendly URIs for a dataset.
    
    Handles both direct feature class connections and joined tables.
    
    Args:
        in_folder (str): Path to the folder containing the .lyrx file.
        data_connection (dict): The data connection info from the .lyrx file.
        def_query (str): The definition query string to append to the URI (or empty string).
            The query should already be in QGIS-compatible format, including the leading "|subset=".
        out_file (str): Path to the converted QGIS .qlr file.

    Returns:
        tuple: (abs_uri, rel_uri, join_info)
          - abs_uri: Absolute QGIS URI for the base dataset
          - rel_uri: Relative QGIS URI for the base dataset
          - join_info: dict describing join (or None if not a join)
    """
    factory = data_connection.get("workspaceFactory")
    conn_str = data_connection.get("workspaceConnectionString", "")
    dataset = data_connection.get("dataset")
    dataset_type = data_connection.get("datasetType")

    # --- Handle direct connections (FileGDB, Shapefile, Raster) ---
    if factory and conn_str and dataset:
        return _make_uris(in_folder, conn_str, factory, dataset, dataset_type, def_query, out_file), None

    # --- Handle table join (CIMRelQueryTableDataConnection) ---
    if data_connection.get("type") == "CIMRelQueryTableDataConnection":
        if def_query:
            raise NotImplementedError("Definition queries on joined layers are not yet supported.")

        source = data_connection.get("sourceTable", {})
        dest = data_connection.get("destinationTable", {})

        # Build URIs for source (feature class) and destination (table)
        (abs_uri, rel_uri), _ = _parse_source(in_folder, source, "", out_file)
        (abs_table_uri, rel_table_uri), _ = _parse_source(in_folder, dest, "", out_file)

        join_info = {
            "primaryKey": data_connection.get("primaryKey"),
            "foreignKey": data_connection.get("foreignKey"),
            "joinType": data_connection.get("joinType", "esriLeftOuterJoin"),
            "destinationAbs": abs_table_uri,
            "destinationRel": rel_table_uri,
            "destinationName": dest.get("dataset")
        }

        return (abs_uri, rel_uri), join_info

    raise NotImplementedError(f"Unsupported dataConnection type: {data_connection.get('type')}")


def _set_scale_visibility(layer: QgsVectorLayer, layer_def: dict):
    """Set the scale visibility for a QGIS layer based on the ArcGIS layer definition."""
    scale_opts = layer_def.get("layerScaleVisibilityOptions", {})
    if scale_opts:
        if scale_opts.get("type") != "CIMLayerScaleVisibilityOptions":
            raise Exception(f"Unexpected layer scale visibility options type: {scale_opts.get('type')}")
        if "showLayerAtAllScales" in scale_opts and scale_opts["showLayerAtAllScales"] is True:
            # Show layer at all scales, so no action needed
            return

    # Not showing at all scales, so set min/max if defined
    min_scale = layer_def.get("minScale", 0)
    max_scale = layer_def.get("maxScale", 0)
    if min_scale == 0 and max_scale == 0:
        # No scale limits defined, so no action needed
        return

    layer.setScaleBasedVisibility(True)
    layer.setMinimumScale(min_scale)
    layer.setMaximumScale(max_scale)


def _set_metadata(layer: QgsVectorLayer, layer_def: dict):
    """
    Sets the metadata for a QGIS layer based on the ArcGIS layer definition.

    Args:
        layer (QgsVectorLayer): The in-memory QGIS layer object to modify.
        layer_def (dict): The parsed JSON dictionary of an ArcGIS layer definition.
    """
    md = layer.metadata()
    title = layer_def.get("name", "")
    if title:
        md.setTitle(title)

    if layer_def.get("useSourceMetadata", False) == False:
        attribution = layer_def.get("attribution", "")
        description = layer_def.get("description", "")
        if attribution:
            md.setRights([attribution])
        if description:
            md.setAbstract(description)
    else:
        attribution = ""
        description = ""

    if attribution or description or title:
        layer.setMetadata(md)


def _set_display_field(layer: QgsVectorLayer, layer_def: dict):
    """
    Sets the display field (or "Display Name") for a QGIS layer.

    In ArcGIS Pro, the "display field" controls what text is shown when using
    the Identify tool. In QGIS, this is called the "Display Name".

    Args:
        layer (QgsVectorLayer): The in-memory QGIS layer object to modify.
        layer_def (dict): The parsed JSON dictionary of an ArcGIS layer definition.
    """
    # In the LYRX JSON, the display field is usually under featureTable
    feature_table = layer_def.get("featureTable", {})
    display_field = feature_table.get("displayField")

    if display_field and layer:
        layer.setDisplayExpression(f'"{display_field}"')


def _set_field_aliases_and_visibility(layer: QgsVectorLayer, layer_def: dict):
    """
    Sets field aliases and visibility for a QGIS layer based on the ArcGIS layer definition.

    Args:
        layer (QgsVectorLayer): The in-memory QGIS layer object to modify.
        layer_def (dict): The parsed JSON dictionary of an ArcGIS layer definition.
    """
    feature_table = layer_def.get("featureTable", {})
    fields_info = feature_table.get("fieldDescriptions", [])

    if not fields_info or not layer:
        return

    # Build a mapping of field name to alias and visibility
    alias_map = {}
    visible_fields = set()
    for field in fields_info:
        name = field.get("fieldName")
        alias = field.get("alias", name)
        visible = field.get("visible", True)
        if name:
            alias_map[name] = alias
            if visible:
                visible_fields.add(name)

    # Apply aliases
    for idx, qgs_field in enumerate(layer.fields()):
        field_name = qgs_field.name()
        if field_name in alias_map:
            layer.setFieldAlias(idx, alias_map[field_name])

    # Configure attribute table visibility
    table_config = layer.attributeTableConfig()
    new_columns = []

    for col in table_config.columns():
        field_name = col.name
        if field_name:  # skip empty/system columns
            col.hidden = field_name not in visible_fields
        new_columns.append(col)

    table_config.setColumns(new_columns)
    layer.setAttributeTableConfig(table_config)


def _convert_feature_layer(in_folder, layer_def, out_file, project):
    layer_name = layer_def['name']
    f_table = layer_def["featureTable"]
    if f_table["type"] != "CIMFeatureTable":
        raise Exception(f"Unexpected feature table type: {f_table['type']}")

    # Parse source: returns (abs_uri, rel_uri), join_info
    def_query = _parse_definition_query(layer_def)
    (abs_uri, rel_uri), join_info = _parse_source(in_folder, f_table["dataConnection"], def_query, out_file)

    # Apply join if present
    if join_info:
        # Data source URIs
        source_uri = abs_uri
        join_uri = join_info["destinationAbs"]

        # Build SQL for the virtual layer
        sql = f"""
            SELECT f.*, j.*
            FROM "{layer_def['name']}" AS f
            LEFT JOIN "{join_info['destinationName']}" AS j
            ON f."{join_info['primaryKey']}" = j."{join_info['foreignKey']}"
        """

        # Create virtual layer definition
        vl_def = QgsVirtualLayerDefinition()
        vl_def.addSource(layer_def['name'], source_uri, "ogr", "")
        vl_def.addSource(join_info['destinationName'], join_uri, "ogr", "")
        vl_def.setQuery(sql)

        # Create virtual layer
        layer = QgsVectorLayer(vl_def.toString(), layer_name, "virtual")
        if not layer.isValid():
            raise RuntimeError(f"Virtual layer failed to create: {layer_name}")

    else:
        # No join, just load the feature layer normally
        layer = QgsVectorLayer(abs_uri, layer_name, "ogr")
        if not layer.isValid():
            raise RuntimeError(f"Layer failed to load: {layer_name} {abs_uri}")
        
        # Attempt to switch to relative URI for portable QLR files
        # This is especially important for network drives where path resolution can be problematic
        test_layer = QgsVectorLayer(rel_uri, f"test_{layer_name}", "ogr")
        if test_layer.isValid():
            # Relative path works, switch the main layer to use it
            layer.setDataSource(rel_uri, layer.name(), layer.providerType())
            if not layer.isValid():
                # If switching to relative path breaks the layer, recreate with absolute path
                layer = QgsVectorLayer(abs_uri, layer_name, "ogr")
        # If relative path doesn't work, keep using absolute path (no action needed)

    # Set other layer properties
    _set_display_field(layer, layer_def)
    renderer_factory = VectorRenderer()
    qgis_renderer = renderer_factory.create_renderer(layer_def.get("renderer", {}), layer, full_layer_def=layer_def)
    layer.setRenderer(qgis_renderer)
    _set_field_aliases_and_visibility(layer, layer_def)
    set_labels(layer, layer_def)

    if not layer.isValid():
        raise RuntimeError(f"Layer became invalid after setting properties: {layer_name}")

    project.addMapLayer(layer, False)

    root = project.layerTreeRoot()
    node = root.addLayer(layer)
    
    # Set visibility if specified
    if 'visibility' in layer_def:
        node.setItemVisibilityChecked(layer_def['visibility'])
    return layer

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
    
    rlayer = QgsRasterLayer(abs_uri, layer_name)
    if not rlayer.isValid():
        error_msg = f"Failed to load raster layer: {abs_uri}"
        if rlayer.error().summary():
            error_msg += f"\nError: {rlayer.error().summary()}"
        
        # Additional debugging info
        if os.path.exists(abs_uri):
            error_msg += f"\nFile exists but GDAL cannot read it. Check file format/permissions."
        else:
            error_msg += f"\nFile does not exist at: {abs_uri}"
        
        print(error_msg)
        raise RuntimeError(error_msg)
    
    return rlayer

def _parse_xml_dataconnection(xml_string):
    """
    Parses XML data connection strings to extract raster path and dataset.
    Handles various XML formats including complex nested structures.
    """
    print(f"    Attempting to parse XML (length: {len(xml_string)})")
    print(f"    First 300 chars: {xml_string[:300]}")
    
    # Method 1: Standard CIMDataConnection format
    ws_match = re.search(
        r"<WorkspaceConnectionString>DATABASE=([^<]+)</WorkspaceConnectionString>",
        xml_string
    )
    dataset_match = re.search(
        r"<Dataset>([^<]+)</Dataset>",
        xml_string
    )
    
    if ws_match and dataset_match:
        path = ws_match.group(1).strip()
        dataset = dataset_match.group(1).strip()
        
        if path.endswith(';'):
            path = path[:-1]
        
        print(f"    Parsed using standard format:")
        print(f"      Path: {path}")
        print(f"      Dataset: {dataset}")
        
        return {
            "workspaceConnectionString": f"DATABASE={path}",
            "dataset": dataset,
            "workspaceFactory": "Raster",
            "datasetType": "esriDTRasterDataset"
        }
    
    # Method 2: Complex nested XML (XmlRasterDataset with GeometricFunction)
    # This is the format in your problematic file
    # Look for RasterDatasetName which contains the actual file info
    if "XmlRasterDataset" in xml_string and "GeometricFunction" in xml_string:
        print(f"    Detected XmlRasterDataset with GeometricFunction")
        
        # Look for the PathName in the nested structure
        path_match = re.search(r"<PathName>([^<]+)</PathName>", xml_string)
        
        # For the dataset name, we need to look in the RasterDatasetName section
        # The actual filename is in a <Name> tag within RasterDatasetName
        # Use a more specific pattern to avoid matching "Geometric Function"
        
        # First try to find the name within RasterDatasetName context
        raster_section = re.search(
            r"RasterDatasetName[^>]*>.*?<Name>([^<]+\.(?:png|tif|tiff|jpg|jpeg|img|sid|ecw))</Name>",
            xml_string,
            re.IGNORECASE | re.DOTALL
        )
        
        if not raster_section:
            # Try alternative: look for Name tag that contains an image extension
            raster_section = re.search(
                r"<Name>([^<]+\.(?:png|tif|tiff|jpg|jpeg|img|sid|ecw))</Name>",
                xml_string,
                re.IGNORECASE
            )
        
        if path_match and raster_section:
            path = path_match.group(1).strip()
            dataset = raster_section.group(1).strip()
            
            print(f"    Parsed XmlRasterDataset format:")
            print(f"      Path: {path}")
            print(f"      Dataset: {dataset}")
            
            return {
                "workspaceConnectionString": f"DATABASE={path}",
                "dataset": dataset,
                "workspaceFactory": "Raster",
                "datasetType": "esriDTRasterDataset"
            }
    
    # Method 3: Look for PathName and any Name tag (but skip "Geometric Function")
    path_match = re.search(r"<PathName>([^<]+)</PathName>", xml_string)
    
    # Find all <Name> tags and filter out function names
    name_matches = re.findall(r"<Name>([^<]+)</Name>", xml_string)
    
    dataset = None
    for name in name_matches:
        # Skip function names and look for actual filenames
        if not any(word in name.lower() for word in ['function', 'geometric', 'transform']):
            # Check if it looks like a filename (has extension)
            if '.' in name and any(name.lower().endswith(ext) for ext in ['.png', '.tif', '.tiff', '.jpg', '.jpeg', '.img', '.sid', '.ecw']):
                dataset = name.strip()
                print(f"    Found dataset name: {dataset}")
                break
    
    if path_match and dataset:
        path = path_match.group(1).strip()
        
        print(f"    Parsed using PathName/filtered Name format:")
        print(f"      Path: {path}")
        print(f"      Dataset: {dataset}")
        
        return {
            "workspaceConnectionString": f"DATABASE={path}",
            "dataset": dataset,
            "workspaceFactory": "Raster",
            "datasetType": "esriDTRasterDataset"
        }
    
    # Method 4: Last resort - look for path and any image filename in the XML
    path = None
    dataset = None
    
    # Try to find a path
    path_patterns = [
        r"<PathName>([^<]+)</PathName>",
        r"DATABASE=([^;<\"]+)",
        r"Workspace\s*=\s*([^;<\"]+)",
    ]
    
    for pattern in path_patterns:
        match = re.search(pattern, xml_string, re.IGNORECASE)
        if match:
            path = match.group(1).strip()
            if ';' in path:
                path = path.split(';')[0]
            print(f"    Found path using pattern '{pattern}': {path}")
            break
    
    # Look for any string that looks like an image filename
    # This regex looks for strings that have image extensions
    file_pattern = r">([^<>]*\.(?:png|tif|tiff|jpg|jpeg|img|sid|ecw))<"
    file_matches = re.findall(file_pattern, xml_string, re.IGNORECASE)
    
    if file_matches:
        # Take the last match as it's more likely to be the actual filename
        # (earlier matches might be in comments or examples)
        dataset = file_matches[-1].strip()
        print(f"    Found dataset using file pattern: {dataset}")
    
    if path and dataset:
        # Clean up Windows paths
        path = path.replace('\\', '/')
        
        print(f"    Successfully parsed using fallback patterns:")
        print(f"      Path: {path}")
        print(f"      Dataset: {dataset}")
        
        return {
            "workspaceConnectionString": f"DATABASE={path}",
            "dataset": dataset,
            "workspaceFactory": "Raster",
            "datasetType": "esriDTRasterDataset"
        }
    
    # If all methods fail, log what we found
    print(f"    ERROR: Could not parse XML")
    print(f"      Path found: {path}")
    print(f"      Dataset found: {dataset}")
    print(f"      All Name tags found: {name_matches if 'name_matches' in locals() else 'None'}")
    print(f"    Last 300 chars: {xml_string[-300:]}")
    
    return None


def _convert_raster_layer(in_folder, layer_def, out_file, project):
    """Create a QgsRasterLayer from a CIMRasterLayer layer definition."""
    
    layer_name = layer_def.get("name", "Raster")
    print(f"Converting raster layer: {layer_name}")
    
    # Get the data connection
    data_connection = layer_def.get("dataConnection")
    
    if not data_connection:
        raise RuntimeError(f"Raster layer '{layer_name}' missing 'dataConnection'.")
    
    # Handle different forms of data_connection
    
    # Case 1: data_connection is a string (XML)
    if isinstance(data_connection, str):
        print(f"  dataConnection is XML string, parsing...")
        parsed = _parse_xml_dataconnection(data_connection)
        if parsed:
            data_connection = parsed
        else:
            # Try to provide more helpful error
            print(f"  Could not parse XML data connection")
            print(f"  XML preview: {data_connection[:500]}")
            raise NotImplementedError(f"Could not parse XML data connection for layer: {layer_name}")
    
    # Case 2: data_connection is a dict
    elif isinstance(data_connection, dict):
        print(f"  dataConnection is dict with keys: {list(data_connection.keys())}")
        
        # Check if the dataset field contains XML
        dataset_value = data_connection.get('dataset', '')
        
        # Check if dataset looks like XML (contains tags and namespaces)
        if isinstance(dataset_value, str) and ('<' in dataset_value or 'xmlns' in dataset_value or 'xsi:type' in dataset_value):
            print(f"  Found XML in 'dataset' field, parsing...")
            print(f"  XML length: {len(dataset_value)}")
            
            # The dataset field contains XML - parse it
            parsed = _parse_xml_dataconnection(dataset_value)
            if parsed:
                # Keep the workspace info from the parent dict if available
                if 'workspaceConnectionString' in data_connection:
                    # Use the parent's workspace if the parsed one doesn't have it
                    if not parsed.get('workspaceConnectionString') or parsed['workspaceConnectionString'] == 'DATABASE=':
                        parsed['workspaceConnectionString'] = data_connection['workspaceConnectionString']
                
                data_connection = parsed
                print(f"  Replaced data_connection with parsed XML")
            else:
                # Parsing failed, but we might still have valid data in the parent dict
                # Check if we have the other required fields
                if 'workspaceConnectionString' in data_connection:
                    print(f"  WARNING: Could not parse XML in dataset field")
                    print(f"  Will attempt to extract dataset name from XML")
                    
                    # Try to extract just the dataset name from the XML
                    name_match = re.search(r">([^<>]+\.(?:png|tif|tiff|jpg|jpeg|img|sid|ecw))<", dataset_value, re.IGNORECASE)
                    if name_match:
                        dataset_name = name_match.group(1).strip()
                        print(f"  Extracted dataset name: {dataset_name}")
                        data_connection['dataset'] = dataset_name
                    else:
                        # Last resort - look for the layer name with an image extension
                        possible_name = f"{layer_name}.png"
                        print(f"  Could not extract dataset name, using: {possible_name}")
                        data_connection['dataset'] = possible_name
                else:
                    raise NotImplementedError(f"Could not parse XML in dataset field and no workspace info available")
    
    # Case 3: Unexpected type
    else:
        raise RuntimeError(f"Unexpected data_connection type: {type(data_connection)}")
    
    # Normalize dictionary keys (handle both lowercase and capitalized)
    normalized = {}
    for key, value in data_connection.items():
        if key == 'WorkspaceConnectionString':
            normalized['workspaceConnectionString'] = value
        elif key == 'Dataset':
            normalized['dataset'] = value
        elif key == 'WorkspaceFactory':
            normalized['workspaceFactory'] = value
        elif key == 'DatasetType':
            normalized['datasetType'] = value
        else:
            normalized[key] = value
    data_connection = normalized
    
    # Validate required keys
    required_keys = ['workspaceConnectionString', 'dataset', 'workspaceFactory']
    missing_keys = [k for k in required_keys if k not in data_connection]
    
    if missing_keys:
        raise RuntimeError(f"data_connection missing required keys: {missing_keys}\nAvailable keys: {list(data_connection.keys())}")
    
    # Final check: ensure dataset is not XML
    if '<' in str(data_connection.get('dataset', '')):
        raise RuntimeError(f"dataset field still contains XML after parsing: {data_connection['dataset'][:100]}...")
    
    print(f"  Final data_connection: {data_connection}")
    
    # Now call _parse_source with the cleaned data_connection
    try:
        (abs_uri, rel_uri), join_info = _parse_source(in_folder, data_connection, "", out_file)
    except Exception as e:
        import traceback
        print(f"  Error in _parse_source: {e}")
        traceback.print_exc()
        raise RuntimeError(f"Failed to parse raster source: {e}")
    
    print(f"  Absolute URI: {abs_uri}")
    print(f"  Relative URI: {rel_uri}")
    
    # Suppress GDAL warnings
    gdal_log_file = os.environ.get('CPL_LOG')
    os.environ['CPL_LOG'] = os.devnull
    
    try:
        # Create the raster layer
        rlayer = QgsRasterLayer(abs_uri, layer_name, "gdal")
        
        if not rlayer.isValid():
            # Detailed error reporting
            if os.path.exists(abs_uri):
                error_msg = f"Raster file exists but GDAL cannot open it: {abs_uri}"
            else:
                error_msg = f"Raster file not found: {abs_uri}"
                parent = os.path.dirname(abs_uri)
                if os.path.exists(parent):
                    try:
                        files = [f for f in os.listdir(parent) if f.endswith(('.png', '.tif', '.jpg'))][:5]
                        error_msg += f"\nImage files in directory: {files}"
                    except:
                        pass
            
            raise RuntimeError(f"Raster layer failed to load: {layer_name}\n{error_msg}")
        
    finally:
        # Restore GDAL logging
        if gdal_log_file:
            os.environ['CPL_LOG'] = gdal_log_file
        else:
            os.environ.pop('CPL_LOG', None)
    
    # Set relative path
    try:
        rlayer.setDataSource(rel_uri, rlayer.name(), rlayer.providerType())
    except Exception:
        print(f"  Warning: Could not set relative path for raster layer")
    
    # Apply symbology
    apply_raster_symbology(rlayer, layer_def)
    
    # Add to project
    project.addMapLayer(rlayer, False)
    print(f"  Successfully converted raster layer: {layer_name}")
    
    return rlayer

def _export_qlr_with_visibility(out_layer, layer_def: dict, out_file: str) -> None:
    """
    Exports a .qlr that contains a layer-tree entry with a "checked" (visible) state.
    """
    root = QgsProject.instance().layerTreeRoot()
    node = root.findLayer(out_layer.id())
    if node:
        # Set visibility before exporting
        if 'visibility' in layer_def:
            node.setItemVisibilityChecked(layer_def['visibility'])

        # Export to an in-memory string instead of a file
        mem_file = io.StringIO()
        ok, error_message = QgsLayerDefinition.exportLayerDefinition(mem_file, [node])
        if not ok:
            raise RuntimeError(f"Failed to export layer definition to memory: {error_message}")
        
        # Get the XML string from memory
        qlr_content = mem_file.getvalue()
        
        # Post-process the XML string to inject symbol levels
        final_qlr_content = VectorRenderer().post_process_qlr_for_symbol_levels(qlr_content, layer_def)

        # Write the final, corrected content to the output file
        print(f"  Attempting to write to: {out_file}")
        print(f"  Content length: {len(final_qlr_content)} characters")
        
        try:
            with open(out_file, 'w', encoding='utf-8') as f:
                f.write(final_qlr_content)
            print(f"  Successfully wrote file")
            
            # Verify the file was created
            if os.path.exists(out_file):
                print(f"  File verified to exist at: {out_file}")
                print(f"  File size: {os.path.getsize(out_file)} bytes")
            else:
                print(f"  WARNING: File write succeeded but file doesn't exist!")
        except Exception as e:
            print(f"  ERROR writing file: {e}")
            raise


def convert_lyrx(in_lyrx, out_folder=None, qgs=None):
    """Convert an ArcGIS Pro .lyrx file to a QGIS .qlr file"""
    print(f"Converting {in_lyrx}...")
    if not out_folder:
        out_folder = os.path.dirname(in_lyrx)
    in_folder = os.path.abspath(os.path.dirname(in_lyrx))
    out_file = os.path.join(out_folder, os.path.basename(in_lyrx).replace(".lyrx", ".qlr"))
    
    manage_qgs = qgs is None
    if manage_qgs:
        qgs = QgsApplication([], False)
        qgs.initQgis()

    project = QgsProject.instance()

    try:
        lyrx = _open_lyrx(in_lyrx)
        if len(lyrx["layers"]) != 1:
            raise Exception(f"Unexpected number of layers found: {len(lyrx['layers'])}")

        layer_uri = lyrx["layers"][0]
        layer_def = next((ld for ld in lyrx.get("layerDefinitions", []) if ld.get("uRI") == layer_uri), {})
        
        layer_type = layer_def.get("type")
        nodes_to_export = []
        
        if layer_type == "CIMGroupLayer":
            root_node = _convert_group_layer(in_folder, layer_def, lyrx, out_file, project)
            nodes_to_export = [root_node]
        elif layer_type == "CIMFeatureLayer":
            out_layer = _convert_feature_layer(in_folder, layer_def, out_file, project)
            _set_metadata(out_layer, layer_def)
            _set_scale_visibility(out_layer, layer_def)
            
            # Get the layer tree node (it should exist now)
            root = QgsProject.instance().layerTreeRoot()
            node = root.findLayer(out_layer.id())
            if node:
                nodes_to_export = [node]
                                
        elif layer_type == 'CIMRasterLayer':
            out_layer = _convert_raster_layer(in_folder, layer_def, out_file, project)
            _set_metadata(out_layer, layer_def)
            _set_scale_visibility(out_layer, layer_def)
            _export_qlr_with_visibility(out_layer, layer_def, out_file)

        elif layer_type == 'CIMAnnotationLayer':
            print("Annotation layers are unsupported")
            return
        else:
            raise Exception(f"Unhandled layer type: {layer_type}")

        # Export the QLR including the layer tree node(s)
        if nodes_to_export:
            # Create a temporary file for initial export
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w', suffix='.qlr', delete=False, encoding='utf-8') as temp_file:
                temp_path = temp_file.name
            
            try:
                # Export to temporary file
                ok, error_message = QgsLayerDefinition.exportLayerDefinition(temp_path, nodes_to_export)
                
                if not ok:
                    raise RuntimeError(f"Failed to export layer definition: {error_message}")
                
                # Read the XML content from the temp file
                with open(temp_path, 'r', encoding='utf-8') as f:
                    qlr_content = f.read()
                
                # Post-process for symbol level
                final_qlr_content = VectorRenderer().post_process_qlr_for_symbol_levels(qlr_content, layer_def)
                
                # Write to the actual output file
                with open(out_file, 'w', encoding='utf-8') as f:
                    f.write(final_qlr_content)
                
            finally:
                # Clean up the temporary file
                if os.path.exists(temp_path):
                    os.remove(temp_path)

        print(f"Successfully converted {in_lyrx} to {out_file}")
    except Exception as e:
        print(f"Error converting LYRX: {e}")
        raise
    finally:
        project.clear()  # Clear the project instance for the next run
        if manage_qgs:
            qgs.exitQgis()
    

def _convert_group_layer(in_folder, group_layer_def, lyrx_json, out_file, project):
    """
    Recursively processes a group layer and its children.
    """
    group_name = group_layer_def.get('name', 'group')
    group_node = QgsLayerTreeGroup(group_name)

    # Set visibility and expanded state for the group itself
    group_node.setItemVisibilityChecked(bool(group_layer_def.get("visibility", True)))
    group_node.setExpanded(bool(group_layer_def.get("expanded", False)))

    # Process child layers using the correct key: "layers"
    for member_uri in group_layer_def.get("layers", []):
        member_def = next((ld for ld in lyrx_json.get("layerDefinitions", []) if ld.get("uRI") == member_uri), None)
        if not member_def:
            continue

        layer_type = member_def.get("type")
        if layer_type == "CIMGroupLayer":
            child_group = _convert_group_layer(in_folder, member_def, lyrx_json, out_file, project)
            group_node.addChildNode(child_group)
        elif layer_type == "CIMFeatureLayer":
            child_layer = _convert_feature_layer(in_folder, member_def, out_file, project)
            _set_metadata(child_layer, member_def)
            _set_scale_visibility(child_layer, member_def)
            node = group_node.addLayer(child_layer)
            if node:
                node.setItemVisibilityChecked(bool(member_def.get("visibility", True)))
                node.setExpanded(bool(member_def.get("expanded", False)))

        elif layer_type == 'CIMRasterLayer':
            child_layer = _convert_raster_layer(in_folder, member_def, out_file, project)
            _set_metadata(child_layer, member_def)
            _set_scale_visibility(child_layer, member_def)
            node = group_node.addLayer(child_layer)
            if node:
                node.setItemVisibilityChecked(bool(member_def.get("visibility", True)))
                node.setExpanded(bool(member_def.get("expanded", False)))

    return group_node


if __name__ == "__main__":
    output_folder = r""
    in_lyrx = r""

    try:
        qgs = QgsApplication([], False)
        qgs.initQgis()

        convert_lyrx(in_lyrx, output_folder, qgs)
    except Exception as e:
        print(f"Error converting LYRX: {e}")
    finally:
        qgs.exitQgis()