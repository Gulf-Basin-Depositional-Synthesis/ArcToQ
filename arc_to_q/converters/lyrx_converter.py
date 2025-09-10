"""Converts ArcGIS Pro layer files (.lyrx) to QGIS layer files (.qlr)."""

import json
import os
from pathlib import Path

from qgis.core import (
    QgsApplication,
    QgsVectorLayer,
    QgsLayerDefinition,
    QgsReadWriteContext
)

from arc_to_q.converters.symbology_converter import set_symbology


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
    out_dir = Path(out_file).parent.resolve()
    rel_path = Path(os.path.relpath(abs_path, start=out_dir))
    rel_uri = f"{rel_path.as_posix()}|layername={dataset}" if factory == "FileGDB" else rel_path.as_posix()

    # Build QGIS source string
    if factory in ["FileGDB", "Raster", "Shapefile"]:
        return abs_uri, rel_uri
    else:
        raise NotImplementedError(f"Unsupported workspaceFactory: {factory}")


def _set_scale_visibility(layer, layer_def):
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


def _convert_feature_layer(in_folder, layer_def, out_file):
    layer_name = layer_def['name']
    if layer_def["useSourceMetadata"] == True:
        raise Exception(f"Unhandled: Layer uses source metadata: {layer_name}")
    f_table = layer_def["featureTable"]
    if f_table["type"] != "CIMFeatureTable":
        raise Exception(f"Unexpected feature table type: {f_table['type']}")

    abs_uri, rel_uri = _parse_source(in_folder, f_table["dataConnection"], out_file)
    layer = QgsVectorLayer(abs_uri, layer_name, "ogr")

    # set_vector_renderer(layer, layer_def["renderer"])

    _set_display_field(layer, layer_def)
    set_symbology(layer, layer_def)
    # props = {
    #     "name": layer_def.get("name"),
    #     "expanded": layer_def.get("expanded", True),
    #     "visibility": layer_def.get("visibility", True),
    #     "labelClasses": layer_def.get("labelClasses", []),
    #     "featureTable": layer_def.get("featureTable", {})
    # }
    # if props["layerScaleVisibilityOptions"]["type"] != "CIMLayerScaleVisibilityOptions":
    #     print(f"Unexpected layer scale visibility options type: {props['layerScaleVisibilityOptions']['type']}")
    # if props["layerScaleVisibilityOptions"]["showLayerAtAllScales"] != True:
    #     print(f"Layer scale visibility options do not show layer at all scales: {props['name']}")


    if not layer.isValid():
        raise RuntimeError(f"Layer failed to load: {layer_name}")
    # Swap to relative URI
    layer.setDataSource(rel_uri, layer.name(), layer.providerType())

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
        if manage_qgs:
            qgs.exitQgis()
