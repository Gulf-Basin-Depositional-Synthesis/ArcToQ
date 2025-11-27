import re
import logging

logger = logging.getLogger("LayoutParsers")

class LayoutParser:
    """
    Utilities for parsing CIM Layout JSON structures and text content.
    """

    @staticmethod
    def find_layout_definition(root):
        """
        Navigates the PAGX JSON root to find the specific layout definition block.
        ArcGIS Pro files vary in structure depending on version and export method.
        """
        if "layoutDefinition" in root: 
            return root["layoutDefinition"]
        if "layout" in root: 
            return root["layout"]
        if "elements" in root: 
            return root
        if "definitions" in root:
            # Search through definitions array for CIMLayout
            for d in root["definitions"]:
                if d.get("type") == "CIMLayout": 
                    return d
        return None

    @staticmethod
    def translate_dynamic_text(text, map_item_name="Map Frame"):
        """
        Translates ArcGIS <dyn> tags to QGIS expressions.
        
        Args:
            text (str): The raw text content from the CIM element.
            map_item_name (str): The QGIS item ID of the map frame to reference 
                                 (for scale, extent, etc.).
                                 
        Returns:
            str: Text with QGIS [% expression %] syntax.
        """
        if not text: 
            return ""
        
        # Cleanup: Remove static labels that often precede dynamic tags in ArcGIS
        # because we are replacing them with composite QGIS expressions.
        # e.g., "Scale: <dyn...>" becomes just the dynamic scale text.
        text = re.sub(r'Upper Left:\s*', '', text, flags=re.IGNORECASE)
        text = re.sub(r'Lower Right:\s*', '', text, flags=re.IGNORECASE)
        text = re.sub(r'Scale:\s*', '', text, flags=re.IGNORECASE)
        
        def replacer(match):
            content = match.group(1)
            # Robust attribute extraction from the tag content
            # Matches key="value" pairs
            attrs = dict(re.findall(r'(\w+)="([^"]*)"', content))
            
            dtype = attrs.get("type", "").lower()
            prop = attrs.get("property", "").lower()
            
            if "mapframe" in dtype:
                if "scale" in prop:
                    # Map Scale -> QGIS format number
                    return f"Scale: [% '1:' || format_number(map_get(item_variables('{map_item_name}'), 'map_scale'), 0) %]"
                
                if "upperleft" in prop or "upper_left" in prop:
                    # Extent Coordinates (DMS)
                    return (
                        f"Upper Left:\n"
                        f"[% to_dms(map_get(item_variables('{map_item_name}'), 'map_extent_xmin'), 'x', 0) %]\n"
                        f"[% to_dms(map_get(item_variables('{map_item_name}'), 'map_extent_ymax'), 'y', 0) %]"
                    )
                
                if "lowerright" in prop or "lower_right" in prop:
                    # Extent Coordinates (DMS)
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
            
            # Fallback for unsupported dynamic tags
            return f"[Dynamic: {dtype}]"

        # Regex matches <dyn ... /> or <dyn ...></dyn>
        # Flags: IGNORECASE for tag case, DOTALL to allow attributes on new lines
        return re.sub(r'<dyn\s+(.*?)(?:/>|>\s*</dyn>)', replacer, text, flags=re.IGNORECASE | re.DOTALL)

    @staticmethod
    def clean_text_content(text):
        """
        Removes HTML tags from text for pure size estimation or logging.
        """
        if not text:
            return ""
        return re.sub(r'<[^>]+>', '', text).strip()

    @staticmethod
    def extract_font_info(element):
        """
        Helper to extract font family, size, and style from a CIM element.
        Returns: (family, size_pt, styles_list)
        """
        symbol = element.get("graphic", {}).get("symbol", {}).get("symbol", {})
        
        font_size = symbol.get("height", 10)
        font_family = symbol.get("fontFamilyName", "Arial")
        
        # Parse style name (e.g., "Bold Italic")
        style_name = symbol.get("fontStyleName", "").lower()
        styles = []
        if "bold" in style_name: 
            styles.append("bold")
        if "italic" in style_name: 
            styles.append("italic")
            
        return font_family, font_size, styles