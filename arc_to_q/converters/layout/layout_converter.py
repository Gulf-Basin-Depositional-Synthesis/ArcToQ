r"""
Enhanced ArcGIS Layout Converter (.pagx to .qgz)
Fixed Y-axis calculation, scale bar units, and text box sizing

& "C:\Program Files\QGIS 3.40.10\bin\python-qgis-ltr.bat" .\arc_to_q\converters\layout\layout_converter.py
"""
import sys
import os
import json
import logging

# Ensure we can import sibling modules if running as a script
if __name__ == "__main__":
    # Add the project root to sys.path
    current_dir = os.path.dirname(os.path.abspath(__file__))
    package_root = os.path.abspath(os.path.join(current_dir, '..', '..'))
    sys.path.insert(0, package_root)

from qgis.core import (
    QgsApplication, QgsProject, QgsPrintLayout, 
    QgsLayoutSize, QgsUnitTypes, QgsLayerDefinition
)

# Relative imports work when this is imported as a module
try:
    from .geometry import GeometryConverter
    from .parsers import LayoutParser
    from .elements.factory import ElementFactory
except ImportError:
    # Fallback for running directly as a script
    from geometry import GeometryConverter
    from parsers import LayoutParser
    from elements.factory import ElementFactory

logging.basicConfig(level=logging.DEBUG, format='%(levelname)s: %(message)s')
logger = logging.getLogger("LayoutConverter")

# ---------------------------------------------------------
# CONFIGURATION (Can be overridden by arguments)
# ---------------------------------------------------------
INPUT_PAGX = r"G:\Working\Students\Undergraduate\For_Vince\ArcGIS_AddOn\ArcGISPaleo_AddOn\Layout.pagx"
QLR_SOURCE_FOLDER = r"G:\Projects\QGIS Support\test_results"
OUTPUT_PROJECT = r"G:\Projects\QGIS Support\test_results\Converted_Layout_Project.qgz"
# ---------------------------------------------------------

class LayoutConverter:
    """
    Main Orchestrator for converting ArcGIS Pro Layouts (.pagx) to QGIS Layouts.
    Delegates specific tasks to helper classes in the `converters.layout` package.
    """
    
    def __init__(self, pagx_path, qlr_folder, project):
        self.pagx_path = pagx_path
        self.qlr_folder = qlr_folder
        self.project = project
        self.geo_converter = None  # Initialized after page size is determined

    def run(self):
        """Main execution flow."""
        if not os.path.exists(self.pagx_path):
            logger.error(f"Input file not found: {self.pagx_path}")
            return

        # 1. Load JSON
        with open(self.pagx_path, 'r', encoding='utf-8') as f:
            root = json.load(f)
        
        # 2. Load Referenced Layers (QLR)
        self._load_layers(root)

        # 3. Find Layout Definition
        layout_def = LayoutParser.find_layout_definition(root)
        if not layout_def:
            logger.error("No Layout Definition found.")
            return

        # 4. Initialize QGIS Layout
        layout = QgsPrintLayout(self.project)
        layout.initializeDefaults()
        layout.setName(layout_def.get("name", "Imported Layout"))

        # 5. Setup Page & Initialize Geometry Engine
        self._setup_page(layout, layout_def, root)

        # 6. Process Elements
        self._process_elements(layout, layout_def)

        # 7. Finalize
        self.project.layoutManager().addLayout(layout)
        logger.info(f"\nLayout built successfully.")

    def _load_layers(self, root):
        """Loads QLR files for layers referenced in the layout."""
        logger.info("--- Loading Layers ---")
        layer_defs = root.get("layerDefinitions", [])
        
        for ldef in layer_defs:
            if not ldef.get("visibility", True): 
                continue 
            
            name = ldef.get("name")
            # Sanitize name to match potential filenames
            safe_name = "".join([c for c in name if c.isalnum() or c in (' ', '.', '_', '-')]).strip()
            
            # Try exact match, then sanitized match
            qlr_path = os.path.join(self.qlr_folder, f"{name}.qlr")
            if not os.path.exists(qlr_path):
                qlr_path = os.path.join(self.qlr_folder, f"{safe_name}.qlr")

            if os.path.exists(qlr_path):
                try:
                    QgsLayerDefinition.loadLayerDefinition(qlr_path, self.project, self.project.layerTreeRoot())
                    logger.info(f"Loaded layer: {name}")
                except Exception as e:
                    logger.warning(f"Failed to load QLR {qlr_path}: {e}")
            else:
                logger.warning(f"QLR file not found for layer: {name}")

    def _setup_page(self, layout, layout_def, root):
        """Configures the page size and initializes the GeometryConverter."""
        page_def = layout_def.get("page") or root.get("page", {})
        
        # Use Geometry helper to parse units
        w_mm, h_mm = GeometryConverter.parse_page_size(page_def)
        
        # Apply to QGIS Layout
        page = layout.pageCollection().page(0)
        page.setPageSize(QgsLayoutSize(w_mm, h_mm, QgsUnitTypes.LayoutMillimeters))
        
        # Initialize the GeometryConverter with the page height (needed for Y-axis flip)
        self.geo_converter = GeometryConverter(page_height_mm=h_mm)
        
        logger.info(f"Page configured: {w_mm:.2f}mm x {h_mm:.2f}mm")

    def _process_elements(self, layout, layout_def):
        """Iterates through layout elements and delegates to Factory."""
        elements = layout_def.get("elements", [])
        
        # Sort: Map Frames first. 
        # This ensures they exist before Scale Bars or Text items try to link to them.
        elements.sort(key=lambda x: (0 if x.get("type") == "CIMMapFrame" else 1, x.get("type", "")))

        logger.info(f"\n--- Processing {len(elements)} Elements ---")
        
        for idx, el in enumerate(elements):
            try:
                # Use the Factory to get the correct handler
                handler = ElementFactory.get_handler(
                    el, self.project, layout, self.geo_converter
                )
                
                if handler:
                    handler.create(el)
                
            except Exception as e:
                logger.error(f"Failed to create element {idx} ({el.get('type')}): {e}")
                # Optional: Keep going even if one element fails
                import traceback
                traceback.print_exc()

if __name__ == "__main__":
    # Standard QGIS standalone script boilerplate
    qgs = QgsApplication([], False)
    qgs.initQgis()
    project = QgsProject.instance()

    try:
        print("="*60)
        print("ARCGIS TO QGIS LAYOUT CONVERTER (MODULAR)")
        print("="*60)
        
        converter = LayoutConverter(INPUT_PAGX, QLR_SOURCE_FOLDER, project)
        converter.run()
        
        project.write(OUTPUT_PROJECT)
        print("\n" + "="*60)
        print("✓ CONVERSION COMPLETE")
        print(f"Output: {OUTPUT_PROJECT}")
        print("="*60)
        
    except Exception as e:
        print(f"\n❌ CRITICAL ERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        qgs.exitQgis()