# arc_to_q/converters/aprx_converter.py

import sys
import os
import json
from pathlib import Path

# ============================================================================
# STAGE 1: ArcGIS Environment - Extraction Only
# ============================================================================

class AprxExtractor:
    """
    Extracts data from an ArcGIS Pro project (.aprx) and saves to JSON.
    Runs in ArcGIS Pro Python environment only.
    """
    
    def __init__(self, aprx_path: str):
        try:
            import arcpy
            self.arcpy = arcpy
        except ImportError:
            raise ImportError("arcpy not found. Run this in ArcGIS Pro Python environment.")
        
        if not os.path.exists(aprx_path):
            raise FileNotFoundError(f"Input .aprx file not found: {aprx_path}")
        
        self.aprx_path = aprx_path
        self.project_name = Path(aprx_path).stem
        self.aprx = self.arcpy.mp.ArcGISProject(aprx_path)
    
    def extract(self, output_folder: str):
        """Extract all project data to a JSON file."""
        print(f"[STAGE 1] Extracting '{self.project_name}.aprx'...")
        
        project_data = {
            "project_name": self.project_name,
            "aprx_path": self.aprx_path,
            "maps": []
        }
        
        for arc_map in self.aprx.listMaps():
            print(f"  Processing map: {arc_map.name}")
            map_data = self._extract_map(arc_map)
            project_data["maps"].append(map_data)
        
        # Save to JSON
        json_path = os.path.join(output_folder, f"{self.project_name}_data.json")
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(project_data, f, indent=2)
        
        print(f"[STAGE 1] Saved extraction to: {json_path}")
        
        # Clean up temp directory if it exists
        temp_dir = os.path.join(os.path.dirname(self.aprx_path), ".temp_lyrx_export")
        if os.path.exists(temp_dir):
            try:
                import shutil
                shutil.rmtree(temp_dir)
                print(f"[STAGE 1] Cleaned up temporary files")
            except:
                pass
        
        return json_path
    
    def _extract_map(self, arc_map):
        """Extract data from a single map."""
        map_data = {
            "name": arc_map.name,
            "crs": None,
            "layers": []
        }
        
        # Extract CRS
        if arc_map.spatialReference:
            try:
                wkid = arc_map.spatialReference.factoryCode
                if wkid:
                    map_data["crs"] = f"EPSG:{wkid}"
            except Exception as e:
                print(f"    Warning: Could not extract CRS. {e}")
        
        # Extract layers
        for arc_layer in reversed(arc_map.listLayers()):
            layer_data = self._extract_layer(arc_layer)
            map_data["layers"].append(layer_data)
        
        return map_data
    
    def _extract_layer(self, arc_layer):
        """Extract data from a single layer."""
        layer_data = {
            "name": arc_layer.name,
            "visible": arc_layer.visible,
            "is_group": arc_layer.isGroupLayer,
            "definition": None,
            "temp_lyrx_path": None,  # Store the path to temp lyrx for Stage 2
            "children": []
        }
        
        if arc_layer.isGroupLayer:
            print(f"    Extracting group: {arc_layer.name}")
            for child_layer in arc_layer.listLayers():
                child_data = self._extract_layer(child_layer)
                layer_data["children"].append(child_data)
        else:
            print(f"    Extracting layer: {arc_layer.name}")
            
            # Create a temp directory in the project folder for layer exports
            temp_dir = os.path.join(os.path.dirname(self.aprx_path), ".temp_lyrx_export")
            os.makedirs(temp_dir, exist_ok=True)
            
            # Try Method 1: Export to .lyrx (gives us proper JSON structure)
            try:
                import time
                temp_name = f"temp_{arc_layer.name.replace(' ', '_')}_{int(time.time()*1000000)}.lyrx"
                tmp_path = os.path.join(temp_dir, temp_name)
                
                # Try to save as .lyrx
                arc_layer.saveACopy(tmp_path)
                
                # Read the JSON from the .lyrx file
                with open(tmp_path, 'r', encoding='utf-8') as f:
                    lyrx_data = json.load(f)
                
                # Extract the layer definition from the .lyrx structure
                if 'layerDefinitions' in lyrx_data and len(lyrx_data['layerDefinitions']) > 0:
                    layer_data["definition"] = lyrx_data['layerDefinitions'][0]
                    # IMPORTANT: Store the directory where the .lyrx was saved
                    # This is needed in Stage 2 to resolve paths correctly
                    layer_data["temp_lyrx_path"] = os.path.dirname(tmp_path)
                    print(f"      ✓ Extracted via .lyrx export (type: {layer_data['definition'].get('type')})")
                else:
                    raise Exception("No layer definitions in .lyrx file")
                
                # Clean up temp file
                try:
                    os.remove(tmp_path)
                except:
                    pass
                    
            except Exception as lyrx_error:
                # Method 1 failed - likely a web/basemap layer that doesn't support saveACopy
                print(f"      .lyrx export failed ({type(lyrx_error).__name__}), trying direct CIM serialization...")
                
                try:
                    # Method 2: Direct CIM serialization (fallback for web layers)
                    cim_definition = arc_layer.getDefinition('V3')
                    layer_data["definition"] = self._cim_to_dict(cim_definition)
                    print(f"      ✓ Extracted via CIM serialization (type: {layer_data['definition'].get('type')})")
                    
                except Exception as cim_error:
                    print(f"      ERROR: Both methods failed: {cim_error}")
        
        return layer_data
    
    def _cim_to_dict(self, obj, _visited=None):
        """
        Convert a CIM object to a dictionary recursively.
        Handles all CIM types by inspecting their properties.
        
        Args:
            obj: The object to convert
            _visited: Set to track visited objects (prevents infinite recursion)
        """
        # Initialize visited set on first call
        if _visited is None:
            _visited = set()
        
        # Handle None
        if obj is None:
            return None
        
        # Handle primitive types
        if isinstance(obj, (str, int, float, bool)):
            return obj
        
        # Handle lists/tuples
        if isinstance(obj, (list, tuple)):
            return [self._cim_to_dict(item, _visited) for item in obj]
        
        # Handle dictionaries
        if isinstance(obj, dict):
            return {k: self._cim_to_dict(v, _visited) for k, v in obj.items()}
        
        # Check for circular references
        obj_id = id(obj)
        if obj_id in _visited:
            # Return a simple reference instead of recursing
            return {"_circular_ref": str(obj.__class__.__name__)}
        
        # Handle CIM objects - check if class name starts with 'CIM'
        class_name = obj.__class__.__name__
        if not class_name.startswith('CIM'):
            # Not a CIM object, try to return as-is or convert to string
            try:
                # Try to convert to a simple type
                if hasattr(obj, '__dict__'):
                    return str(obj)
                return obj
            except:
                return None
        
        # Mark this object as visited
        _visited.add(obj_id)
        
        # This is a CIM object - serialize it
        result = {'type': class_name}
        
        # Get all properties (attributes that don't start with _ and aren't methods)
        # Sort attributes to ensure consistent ordering
        attrs = sorted([a for a in dir(obj) if not a.startswith('_')])
        
        for attr_name in attrs:
            try:
                attr_value = getattr(obj, attr_name)
                
                # Skip methods and callable attributes
                if callable(attr_value):
                    continue
                
                # Skip class attributes that aren't instance-specific
                if attr_name in ('__class__', '__doc__', '__module__'):
                    continue
                
                # Recursively convert the attribute value
                converted_value = self._cim_to_dict(attr_value, _visited)
                
                # Only include the attribute if conversion succeeded and it's not None
                # Unless the original value was explicitly None
                if converted_value is not None or attr_value is None:
                    result[attr_name] = converted_value
                
            except AttributeError:
                # Property doesn't exist or can't be accessed
                pass
            except Exception as e:
                # Some other error accessing the property
                # Store a placeholder so we know something was here
                result[attr_name] = f"<error accessing: {type(e).__name__}>"
        
        # Remove from visited set after processing (allows reuse in different branches)
        _visited.discard(obj_id)
        
        return result


