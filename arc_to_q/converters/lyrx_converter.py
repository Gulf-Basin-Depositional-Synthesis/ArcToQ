"""Converts ArcGIS Pro layer files (.lyrx) to QGIS layer files (.qlr)."""

import json
import os
from pathlib import Path

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
        # Swap to relative URI for QLR
        layer.setDataSource(rel_uri, layer.name(), layer.providerType())

    # Set other layer properties
    _set_display_field(layer, layer_def)
    renderer_factory = VectorRenderer()
    qgis_renderer = renderer_factory.create_renderer(layer_def.get("renderer", {}), layer)
    layer.setRenderer(qgis_renderer)
    _set_field_aliases_and_visibility(layer, layer_def)
    set_labels(layer, layer_def)

    if not layer.isValid():
        raise RuntimeError(f"Layer became invalid after setting relative path or query: {layer_name}")

    project.addMapLayer(layer, False)
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

def _convert_raster_layer(in_folder, layer_def, out_file, project):
    """Create a QgsRasterLayer from a CIMRasterLayer layer definition."""
    layer_name = layer_def.get("name", "Raster")

    # ArcGIS CIM for rasters typically stores a dataConnection directly on the layer.
    # Fallback in case it's nested (some exports).
    data_connection = (
        layer_def.get("dataConnection")
        or layer_def.get("raster", {}).get("dataConnection")
        or {}
    )
    if not data_connection:
        raise RuntimeError("Raster layer missing 'dataConnection'.")

    # No definition query for rasters
    (abs_uri, rel_uri), _ = _parse_source(in_folder, data_connection, "", out_file)

    # Load with GDAL provider
    rlayer = QgsRasterLayer(abs_uri, layer_name, "gdal")
    if not rlayer.isValid():
        raise RuntimeError(f"Raster layer failed to load: {layer_name} {abs_uri}")

    # Prefer relative path in the saved QLR
    # setDataSource is available in QGIS 3 for generic map layers; if unavailable,
    # you can remove this line to keep absolute paths in the QLR.
    try:
        rlayer.setDataSource(rel_uri, rlayer.name(), rlayer.providerType())
    except Exception:
        print("Warning: Could not set relative path for raster layer; using absolute path in QLR.")

    apply_raster_symbology(rlayer, layer_def)
    switch_to_relative_path(rlayer, rel_uri)

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
    # Determine visibility and expansion from LYRX (ArcGIS Pro)
    # In ArcGIS Pro, `visibility` corresponds to whether the item is checked in the Contents pane.
    visible = bool(layer_def.get("visibility", True))
    expanded = bool(layer_def.get("expanded", False))

    # Build a minimal in-memory layer tree and set visibility
    root = QgsLayerTreeGroup()                  # temporary root (not tied to a QgsProject)
    node = root.addLayer(out_layer)             # creates a QgsLayerTreeLayer
    node.setItemVisibilityChecked(visible)      # <-- the important bit (checked/unchecked)
    node.setExpanded(expanded)

    # Export the QLR including the layer tree node
    error_message = ""
    ok, error_message = QgsLayerDefinition.exportLayerDefinition(out_file, [node])
    if not ok:
        raise RuntimeError(f"Failed to export layer definition: {error_message}")


def convert_lyrx(in_lyrx, out_folder=None, qgs=None):
    """Convert an ArcGIS Pro .lyrx file to a QGIS .qlr file

    Args:
        in_lyrx (str): Path to the input .lyrx file.
        out_folder (str, optional): Folder to save the output .qlr file. If not provided,
            the output will be saved in the same folder as the input .lyrx file.
        qgs (QgsApplication, optional): An initialized QgsApplication instance. If not provided,
            a new instance will be created and initialized within this function.
    """
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
            _export_qlr_with_visibility(out_layer, layer_def, out_file)
          
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
            ok, error_message = QgsLayerDefinition.exportLayerDefinition(out_file, nodes_to_export)
            if not ok:
                raise RuntimeError(f"Failed to export layer definition: {error_message}")

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