"""Converts ArcGIS Pro layer files (.lyrx) to QGIS layer files (.qlr)."""

import json
import os
from pathlib import Path
import urllib.parse

from qgis.core import (
    QgsApplication,
    QgsVectorLayer,
    QgsLayerDefinition,
    QgsReadWriteContext,
    QgsSingleSymbolRenderer,
    QgsSymbol,
)

from arc_to_q.converters.vector.vector_renderer import RendererFactory
from arc_to_q.converters.label_converter import set_labels
from arc_to_q.converters.annotation_converter import set_annotation_labels
from arc_to_q.converters.raster.raster_renderer import *
from arc_to_q.converters.custom_crs_registry import CUSTOM_CRS_DEFINITIONS, save_custom_crs_to_database


def _open_lyrx(lyrx):
    with open(lyrx, 'r', encoding='utf-8') as f:
        data = json.load(f)

    layers = data.get("layers", [])
    if len(layers) != 1:
        raise Exception(f"Unexpected number of layers found: {len(layers)}")

    return data


def _parse_source(in_folder, data_connection, out_file):
    """Build both absolute and relative QGIS-friendly URIs for a dataset.
    
    Args:
        in_folder (str): The absolute path to the input folder containing the .lyrx file. This is used
            to determine the absolute path to the input data.
        data_connection (dict): The data connection information from the .lyrx file.
        out_file (str): The output file path for the converted QGIS layer. This is used
            to determine the relative path for the output.

    Returns:
        tuple: (absolute path, relative path) where each is a QGIS data source string.
    """
    factory = data_connection.get("workspaceFactory")
    conn_str = data_connection.get("workspaceConnectionString", "")
    dataset = data_connection.get("dataset")

    if not factory or not conn_str or not dataset:
        raise ValueError("Missing required fields in dataConnection.")

    # Extract path from ArcGIS-style connection string
    # Example: "DATABASE=..\\Database\\GBDS.gdb" → "..\\Database\\GBDS.gdb"
    if "=" in conn_str:
        _, raw_path = conn_str.split("=", 1)
    else:
        raw_path = conn_str

    # Resolve relative to the .lyrx file's folder
    lyrx_dir = Path(in_folder)
    abs_path = (lyrx_dir / raw_path).resolve()
    abs_uri = f"{abs_path.as_posix()}|layername={dataset}" if factory == "FileGDB" else abs_path.as_posix()

    # Build relative URI for saving in QLR
    # Try to build a relative path, but fall back to absolute if they are on different drives.
    try:
        out_dir = Path(out_file).parent.resolve()
        rel_path = Path(os.path.relpath(abs_path, start=out_dir))
        rel_uri = f"{rel_path.as_posix()}|layername={dataset}" if factory == "FileGDB" else rel_path.as_posix()
        #print(f"Successfully created relative path: {rel_uri}")
    except ValueError:
        # This error occurs when paths are on different drives.
        print("Warning: Input data and output folder are on different drives.")
        print("Falling back to using an absolute path in the QGIS layer file.")
        rel_uri = abs_uri # Fallback to the absolute path

    # Build QGIS source string
    if factory in ["FileGDB", "Raster", "Shapefile"]:
        return abs_uri, rel_uri
    else:
        raise NotImplementedError(f"Unsupported workspaceFactory: {factory}")

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
    attribution = layer_def.get("attribution", "")
    description = layer_def.get("description", "")
    title = layer_def.get("name", "")

    md = layer.metadata()

    if attribution:
        md.setRights([attribution])
    if description:
        md.setAbstract(description)
    if title:
        md.setTitle(title)

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

def _set_definition_query(layer: QgsVectorLayer, layer_def: dict):
    """
    Sets the definition query (subset string) for a QGIS layer and adds debugging output.

    Args:
        layer (QgsVectorLayer): The in-memory QGIS layer object to modify.
        layer_def (dict): The parsed JSON dictionary of an ArcGIS layer definition.
    """
    
    feature_table = layer_def.get("featureTable", {})
    definition_query = feature_table.get("definitionExpression")

    if not definition_query:
        #print("Result: No 'definitionExpression' found in the .lyrx file.")
        #print("------------------------------------")
        return

    #print(f"Found ArcGIS query: {definition_query}")

    # Simple syntax translation: [FieldName] -> "FieldName"
    # This is a common point of failure if the query is complex.
    qgis_query = definition_query.strip().replace("[", "\"").replace("]", "\"")
    #print(f"Attempting to apply translated QGIS query: {qgis_query}")

    # Apply the filter
    layer.setSubsetString(qgis_query)

    # Verify if the filter was actually applied to the layer object
    applied_query = layer.subsetString()
    if applied_query:
        return None
    else:
        print("Error: Failed to apply query. The layer's subset string is still empty.")
        print("This often happens if the layer is invalid or the query syntax is incorrect for the data provider.")