# ============================================================================
# STAGE 2: QGIS Environment - Building Only
# ============================================================================

class QgzBuilder:
    """
    Builds a QGIS project (.qgz) from extracted JSON data.
    Runs in QGIS Python environment only.
    """
    
    def __init__(self):
        try:
            from qgis.core import QgsProject, QgsCoordinateReferenceSystem
            self.QgsProject = QgsProject
            self.QgsCoordinateReferenceSystem = QgsCoordinateReferenceSystem
        except ImportError:
            raise ImportError("QGIS modules not found. Run this in QGIS Python environment.")
        
        # Import other QGIS modules and converters
        from arc_to_q.converters.lyrx_converter import (
            _convert_feature_layer,
            _set_metadata,
            _set_scale_visibility
        )
        # Import raster converter separately to customize behavior
        from arc_to_q.converters.lyrx_converter import _convert_raster_layer as _orig_convert_raster_layer
        
        self._convert_feature_layer = _convert_feature_layer
        self._set_metadata = _set_metadata
        self._set_scale_visibility = _set_scale_visibility
        
        # Create a wrapper for raster conversion that skips relative path switching
        def _convert_raster_layer_no_relative(in_folder, layer_def, out_file, project):
            """Wrapper that converts raster but doesn't switch to relative paths."""
            from qgis.core import QgsRasterLayer
            from arc_to_q.converters.lyrx_converter import _parse_source
            from arc_to_q.converters.raster.raster_renderer import apply_raster_symbology
            import os
            
            layer_name = layer_def.get("name", "Raster")
            data_connection = layer_def.get("dataConnection")
            
            if not data_connection:
                raise RuntimeError(f"Raster layer '{layer_name}' is missing the 'dataConnection' definition.")
            
            if isinstance(data_connection, dict):
                data_connection = {k[0].lower() + k[1:]: v for k, v in data_connection.items()}
            
            (abs_uri, rel_uri), _ = _parse_source(in_folder, data_connection, "", out_file)
            
            # Suppress GDAL warnings
            gdal_log_file = os.environ.get('CPL_LOG')
            os.environ['CPL_LOG'] = os.devnull
            rlayer = None
            
            try:
                rlayer = QgsRasterLayer(abs_uri, layer_name, "gdal")
            finally:
                if gdal_log_file:
                    os.environ['CPL_LOG'] = gdal_log_file
                else:
                    os.environ.pop('CPL_LOG', None)
            
            if not rlayer or not rlayer.isValid():
                error_msg = f"Raster layer failed to load: {layer_name}"
                if os.path.exists(abs_uri):
                    error_msg += f"\nFile exists at '{abs_uri}' but GDAL could not open it."
                else:
                    error_msg += f"\nFile not found at '{abs_uri}'."
                raise RuntimeError(error_msg)
            
            # Apply symbology but DON'T switch to relative path (that's what's breaking)
            apply_raster_symbology(rlayer, layer_def)
            # Skip: switch_to_relative_path(rlayer, rel_uri)
            
            # Add to project WITHOUT adding to tree (we'll handle tree separately)
            project.addMapLayer(rlayer, False)
            
            # Add to layer tree (same as vector converter does)
            root = project.layerTreeRoot()
            node = root.addLayer(rlayer)
            
            return rlayer
        
        self._convert_raster_layer = _convert_raster_layer_no_relative
        
        self.qgs_project = self.QgsProject.instance()
    
    def build(self, json_path: str, output_folder: str):
        """Build QGIS project from JSON data."""
        print(f"[STAGE 2] Building QGIS project from: {json_path}")
        
        # Load JSON data
        with open(json_path, 'r', encoding='utf-8') as f:
            project_data = json.load(f)
        
        print(f"[STAGE 2] Loaded project data:")
        print(f"  - Project name: {project_data['project_name']}")
        print(f"  - Number of maps: {len(project_data['maps'])}")
        
        # Set project name
        project_name = project_data["project_name"]
        aprx_dir = os.path.dirname(project_data["aprx_path"])
        
        # Process each map
        for map_data in project_data["maps"]:
            print(f"  Building map: {map_data['name']} (contains {len(map_data['layers'])} layers)")
            self._build_map(map_data, aprx_dir, output_folder)
        
        # Check what's in the project
        layer_count = len(self.qgs_project.mapLayers())
        print(f"\n[STAGE 2] Project contains {layer_count} layers after building")
        
        if layer_count == 0:
            print("[STAGE 2] WARNING: No layers were added to the project!")
            print("[STAGE 2] This usually means layer sources couldn't be found or conversion failed.")
        
        # Save project
        output_path = os.path.join(output_folder, f"{project_name}.qgz")
        if self.qgs_project.write(output_path):
            print(f"[STAGE 2] Successfully saved: {output_path}")
        else:
            print(f"[STAGE 2] ERROR: Failed to save: {output_path}")
        
        self.qgs_project.clear()
        
        # Clean up JSON file (comment this out to keep for debugging)
        # try:
        #     os.remove(json_path)
        #     print(f"[STAGE 2] Cleaned up temporary file: {json_path}")
        # except:
        #     pass
    
    def _build_map(self, map_data, aprx_dir, output_folder):
        """Build a single map."""
        # Set CRS
        if map_data["crs"]:
            try:
                crs = self.QgsCoordinateReferenceSystem(map_data["crs"])
                if crs.isValid():
                    self.qgs_project.setCrs(crs)
                    print(f"    Set CRS to {map_data['crs']}")
            except Exception as e:
                print(f"    Warning: Could not set CRS. {e}")
        
        # Build layers
        self._build_layer_tree(
            map_data["layers"],
            self.qgs_project.layerTreeRoot(),
            aprx_dir,
            output_folder
        )
    
    def _build_layer_tree(self, layers_data, qgs_parent_node, aprx_dir, output_folder):
        """Recursively build layer tree."""
        # Reverse the order so layers appear in the same order as ArcGIS
        # (QGIS adds layers from bottom to top)
        for layer_data in reversed(layers_data):
            if layer_data["is_group"]:
                print(f"    Creating group: {layer_data['name']}")
                group_node = qgs_parent_node.addGroup(layer_data["name"])
                group_node.setItemVisibilityChecked(layer_data["visible"])
                self._build_layer_tree(
                    layer_data["children"],
                    group_node,
                    aprx_dir,
                    output_folder
                )
            else:
                self._build_layer(layer_data, qgs_parent_node, aprx_dir, output_folder)
    
    def _build_layer(self, layer_data, qgs_parent_node, aprx_dir, output_folder):
        """Build a single layer."""
        print(f"    Building layer: {layer_data['name']}")
        
        layer_def = layer_data.get("definition")
        if not layer_def:
            print(f"    Skipping layer (no definition): {layer_data['name']}")
            return
        
        try:
            layer_type = layer_def.get("type")
            print(f"      Layer type: {layer_type}")
            
            # Use the temp_lyrx_path if available (for proper path resolution)
            # This is the directory where the temporary .lyrx was saved during extraction
            in_folder = layer_data.get("temp_lyrx_path", aprx_dir)
            if in_folder != aprx_dir:
                print(f"      Using temp lyrx path for resolution: {in_folder}")
            
            # Get current layer count
            layers_before = set(self.qgs_project.mapLayers().keys())
            
            if layer_type == "CIMFeatureLayer":
                qgs_layer = self._convert_feature_layer(
                    in_folder, layer_def, output_folder, self.qgs_project
                )
            elif layer_type == "CIMRasterLayer":
                qgs_layer = self._convert_raster_layer(
                    in_folder, layer_def, output_folder, self.qgs_project
                )
            else:
                print(f"    Skipping unsupported layer type: {layer_type}")
                return
            
            # Check what was added
            layers_after = set(self.qgs_project.mapLayers().keys())
            new_layers = layers_after - layers_before
            
            if not new_layers:
                print(f"      WARNING: No layer was added to project")
                return
            
            if len(new_layers) > 1:
                print(f"      WARNING: Multiple layers added ({len(new_layers)})")
            
            # The lyrx_converter functions add the layer to the root tree
            # We need to move it to the correct parent node if it's not root
            if qgs_layer and qgs_layer.isValid():
                print(f"      Layer created successfully: {qgs_layer.name()}")
                print(f"      Layer ID: {qgs_layer.id()}")
                
                # Find the tree node that was created by lyrx_converter
                root = self.qgs_project.layerTreeRoot()
                node = root.findLayer(qgs_layer.id())
                
                if node and qgs_parent_node != root:
                    # Layer is in root, but we want it in a different parent (group)
                    # Clone the node to the correct parent
                    clone = node.clone()
                    qgs_parent_node.addChildNode(clone)
                    # Remove from root
                    root.removeChildNode(node)
                    node = clone
                    print(f"      Moved layer to group: {qgs_parent_node.name()}")
                
                if node:
                    node.setItemVisibilityChecked(layer_data["visible"])
                    node.setName(layer_data["name"])
                    print(f"      Set visibility: {layer_data['visible']}")
                
                # Set metadata and scale visibility
                self._set_metadata(qgs_layer, layer_def)
                self._set_scale_visibility(qgs_layer, layer_def)
            else:
                print(f"      ERROR: Layer is invalid or None")
        
        except Exception as e:
            print(f"    ERROR building layer '{layer_data['name']}': {e}")
            import traceback
            traceback.print_exc()


