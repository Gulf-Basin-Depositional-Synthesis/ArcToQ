"""Converts ArcGIS Pro layer files (.lyrx) to QGIS layer files (.qlr)."""

import json
import os
from pathlib import Path

from qgis.core import (
    QgsApplication,
    QgsVectorLayer,
    QgsLayerDefinition,
    QgsReadWriteContext,
    QgsRasterLayer,
    QgsCoordinateReferenceSystem,
)

#from arc_to_q.converters.symbology_converter import set_symbology
from arc_to_q.converters.vector.vector_renderer import RendererFactory
from arc_to_q.converters.label_converter import set_labels
from arc_to_q.converters.raster.color_mapping import create_classified_renderer
from arc_to_q.converters.raster.resampling import get_resampling_method


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

def _parse_raster_source(in_folder, data_connection, out_file):
    """Build both absolute and relative QGIS-friendly URIs for a raster dataset.
    
    Args:
        in_folder (str): The absolute path to the input folder containing the .lyrx file.
        data_connection (dict): The data connection information from the .lyrx file.
        out_file (str): The output file path for the converted QGIS layer.

    Returns:
        tuple: (absolute path, relative path) where each is a QGIS data source string.
    """
    factory = data_connection.get("workspaceFactory")
    conn_str = data_connection.get("workspaceConnectionString", "")
    dataset = data_connection.get("dataset")

    if not factory or not conn_str or not dataset:
        raise ValueError("Missing required fields in dataConnection.")

    # Extract path from ArcGIS-style connection string
    # Example: "DATABASE=G:\\Current_Database\\Database\\tif\\SandGrainVol" → "G:\\Current_Database\\Database\\tif\\SandGrainVol"
    if "=" in conn_str:
        _, raw_path = conn_str.split("=", 1)
    else:
        raw_path = conn_str

    # For raster data, the dataset is the actual filename, not a layer name
    # So we need to join the workspace path with the dataset filename
    lyrx_dir = Path(in_folder)
    workspace_path = (lyrx_dir / raw_path).resolve()
    
    # Build the full raster file path
    if factory == "Raster":
        abs_path = workspace_path / dataset
        abs_uri = abs_path.as_posix()
        
        # Build relative URI for saving in QLR
        out_dir = Path(out_file).parent.resolve()
        rel_path = Path(os.path.relpath(abs_path, start=out_dir))
        rel_uri = rel_path.as_posix()
        
        return abs_uri, rel_uri
    else:
        raise NotImplementedError(f"Unsupported raster workspaceFactory: {factory}")


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

