"""Converts ArcGIS Pro layer files (.lyrx) to QGIS layer files (.qlr)."""

import json
import os
from pathlib import Path

from qgis.core import (
    QgsApplication,
    QgsVectorLayer,
    QgsLayerDefinition,
    QgsReadWriteContext,
    QgsSingleSymbolRenderer,
    QgsSymbol,
    QgsVirtualLayerDefinition,
)
from arc_to_q.converters.vector.vector_renderer import RendererFactory
from arc_to_q.converters.label_converter import set_labels
from arc_to_q.converters.annotation_converter import *
from arc_to_q.converters.raster.raster_renderer import *
from arc_to_q.converters.custom_crs_registry import CUSTOM_CRS_DEFINITIONS, save_custom_crs_to_database


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
    """
    feature_table = layer_def.get("featureTable", {})
    definition_query = feature_table.get("definitionExpression", "").strip()

    if definition_query:
        qgis_query = definition_query.replace("<>", "!=")
        return f"|subset={qgis_query}"
    return ""


def _make_uris(in_folder, conn_str, factory, dataset, def_query, out_file):
    """Helper to build absolute and relative URIs for a dataset."""
    if "=" in conn_str:
        _, raw_path = conn_str.split("=", 1)
    else:
        raw_path = conn_str

    lyrx_dir = Path(in_folder)
    abs_path = (lyrx_dir / raw_path).resolve()

    if factory == "FileGDB":
        abs_uri = f"{abs_path.as_posix()}|layername={dataset}"
    else:
        abs_uri = abs_path.as_posix()

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
    """Build both absolute and relative QGIS-friendly URIs for a dataset."""
    factory = data_connection.get("workspaceFactory")
    conn_str = data_connection.get("workspaceConnectionString", "")
    dataset = data_connection.get("dataset")

    if factory and conn_str and dataset:
        return _make_uris(in_folder, conn_str, factory, dataset, def_query, out_file), None

    if data_connection.get("type") == "CIMRelQueryTableDataConnection":
        if def_query:
            raise NotImplementedError("Definition queries on joined layers are not yet supported.")

        source = data_connection.get("sourceTable", {})
        dest = data_connection.get("destinationTable", {})

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
    min_scale = layer_def.get("minScale", 0)
    max_scale = layer_def.get("maxScale", 0)
    if min_scale != 0 or max_scale != 0:
        layer.setScaleBasedVisibility(True)
        layer.setMinimumScale(min_scale)
        layer.setMaximumScale(max_scale)


def _set_metadata(layer: QgsVectorLayer, layer_def: dict):
    """Sets the metadata for a QGIS layer based on the ArcGIS layer definition."""
    md = layer.metadata()
    if title := layer_def.get("name"):
        md.setTitle(title)
    if not layer_def.get("useSourceMetadata", False):
        if attribution := layer_def.get("attribution"):
            md.setRights([attribution])
        if description := layer_def.get("description"):
            md.setAbstract(description)
    layer.setMetadata(md)


def _set_display_field(layer: QgsVectorLayer, layer_def: dict):
    """Sets the display field for a QGIS layer."""
    if feature_table := layer_def.get("featureTable"):
        if display_field := feature_table.get("displayField"):
            layer.setDisplayExpression(f'"{display_field}"')


def _set_definition_query(layer: QgsVectorLayer, layer_def: dict):
    """Sets the definition query (subset string) for a QGIS layer."""
    if feature_table := layer_def.get("featureTable"):
        if definition_query := feature_table.get("definitionExpression"):
            qgis_query = definition_query.strip().replace("[", "\"").replace("]", "\"").replace("<>", "!=")
            layer.setSubsetString(qgis_query)


def _convert_feature_layer(in_folder, layer_def, out_file):
    layer_name = layer_def['name']
    f_table = layer_def["featureTable"]
    if f_table["type"] != "CIMFeatureTable":
        raise Exception(f"Unexpected feature table type: {f_table['type']}")

    def_query = _parse_definition_query(layer_def)
    (abs_uri, rel_uri), join_info = _parse_source(in_folder, f_table["dataConnection"], def_query, out_file)

    if join_info:
        sql = f"""
            SELECT f.*, j.*
            FROM "{layer_name}" AS f
            LEFT JOIN "{join_info['destinationName']}" AS j
            ON f."{join_info['primaryKey']}" = j."{join_info['foreignKey']}"
        """
        vl_def = QgsVirtualLayerDefinition()
        vl_def.addSource(layer_name, abs_uri, "ogr", "")
        vl_def.addSource(join_info['destinationName'], join_info["destinationAbs"], "ogr", "")
        vl_def.setQuery(sql)
        layer = QgsVectorLayer(vl_def.toString(), layer_name, "virtual")
    else:
        layer = QgsVectorLayer(abs_uri, layer_name, "ogr")

    if not layer.isValid():
        raise RuntimeError(f"Layer failed to load: {layer_name} | Source: {abs_uri}")

    if not join_info:
        layer.setDataSource(rel_uri, layer.name(), layer.providerType())

    _set_display_field(layer, layer_def)

    renderer_factory = RendererFactory()
    qgis_renderer = renderer_factory.create_renderer(layer_def.get("renderer", {}), layer)
    layer.setRenderer(qgis_renderer)

    set_labels(layer, layer_def)
    _set_definition_query(layer, layer_def)

    if not layer.isValid():
        raise RuntimeError(f"Layer became invalid after setting relative path or query: {layer_name}")

    return layer


def _convert_raster_layer(in_folder, layer_def, out_file):
    """Converts a raster layer, ensuring custom CRS is registered."""
    if arcgis_crs_name := layer_def.get('spatialReference', {}).get('name'):
        if proj_string := CUSTOM_CRS_DEFINITIONS.get(arcgis_crs_name):
            save_custom_crs_to_database(arcgis_crs_name, proj_string)

    data_connection = layer_def.get('dataConnection', {})
    abs_uri, rel_uri = parse_raster_source(in_folder, data_connection, out_file)
    layer_name = layer_def.get('name', os.path.basename(abs_uri))

    qgis_layer = create_raster_layer(abs_uri, layer_name)
    print_raster_debug_info(qgis_layer)
    apply_raster_symbology(qgis_layer, layer_def)
    switch_to_relative_path(qgis_layer, rel_uri)
    return qgis_layer


def _convert_annotation_layer(in_folder, layer_def, out_file):
    """Converts a CIMAnnotationLayer to a QgsVectorLayer with data-defined labeling."""
    layer_name = layer_def['name']
    
    # Create the definition query (it will be an empty string for annotations)
    def_query = _parse_definition_query(layer_def)
    
    # CORRECTED: Added the 'def_query' argument to the function call
    (abs_uri, rel_uri), _ = _parse_source(in_folder, layer_def["featureTable"]["dataConnection"], def_query, out_file)
    
    layer = QgsVectorLayer(abs_uri, layer_name, "ogr")
    if not layer.isValid():
        raise RuntimeError(f"Annotation layer failed to load: {layer_name} | Source: {abs_uri}")

    symbol = QgsSymbol.defaultSymbol(layer.geometryType())
    symbol.setOpacity(0)
    layer.setRenderer(QgsSingleSymbolRenderer(symbol))

    layer.setLabelsEnabled(True)
    if not apply_enhanced_annotation_converter(layer):
        print(f"WARNING: Enhanced annotation conversion failed for layer {layer_name}")
        # Add fallback basic labeling if needed
    
    layer.setDataSource(rel_uri, layer.name(), layer.providerType())
    _set_definition_query(layer, layer_def)
    return layer


def convert_lyrx(in_lyrx, out_folder=None, qgs=None):
    """Convert an ArcGIS Pro .lyrx file to a QGIS .qlr file"""
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
        
        layer_type = layer_def.get("type")
        if layer_type == "CIMFeatureLayer":
            out_layer = _convert_feature_layer(in_folder, layer_def, out_file)
        elif layer_type == 'CIMRasterLayer':
            out_layer = _convert_raster_layer(in_folder, layer_def, out_file)
        elif layer_type == 'CIMAnnotationLayer':
            out_layer = _convert_annotation_layer(in_folder, layer_def, out_file)
        else:
            raise Exception(f"Unhandled layer type: {layer_type}")

        _set_metadata(out_layer, layer_def)
        _set_scale_visibility(out_layer, layer_def)

        doc = QgsLayerDefinition.exportLayerDefinitionLayers([out_layer], QgsReadWriteContext())
        with open(out_file, 'w', encoding='utf-8') as f:
            f.write(doc.toString())
        print(f"Successfully converted {in_lyrx} to {out_file}")
    except Exception as e:
        print(f"Error converting LYRX: {e}")
        raise
    finally:
        if manage_qgs:
            qgs.exitQgis()