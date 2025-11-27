import logging
from qgis.core import (
    QgsLayoutItemLabel, 
    QgsLayoutItemMap,
    QgsUnitTypes, 
    QgsLayoutPoint, 
    QgsLayoutSize
)
from qgis.PyQt.QtGui import QColor, QFont
from qgis.PyQt.QtCore import Qt

from .base import BaseElementHandler

# IMPORT FIX: Handle running as script vs package
try:
    # Package mode (e.g. running from main plugin)
    from ..parsers import LayoutParser
except ImportError:
    # Script mode (running layout_converter.py directly)
    # 'parsers' is available at the top level of sys.path
    from parsers import LayoutParser

logger = logging.getLogger("TextHandler")

class TextHandler(BaseElementHandler):
    """
    Handles Text Graphics and Paragraph Text.
    Manages font styling, alignment, and dynamic text translation.
    """

    def create(self, element):
        # 1. Calculate Geometry
        x, y, w, h = self.geo_converter.get_qgis_rect(element)
        
        # 2. Prepare Text Content
        raw_text = element.get("text") or element.get("graphic", {}).get("text", "Text")
        
        # Determine associated Map Frame for dynamic text (e.g., Scale)
        map_frame_name = element.get("mapFrame")
        if not map_frame_name:
            # Fallback: Find the first map frame in the layout
            map_items = [i for i in self.layout.items() if isinstance(i, QgsLayoutItemMap)]
            if map_items:
                map_frame_name = map_items[0].id()
            else:
                map_frame_name = "Map Frame"

        text = LayoutParser.translate_dynamic_text(raw_text, map_frame_name)
        
        # 3. Create Label Item
        label = QgsLayoutItemLabel(self.layout)
        label.setText(text)
        
        # 4. Apply Font Styling
        self._apply_font_style(label, element)
        
        # 5. Apply Alignment
        self._apply_alignment(label, element)
        
        # 6. Adjust Dimensions for Dynamic Content
        # Dynamic text often expands (e.g. <dyn type="scale"/> -> "1:50,000")
        if '[%' in text:
            w = max(w, 50)  # Ensure minimum width
            if 'map_scale' in text or 'format_number' in text:
                w = max(w, 80)
        
        # Ensure height accommodates multi-line text
        font = label.textFormat().font()
        line_count = text.count('\n') + 1
        min_h = line_count * font.pointSizeF() * 0.3528 * 1.5 # Points to mm * line spacing
        if h < min_h:
            h = min_h

        # 7. Finalize
        self._set_common_properties(label, x, y, w, h, element)
        logger.info(f"✓ Label created: '{LayoutParser.clean_text_content(text)[:30]}...'")

    def _apply_font_style(self, label, element):
        """Extracts font properties and applies them to the label."""
        family, size_pt, styles = LayoutParser.extract_font_info(element)
        
        font = QFont(family)
        font.setPointSizeF(size_pt)
        font.setBold("bold" in styles)
        font.setItalic("italic" in styles)
        
        text_format = label.textFormat()
        text_format.setFont(font)
        text_format.setSize(size_pt)
        
        # Color
        symbol = element.get("graphic", {}).get("symbol", {}).get("symbol", {})
        if "color" in symbol:
            vals = symbol["color"].get("values", [])
            if len(vals) >= 3:
                # ArcGIS Colors are 0-255 RGB
                color = QColor(int(vals[0]), int(vals[1]), int(vals[2]))
                text_format.setColor(color)
        
        label.setTextFormat(text_format)

    def _apply_alignment(self, label, element):
        """Sets horizontal and vertical alignment."""
        symbol = element.get("graphic", {}).get("symbol", {}).get("symbol", {})
        h_align = symbol.get("horizontalAlignment", "Left")
        
        # QGIS Vertical alignment for labels is mostly strictly 'Top' or 'Middle' 
        # relative to the box, defaulting to Top for standard text boxes.
        
        if h_align == "Center": 
            label.setHAlign(Qt.AlignHCenter)
        elif h_align == "Right": 
            label.setHAlign(Qt.AlignRight)
        else:
            label.setHAlign(Qt.AlignLeft)
        
        # Note: Vertical alignment in ArcGIS text symbols is complex 
        # and often handled by the anchor point calculation in geometry.py