# ============================================================================
# Convenience function for two-stage conversion
# ============================================================================

def convert_aprx_to_qgz(aprx_path: str, output_folder: str, stage: str = "auto"):
    """
    Convert .aprx to .qgz using appropriate stage.
    
    Args:
        aprx_path: Path to input .aprx file
        output_folder: Path to output folder
        stage: "extract", "build", or "auto" (determines environment)
    
    Returns:
        Path to output file (JSON for extract, .qgz for build)
    """
    if stage == "auto":
        # Detect environment
        try:
            import arcpy
            stage = "extract"
        except ImportError:
            try:
                from qgis.core import QgsProject
                stage = "build"
            except ImportError:
                raise ImportError("Neither arcpy nor qgis found. Cannot determine stage.")
    
    if stage == "extract":
        extractor = AprxExtractor(aprx_path)
        return extractor.extract(output_folder)
    
    elif stage == "build":
        # Find the JSON file
        project_name = Path(aprx_path).stem
        json_path = os.path.join(output_folder, f"{project_name}_data.json")
        if not os.path.exists(json_path):
            raise FileNotFoundError(f"JSON data file not found: {json_path}")
        
        builder = QgzBuilder()
        builder.build(json_path, output_folder)
        return os.path.join(output_folder, f"{project_name}.qgz")
    
    else:
        raise ValueError(f"Invalid stage: {stage}. Use 'extract', 'build', or 'auto'.")