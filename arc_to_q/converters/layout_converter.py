"""
Builds a QGIS Project (.qgz) from an ArcGIS Layout File (.pagx) 
by assembling existing .qlr layer files.

& "C:\Program Files\QGIS 3.40.10\bin\python-qgis-ltr.bat" .\arc_to_q\converters\layout_converter.py
"""
import sys
import os
import json
import logging

# 1. SETUP PATHS (EDIT THESE)
# ---------------------------------------------------------
INPUT_PAGX = r"G:\Working\Students\Undergraduate\For_Vince\ArcGIS_AddOn\ArcGISPaleo_AddOn\Layout.pagx"
QLR_SOURCE_FOLDER = r"G:\Projects\QGIS Support\test_results"
OUTPUT_PROJECT = r"G:\Projects\QGIS Support\test_results\Converted_Layout_Project.qgz"
# ---------------------------------------------------------

# Add package path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from qgis.core import (
    QgsApplication, QgsProject, QgsPrintLayout, QgsLayoutItemMap, 
    QgsLayoutItemLabel, QgsLayoutItemScaleBar, QgsLayoutItemPicture,
    QgsLayoutSize, QgsUnitTypes, QgsLayerDefinition, QgsLayoutPoint
)
from qgis.PyQt.QtCore import QPointF, Qt
from qgis.PyQt.QtGui import QColor, QFont

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger("LayoutBuilder")

