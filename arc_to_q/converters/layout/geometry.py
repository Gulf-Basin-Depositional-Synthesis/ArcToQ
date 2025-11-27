import logging
import re

logger = logging.getLogger("LayoutGeometry")

class GeometryConverter:
    """
    Handles coordinate transformation between ArcGIS (Bottom-Left origin, usually Inches)
    and QGIS (Top-Left origin, Millimeters).
    """
    
    def __init__(self, page_height_mm):
        """
        Args:
            page_height_mm (float): The total height of the page in millimeters.
                                    Required for flipping the Y-axis.
        """
        self.page_height_mm = page_height_mm

    @staticmethod
    def parse_page_size(page_def):
        """
        Parses page definition to return dimensions in MM.
        Handles various unit formats (WKIDs, strings).
        
        Returns:
            tuple: (width_mm, height_mm)
        """
        w = page_def.get("width", 8.5)
        h = page_def.get("height", 11.0)
        units = page_def.get("units", "INCH")

        # Handle WKID-based unit definitions
        if isinstance(units, dict):
            wkid = units.get("wkid") or units.get("uwkid")
            if wkid == 109008:
                units = "INCH"
            elif wkid == 9001:
                units = "METER" # Rare for page size, but possible
            else:
                logger.warning(f"Unknown WKID {wkid}, assuming inches")
                units = "INCH"
        
        units = str(units).upper()
        
        # Convert all to Millimeters
        if "INCH" in units:
            return w * 25.4, h * 25.4
        elif "MILLIMETER" in units:
            return w, h
        elif "CENTIMETER" in units:
            return w * 10, h * 10
        elif "POINT" in units:
            # 72 points = 1 inch
            return (w / 72.0) * 25.4, (h / 72.0) * 25.4
        else:
            logger.warning(f"Unknown page units '{units}', defaulting to inches conversion")
            return w * 25.4, h * 25.4

    def get_qgis_rect(self, element):
        """
        Calculates QGIS layout coordinates (Top-Left origin, mm) from ArcGIS definition.
        
        Returns:
            tuple: (x_mm, y_mm, width_mm, height_mm)
        """
        # Default bounding box in inches (ArcGIS standard internal unit)
        cim_x_min, cim_y_min, cim_x_max, cim_y_max = 0, 0, 1, 1
        found_box = False
        source = "unknown"

        # --- Strategy A: Frame Rings (Polygons) ---
        # Most accurate for Frames/Rectangles/Maps
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

        # --- Strategy B: Graphic Shape Rings (Polygons) ---
        # Useful for Text Boxes with borders
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

        # --- Strategy C: Anchor Point + Estimated Dimensions (Fallback) ---
        if not found_box:
            pt_x, pt_y = self._get_anchor_point(element)
            w_in, h_in = self._estimate_element_size(element)
            
            # Apply Anchor Logic to find bounding box relative to point
            cim_x_min, cim_y_min, cim_x_max, cim_y_max = self._apply_anchor(
                element, pt_x, pt_y, w_in, h_in
            )
            source = "anchor estimation"

        # Calculate dimensions in mm
        w_mm = (cim_x_max - cim_x_min) * 25.4
        h_mm = (cim_y_max - cim_y_min) * 25.4
        
        # X coordinate: direct conversion (both left-aligned)
        x_mm = cim_x_min * 25.4
        
        # Y coordinate: FLIP AXIS
        # ArcGIS: y=0 at BOTTOM. cim_y_max is the top edge distance from bottom.
        # QGIS: y=0 at TOP. We need distance from top to top edge.
        # y_qgis = PageHeight - y_arcgis_top
        y_mm = self.page_height_mm - (cim_y_max * 25.4)

        logger.debug(f"Geometry [{source}]: ({x_mm:.1f}, {y_mm:.1f}) mm, Size: {w_mm:.1f}x{h_mm:.1f} mm")
        return x_mm, y_mm, w_mm, h_mm

    def _get_anchor_point(self, element):
        """Extracts the insertion point (x, y) from the element."""
        pt_x, pt_y = 0.0, 0.0
        
        if "graphic" in element and "shape" in element["graphic"]:
            shape = element["graphic"]["shape"]
            pt_x = shape.get("x", 0.0)
            pt_y = shape.get("y", 0.0)
        elif "anchor" in element and isinstance(element.get("anchor"), dict):
            pt_x = element["anchor"].get("x", 0.0)
            pt_y = element["anchor"].get("y", 0.0)
        elif "rotationCenter" in element and isinstance(element.get("rotationCenter"), dict):
            pt_x = element["rotationCenter"].get("x", 0.0)
            pt_y = element["rotationCenter"].get("y", 0.0)
            
        return pt_x, pt_y

    def _estimate_element_size(self, element):
        """Estimates Width/Height in INCHES based on element type and content."""
        w_in, h_in = 2.0, 1.0  # Default fallback
        el_type = element.get("type", "")
        
        if "Scale" in el_type: 
            w_in, h_in = 6.0, 0.5
        elif "North" in el_type: 
            w_in, h_in = 1.0, 2.0
        
        # Text size estimation
        if "graphic" in element:
            symbol = element.get("graphic", {}).get("symbol", {}).get("symbol", {})
            h_points = symbol.get("height", 10)
            
            text = element.get("text") or element.get("graphic", {}).get("text", "")
            if text:
                # Remove HTML tags
                clean_text = re.sub(r'<[^>]+>', '', text)
                lines = clean_text.strip().split('\n')
                line_count = len([l for l in lines if l.strip()]) or 1
                
                # Height: font size * lines * spacing
                h_in = (h_points / 72.0) * line_count * 1.2
                
                # Width: max line length * approx char width
                max_line_len = max(len(line.strip()) for line in lines) if lines else len(clean_text)
                char_width = (h_points / 72.0) * 0.55
                w_in = max_line_len * char_width
            else:
                # Just one line height if no text found but graphic exists
                h_in = h_points / 72.0
                w_in = h_in # Square fallback
                
        return w_in, h_in

    def _apply_anchor(self, element, pt_x, pt_y, w_in, h_in):
        """Calculates bounding box (min/max x/y) based on anchor position."""
        anchor = element.get("anchor", "TopLeft")
        if isinstance(anchor, dict): 
            anchor = anchor.get("location", "TopLeft")
        
        # Calculate min/max based on where the point is relative to the box
        if "Center" in anchor and "Bottom" not in anchor and "Top" not in anchor:
            # Absolute Center
            return pt_x - w_in/2, pt_y - h_in/2, pt_x + w_in/2, pt_y + h_in/2
        elif "BottomRight" in anchor:
            return pt_x - w_in, pt_y, pt_x, pt_y + h_in
        elif "TopRight" in anchor:
            return pt_x - w_in, pt_y - h_in, pt_x, pt_y
        elif "TopLeft" in anchor or "TopLeftCorner" in anchor:
            return pt_x, pt_y - h_in, pt_x + w_in, pt_y
        elif "BottomCenter" in anchor:
            return pt_x - w_in/2, pt_y, pt_x + w_in/2, pt_y + h_in
        elif "TopCenter" in anchor:
            return pt_x - w_in/2, pt_y - h_in, pt_x + w_in/2, pt_y
        else:  
            # Default: BottomLeft (Standard Cartesian Origin)
            return pt_x, pt_y, pt_x + w_in, pt_y + h_in