def _convert_feature_layer(in_folder, layer_def, out_file):
    layer_name = layer_def['name']
    if layer_def["useSourceMetadata"] == True:
        raise Exception(f"Unhandled: Layer uses source metadata: {layer_name}")
    f_table = layer_def["featureTable"]
    if f_table["type"] != "CIMFeatureTable":
        raise Exception(f"Unexpected feature table type: {f_table['type']}")

    abs_uri, rel_uri = _parse_source(in_folder, f_table["dataConnection"], out_file)
    layer = QgsVectorLayer(abs_uri, layer_name, "ogr")

    if not layer.isValid():
        raise RuntimeError(f"Layer failed to load with absolute path: {layer_name} | Source: {abs_uri}")
        
    _set_display_field(layer, layer_def)

    renderer_factory = RendererFactory()
    renderer_def = layer_def.get("renderer", {})
    qgis_renderer = renderer_factory.create_renderer(renderer_def, layer)
    layer.setRenderer(qgis_renderer)
    
    set_labels(layer, layer_def)


    # Switch the data source to the relative path. This resets the filter.
    layer.setDataSource(rel_uri, layer.name(), layer.providerType())

    # Apply the definition query. It will be the last thing set before saving.
    _set_definition_query(layer, layer_def)

    if not layer.isValid():
        # This final check ensures the layer is still valid with the new path and query
        print(f"CRITICAL ERROR: Layer '{layer_name}' became invalid after setting relative path or query.")
        print(f"Check the query syntax and relative path logic: {layer.error().summary()}")
        raise RuntimeError(f"Layer became invalid: {layer_name}")

    return layer

def _convert_raster_layer(in_folder, layer_def, out_file):
    """
    Final version: Converts a raster layer by first ensuring its custom CRS
    is registered in the QGIS user database.
    """
    print(f"Processing Raster Layer: {layer_def.get('name')}")
    
    # Step 1: Check for and register any necessary custom CRS
    arcgis_crs_name = layer_def.get('spatialReference', {}).get('name')
    if arcgis_crs_name in CUSTOM_CRS_DEFINITIONS:
        proj_string = CUSTOM_CRS_DEFINITIONS[arcgis_crs_name]
        # This is the new, critical step:
        save_custom_crs_to_database(arcgis_crs_name, proj_string)

    # Step 2: Parse source and load the layer normally
    data_connection = layer_def.get('dataConnection', {})
    abs_uri, rel_uri = parse_raster_source(in_folder, data_connection, out_file)
    layer_name = layer_def.get('name', os.path.basename(abs_uri))
    
    # QGIS will now recognize the CRS name when it loads the layer
    qgis_layer = create_raster_layer(abs_uri, layer_name)

    # Step 3: Apply symbology and switch to a relative path
    print_raster_debug_info(qgis_layer)
    apply_raster_symbology(qgis_layer, layer_def)
    switch_to_relative_path(qgis_layer, rel_uri)
    
    return qgis_layer

def _convert_annotation_layer(in_folder, layer_def, out_file):
    """
    Converts a CIMAnnotationLayer to a QgsVectorLayer with data-defined labeling
    and a transparent renderer for the feature geometry.
    """
    layer_name = layer_def['name']
    f_table = layer_def["featureTable"]
    
    # 1. Load the annotation feature class as a standard vector layer
    abs_uri, rel_uri = _parse_source(in_folder, f_table["dataConnection"], out_file)
    layer = QgsVectorLayer(abs_uri, layer_name, "ogr")

    if not layer.isValid():
        raise RuntimeError(f"Annotation layer failed to load: {layer_name} | Source: {abs_uri}")
    
    # 2. Create a transparent symbol
    symbol = QgsSymbol.defaultSymbol(layer.geometryType())
    symbol.setOpacity(0)
    
    # 3. Create a renderer with the transparent symbol
    renderer = QgsSingleSymbolRenderer(symbol)
    layer.setRenderer(renderer)

    # 4. Apply data-defined labeling settings
    set_annotation_labels(layer)

    # 5. Set display field, definition query, and relative path
    _set_display_field(layer, layer_def)
    layer.setDataSource(rel_uri, layer.name(), layer.providerType())
    _set_definition_query(layer, layer_def)

    if not layer.isValid():
        raise RuntimeError(f"Annotation layer became invalid after setting relative path or query: {layer_name}")

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
        elif layer_def.get("type") == 'CIMRasterLayer':
            out_layer = _convert_raster_layer(in_folder, layer_def, out_file)
        elif layer_def.get("type") == 'CIMAnnotationLayer':
            out_layer = _convert_annotation_layer(in_folder, layer_def, out_file)
        else:
            raise Exception(f"Unhandled layer type: {layer_def.get('type')}")

        # Common properties
        _set_metadata(out_layer, layer_def)
        _set_scale_visibility(out_layer, layer_def)

        # Save the layer definition
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

if __name__ == "__main__":
    output_folder = r""
    in_lyrx = r""

    manage_qgs = True
    qgs = None
    
    try:
        qgs = QgsApplication([], False)
        qgs.initQgis()

        convert_lyrx(in_lyrx, output_folder, qgs)
    except Exception as e:
        print(f"Error converting LYRX: {e}")
    finally:
        if manage_qgs and qgs:
            qgs.exitQgis()