def create_gbds_albers_crs():
    """
    Creates a custom CRS for GBDS_Albers_Full_ft based on typical Albers projections.
    This is a best guess - you should get the exact parameters from your organization.
    """
    # This is a template - you'll need the exact parameters
    # Common Albers Equal Area parameters for US data in feet:
    proj4_string = '+proj=aea +lat_0=23 +lon_0=-96 +lat_1=29.5 +lat_2=45.5 +x_0=0 +y_0=0 +datum=NAD83 +units=ft +no_defs'
    
    custom_crs = QgsCoordinateReferenceSystem()
    success = custom_crs.createFromProj(proj4_string)
    
    if success:
        print(f"Created custom CRS: {custom_crs.description()}")
        return custom_crs
    else:
        print("Failed to create custom CRS")
        return None
    


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

    # --- THE FIX ---
    # 1. Switch the data source to the relative path. This resets the filter.
    layer.setDataSource(rel_uri, layer.name(), layer.providerType())

    # 2. NOW, apply the definition query. It will be the last thing set before saving.
    _set_definition_query(layer, layer_def)
    # ---------------

    if not layer.isValid():
        # This final check ensures the layer is still valid with the new path and query
        print(f"CRITICAL ERROR: Layer '{layer_name}' became invalid after setting relative path or query.")
        print(f"Check the query syntax and relative path logic: {layer.error().summary()}")
        raise RuntimeError(f"Layer became invalid: {layer_name}")

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
            print(f"Processing Raster Layer: {layer_def.get('name')}")
            
            # Use the raster-specific path parsing logic
            data_connection = layer_def.get('dataConnection', {})
            try:
                abs_uri, rel_uri = _parse_raster_source(in_folder, data_connection, out_file)
            except Exception as e:
                print(f"Error parsing raster source: {e}")
                return
            
            layer_name = layer_def.get('name', os.path.basename(abs_uri))
            print(f"Attempting to load raster from: {abs_uri}")

            # Create the QGIS raster layer object with absolute path first
            qgis_layer = QgsRasterLayer(abs_uri, layer_name)
            if not qgis_layer.isValid():
                print(f"Failed to load raster layer: {abs_uri}")
                print(f"Error: {qgis_layer.error().summary()}")
                
                # Try to check if file exists
                if os.path.exists(abs_uri):
                    print(f"File exists but GDAL cannot read it. Check file format/permissions.")
                else:
                    print(f"File does not exist at: {abs_uri}")
                return

            # Check current CRS
            current_crs = qgis_layer.crs()
            print(f"Current CRS: {current_crs.authid()} - {current_crs.description()}")
            
            # Handle custom CRS issue
            if not current_crs.isValid() or current_crs.description() == "GBDS_Albers_Full_ft":
                print("Detected custom/invalid CRS. Attempting to create GBDS Albers projection...")
                
                # Try to create the custom CRS
                custom_crs = create_gbds_albers_crs()
                if custom_crs and custom_crs.isValid():
                    print(f"Setting custom CRS: {custom_crs.description()}")
                    qgis_layer.setCrs(custom_crs)
                else:
                    print("Custom CRS creation failed, trying standard projections...")
                    # Fall back to standard projections
                    candidate_crs = [
                        "EPSG:2163",    # US National Atlas Equal Area (meters)
                        "EPSG:5070",    # NAD83 Conus Albers (meters)
                        "EPSG:3081",    # NAD83 / Texas Centric Albers Equal Area (feet)
                        "EPSG:2780",    # NAD83(HARN) / Texas State Mapping System (feet)
                        "EPSG:3857",    # Web Mercator (meters) - last resort
                    ]
                    
                    for crs_code in candidate_crs:
                        test_crs = QgsCoordinateReferenceSystem(crs_code)
                        if test_crs.isValid():
                            print(f"Trying CRS: {crs_code} - {test_crs.description()}")
                            qgis_layer.setCrs(test_crs)
                            print(f"Set CRS to: {test_crs.authid()} - {test_crs.description()}")
                            break
                
                # Alternative: Try to create CRS from the raster's spatial extent
                # This is a fallback if none of the standard projections work well
            
            # Look for any CRS information in the layer definition (just in case)
            spatial_reference = layer_def.get('spatialReference')
            if spatial_reference:
                wkid = spatial_reference.get('wkid')
                latest_wkid = spatial_reference.get('latestWkid')
                wkt = spatial_reference.get('wkt')
                
                print(f"Found ArcGIS CRS info - WKID: {wkid}, Latest WKID: {latest_wkid}")
                
                # Try to set the correct CRS from ArcGIS info
                target_crs = None
                if latest_wkid:
                    target_crs = QgsCoordinateReferenceSystem(f"EPSG:{latest_wkid}")
                elif wkid:
                    target_crs = QgsCoordinateReferenceSystem(f"EPSG:{wkid}")
                elif wkt:
                    target_crs = QgsCoordinateReferenceSystem()
                    target_crs.createFromWkt(wkt)
                    
                if target_crs and target_crs.isValid():
                    print(f"Setting CRS from ArcGIS to: {target_crs.authid()} - {target_crs.description()}")
                    qgis_layer.setCrs(target_crs)
            
            # Add debugging information
            print("=== RASTER DEBUGGING INFO ===")
            data_provider = qgis_layer.dataProvider()
            if data_provider:
                print(f"Raster width: {qgis_layer.width()}")
                print(f"Raster height: {qgis_layer.height()}")
                print(f"Band count: {qgis_layer.bandCount()}")
                
                # Get the raster extent
                extent = qgis_layer.extent()
                print(f"Extent: {extent.toString()}")
                
                # Try to get transform information (method varies by QGIS version)
                try:
                    # Try different methods to get geotransform
                    if hasattr(data_provider, 'geoTransform'):
                        transform = data_provider.geoTransform()
                    else:
                        # Alternative method for older QGIS versions
                        transform = None
                        print("Cannot access geotransform directly")
                        
                    if transform:
                        print(f"GeoTransform: {transform}")
                        print(f"  - Top-left X: {transform[0]}")
                        print(f"  - Pixel width: {transform[1]}")  
                        print(f"  - X rotation: {transform[2]}")    # This might be the issue!
                        print(f"  - Top-left Y: {transform[3]}")
                        print(f"  - Y rotation: {transform[4]}")    # This might be the issue!
                        print(f"  - Pixel height: {transform[5]}")
                        
                        # Check if there's rotation in the transform
                        if transform[2] != 0 or transform[4] != 0:
                            print("*** WARNING: Raster has rotation in its geotransform! ***")
                            print(f"X rotation: {transform[2]}, Y rotation: {transform[4]}")
                except Exception as e:
                    print(f"Could not get geotransform: {e}")
                
            print("=== END DEBUGGING INFO ===")

            # Get the symbology info from the colorizer
            colorizer_def = layer_def.get('colorizer', {})
            if colorizer_def:
                # Check if the colorizer is the classified type we support
                if colorizer_def.get('type') == 'CIMRasterClassifyColorizer':
                    # Call the function from color_mapping.py to create the renderer
                    renderer = create_classified_renderer(qgis_layer, colorizer_def)
                    if renderer:
                        # Apply the renderer to the layer
                        qgis_layer.setRenderer(renderer)
                
                # Set resampling method on the raster layer's data provider
                resampling = get_resampling_method(colorizer_def)
                data_provider = qgis_layer.dataProvider()
                if data_provider:
                    # Set resampling for zoomed in (overview) display
                    data_provider.setZoomedInResamplingMethod(resampling)
                    # Set resampling for zoomed out (overview) display  
                    data_provider.setZoomedOutResamplingMethod(resampling)
            
            # Switch to relative path (similar to how vector layers are handled)
            qgis_layer.setDataSource(rel_uri, qgis_layer.name(), qgis_layer.providerType())
            
            if not qgis_layer.isValid():
                print(f"CRITICAL ERROR: Raster layer '{layer_name}' became invalid after setting relative path.")
                print(f"Relative path: {rel_uri}")
                print(f"Error: {qgis_layer.error().summary()}")
                raise RuntimeError(f"Raster layer became invalid: {layer_name}")
            
            # Set this as the out_layer for further processing
            out_layer = qgis_layer
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
