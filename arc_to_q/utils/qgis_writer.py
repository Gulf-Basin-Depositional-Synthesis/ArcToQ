import os
import xml.etree.ElementTree as ET
from arc_to_q.utils.logging_utils import log_info, log_error

def write_layer(props, output_path):
    """Create a minimal QLR file with layer name and data source."""
    layer_name = props.get("name")
    feature_table = props.get("featureTable", {})
    data_source = feature_table.get("datasetSource", {}).get("workspacePath")

    if not layer_name or not data_source:
        log_error("Missing layer name or data source.")
        return

    # Build QLR XML structure
    qlr = ET.Element("qlrfile")
    layer_tree = ET.SubElement(qlr, "layer-tree-group", attrib={"name": "Converted Layers"})
    layer_elem = ET.SubElement(layer_tree, "maplayer", attrib={
        "name": layer_name,
        "type": "vector",
        "geometry": "unknown",  # can be refined later
        "datasource": data_source,
        "provider": "ogr"
    })

    ET.SubElement(layer_elem, "layername").text = layer_name
    ET.SubElement(layer_elem, "datasource").text = data_source

    # Output path handling
    if not output_path:
        output_path = os.path.join(os.getcwd(), f"{layer_name}.qlr")
    elif os.path.isdir(output_path):
        output_path = os.path.join(output_path, f"{layer_name}.qlr")

    try:
        tree = ET.ElementTree(qlr)
        tree.write(output_path, encoding="utf-8", xml_declaration=True)
        log_info(f"QLR file written to: {output_path}")
    except Exception as e:
        log_error(f"Failed to write QLR file: {e}")