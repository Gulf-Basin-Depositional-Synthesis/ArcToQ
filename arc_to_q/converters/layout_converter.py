"""
Enhanced ArcGIS Layout Converter (.pagx to .qgz)
Fixed Y-axis calculation, scale bar units, and text box sizing

& "C:\Program Files\QGIS 3.40.10\bin\python-qgis-ltr.bat" .\arc_to_q\converters\layout_converter.py
"""
import sys
import os
import json
import logging
import re

# 1. SETUP PATHS
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
    QgsLayoutSize, QgsUnitTypes, QgsLayerDefinition, QgsLayoutPoint,
    QgsScaleBarSettings, QgsCoordinateReferenceSystem
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor, QFont

logging.basicConfig(level=logging.DEBUG, format='%(levelname)s: %(message)s')
logger = logging.getLogger("LayoutBuilder")

class LayoutBuilder:
    def __init__(self, pagx_path, qlr_folder, project):
        self.pagx_path = pagx_path
        self.qlr_folder = qlr_folder
        self.project = project
        
        # Page dimensions will be set from the PAGX file
        self.page_height_mm = 279.4  # Default letter size
        self.page_width_mm = 215.9
        self.page_height_inches = 11.0
        self.page_width_inches = 8.5
        
        # Map frame tracking
        self.map_items = {}  # Map frame name -> QgsLayoutItemMap
        self.default_map_frame = None

    def run(self):
        if not os.path.exists(self.pagx_path):
            logger.error(f"Input file not found: {self.pagx_path}")
            return

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

        # Setup Page (must happen before processing elements)
        page_def = layout_def.get("page") or root.get("page", {})
        self._setup_page(layout, page_def)

        # Process Elements
        elements = layout_def.get("elements", [])
        
        # Sort: Map Frame first so it exists before Scale Bars/Text reference it
        elements.sort(key=lambda x: (0 if x.get("type") == "CIMMapFrame" else 1, x.get("type", "")))

        for idx, el in enumerate(elements):
            try:
                logger.info(f"\n--- Processing Element {idx}: {el.get('type')} '{el.get('name')}' ---")
                
                # DEBUG: Print full element for problematic items
                if el.get('name') in ['Text 1', 'Map Frame']:
                    logger.debug(f"Full element data:\n{json.dumps(el, indent=2)}")
                
                self._dispatch_element(layout, el)
            except Exception as e:
                logger.error(f"Failed to create element {idx} ({el.get('type')}): {e}")
                import traceback
                traceback.print_exc()

        self.project.layoutManager().addLayout(layout)
        logger.info(f"\nLayout built successfully with {len(elements)} elements.")

    def _load_layers_from_def(self, root):
        """Loads layers referenced in the layout from QLR files."""
        layer_defs = root.get("layerDefinitions", [])
        for ldef in layer_defs:
            if not ldef.get("visibility", True): 
                continue 
            name = ldef.get("name")
            
            # Sanitize name
            safe_name = "".join([c for c in name if c.isalnum() or c in (' ', '.', '_', '-')]).strip()
            
            # Try exact match, then sanitized
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

    def _setup_page(self, layout, page_def):
        """
        Setup page size from PAGX definition.
        ArcGIS stores page dimensions in various units.
        WKID 109008 = Inch_US
        """
        w = page_def.get("width", 8.5)
        h = page_def.get("height", 11)
        units = page_def.get("units", "INCH")
        
        logger.info(f"Raw page definition: width={w}, height={h}, units={units}")
        
        # Handle WKID-based unit definitions
        if isinstance(units, dict):
            wkid = units.get("wkid") or units.get("uwkid")
            if wkid == 109008:
                logger.info("Detected WKID 109008 (Inch_US)")
                units = "INCH"
            else:
                logger.warning(f"Unknown WKID {wkid}, assuming inches")
                units = "INCH"
        
        # Store page dimensions in both inches and mm for calculations
        if units == "INCH" or units == "INCHES":
            self.page_width_inches = w
            self.page_height_inches = h
            self.page_width_mm = w * 25.4
            self.page_height_mm = h * 25.4
        elif units == "MILLIMETER":
            self.page_width_mm = w
            self.page_height_mm = h
            self.page_width_inches = w / 25.4
            self.page_height_inches = h / 25.4
        elif units == "CENTIMETER":
            self.page_width_mm = w * 10
            self.page_height_mm = h * 10
            self.page_width_inches = (w * 10) / 25.4
            self.page_height_inches = (h * 10) / 25.4
        elif units == "POINT":
            # 72 points = 1 inch
            self.page_width_inches = w / 72.0
            self.page_height_inches = h / 72.0
            self.page_width_mm = self.page_width_inches * 25.4
            self.page_height_mm = self.page_height_inches * 25.4
        else:
            # Fallback: assume inches
            logger.warning(f"Unknown page units '{units}', assuming inches")
            self.page_width_inches = w
            self.page_height_inches = h
            self.page_width_mm = w * 25.4
            self.page_height_mm = h * 25.4
            
        layout.pageCollection().page(0).setPageSize(
            QgsLayoutSize(self.page_width_mm, self.page_height_mm, QgsUnitTypes.LayoutMillimeters)
        )
        logger.info(f"Page size: {self.page_width_inches}\" x {self.page_height_inches}\" ({self.page_width_mm:.2f} x {self.page_height_mm:.2f} mm)")

    def _get_geometry_mm(self, element):
        """
        Calculates QGIS layout coordinates (Top-Left origin, mm) from ArcGIS definition.
        
        ArcGIS coordinate system:
        - Origin: Bottom-Left
        - Units: Inches (for WKID 109008)
        - Y increases upward
        
        QGIS coordinate system:
        - Origin: Top-Left
        - Units: Millimeters
        - Y increases downward
        """
        # Default bounding box in inches
        cim_x_min, cim_y_min, cim_x_max, cim_y_max = 0, 0, 1, 1
        found_box = False
        source = "unknown"

        # Strategy A: Frame Rings (Polygons) - Most accurate for Frames/Rectangles
        if "frame" in element and "rings" in element["frame"]:
            rings = element["frame"]["rings"]
            if rings:
                xs = [pt[0] for ring in rings for pt in ring]
                ys = [pt[1] for ring in rings for pt in ring]
                if xs and ys:
                    cim_x_min, cim_x_max = min(xs), max(xs)
                    cim_y_min, cim_y_max = min(ys), max(ys)
                    found_box = True
                    source = "frame rings"

        # Strategy B: Graphic Shape Rings (Polygons) - for Text Boxes with borders
        if not found_box and "graphic" in element:
            graphic = element["graphic"]
            if "shape" in graphic and "rings" in graphic["shape"]:
                rings = graphic["shape"]["rings"]
                if rings:
                    xs = [pt[0] for ring in rings for pt in ring]
                    ys = [pt[1] for ring in rings for pt in ring]
                    if xs and ys:
                        cim_x_min, cim_x_max = min(xs), max(xs)
                        cim_y_min, cim_y_max = min(ys), max(ys)
                        found_box = True
                        source = "graphic shape rings"

        # Strategy C: Anchor Point + Estimated Dimensions (Fallback)
        if not found_box:
            # 1. Find Anchor Point (Insertion Point)
            pt_x, pt_y = 0.0, 0.0
            if "graphic" in element and "shape" in element["graphic"]:
                shape = element["graphic"]["shape"]
                pt_x, pt_y = shape.get("x", 0.0), shape.get("y", 0.0)
            elif "anchor" in element and isinstance(element.get("anchor"), dict):
                pt_x = element["anchor"].get("x", 0.0)
                pt_y = element["anchor"].get("y", 0.0)
            elif "rotationCenter" in element and isinstance(element.get("rotationCenter"), dict):
                pt_x = element["rotationCenter"].get("x", 0.0)
                pt_y = element["rotationCenter"].get("y", 0.0)

            # 2. Estimate Size (in inches)
            w_in, h_in = 2.0, 1.0  # Fallback
            el_type = element.get("type", "")
            
            if "Scale" in el_type: 
                w_in, h_in = 6.0, 0.5  # Scale bars are typically wide and short
            elif "North" in el_type: 
                w_in, h_in = 1.0, 2.0
            
            # Text size estimation based on font height and char count
            if "graphic" in element:
                symbol = element.get("graphic", {}).get("symbol", {}).get("symbol", {})
                # Font height is in points
                h_points = symbol.get("height", 10)
                h_in = h_points / 72.0  # Base height without multiplier
                    
                text = element.get("text") or element.get("graphic", {}).get("text", "")
                if text:
                    # Remove HTML tags and count lines
                    clean_text = re.sub(r'<[^>]+>', '', text)
                    lines = clean_text.strip().split('\n')
                    line_count = len([l for l in lines if l.strip()])  # Count non-empty lines
                    
                    # Height: font size * line count + spacing
                    h_in = (h_points / 72.0) * line_count * 1.2  # 1.2 for line spacing
                    
                    # Estimate width based on longest line
                    max_line_len = max(len(line.strip()) for line in lines) if lines else len(clean_text)
                    # Approximate character width as 0.6 * height for proportional fonts
                    char_width = (h_points / 72.0) * 0.55  # Slightly narrower estimate
                    w_in = max_line_len * char_width
                    
                    logger.debug(f"Text: '{clean_text[:40]}...', lines={line_count}, font={h_points:.1f}pt")
                    logger.debug(f"  Estimated size: {w_in:.3f}\" x {h_in:.3f}\" (char_width={char_width:.4f}\")")
                else: 
                    w_in = h_in = h_points / 72.0

            # 3. Apply Anchor Logic
            # Get anchor - can be string or dict with "location" key
            anchor = element.get("anchor", "TopLeft")
            if isinstance(anchor, dict): 
                anchor = anchor.get("location", "TopLeft")
            
            logger.debug(f"Anchor point: ({pt_x:.4f}, {pt_y:.4f}), anchor type: {anchor}, estimated size: {w_in:.3f}\" x {h_in:.3f}\"")
            
            # ArcGIS anchor meanings (with bottom-left origin):
            # The anchor point is where the element is "attached" to the page
            # For text, this is typically the insertion point
            
            if "Center" in anchor:
                # Anchor is at center of element
                cim_x_min, cim_y_min = pt_x - w_in/2, pt_y - h_in/2
                cim_x_max, cim_y_max = pt_x + w_in/2, pt_y + h_in/2
            elif "BottomRight" in anchor:
                # Anchor is at bottom-right corner
                cim_x_min, cim_y_min = pt_x - w_in, pt_y
                cim_x_max, cim_y_max = pt_x, pt_y + h_in
            elif "TopRight" in anchor:
                # Anchor is at top-right corner
                cim_x_min, cim_y_min = pt_x - w_in, pt_y - h_in
                cim_x_max, cim_y_max = pt_x, pt_y
            elif "TopLeft" in anchor or "TopLeftCorner" in anchor:
                # Anchor is at top-left corner
                cim_x_min, cim_y_min = pt_x, pt_y - h_in
                cim_x_max, cim_y_max = pt_x + w_in, pt_y
            elif "BottomCenter" in anchor:
                # Anchor is at bottom center
                cim_x_min, cim_y_min = pt_x - w_in/2, pt_y
                cim_x_max, cim_y_max = pt_x + w_in/2, pt_y + h_in
            elif "TopCenter" in anchor:
                # Anchor is at top center
                cim_x_min, cim_y_min = pt_x - w_in/2, pt_y - h_in
                cim_x_max, cim_y_max = pt_x + w_in/2, pt_y
            else:  # BottomLeft, BottomLeftCorner, or unknown
                # Anchor is at bottom-left corner - this is the default for text
                cim_x_min, cim_y_min = pt_x, pt_y
                cim_x_max, cim_y_max = pt_x + w_in, pt_y + h_in
            
            source = "anchor estimation"

        logger.debug(f"Geometry source: {source}")
        logger.debug(f"ArcGIS coords (inches, bottom-left origin): x=[{cim_x_min:.4f}, {cim_x_max:.4f}], y=[{cim_y_min:.4f}, {cim_y_max:.4f}]")

        # Calculate width and height in millimeters
        w_mm = (cim_x_max - cim_x_min) * 25.4
        h_mm = (cim_y_max - cim_y_min) * 25.4
        
        # X coordinate: direct conversion (both use left edge)
        x_mm = cim_x_min * 25.4
        
        # Y coordinate: CRITICAL FIX
        # ArcGIS: y=0 at BOTTOM, y increases UPWARD
        # QGIS: y=0 at TOP, y increases DOWNWARD
        # 
        # For the BOTTOM edge of element in ArcGIS: cim_y_min inches from bottom
        # In QGIS, this same edge should be: (page_height - cim_y_min) inches from top
        # But we want the TOP edge in QGIS, so we need: (page_height - cim_y_max) inches from top
        y_from_top_inches = self.page_height_inches - cim_y_max
        y_mm = y_from_top_inches * 25.4

        logger.debug(f"QGIS coords (mm, top-left origin): x={x_mm:.2f}, y={y_mm:.2f}, w={w_mm:.2f}, h={h_mm:.2f}")
        
        return x_mm, y_mm, w_mm, h_mm

    def _dispatch_element(self, layout, element):
        etype = element.get("type")
        if etype == "CIMMapFrame":
            self._create_map_frame(layout, element)
        elif etype in ["CIMTextGraphic", "CIMParagraphTextGraphic"]:
            self._create_label(layout, element)
        elif etype == "CIMGraphicElement":
            gtype = element.get("graphic", {}).get("type")
            if gtype in ["CIMTextGraphic", "CIMParagraphTextGraphic"]:
                self._create_label(layout, element)
        elif etype in ["CIMScaleLine", "CIMScaleBar"]:
            self._create_scalebar(layout, element)
        elif etype in ["CIMMarkerNorthArrow", "CIMNorthArrow"]:
            self._create_north_arrow(layout, element)

    def _create_map_frame(self, layout, element):
        x, y, w, h = self._get_geometry_mm(element)
        map_item = QgsLayoutItemMap(layout)
        map_item.attemptMove(QgsLayoutPoint(x, y, QgsUnitTypes.LayoutMillimeters))
        map_item.attemptResize(QgsLayoutSize(w, h, QgsUnitTypes.LayoutMillimeters))
        map_item.setFrameEnabled(True)
        
        # Set ID from element name
        map_name = element.get("name", "Map Frame")
        map_item.setId(map_name)
        self.map_items[map_name] = map_item
        
        # Set as default if it's the first one
        if self.default_map_frame is None:
            self.default_map_frame = map_item
        
        layers = list(self.project.mapLayers().values())
        if layers:
            map_item.setLayers(layers)
            
            # CRITICAL: Get the CRS from the view definition in ArcGIS
            # ArcGIS stores the actual map CRS, not just using layer CRS
            target_crs = None
            
            # Try to get CRS from map view camera coordinates
            if "view" in element and "camera" in element["view"]:
                camera = element["view"]["camera"]
                x_coord = camera.get("x")
                y_coord = camera.get("y")
                viewport_width = camera.get("viewportWidth")
                viewport_height = camera.get("viewportHeight")
                
                # If coordinates are in degrees range (-180 to 180, -90 to 90), likely geographic
                if x_coord and y_coord:
                    if -180 <= x_coord <= 180 and -90 <= y_coord <= 90:
                        logger.info(f"Camera coordinates suggest Geographic CRS: ({x_coord:.2f}, {y_coord:.2f})")
                        target_crs = QgsCoordinateReferenceSystem("EPSG:4326")  # WGS84
                        
                        # CRITICAL FIX: viewportWidth/Height are in METERS (ground distance)
                        # For geographic CRS, we need to convert to degrees
                        # At the equator, 1 degree ≈ 111,320 meters
                        # Use actual latitude for more accurate conversion
                        if viewport_width and viewport_height:
                            import math
                            # Meters per degree longitude varies with latitude
                            lat_rad = math.radians(abs(y_coord))
                            meters_per_deg_lon = 111320 * math.cos(lat_rad)
                            meters_per_deg_lat = 111320  # Roughly constant
                            
                            # Convert viewport from meters to degrees
                            viewport_width_deg = viewport_width / meters_per_deg_lon
                            viewport_height_deg = viewport_height / meters_per_deg_lat
                            
                            logger.info(f"Viewport: {viewport_width:.0f}m x {viewport_height:.0f}m")
                            logger.info(f"Converted to: {viewport_width_deg:.4f}° x {viewport_height_deg:.4f}°")
                            
                            # Create extent in degrees
                            from qgis.core import QgsRectangle
                            half_width = viewport_width_deg / 2
                            half_height = viewport_height_deg / 2
                            
                            extent = QgsRectangle(
                                x_coord - half_width,
                                y_coord - half_height,
                                x_coord + half_width,
                                y_coord + half_height
                            )
                            map_item.setExtent(extent)
                            logger.info(f"Map extent: {extent.toString()}")
                    else:
                        logger.info(f"Camera coordinates suggest Projected CRS: ({x_coord:.2f}, {y_coord:.2f})")
                        # For projected coordinates, viewport is already in correct units
                        if viewport_width and viewport_height:
                            from qgis.core import QgsRectangle
                            half_width = viewport_width / 2
                            half_height = viewport_height / 2
                            
                            extent = QgsRectangle(
                                x_coord - half_width,
                                y_coord - half_height,
                                x_coord + half_width,
                                y_coord + half_height
                            )
                            map_item.setExtent(extent)
            
            # Fallback to first layer CRS if we couldn't determine from camera
            if not target_crs or not target_crs.isValid():
                target_crs = layers[0].crs()
                logger.warning(f"Using layer CRS as fallback: {target_crs.authid()}")
            
            if target_crs.isValid():
                self.project.setCrs(target_crs)
                map_item.setCrs(target_crs)
                logger.info(f"Map CRS set to: {target_crs.authid()} ({target_crs.description()})")
            
            # Try to get scale from element
            scale = None
            if "view" in element and "camera" in element["view"]:
                scale = element["view"]["camera"].get("scale")
            elif "autoCamera" in element:
                scale = element["autoCamera"].get("scale")
            
            if scale:
                map_item.setScale(scale)
                logger.info(f"Map scale: 1:{scale:,.0f}")
        
        layout.addLayoutItem(map_item)
        logger.info(f"✓ Map frame created: '{map_name}'")
        logger.info(f"  Position: ({x:.1f}, {y:.1f}) mm, Size: ({w:.1f} x {h:.1f}) mm")

    def _translate_dynamic_text(self, text, map_item_name="Map Frame"):
        """
        Translates ArcGIS <dyn> tags to QGIS expressions.
        Handles coordinate formatting (DMS) and scale formatting.
        """
        if not text: 
            return ""
        
        # Remove any existing static labels that will be replaced by dynamic text
        # e.g., "Upper Left: <dyn ...>" becomes just the dynamic part
        text = re.sub(r'Upper Left:\s*', '', text, flags=re.IGNORECASE)
        text = re.sub(r'Lower Right:\s*', '', text, flags=re.IGNORECASE)
        text = re.sub(r'Scale:\s*', '', text, flags=re.IGNORECASE)
        
        def replacer(match):
            content = match.group(1)
            # Robust attribute extraction
            attrs = dict(re.findall(r'(\w+)="([^"]*)"', content))
            
            dtype = attrs.get("type", "").lower()
            prop = attrs.get("property", "").lower()
            
            if "mapframe" in dtype:
                if "scale" in prop:
                    # Number format: 1:20,000
                    return f"Scale: [% '1:' || format_number(map_get(item_variables('{map_item_name}'), 'map_scale'), 0) %]"
                
                if "upperleft" in prop or "upper_left" in prop:
                    # DMS Coordinates for upper left corner
                    return (
                        f"Upper Left:\n"
                        f"[% to_dms(map_get(item_variables('{map_item_name}'), 'map_extent_xmin'), 'x', 0) %]\n"
                        f"[% to_dms(map_get(item_variables('{map_item_name}'), 'map_extent_ymax'), 'y', 0) %]"
                    )
                
                if "lowerright" in prop or "lower_right" in prop:
                    # DMS Coordinates for lower right corner
                    return (
                        f"Lower Right:\n"
                        f"[% to_dms(map_get(item_variables('{map_item_name}'), 'map_extent_xmax'), 'x', 0) %]\n"
                        f"[% to_dms(map_get(item_variables('{map_item_name}'), 'map_extent_ymin'), 'y', 0) %]"
                    )

            if "date" in dtype:
                fmt = attrs.get("format", "yyyy-MM-dd")
                return f"[% format_date(now(), '{fmt}') %]"
            
            if "pagename" in dtype: 
                return "[% @layout_name %]"
            
            return f"[Dynamic: {dtype}]"

        # Regex allows for multi-line tags or loose spacing
        return re.sub(r'<dyn\s+(.*?)(?:/>|>\s*</dyn>)', replacer, text, flags=re.IGNORECASE | re.DOTALL)

    def _create_label(self, layout, element):
        x, y, w, h = self._get_geometry_mm(element)
        
        raw_text = element.get("text") or element.get("graphic", {}).get("text", "Text")
        logger.debug(f"Raw text before translation: '{raw_text}'")
        
        # Get associated map frame name if available
        map_frame_ref = element.get("mapFrame", self.default_map_frame.id() if self.default_map_frame else "Map Frame")
        text = self._translate_dynamic_text(raw_text, map_frame_ref)
        
        logger.debug(f"Translated text: '{text[:100]}...'")
        
        label = QgsLayoutItemLabel(layout)
        label.setText(text)
        
        symbol = element.get("graphic", {}).get("symbol", {}).get("symbol", {})
        font_size = symbol.get("height", 10)
        font_family = symbol.get("fontFamilyName", "Arial")
        
        font = QFont(font_family)
        font.setPointSizeF(font_size)
        
        style_name = symbol.get("fontStyleName", "").lower()
        if "bold" in style_name: 
            font.setBold(True)
        if "italic" in style_name: 
            font.setItalic(True)
        
        # Use textFormat() instead of deprecated setFont()
        text_format = label.textFormat()
        text_format.setFont(font)
        text_format.setSize(font_size)
        
        if "color" in symbol:
            vals = symbol["color"].get("values", [])
            if len(vals) >= 3:
                color = QColor(int(vals[0]), int(vals[1]), int(vals[2]))
                text_format.setColor(color)
        
        label.setTextFormat(text_format)

        # Handle alignment
        h_align = symbol.get("horizontalAlignment", "Left")
        v_align = symbol.get("verticalAlignment", "Bottom")
        
        if h_align == "Center": 
            label.setHAlign(Qt.AlignHCenter)
        elif h_align == "Right": 
            label.setHAlign(Qt.AlignRight)
        else:
            label.setHAlign(Qt.AlignLeft)
        
        # For multi-line text or dynamic text, ensure adequate dimensions
        line_count = text.count('\n') + 1
        
        # If text contains dynamic expressions ([% ... %]), it may expand
        if '[%' in text:
            # Dynamic text may be longer than estimated - add extra width
            w = max(w, 50)  # Minimum 50mm for dynamic text
            
            # If it's scale text (contains "format_number" or "map_scale"), needs more width
            if 'map_scale' in text or 'format_number' in text:
                w = max(w, 80)  # Scale numbers can be long: "1:19,390,660"
        
        if line_count > 1:
            # Ensure adequate height for multi-line text
            h = max(h, line_count * font_size * 1.5 * 0.3528)  # Convert points to mm with spacing
        
        label.attemptMove(QgsLayoutPoint(x, y, QgsUnitTypes.LayoutMillimeters))
        label.attemptResize(QgsLayoutSize(w, h, QgsUnitTypes.LayoutMillimeters))
        layout.addLayoutItem(label)
        logger.info(f"✓ Label created: '{text[:50]}...' at ({x:.1f}, {y:.1f}) mm, size: ({w:.1f} x {h:.1f}) mm")
    def _extract_unit_info(self, element):
        """
        Extract unit information from scale bar element.
        Returns (unit_label, meters_per_unit, division_value)
        """
        # Get units field
        units_value = element.get("units", {})
        
        logger.debug(f"Raw units value: {units_value}")
        
        # Initialize defaults
        unit_label = "m"
        meters_per_unit = 1.0
        
        # Try to parse units
        if isinstance(units_value, str):
            units_str = units_value.lower()
        elif isinstance(units_value, dict):
            # Check for 'value' key (string)
            if "value" in units_value:
                units_str = str(units_value["value"]).lower()
            # Check for esri constants in wkid
            elif "wkid" in units_value or "uwkid" in units_value:
                wkid = units_value.get("wkid") or units_value.get("uwkid")
                # Common esri unit WKIDs
                if wkid == 9001: units_str = "meter"
                elif wkid == 9002: units_str = "foot"
                elif wkid == 9003: units_str = "foot_us"
                elif wkid == 9036: units_str = "kilometer"
                elif wkid == 9093: units_str = "mile"
                else:
                    logger.warning(f"Unknown unit WKID: {wkid}, checking unitLabel")
                    units_str = ""
            else:
                units_str = ""
        else:
            logger.warning(f"Unknown units type: {type(units_value)}")
            units_str = ""
        
        # Check unitLabel as fallback
        if not units_str or units_str == "":
            unit_label_value = element.get("unitLabel", "")
            if unit_label_value:
                units_str = unit_label_value.lower()
                logger.debug(f"Using unitLabel: {units_str}")
        
        # Parse unit string
        if "kilometer" in units_str or "km" in units_str:
            unit_label, meters_per_unit = "km", 1000.0
        elif "mile" in units_str or "mi" in units_str:
            unit_label, meters_per_unit = "mi", 1609.34
        elif "meter" in units_str or "m" in units_str:
            unit_label, meters_per_unit = "m", 1.0
        elif "foot" in units_str or "feet" in units_str or "ft" in units_str:
            unit_label, meters_per_unit = "ft", 0.3048
        else:
            logger.warning(f"Could not parse units from: '{units_str}', defaulting to meters")
            unit_label, meters_per_unit = "m", 1.0
        
        # Get division value
        division = element.get("division", 100.0)
        
        logger.info(f"Scale bar units: {unit_label} ({meters_per_unit} m/unit), division: {division}")
        
        return unit_label, meters_per_unit, division

    def _create_scalebar(self, layout, element):
        # Find associated map frame
        map_frame_name = element.get("mapFrame")
        map_item = None
        
        if map_frame_name and map_frame_name in self.map_items:
            map_item = self.map_items[map_frame_name]
        elif self.default_map_frame:
            map_item = self.default_map_frame
        
        if not map_item:
            logger.warning("No map frame available for scale bar")
            return
            
        x, y, w, h = self._get_geometry_mm(element)
        
        sb = QgsLayoutItemScaleBar(layout)
        sb.setLinkedMap(map_item)
        sb.setStyle("Single Box")
        
        # Extract units properly
        unit_label, meters_per_unit, division = self._extract_unit_info(element)
        
        # Get map CRS info
        map_units = 0  # Default to meters
        if map_item.crs().isValid():
            map_units = map_item.crs().mapUnits()
            logger.debug(f"Map CRS: {map_item.crs().authid()}, units: {map_units}")
        
        # For ALL cases (geographic or projected), set the scale bar to display in the requested units
        # The key is to set BOTH the units AND the conversion factor correctly
        
        if unit_label == "km":
            sb.setUnitLabel("km")
            if map_units == 6:  # Geographic (degrees)
                # Map is in degrees, we want to display km
                # At equator: 1 degree ≈ 111.32 km
                # This will vary with latitude, but QGIS handles this
                sb.setMapUnitsPerScaleBarUnit(111320)  # meters per degree * 1000 for km
            else:
                # Map is in meters (or other projected units)
                sb.setMapUnitsPerScaleBarUnit(1000)  # 1000 meters per km
                
        elif unit_label == "mi":
            sb.setUnitLabel("mi")
            if map_units == 6:
                sb.setMapUnitsPerScaleBarUnit(69.17 * 1609.34)  # miles per degree in meters
            else:
                sb.setMapUnitsPerScaleBarUnit(1609.34)
                
        elif unit_label == "ft":
            sb.setUnitLabel("ft")
            if map_units == 6:
                sb.setMapUnitsPerScaleBarUnit(111320 / 0.3048)  # meters per degree / meters per foot
            else:
                sb.setMapUnitsPerScaleBarUnit(0.3048)
        else:  # meters
            sb.setUnitLabel("m")
            if map_units == 6:
                sb.setMapUnitsPerScaleBarUnit(111320)  # meters per degree
            else:
                sb.setMapUnitsPerScaleBarUnit(1)
        
        logger.info(f"Scale bar: {unit_label}, map_units={map_units}, conversion set")
        
        sb.setUnitsPerSegment(division)
        sb.setSegmentSizeMode(QgsScaleBarSettings.SegmentSizeMode.Fixed)
        
        num_divisions = element.get("divisions", 2)
        sb.setNumberOfSegments(num_divisions)
        sb.setNumberOfSegmentsLeft(0)
        
        # Apply default sizing first
        sb.applyDefaultSize()
        
        # Position the scale bar
        sb.attemptMove(QgsLayoutPoint(x, y, QgsUnitTypes.LayoutMillimeters))
        
        # Use the width from ArcGIS
        final_width = max(w, 120)  # Ensure minimum width for labels
        sb.attemptResize(QgsLayoutSize(final_width, h, QgsUnitTypes.LayoutMillimeters))
        
        layout.addLayoutItem(sb)
        logger.info(f"✓ Scale bar created at ({x:.1f}, {y:.1f}) mm, size: ({final_width:.1f} x {h:.1f}) mm")

    def _create_north_arrow(self, layout, element):
        x, y, w, h = self._get_geometry_mm(element)
        
        arrow = QgsLayoutItemPicture(layout)
        arrow.setPicturePath(":/images/north_arrows/layout_default_north_arrow.svg")
        
        # Limit size to reasonable maximum
        max_dim_mm = 50
        if w > max_dim_mm or h > max_dim_mm:
            ratio = w / h if h > 0 else 1
            if w > h:
                w, h = max_dim_mm, max_dim_mm / ratio
            else:
                w, h = max_dim_mm * ratio, max_dim_mm
        
        arrow.attemptMove(QgsLayoutPoint(x, y, QgsUnitTypes.LayoutMillimeters))
        arrow.attemptResize(QgsLayoutSize(w, h, QgsUnitTypes.LayoutMillimeters))
        layout.addLayoutItem(arrow)
        logger.info(f"✓ North arrow created")

    def _find_layout_def(self, root):
        if "layoutDefinition" in root: 
            return root["layoutDefinition"]
        if "layout" in root: 
            return root["layout"]
        if "elements" in root: 
            return root
        if "definitions" in root:
            for d in root["definitions"]:
                if d.get("type") == "CIMLayout": 
                    return d
        return None

if __name__ == "__main__":
    qgs = QgsApplication([], False)
    qgs.initQgis()
    project = QgsProject.instance()

    try:
        print("="*60)
        print("ARCGIS TO QGIS LAYOUT CONVERTER")
        print("="*60)
        builder = LayoutBuilder(INPUT_PAGX, QLR_SOURCE_FOLDER, project)
        builder.run()
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