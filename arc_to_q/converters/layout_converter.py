"""
Enhanced ArcGIS Layout Converter (.pagx to .qgz)
Improved geometry extraction, text handling, and debugging

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
DEBUG_JSON_OUTPUT = r"G:\Projects\QGIS Support\test_results\debug_pagx_structure.json"
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

logging.basicConfig(level=logging.DEBUG, format='%(levelname)s: %(message)s')
logger = logging.getLogger("LayoutBuilder")

class LayoutBuilder:
    def __init__(self, pagx_path, qlr_folder, project):
        self.pagx_path = pagx_path
        self.qlr_folder = qlr_folder
        self.project = project
        self.page_height_mm = 279.4 
        self.page_width_mm = 215.9
        self.map_item = None 
        self.debug_elements = []

    def run(self):
        with open(self.pagx_path, 'r', encoding='utf-8') as f:
            root = json.load(f)
        
        # Save debug JSON
        self._save_debug_structure(root)
        
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
        logger.info(f"Found {len(elements)} elements to process")
        
        # Sort: Map Frame first, then by type
        elements.sort(key=lambda x: (0 if x.get("type") == "CIMMapFrame" else 1, x.get("type", "")))

        for idx, el in enumerate(elements):
            el_type = el.get("type", "Unknown")
            el_name = el.get("name", f"Element_{idx}")
            logger.info(f"\n{'='*60}")
            logger.info(f"Processing Element {idx+1}/{len(elements)}: {el_name} ({el_type})")
            
            try:
                self._debug_element_structure(el, idx)
                self._dispatch_element(layout, el)
                logger.info(f"✓ Successfully created: {el_name}")
            except Exception as e:
                logger.error(f"✗ Failed to create '{el_name}': {e}")
                import traceback
                logger.debug(traceback.format_exc())

        self.project.layoutManager().addLayout(layout)
        logger.info(f"\n{'='*60}")
        logger.info("Layout built successfully.")
        logger.info(f"Debug information saved to: {DEBUG_JSON_OUTPUT}")

    def _save_debug_structure(self, root):
        """Save a simplified debug version of the JSON structure"""
        try:
            debug_data = {
                "layout_keys": list(root.keys()),
                "elements_summary": []
            }
            
            layout_def = self._find_layout_def(root)
            if layout_def:
                elements = layout_def.get("elements", [])
                for idx, el in enumerate(elements):
                    debug_data["elements_summary"].append({
                        "index": idx,
                        "type": el.get("type"),
                        "name": el.get("name"),
                        "keys": list(el.keys()),
                        "has_frame": "frame" in el,
                        "has_graphic": "graphic" in el,
                        "has_graphicFrame": "graphicFrame" in el,
                        "has_shape": "shape" in el,
                        "has_anchor": "anchorPoint" in el,
                        "has_text": "text" in el or ("graphic" in el and "text" in el.get("graphic", {}))
                    })
            
            with open(DEBUG_JSON_OUTPUT, 'w', encoding='utf-8') as f:
                json.dump(debug_data, f, indent=2)
                
        except Exception as e:
            logger.warning(f"Could not save debug structure: {e}")

    def _debug_element_structure(self, element, idx):
        """Log detailed element structure for debugging"""
        logger.debug(f"Element keys: {list(element.keys())}")
        
        # Check all possible geometry sources
        if "frame" in element:
            logger.debug(f"  frame keys: {list(element['frame'].keys())}")
            if "rings" in element["frame"]:
                rings = element["frame"]["rings"]
                if rings and len(rings) > 0:
                    logger.debug(f"  frame.rings has {len(rings)} ring(s)")
                    for ring_idx, ring in enumerate(rings):
                        logger.debug(f"    Ring {ring_idx}: {len(ring)} points")
                        if len(ring) <= 6:  # Show all points if 6 or fewer
                            for pt_idx, pt in enumerate(ring):
                                logger.debug(f"      Point {pt_idx}: {pt}")
                        else:  # Just show first and last
                            logger.debug(f"      First: {ring[0]}")
                            logger.debug(f"      Last: {ring[-1]}")
        
        if "graphic" in element:
            logger.debug(f"  graphic keys: {list(element['graphic'].keys())}")
            graphic = element["graphic"]
            
            if "shape" in graphic:
                logger.debug(f"    shape keys: {list(graphic['shape'].keys())}")
                if "rings" in graphic["shape"]:
                    rings = graphic["shape"]["rings"]
                    if rings and len(rings) > 0:
                        logger.debug(f"    shape.rings has {len(rings)} ring(s) with {len(rings[0])} points in first ring")
            
            if "geometry" in graphic:
                logger.debug(f"    geometry keys: {list(graphic['geometry'].keys())}")
            
            if "frame" in graphic:
                logger.debug(f"    graphic.frame keys: {list(graphic['frame'].keys())}")
            
            if "symbol" in graphic:
                logger.debug(f"    symbol keys: {list(graphic['symbol'].keys())}")
        
        if "graphicFrame" in element:
            logger.debug(f"  graphicFrame keys: {list(element['graphicFrame'].keys())}")
        
        if "anchor" in element:
            logger.debug(f"  anchor: {element['anchor']}")
        
        if "anchorPoint" in element:
            logger.debug(f"  anchorPoint: {element['anchorPoint']}")
        
        if "rotationCenter" in element:
            logger.debug(f"  rotationCenter: {element['rotationCenter']}")

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
            
            # Detect units: if values are small (< 50), assume inches
            if w < 50 and h < 50:
                width_mm = w * 25.4
                height_mm = h * 25.4
                logger.info(f"Page size: {w}\" x {h}\" ({width_mm:.1f}mm x {height_mm:.1f}mm)")
            else:
                width_mm = w
                height_mm = h
                logger.info(f"Page size: {width_mm:.1f}mm x {height_mm:.1f}mm")

        self.page_height_mm = height_mm
        self.page_width_mm = width_mm
        layout.pageCollection().page(0).setPageSize(
            QgsLayoutSize(width_mm, height_mm, QgsUnitTypes.LayoutMillimeters)
        )

    def _get_geometry_mm(self, element):
        """
        Enhanced geometry extraction with multiple fallback strategies
        Returns: (x_mm, y_mm, width_mm, height_mm)
        """
        x_min, y_min = None, None
        x_max, y_max = None, None
        found_box = False
        
        # Strategy 1: Check element.frame.rings
        if "frame" in element and "rings" in element["frame"]:
            rings = element["frame"]["rings"]
            if rings and len(rings) > 0:
                try:
                    # Rings contain arrays of [x,y] coordinate pairs forming a polygon
                    for ring in rings:
                        for pt in ring:
                            if len(pt) >= 2:  # Ensure it's a valid coordinate
                                if x_min is None or pt[0] < x_min: x_min = pt[0]
                                if y_min is None or pt[1] < y_min: y_min = pt[1]
                                if x_max is None or pt[0] > x_max: x_max = pt[0]
                                if y_max is None or pt[1] > y_max: y_max = pt[1]
                    
                    if x_min is not None and x_max is not None:
                        found_box = True
                        logger.debug(f"  Found geometry in frame.rings: ({x_min:.3f}, {y_min:.3f}) to ({x_max:.3f}, {y_max:.3f})")
                        logger.debug(f"    Width: {x_max - x_min:.3f}\", Height: {y_max - y_min:.3f}\"")
                except Exception as e:
                    logger.debug(f"  Error parsing frame.rings: {e}")
        
        # Strategy 2: Check element.graphic.shape (for text elements!)
        if not found_box and "graphic" in element:
            graphic = element["graphic"]
            if "shape" in graphic:
                shape = graphic["shape"]
                # Shape often has rings array with coordinates
                if "rings" in shape and shape["rings"]:
                    try:
                        for ring in shape["rings"]:
                            for pt in ring:
                                if len(pt) >= 2:
                                    if x_min is None or pt[0] < x_min: x_min = pt[0]
                                    if y_min is None or pt[1] < y_min: y_min = pt[1]
                                    if x_max is None or pt[0] > x_max: x_max = pt[0]
                                    if y_max is None or pt[1] > y_max: y_max = pt[1]
                        
                        if x_min is not None and x_max is not None:
                            found_box = True
                            logger.debug(f"  Found geometry in graphic.shape.rings: ({x_min:.3f}, {y_min:.3f}) to ({x_max:.3f}, {y_max:.3f})")
                    except Exception as e:
                        logger.debug(f"  Error parsing graphic.shape.rings: {e}")
                # Some shapes just have x, y (point geometry)
                elif "x" in shape and "y" in shape:
                    # This is just a point, we'll need to estimate size later
                    logger.debug(f"  Found point geometry in graphic.shape: ({shape['x']}, {shape['y']})")
                    # Don't set found_box=True, let it fall through to Strategy 5
        
        # Strategy 3: Check element.graphic.geometry.rings
        if not found_box and "graphic" in element:
            graphic = element["graphic"]
            if "geometry" in graphic and "rings" in graphic["geometry"]:
                rings = graphic["geometry"]["rings"]
                if rings and len(rings) > 0:
                    try:
                        for ring in rings:
                            for pt in ring:
                                if len(pt) >= 2:
                                    if x_min is None or pt[0] < x_min: x_min = pt[0]
                                    if y_min is None or pt[1] < y_min: y_min = pt[1]
                                    if x_max is None or pt[0] > x_max: x_max = pt[0]
                                    if y_max is None or pt[1] > y_max: y_max = pt[1]
                        
                        if x_min is not None and x_max is not None:
                            found_box = True
                            logger.debug(f"  Found geometry in graphic.geometry.rings")
                    except Exception as e:
                        logger.debug(f"  Error parsing graphic.geometry.rings: {e}")
        
        # Strategy 4: Check element.graphic.frame.rings
        if not found_box and "graphic" in element:
            graphic = element["graphic"]
            if "frame" in graphic and "rings" in graphic["frame"]:
                rings = graphic["frame"]["rings"]
                if rings and len(rings) > 0:
                    try:
                        for ring in rings:
                            for pt in ring:
                                if len(pt) >= 2:
                                    if x_min is None or pt[0] < x_min: x_min = pt[0]
                                    if y_min is None or pt[1] < y_min: y_min = pt[1]
                                    if x_max is None or pt[0] > x_max: x_max = pt[0]
                                    if y_max is None or pt[1] > y_max: y_max = pt[1]
                        
                        if x_min is not None and x_max is not None:
                            found_box = True
                            logger.debug(f"  Found geometry in graphic.frame.rings")
                    except Exception as e:
                        logger.debug(f"  Error parsing graphic.frame.rings: {e}")
        
        # Strategy 5: Use anchor + width/height if available
        if not found_box:
            # Get anchor point - anchor can be a string or dict, so check carefully
            anchor = None
            if "rotationCenter" in element and isinstance(element["rotationCenter"], dict):
                anchor = element["rotationCenter"]
            elif "anchorPoint" in element and isinstance(element["anchorPoint"], dict):
                anchor = element["anchorPoint"]
            elif "anchor" in element and isinstance(element["anchor"], dict):
                anchor = element["anchor"]
            
            # Also check graphic.shape for x,y point
            if "graphic" in element and "shape" in element["graphic"]:
                shape = element["graphic"]["shape"]
                if "x" in shape and "y" in shape:
                    x_in = shape["x"]
                    y_in = shape["y"]
                    logger.debug(f"  Using graphic.shape point: ({x_in}, {y_in})")
                elif anchor and isinstance(anchor, dict):
                    x_in = anchor.get("x", 0)
                    y_in = anchor.get("y", 0)
                    logger.debug(f"  Using anchor point: ({x_in}, {y_in})")
                else:
                    x_in, y_in = 0, 0
                    logger.warning("  No valid anchor point found, using (0, 0)")
            elif anchor and isinstance(anchor, dict):
                x_in = anchor.get("x", 0)
                y_in = anchor.get("y", 0)
                logger.debug(f"  Using anchor point: ({x_in}, {y_in})")
            else:
                x_in, y_in = 0, 0
                logger.warning("  No valid anchor point found, using (0, 0)")
            
            # Try to get width/height from various sources
            w_in = None
            h_in = None
            
            # Check graphic.symbol for size
            if "graphic" in element:
                symbol = element["graphic"].get("symbol", {}).get("symbol", {})
                if "height" in symbol:
                    h_in = symbol["height"] / 72.0  # Points to inches
                    # For text, estimate width based on text length
                    text = element.get("text") or element["graphic"].get("text", "")
                    if text:
                        # Clean dynamic tags before measuring
                        if "<dyn" in text.lower():
                            text = text.split("<")[0].strip()
                        # Rough estimate: 0.6 * height per character
                        char_width = h_in * 0.6
                        w_in = max(len(text) * char_width, h_in)  # At least as wide as tall
                        logger.debug(f"  Estimated text box: {w_in:.2f}\" x {h_in:.2f}\" for '{text[:20]}{'...' if len(text) > 20 else ''}' ({len(text)} chars)")
                    else:
                        w_in = h_in  # Square if no text
            
            # Default sizes if nothing found
            if w_in is None or h_in is None:
                el_type = element.get("type", "")
                if "Text" in el_type or "Graphic" in el_type:
                    w_in, h_in = 3.0, 0.5  # Wide and short for text
                elif "North" in el_type or "Arrow" in el_type:
                    w_in, h_in = 0.5, 0.5  # Small square for north arrow
                elif "Scale" in el_type:
                    w_in, h_in = 2.0, 0.3  # Wide and short for scalebar
                else:
                    w_in, h_in = 2.0, 1.0  # Default
                logger.debug(f"  Using default size for {el_type}: {w_in}\" x {h_in}\"")
            
            x_min, y_min = x_in, y_in
            x_max, y_max = x_in + w_in, y_in + h_in

        # Convert inches to millimeters
        x_mm = x_min * 25.4
        y_coord_mm = y_min * 25.4  # Raw Y coordinate
        w_mm = (x_max - x_min) * 25.4
        h_mm = (y_max - y_min) * 25.4

        logger.debug(f"  Raw coordinates: x={x_mm:.1f}mm, y={y_coord_mm:.1f}mm, w={w_mm:.1f}mm, h={h_mm:.1f}mm")

        # Handle anchor positioning ONLY if we used an anchor point (not a bounding box)
        if not found_box and "anchor" in element and isinstance(element["anchor"], str):
            anchor_type = element["anchor"]
            logger.debug(f"  Adjusting for anchor type: {anchor_type}")
            
            # Adjust based on anchor type to get top-left corner
            if "Center" in anchor_type:
                x_mm = x_mm - (w_mm / 2)
                y_coord_mm = y_coord_mm - (h_mm / 2)
            elif "BottomLeft" in anchor_type or anchor_type == "BottomLeftCorner":
                # Anchor at bottom-left, top-left is same X, Y plus height
                y_coord_mm = y_coord_mm + h_mm
            elif "BottomRight" in anchor_type:
                x_mm = x_mm - w_mm
                y_coord_mm = y_coord_mm + h_mm
            elif "TopRight" in anchor_type:
                x_mm = x_mm - w_mm
            # TopLeft is default (no adjustment needed)
            
            logger.debug(f"  After anchor adjustment: x={x_mm:.1f}mm, y={y_coord_mm:.1f}mm")
        else:
            logger.debug(f"  Using bounding box directly (no anchor adjustment)")

        # TRY BOTH: Maybe ArcGIS Y is from TOP not BOTTOM?
        # Calculate both possibilities
        y_from_top_mm = y_coord_mm
        y_from_bottom_mm = self.page_height_mm - (y_coord_mm + h_mm)
        
        logger.debug(f"  TESTING TWO SCENARIOS:")
        logger.debug(f"    IF Y is from TOP: y={y_from_top_mm:.1f}mm")
        logger.debug(f"    IF Y is from BOTTOM: y={y_from_bottom_mm:.1f}mm")
        
        # For now, assume Y is from BOTTOM (standard ArcGIS)
        y_top_mm = self.page_height_mm - (y_coord_mm + h_mm)
        
        logger.debug(f"  USING: y from bottom → top edge at {y_top_mm:.1f}mm from top")
        logger.debug(f"  Final geometry (mm): x={x_mm:.1f}, y={y_top_mm:.1f}, w={w_mm:.1f}, h={h_mm:.1f}")
        
        # Sanity checks
        if w_mm <= 0 or h_mm <= 0:
            logger.warning(f"  Invalid dimensions! w={w_mm:.1f}, h={h_mm:.1f} - Setting minimum size.")
            w_mm = max(w_mm, 10)
            h_mm = max(h_mm, 10)
        
        if x_mm < 0 or y_top_mm < 0:
            logger.warning(f"  Negative position detected: x={x_mm:.1f}, y={y_top_mm:.1f}")
        
        if y_top_mm + h_mm > self.page_height_mm + 1:  # Allow 1mm tolerance
            logger.warning(f"  Element extends below page: y_top={y_top_mm:.1f} + h={h_mm:.1f} = {y_top_mm + h_mm:.1f} > {self.page_height_mm:.1f}mm")
        
        if x_mm + w_mm > self.page_width_mm + 1:  # Allow 1mm tolerance
            logger.warning(f"  Element extends past right edge: x={x_mm:.1f} + w={w_mm:.1f} = {x_mm + w_mm:.1f} > {self.page_width_mm:.1f}mm")
        
        return x_mm, y_top_mm, w_mm, h_mm

    def _dispatch_element(self, layout, element):
        etype = element.get("type")
        
        # Map frame
        if etype == "CIMMapFrame":
            self._create_map_frame(layout, element)
        
        # Text elements - check multiple patterns
        elif etype in ["CIMTextGraphic", "CIMParagraphTextGraphic"]:
            self._create_label(layout, element)
        elif etype == "CIMGraphicElement":
            # CIMGraphicElement can contain text or other graphics
            graphic = element.get("graphic", {})
            gtype = graphic.get("type")
            if gtype in ["CIMTextGraphic", "CIMParagraphTextGraphic"]:
                self._create_label(layout, element)
            else:
                logger.debug(f"  Skipping CIMGraphicElement with graphic type: {gtype}")
        
        # Map surrounds
        elif etype == "CIMScaleLine" or etype == "CIMScaleBar":
            self._create_scalebar(layout, element)
        elif etype == "CIMMarkerNorthArrow" or etype == "CIMNorthArrow":
            self._create_north_arrow(layout, element)
        elif etype == "CIMLegend":
            logger.info(f"  Legend element found but not yet implemented")
        else:
            logger.debug(f"  Unhandled element type: {etype}")

    def _create_map_frame(self, layout, element):
        x, y, w, h = self._get_geometry_mm(element)
        
        logger.info(f"  Creating map frame at: x={x:.1f}mm, y={y:.1f}mm, w={w:.1f}mm, h={h:.1f}mm")
        
        map_item = QgsLayoutItemMap(layout)
        
        # Try using attemptMove and attemptResize instead of setRect
        map_item.attemptMove(QgsLayoutPoint(x, y, QgsUnitTypes.LayoutMillimeters))
        map_item.attemptResize(QgsLayoutSize(w, h, QgsUnitTypes.LayoutMillimeters))
        
        map_item.setFrameEnabled(True)
        
        layers = list(self.project.mapLayers().values())
        if layers:
            map_item.setLayers(layers)
            
            # Set extent to show all layers
            extent = layers[0].extent()
            for l in layers[1:]:
                extent.combineExtentWith(l.extent())
            map_item.setExtent(extent)
            logger.info(f"  Map extent set to: {extent.toString()}")
        else:
            logger.warning("  No layers loaded - map frame will be empty")
            
        layout.addLayoutItem(map_item)
        self.map_item = map_item

    def _create_label(self, layout, element):
        x, y, w, h = self._get_geometry_mm(element)
        
        # Extract text from multiple possible locations
        text_str = element.get("text", "")
        if not text_str:
            graphic = element.get("graphic", {})
            text_str = graphic.get("text", "")
        
        if not text_str:
            text_str = "Text"
            logger.warning("  No text found in element, using default")
        
        # Clean dynamic tags
        if "<dyn" in text_str.lower():
            text_str = text_str.split("<")[0].strip()
            logger.debug(f"  Cleaned dynamic tag from text")
        
        logger.info(f"  Text content: '{text_str[:50]}{'...' if len(text_str) > 50 else ''}'")
        logger.info(f"  Creating label at: x={x:.1f}mm, y={y:.1f}mm, w={w:.1f}mm, h={h:.1f}mm")
        
        label = QgsLayoutItemLabel(layout)
        label.setText(text_str)
        
        # Extract formatting
        graphic = element.get("graphic", {})
        symbol_ref = graphic.get("symbol", {})
        symbol_obj = symbol_ref.get("symbol", {})
        
        # Horizontal alignment
        align_str = symbol_obj.get("horizontalAlignment", "Left")
        if align_str == "Center":
            label.setHAlign(Qt.AlignHCenter)
        elif align_str == "Right":
            label.setHAlign(Qt.AlignRight)
        else:
            label.setHAlign(Qt.AlignLeft)
        logger.debug(f"  Alignment: {align_str}")
        
        # Vertical alignment
        v_align_str = symbol_obj.get("verticalAlignment", "Top")
        if v_align_str == "Center":
            label.setVAlign(Qt.AlignVCenter)
        elif v_align_str == "Bottom":
            label.setVAlign(Qt.AlignBottom)
        else:
            label.setVAlign(Qt.AlignTop)
        
        # Font
        font_size = symbol_obj.get("height", 10.0)
        font_family = symbol_obj.get("fontFamilyName", "Arial")
        font_style = symbol_obj.get("fontStyleName", "Regular")
        
        f = QFont(font_family)
        f.setPointSizeF(font_size)
        
        # Handle font styles
        if "Bold" in font_style:
            f.setBold(True)
        if "Italic" in font_style:
            f.setItalic(True)
        
        label.setFont(f)
        logger.debug(f"  Font: {font_family} {font_size}pt {font_style}")
        
        # Color
        if "color" in symbol_obj:
            color_data = symbol_obj["color"]
            if "values" in color_data and len(color_data["values"]) >= 3:
                r, g, b = color_data["values"][:3]
                a = color_data["values"][3] if len(color_data["values"]) > 3 else 255
                qcolor = QColor(int(r), int(g), int(b), int(a))
                label.setFontColor(qcolor)
                logger.debug(f"  Color: RGB({r}, {g}, {b})")
        
        # Set geometry using attemptMove and attemptResize
        label.attemptMove(QgsLayoutPoint(x, y, QgsUnitTypes.LayoutMillimeters))
        label.attemptResize(QgsLayoutSize(w, h, QgsUnitTypes.LayoutMillimeters))
        
        layout.addLayoutItem(label)

    def _create_scalebar(self, layout, element):
        if not self.map_item:
            logger.warning("  Cannot create scalebar without map frame")
            return
            
        x, y, w, h = self._get_geometry_mm(element)
        
        sb = QgsLayoutItemScaleBar(layout)
        sb.setLinkedMap(self.map_item)
        
        # Style
        style_name = element.get("style", "Single Box")
        sb.setStyle("Single Box")  # Default, can map other styles
        
        # Units
        u_lbl = element.get("unitLabel", "").lower()
        if "kilometer" in u_lbl or "km" in u_lbl:
            sb.setUnitLabel("km")
            sb.setMapUnitsPerScaleBarUnit(1000)
            logger.debug("  Units: kilometers")
        elif "mile" in u_lbl or "mi" in u_lbl:
            sb.setUnitLabel("mi")
            sb.setMapUnitsPerScaleBarUnit(1609.34)
            logger.debug("  Units: miles")
        elif "meter" in u_lbl or "m" == u_lbl:
            sb.setUnitLabel("m")
            sb.setMapUnitsPerScaleBarUnit(1)
            logger.debug("  Units: meters")
        elif "feet" in u_lbl or "ft" in u_lbl:
            sb.setUnitLabel("ft")
            sb.setMapUnitsPerScaleBarUnit(0.3048)
            logger.debug("  Units: feet")
        else:
            logger.debug(f"  Unknown unit: {u_lbl}, using default")
        
        # Divisions
        divisions = element.get("divisions", 2)
        sb.setNumberOfSegments(divisions)
        
        # Sizing
        sb.applyDefaultSize()
        point = QgsLayoutPoint(x, y, QgsUnitTypes.LayoutMillimeters)
        sb.attemptMove(point)
        
        # Try to set width if provided
        if w > 0:
            sb.setMaximumBarWidth(w)
        
        layout.addLayoutItem(sb)

    def _create_north_arrow(self, layout, element):
        x, y, w, h = self._get_geometry_mm(element)
        
        # Use default QGIS north arrow
        svg_path = ":/images/north_arrows/layout_default_north_arrow.svg"
        arrow = QgsLayoutItemPicture(layout)
        arrow.setPicturePath(svg_path)
        
        # North arrows from frame.rings are often too large - constrain them
        max_size = 50  # Maximum 50mm
        if w > max_size or h > max_size:
            # Maintain aspect ratio
            if w > h:
                h = (h / w) * max_size
                w = max_size
            else:
                w = (w / h) * max_size
                h = max_size
            logger.info(f"  Constrained oversized north arrow to {w:.1f}mm x {h:.1f}mm")
        
        logger.info(f"  Creating north arrow at: x={x:.1f}mm, y={y:.1f}mm, w={w:.1f}mm, h={h:.1f}mm")
        
        arrow.attemptMove(QgsLayoutPoint(x, y, QgsUnitTypes.LayoutMillimeters))
        arrow.attemptResize(QgsLayoutSize(w, h, QgsUnitTypes.LayoutMillimeters))
        
        # Try to maintain aspect ratio
        arrow.setResizeMode(QgsLayoutItemPicture.Zoom)
        
        layout.addLayoutItem(arrow)

    def _find_layout_def(self, root):
        """Find layout definition in various possible locations"""
        # Direct properties
        if "layoutDefinition" in root:
            return root["layoutDefinition"]
        if "layout" in root:
            return root["layout"]
        if "elements" in root:
            return root
        
        # Search in definitions array
        if "definitions" in root:
            for d in root["definitions"]:
                if d.get("type") == "CIMLayout":
                    return d
        
        # Search in binaryReferences
        if "binaryReferences" in root:
            for ref in root["binaryReferences"]:
                if ref.get("type") == "CIMLayout":
                    return ref
        
        logger.error("Could not find layout definition in JSON structure")
        logger.info(f"Available root keys: {list(root.keys())}")
        return None

if __name__ == "__main__":
    qgs = QgsApplication([], False)
    qgs.initQgis()
    project = QgsProject.instance()

    try:
        print("="*60)
        print("ARCGIS TO QGIS LAYOUT CONVERTER")
        print("="*60)
        print(f"Input:  {INPUT_PAGX}")
        print(f"Layers: {QLR_SOURCE_FOLDER}")
        print(f"Output: {OUTPUT_PROJECT}")
        print("="*60)
        
        builder = LayoutBuilder(INPUT_PAGX, QLR_SOURCE_FOLDER, project)
        builder.run()
        
        print(f"\nSaving Project to: {OUTPUT_PROJECT}")
        project.write(OUTPUT_PROJECT)
        print("\n" + "="*60)
        print("✓ CONVERSION COMPLETE")
        print("="*60)
        
    except Exception as e:
        print(f"\n{'='*60}")
        print("✗ CRITICAL ERROR")
        print("="*60)
        print(f"{e}")
        import traceback
        traceback.print_exc()
    finally:
        qgs.exitQgis()