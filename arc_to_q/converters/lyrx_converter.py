"""Converts ArcGIS Pro layer files (.lyrx) to QGIS layer files (.qlr)."""

import json
import os
from pathlib import Path
import re
import io
import tempfile

from qgis.core import (
    QgsApplication,
    QgsVectorLayer,
    QgsRasterLayer,
    QgsMapLayer,
    QgsVirtualLayerDefinition,
    QgsLayerDefinition,
    QgsReadWriteContext,
    QgsLayerTreeGroup,
    QgsProject,
    QgsDataSourceUri,
    QgsVectorLayerTemporalProperties,
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

def _parse_xml_dataconnection(xml_string: str) -> dict | None:
    """
    Parses complex XML data connection strings to extract raster path and dataset.

    Some .lyrx files, especially those involving raster functions or complex sources,
    store the data connection as a nested XML string instead of a simple dictionary.
    This function attempts to extract the key workspace and dataset information
    using several regular expression patterns.

    Args:
        xml_string (str): The XML content from the 'dataConnection' or 'dataset' field.

    Returns:
        dict | None: A dictionary with 'workspaceConnectionString', 'dataset', 'workspaceFactory',
                      and 'datasetType' keys, or None if parsing fails.
    """
    # Method 1: Look for a standard CIMDataConnection format within the XML.
    ws_match = re.search(r"<WorkspaceConnectionString>DATABASE=([^<]+)</WorkspaceConnectionString>", xml_string)
    dataset_match = re.search(r"<Dataset>([^<]+)</Dataset>", xml_string)
    if ws_match and dataset_match:
        path = ws_match.group(1).strip().rstrip(';')
        dataset = dataset_match.group(1).strip()
        return {
            "workspaceConnectionString": f"DATABASE={path}",
            "dataset": dataset,
            "workspaceFactory": "Raster",
            "datasetType": "esriDTRasterDataset"
        }

    # Method 2: Handle complex nested XML (e.g., XmlRasterDataset with GeometricFunction).
    # This format often buries the true path and filename in different tags.
    if "XmlRasterDataset" in xml_string:
        path_match = re.search(r"<PathName>([^<]+)</PathName>", xml_string)
        # The actual filename is often in a <Name> tag inside a RasterDatasetName section.
        raster_section_match = re.search(
            r"RasterDatasetName[^>]*>.*?<Name>([^<]+\.(?:png|tif|tiff|jpg|jpeg|img|sid|ecw))</Name>",
            xml_string,
            re.IGNORECASE | re.DOTALL
        )
        if path_match and raster_section_match:
            path = path_match.group(1).strip()
            dataset = raster_section_match.group(1).strip()
            return {
                "workspaceConnectionString": f"DATABASE={path}",
                "dataset": dataset,
                "workspaceFactory": "Raster",
                "datasetType": "esriDTRasterDataset"
            }

    # Method 3: Fallback to find any path and a plausible-looking dataset name.
    path_match = re.search(r"<PathName>([^<]+)</PathName>", xml_string)
    name_matches = re.findall(r"<Name>([^<]+)</Name>", xml_string)
    dataset = None
    for name in name_matches:
        # Skip names that are likely function types.
        if not any(word in name.lower() for word in ['function', 'geometric', 'transform']):
            # Check if it looks like a filename (has a common image extension).
            if '.' in name and any(name.lower().endswith(ext) for ext in ['.png', '.tif', '.tiff', '.jpg', '.jpeg', '.img', '.sid', '.ecw']):
                dataset = name.strip()
                break # Found a suitable dataset name

    if path_match and dataset:
        path = path_match.group(1).strip()
        return {
            "workspaceConnectionString": f"DATABASE={path}",
            "dataset": dataset,
            "workspaceFactory": "Raster",
            "datasetType": "esriDTRasterDataset"
        }

    return None

def _make_uris(in_folder, conn_str, factory, dataset, dataset_type, def_query, out_file):
    """Helper to build absolute/relative URIs and determine provider type.
    
    Returns:
        tuple: (abs_uri, rel_uri, provider)
    """
    # --- Handle Web Feature Services ---
    if factory == "FeatureService":
        # Strip 'URL=' prefix if present
        url = conn_str.replace("URL=", "").strip()
        
        # Construct the base URL (Service + Layer ID)
        if url.endswith("/"):
            base_url = f"{url}{dataset}"
        else:
            base_url = f"{url}/{dataset}"
            
        # FIX: Create a proper QGIS URI for the 'arcgisfeatureserver' provider.
        # It expects a string like: "url='https://.../MapServer/1' crs='...'"
        ds_uri = QgsDataSourceUri()
        ds_uri.setParam("url", base_url)
        
        # If you had a definition query, you might set it here too, but for now
        # we return the URI string. The provider often handles SQL via 'sql=' param
        # but standard QGIS subset strings might not apply directly without loading.
        
        uri = ds_uri.uri()
        return uri, uri, "arcgisfeatureserver"

    # --- Handle Local Files ---
    if "=" in conn_str:
        _, raw_path = conn_str.split("=", 1)
    else:
        raw_path = conn_str

    lyrx_dir = Path(in_folder)
    abs_path = (lyrx_dir / raw_path).resolve()

    provider = "ogr" # Default to OGR for vector files

    # Absolute URI
    if factory == "FileGDB":
        if dataset_type == "esriDTFeatureClass" or dataset_type == "esriDTTable":
            abs_uri = f"{abs_path.as_posix()}|layername={dataset}"
        elif dataset_type == "esriDTRasterDataset":
            abs_uri = os.path.join(abs_path.as_posix(), dataset)
            provider = "gdal"
        else:
            raise NotImplementedError(f"Unsupported FileGDB dataset type: {dataset_type}")
    else:
        # Shapefiles, Rasters, etc.
        abs_uri = os.path.join(abs_path.as_posix(), dataset)
        if dataset_type == "esriDTRasterDataset":
            provider = "gdal"

    # Relative URI
    out_dir = Path(out_file).parent.resolve()
    try:
        rel_path = Path(os.path.relpath(abs_path, start=out_dir))
    except ValueError:
        # If paths are on different drives, relpath fails. Fallback to absolute.
        rel_path = abs_path

    if factory == "FileGDB":
        if dataset_type == "esriDTFeatureClass" or dataset_type == "esriDTTable":
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

    return abs_uri, rel_uri, provider

def _parse_source(in_folder, data_connection, def_query, out_file):
    """Build URIs and determine provider.
    
    Returns:
        tuple: ( (abs_uri, rel_uri, provider), join_info )
    """
    factory = data_connection.get("workspaceFactory")
    conn_str = data_connection.get("workspaceConnectionString", "")
    dataset = data_connection.get("dataset")
    dataset_type = data_connection.get("datasetType")

    # --- Handle direct connections ---
    if factory and conn_str and dataset:
        return _make_uris(in_folder, conn_str, factory, dataset, dataset_type, def_query, out_file), None

    # --- Handle table join ---
    if data_connection.get("type") == "CIMRelQueryTableDataConnection":
        if def_query:
            raise NotImplementedError("Definition queries on joined layers are not yet supported.")

        source = data_connection.get("sourceTable", {})
        dest = data_connection.get("destinationTable", {})

        (abs_uri, rel_uri, src_provider), _ = _parse_source(in_folder, source, "", out_file)
        (abs_table_uri, rel_table_uri, dest_provider), _ = _parse_source(in_folder, dest, "", out_file)

        join_info = {
            "primaryKey": data_connection.get("primaryKey"),
            "foreignKey": data_connection.get("foreignKey"),
            "joinType": data_connection.get("joinType", "esriLeftOuterJoin"),
            "destinationAbs": abs_table_uri,
            "destinationRel": rel_table_uri,
            "destinationName": dest.get("dataset"),
            "sourceProvider": src_provider,
            "destinationProvider": dest_provider
        }

        return (abs_uri, rel_uri, src_provider), join_info

    raise NotImplementedError(f"Unsupported dataConnection type: {data_connection.get('type')}")


def _set_layer_transparency(layer: QgsMapLayer, layer_def: dict):
    """Set the transparency for a QGIS layer based on the ArcGIS layer definition."""
    transparency = layer_def.get("transparency", 0)
    if transparency:
        layer.setOpacity(1 - (transparency / 100.0))


def _set_scale_visibility(layer: QgsMapLayer, layer_def: dict):
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

def _set_temporal_properties(layer: QgsVectorLayer, layer_def: dict):
    """
    Configures the temporal properties of a layer based on ArcGIS time definitions.
    This enables the use of the QGIS Temporal Controller.
    """
    feature_table = layer_def.get("featureTable", {})
    time_fields = feature_table.get("timeFields", {})
    
    if not time_fields:
        return

    # Parse fields from JSON
    start_field = time_fields.get("startTimeField")
    end_field = time_fields.get("endTimeField")

    if start_field:
        tprops = layer.temporalProperties()
        
        # Enable temporal support for this layer
        tprops.setIsActive(True)
        
        if end_field:
            # Mode: Start and End fields
            tprops.setMode(Qgis.VectorTemporalMode.FeatureDateTimeStartAndEndFromFields)
            tprops.setEndField(end_field)
        else:
            # Mode: Single field (Instant)
            tprops.setMode(Qgis.VectorTemporalMode.FeatureDateTimeInstantFromField)
            
        tprops.setStartField(start_field)
        print(f"Enabled temporal properties for '{layer.name()}'. Start: {start_field}, End: {end_field}")


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

    # Parse source: returns (abs_uri, rel_uri, provider), join_info
    def_query = _parse_definition_query(layer_def)
    (abs_uri, rel_uri, provider), join_info = _parse_source(in_folder, f_table["dataConnection"], def_query, out_file)

    # Apply join if present
    if join_info:
        source_uri = abs_uri
        join_uri = join_info["destinationAbs"]
        src_prov = join_info.get("sourceProvider", "ogr")
        dst_prov = join_info.get("destinationProvider", "ogr")

        sql = f"""
            SELECT f.*, j.*
            FROM "{layer_def['name']}" AS f
            LEFT JOIN "{join_info['destinationName']}" AS j
            ON f."{join_info['primaryKey']}" = j."{join_info['foreignKey']}"
        """

        vl_def = QgsVirtualLayerDefinition()
        vl_def.addSource(layer_def['name'], source_uri, src_prov, "")
        vl_def.addSource(join_info['destinationName'], join_uri, dst_prov, "")
        vl_def.setQuery(sql)

        layer = QgsVectorLayer(vl_def.toString(), layer_name, "virtual")
        if not layer.isValid():
            raise RuntimeError(f"Virtual layer failed to create: {layer_name}")

    else:
        # No join: Load layer using the detected provider (ogr, arcgisfeatureserver, etc.)
        print(f"Loading layer '{layer_name}' with provider '{provider}' at {abs_uri}")
        layer = QgsVectorLayer(abs_uri, layer_name, provider)
        
        if not layer.isValid():
            raise RuntimeError(f"Layer failed to load: {layer_name} {abs_uri} (Provider: {provider})")
        
        # Only attempt relative path switch for file-based providers (OGR)
        if provider == "ogr":
            test_layer = QgsVectorLayer(rel_uri, f"test_{layer_name}", "ogr")
            if test_layer.isValid():
                layer.setDataSource(rel_uri, layer.name(), layer.providerType())
                if not layer.isValid():
                    layer = QgsVectorLayer(abs_uri, layer_name, "ogr")

    # Set other layer properties
    _set_display_field(layer, layer_def)
    renderer_factory = VectorRenderer()
    qgis_renderer = renderer_factory.create_renderer(layer_def.get("renderer", {}), layer, full_layer_def=layer_def)
    layer.setRenderer(qgis_renderer)
    _set_field_aliases_and_visibility(layer, layer_def)
    set_labels(layer, layer_def)
    _set_temporal_properties(layer, layer_def)

    if not layer.isValid():
        raise RuntimeError(f"Layer became invalid after setting properties: {layer_name}")

    project.addMapLayer(layer, False)

    root = project.layerTreeRoot()
    node = root.addLayer(layer)
    
    if 'visibility' in layer_def:
        node.setItemVisibilityChecked(layer_def['visibility'])
    return layer


def _convert_raster_layer(in_folder, layer_def, out_file, project):
    """
    Creates a QgsRasterLayer from a CIMRasterLayer definition.
    """
    layer_name = layer_def.get("name", "Raster")
    data_connection = layer_def.get("dataConnection")

    if not data_connection:
        raise RuntimeError(f"Raster layer '{layer_name}' is missing the 'dataConnection' definition.")

    if isinstance(data_connection, str):
        parsed_connection = _parse_xml_dataconnection(data_connection)
        if not parsed_connection:
            raise RuntimeError(f"Failed to parse XML data connection for raster layer: {layer_name}")
        data_connection = parsed_connection
    elif isinstance(data_connection, dict):
        dataset_value = data_connection.get('dataset', '')
        if isinstance(dataset_value, str) and '<' in dataset_value:
            parsed_connection = _parse_xml_dataconnection(dataset_value)
            if parsed_connection:
                if 'workspaceConnectionString' in data_connection and parsed_connection.get('workspaceConnectionString') in (None, 'DATABASE='):
                    parsed_connection['workspaceConnectionString'] = data_connection['workspaceConnectionString']
                data_connection = parsed_connection
            else:
                 raise RuntimeError(f"Failed to parse XML in 'dataset' field for raster layer: {layer_name}")

    if not isinstance(data_connection, dict):
        raise RuntimeError(f"Unexpected data_connection type: {type(data_connection)} for layer {layer_name}")

    data_connection = {k[0].lower() + k[1:]: v for k, v in data_connection.items()}

    # Unpack the new 3-item tuple (abs, rel, provider), ignoring provider for now as we default to gdal
    (abs_uri, rel_uri, provider), _ = _parse_source(in_folder, data_connection, "", out_file)

    gdal_log_file = os.environ.get('CPL_LOG')
    os.environ['CPL_LOG'] = os.devnull
    rlayer = None

    # Use the detected provider if possible, otherwise fallback to gdal
    raster_provider = provider if provider else "gdal"
    
    try:
        rlayer = QgsRasterLayer(abs_uri, layer_name, raster_provider)
    finally:
        if gdal_log_file:
            os.environ['CPL_LOG'] = gdal_log_file
        else:
            os.environ.pop('CPL_LOG', None)

    if not rlayer or not rlayer.isValid():
        error_msg = f"Raster layer failed to load: {layer_name}"
        if os.path.exists(abs_uri):
            error_msg += f"\nFile exists at '{abs_uri}' but GDAL could not open it. Check format or permissions."
        else:
            error_msg += f"\nFile not found at '{abs_uri}'."
        raise RuntimeError(error_msg)

    # Switch path (only for file-based gdal layers)
    if raster_provider == "gdal":
        try:
            test_layer = QgsRasterLayer(rel_uri, "test", "gdal")
            if test_layer.isValid():
                switch_to_relative_path(rlayer, rel_uri)
        except Exception as e:
            print(f"Warning: Could not set relative path for raster layer '{layer_name}'; using absolute path in QLR. Error: {e}")

    apply_raster_symbology(rlayer, layer_def)

    project.addMapLayer(rlayer, False)
    return rlayer

def _export_qlr_with_visibility(out_layer, layer_def: dict, out_file: str) -> None:
    """
    Exports a .qlr that contains a layer-tree entry with a "checked" (visible) state.

    Why this is needed:
      - QgsLayerDefinition.exportLayerDefinitionLayers(...) does NOT write any layer tree,
        so it cannot preserve 'checked' visibility. We must export selected tree nodes instead.
        (QGIS API: "This is a low-level routine that does not write layer tree.")  # noqa
      - By creating a temporary layer-tree node (QgsLayerTreeLayer) and calling
        QgsLayerDefinition.exportLayerDefinition(...), the resulting QLR includes
        <layer-tree-layer ... checked="Qt::Checked"> (visibility on).  # noqa

    Args:
        out_layer (QgsMapLayer): the in-memory layer you constructed.
        layer_def (dict): parsed LYRX layer definition (used to read ArcGIS 'visibility'/'expanded').
        out_file (str): path to save the .qlr.
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
            _set_layer_transparency(child_layer, member_def)
            node = group_node.addLayer(child_layer)
            if node:
                node.setItemVisibilityChecked(bool(member_def.get("visibility", True)))
                node.setExpanded(bool(member_def.get("expanded", False)))

        elif layer_type == 'CIMRasterLayer':
            child_layer = _convert_raster_layer(in_folder, member_def, out_file, project)
            _set_metadata(child_layer, member_def)
            _set_scale_visibility(child_layer, member_def)
            _set_layer_transparency(child_layer, member_def)
            node = group_node.addLayer(child_layer)
            if node:
                node.setItemVisibilityChecked(bool(member_def.get("visibility", True)))
                node.setExpanded(bool(member_def.get("expanded", False)))

    return group_node

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
            _set_layer_transparency(out_layer, layer_def)

            root = QgsProject.instance().layerTreeRoot()
            node = root.findLayer(out_layer.id())
            if node:
                nodes_to_export = [node]
                                
        elif layer_type == 'CIMRasterLayer':
            out_layer = _convert_raster_layer(in_folder, layer_def, out_file, project)
            _set_metadata(out_layer, layer_def)
            _set_scale_visibility(out_layer, layer_def)
            _set_layer_transparency(out_layer, layer_def)
            
            # Explicitly add raster layer to layer tree so it can be found for export
            root = QgsProject.instance().layerTreeRoot()
            node = root.addLayer(out_layer)
            
            if node:
                if 'visibility' in layer_def:
                    node.setItemVisibilityChecked(layer_def['visibility'])
                nodes_to_export = [node]

        elif layer_type == 'CIMAnnotationLayer':
            print("Annotation layers are unsupported")
            return
        else:
            raise Exception(f"Unhandled layer type: {layer_type}")

        # Export the QLR
        if nodes_to_export:
            # Use tempfile to create a valid file path for export (fixes StringIO error)
            with tempfile.NamedTemporaryFile(mode='w', suffix='.qlr', delete=False, encoding='utf-8') as temp_file:
                temp_path = temp_file.name
            
            try:
                ok, error_message = QgsLayerDefinition.exportLayerDefinition(temp_path, nodes_to_export)
                
                if not ok:
                    raise RuntimeError(f"Failed to export layer definition: {error_message}")
                
                # Read the temporary file content
                with open(temp_path, 'r', encoding='utf-8') as f:
                    qlr_content = f.read()
                
                # Post-process content (e.g. for symbol levels)
                final_qlr_content = VectorRenderer().post_process_qlr_for_symbol_levels(qlr_content, layer_def)
                
                # Write to final output location
                with open(out_file, 'w', encoding='utf-8') as f:
                    f.write(final_qlr_content)
                
            finally:
                if os.path.exists(temp_path):
                    os.remove(temp_path)

        print(f"Successfully converted {in_lyrx} to {out_file}")
    except Exception as e:
        print(f"Error converting LYRX: {e}")
        raise
    finally:
        project.clear()
        if manage_qgs:
            qgs.exitQgis()


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