class LayoutBuilder:
    def __init__(self, pagx_path, qlr_folder, project):
        self.pagx_path = pagx_path
        self.qlr_folder = qlr_folder
        self.project = project
        self.page_height_mm = 279.4 
        self.map_item = None 

    def run(self):
        with open(self.pagx_path, 'r', encoding='utf-8') as f:
            root = json.load(f)
        
        self._load_layers_from_def(root)

        layout_def = self._find_layout_def(root)
        if not layout_def:
            logger.error("No Layout Definition found.")
            return

        layout = QgsPrintLayout(self.project)
        layout.initializeDefaults()
        layout.setName(layout_def.get("name", "Imported Layout"))

        # Setup Page
        page_def = layout_def.get("page") or root.get("page", {})
        self._setup_page(layout, page_def)

        # Process Elements
        elements = layout_def.get("elements", [])
        # Sort: Map Frame first
        elements.sort(key=lambda x: 0 if x.get("type") == "CIMMapFrame" else 1)

        for el in elements:
            try:
                self._dispatch_element(layout, el)
            except Exception as e:
                name = el.get("name", el.get("type"))
                logger.warning(f"Skipping '{name}': {e}")

        self.project.layoutManager().addLayout(layout)
        logger.info("Layout built successfully.")

    def _load_layers_from_def(self, root):
        logger.info("--- Scanning for Layers ---")
        layer_defs = root.get("layerDefinitions", [])
        
        for ldef in layer_defs:
            if not ldef.get("visibility", True):
                continue 

            name = ldef.get("name")
            if not name: continue

            qlr_name = f"{name}.qlr"
            qlr_path = os.path.join(self.qlr_folder, qlr_name)

            if os.path.exists(qlr_path):
                try:
                    QgsLayerDefinition.loadLayerDefinition(
                        qlr_path, self.project, self.project.layerTreeRoot()
                    )
                    logger.info(f"Loaded: {name}")
                except Exception as e:
                    logger.error(f"Failed to load {qlr_name}: {e}")

    def _setup_page(self, layout, page_def):
        if not page_def: 
            width_mm, height_mm = 215.9, 279.4
        else:
            w = page_def.get("width", 8.5)
            h = page_def.get("height", 11)
            # Assume inches if small numbers, else mm
            mult = 25.4 if w < 50 else 1
            width_mm = w * mult
            height_mm = h * mult

        self.page_height_mm = height_mm
        layout.pageCollection().page(0).setPageSize(QgsLayoutSize(width_mm, height_mm, QgsUnitTypes.LayoutMillimeters))

    def _get_geometry_mm(self, element):
        """
        Extracts geometry. Priorities:
        1. 'frame.rings' (Explicit box)
        2. 'graphic.geometry.rings' (Explicit box)
        3. 'graphic.frame.rings' (Nested box)
        4. 'anchor' point (Fallback)
        """
        rings = element.get("frame", {}).get("rings")
        if not rings:
            # Check graphic.geometry
            graphic = element.get("graphic", {})
            rings = graphic.get("geometry", {}).get("rings")
            # Check graphicFrame (common in North Arrows)
            if not rings:
                rings = element.get("graphicFrame", {}).get("frame", {}).get("rings")

        x_min, y_min = float('inf'), float('inf')
        x_max, y_max = float('-inf'), float('-inf')
        found_box = False
        
        if rings:
            try:
                for ring in rings:
                    for pt in ring:
                        x_min = min(x_min, pt[0])
                        y_min = min(y_min, pt[1])
                        x_max = max(x_max, pt[0])
                        y_max = max(y_max, pt[1])
                found_box = True
            except:
                pass
            
        if not found_box:
            # Fallback to anchor/shape point
            shape = element.get("shape", {})
            x_in = shape.get("x", 0)
            y_in = shape.get("y", 0)
            
            if x_in == 0 and y_in == 0:
                anchor = element.get("anchorPoint") or element.get("rotationCenter")
                if anchor:
                    x_in = anchor.get("x", 0)
                    y_in = anchor.get("y", 0)

            # Assign default sizes if we only have a point
            w_in = 2.0
            h_in = 1.0
            x_min, y_min = x_in, y_in
            x_max, y_max = x_in + w_in, y_in + h_in

        # Convert to MM
        x = x_min * 25.4
        y_bottom = y_min * 25.4
        w = (x_max - x_min) * 25.4
        h = (y_max - y_min) * 25.4

        # FLIP Y (ArcGIS Y is Bottom-Up)
        y = self.page_height_mm - (y_bottom + h)

        return x, y, w, h

    def _dispatch_element(self, layout, element):
        etype = element.get("type")
        if etype == "CIMMapFrame":
            self._create_map_frame(layout, element)
        elif etype in ["CIMTextGraphic", "CIMGraphicElement"]:
            # Check internal graphic type
            gtype = element.get("graphic", {}).get("type")
            if gtype == "CIMTextGraphic" or etype == "CIMTextGraphic":
                self._create_label(layout, element)
        elif etype == "CIMScaleLine":
            self._create_scalebar(layout, element)
        elif etype == "CIMMarkerNorthArrow":
            self._create_north_arrow(layout, element)

    def _create_map_frame(self, layout, element):
        x, y, w, h = self._get_geometry_mm(element)
        map_item = QgsLayoutItemMap(layout)
        map_item.setRect(x, y, w, h)
        map_item.setFrameEnabled(True)
        
        layers = list(self.project.mapLayers().values())
        map_item.setLayers(layers)
        
        if layers:
            extent = layers[0].extent()
            for l in layers[1:]:
                extent.combineExtentWith(l.extent())
            map_item.setExtent(extent)
            
        layout.addLayoutItem(map_item)
        self.map_item = map_item

    def _create_label(self, layout, element):
        x, y, w, h = self._get_geometry_mm(element)
        
        graphic = element.get("graphic", {})
        text_str = element.get("text") or graphic.get("text", "Text")
        if "<dyn" in text_str: text_str = text_str.split("<")[0] # Clean dynamic tags

        label = QgsLayoutItemLabel(layout)
        label.setText(text_str)
        
        # --- Alignment Fix ---
        # ArcGIS: "Center", "Left", "Right"
        # QGIS: Qt.AlignHCenter, Qt.AlignLeft, Qt.AlignRight
        symbol_obj = graphic.get("symbol", {}).get("symbol", {})
        align_str = symbol_obj.get("horizontalAlignment", "Left")
        
        if align_str == "Center":
            label.setHAlign(Qt.AlignHCenter)
        elif align_str == "Right":
            label.setHAlign(Qt.AlignRight)
        else:
            label.setHAlign(Qt.AlignLeft)

        # --- Font Fix ---
        font_size = symbol_obj.get("height", 10)
        font_family = symbol_obj.get("fontFamilyName", "Arial")
        
        f = QFont(font_family)
        f.setPointSizeF(font_size)
        label.setFont(f) 
        
        label.setRect(x, y, w, h)
        # Removed adjustSizeToText() as it was shrinking boxes too much
        layout.addLayoutItem(label)

    def _create_scalebar(self, layout, element):
        if not self.map_item: return
        x, y, w, h = self._get_geometry_mm(element)
        
        sb = QgsLayoutItemScaleBar(layout)
        sb.setLinkedMap(self.map_item)
        sb.applyDefaultSize()
        sb.setStyle("Single Box") 
        
        # Simple Unit Mapping
        u_lbl = element.get("unitLabel", "").lower()
        if "kilometer" in u_lbl:
            sb.setUnitLabel("km")
            sb.setMapUnitsPerScaleBarUnit(1000) 
        elif "mile" in u_lbl:
            sb.setUnitLabel("mi")
            sb.setMapUnitsPerScaleBarUnit(1609.34)
            
        sb.setNumberOfSegments(element.get("divisions", 2))
        sb.setBoxContentSpace(1.0)

        # FIX: Use QgsLayoutPoint for attemptMove
        point = QgsLayoutPoint(x, y, QgsUnitTypes.LayoutMillimeters)
        sb.attemptMove(point)
        
        layout.addLayoutItem(sb)

    def _create_north_arrow(self, layout, element):
        x, y, w, h = self._get_geometry_mm(element)
        
        svg_path = ":/images/north_arrows/layout_default_north_arrow.svg"
        arrow = QgsLayoutItemPicture(layout)
        arrow.setPicturePath(svg_path)
        
        # Sanity check size. If width > 50mm, it's probably the huge size bug.
        # Constrain to reasonable aspect if it looks wrong.
        if w > 80: 
            w, h = 20, 20
            
        arrow.setRect(x, y, w, h)
        layout.addLayoutItem(arrow)

    def _find_layout_def(self, root):
        if "layoutDefinition" in root: return root["layoutDefinition"]
        if "layout" in root: return root["layout"]
        if "elements" in root: return root
        if "definitions" in root:
            for d in root["definitions"]:
                if d.get("type") == "CIMLayout": return d
        return None

if __name__ == "__main__":
    qgs = QgsApplication([], False)
    qgs.initQgis()
    project = QgsProject.instance()

    try:
        print("--- STARTING PROJECT BUILDER ---")
        builder = LayoutBuilder(INPUT_PAGX, QLR_SOURCE_FOLDER, project)
        builder.run()
        
        print(f"Saving Project to: {OUTPUT_PROJECT}")
        project.write(OUTPUT_PROJECT)
        print("--- SUCCESS ---")
        
    except Exception as e:
        print(f"CRITICAL ERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        qgs.exitQgis()