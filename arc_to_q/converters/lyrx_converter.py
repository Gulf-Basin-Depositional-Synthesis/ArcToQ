"""Converts ArcGIS Pro layer files (.lyrx) to QGIS layer files (.qlr)."""

import json
import os
from pathlib import Path

from qgis.core import (
    QgsApplication,
    QgsVectorLayer,
    QgsVectorLayerJoinInfo,
    QgsVirtualLayerDefinition,
    QgsLayerDefinition,
    QgsReadWriteContext
)

from arc_to_q.converters.symbology_converter import set_symbology
from arc_to_q.converters.label_converter import set_labels


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

    Example QGIS equivalents (including pipe delimiter for source URI):
        |subset=Unit_Id = 22
        |subset="WellData_UnitThk" != -9999 AND "WellData_Unit_Id" = 22

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

        # Optionally, handle other syntax differences here if needed

        # Return the query string with the pipe delimiter for QGIS
        return f"|subset={qgis_query}"
    return ""


def _make_uris(in_folder, conn_str, factory, dataset, def_query, out_file):
    """Helper to build absolute and relative URIs for a dataset.
    
    Args:
        in_folder (str): Path to the folder containing the .lyrx file.
        conn_str (str): The workspace connection string from the .lyrx file.
        factory (str): The workspace factory type (e.g. "FileGDB", "Shapefile").
        dataset (str): The dataset name (e.g. feature class or table name).
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
        abs_uri = f"{abs_path.as_posix()}|layername={dataset}"
    else:
        abs_uri = abs_path.as_posix()

    # Relative URI
    out_dir = Path(out_file).parent.resolve()
    rel_path = Path(os.path.relpath(abs_path, start=out_dir))
    if factory == "FileGDB":
        rel_uri = f"{rel_path.as_posix()}|layername={dataset}"
    else:
        rel_uri = rel_path.as_posix()

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

    # --- Handle direct connections (FileGDB, Shapefile, Raster) ---
    if factory and conn_str and dataset:
        return _make_uris(in_folder, conn_str, factory, dataset, def_query, out_file), None

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


def _convert_feature_layer(in_folder, layer_def, out_file):
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
            raise RuntimeError(f"Layer failed to load: {layer_name}")
        # Swap to relative URI for QLR
        layer.setDataSource(rel_uri, layer.name(), layer.providerType())

    # Set other layer properties
    _set_display_field(layer, layer_def)
    set_symbology(layer, layer_def)
    # set_labels(layer, layer_def)

    return layer


def convert_lyrx(in_lyrx, out_folder=None, qgs=None):
    """Convert an ArcGIS Pro .lyrx file to a QGIS .qlr file

    Args:
        in_lyrx (str): Path to the input .lyrx file.
        out_folder (str, optional): Folder to save the output .qlr file. If not provided,
            the output will be saved in the same folder as the input .lyrx file.
        qgs (QgsApplication, optional): An initialized QgsApplication instance. If not provided,
            a new instance will be created and initialized within this function.
    """
    if not out_folder:
        out_folder = os.path.dirname(in_lyrx)
    in_folder = os.path.abspath(os.path.dirname(in_lyrx))
    out_file = os.path.join(out_folder, os.path.basename(in_lyrx).replace(".lyrx", ".qlr"))

    manage_qgs = qgs is None
    if manage_qgs:
        qgs = QgsApplication([], False)
        qgs.initQgis()

    try:
        lyrx = _open_lyrx(in_lyrx)
        layer_uri = lyrx["layers"][0]
        layer_def = next((ld for ld in lyrx.get("layerDefinitions", []) if ld.get("uRI") == layer_uri), {})
        if layer_def.get("type") == "CIMFeatureLayer":
            out_layer = _convert_feature_layer(in_folder, layer_def, out_file)
        else:
            raise Exception(f"Unhandled layer type: {layer_def.get('type')}")

        # # Common properties
        _set_metadata(out_layer, layer_def)
        _set_scale_visibility(out_layer, layer_def)

        # visibility = layer_def.get("visibility", False)
        # expanded = layer_def.get("expanded", False)

        doc = QgsLayerDefinition.exportLayerDefinitionLayers([out_layer], QgsReadWriteContext())
        with open(out_file, 'w', encoding='utf-8') as f:
            f.write(doc.toString())
    except Exception as e:
        print(f"Error converting LYRX: {e}")
    finally:
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
