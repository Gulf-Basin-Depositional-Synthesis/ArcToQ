import logging
from qgis.core import (
    QgsLayoutItemPicture,
    QgsLayoutPoint,
    QgsLayoutSize,
    QgsUnitTypes
)
from .base import BaseElementHandler

logger = logging.getLogger("GraphicsHandler")

class NorthArrowHandler(BaseElementHandler):
    """
    Handles North Arrow elements (CIMMarkerNorthArrow).
    Currently maps all North Arrows to a default QGIS SVG to ensure visibility.
    """

    def create(self, element):
        # 1. Calculate Geometry
        x, y, w, h = self.geo_converter.get_qgis_rect(element)
        
        # 2. Create Picture Item
        arrow = QgsLayoutItemPicture(self.layout)
        
        # Use default QGIS North Arrow
        # Future improvement: Map specific ArcGIS arrow styles to similar QGIS SVGs
        arrow.setPicturePath(":/images/north_arrows/layout_default_north_arrow.svg")
        
        # 3. Apply Size Constraints
        # ArcGIS bounding boxes for north arrows can be misleadingly large.
        # We limit the maximum dimension to 50mm to prevent layout clutter.
        max_dim_mm = 50
        
        if w > max_dim_mm or h > max_dim_mm:
            ratio = w / h if h > 0 else 1
            if w > h:
                w = max_dim_mm
                h = max_dim_mm / ratio
            else:
                w = max_dim_mm * ratio
                h = max_dim_mm
                
        # 4. Finalize
        # We pass the modified w/h here, overriding the raw geometry calculation
        self._set_common_properties(arrow, x, y, w, h, element)
        
        logger.info(f"✓ North arrow created at ({x:.1f}, {y:.1f}) mm")

class PictureHandler(BaseElementHandler):
    """
    Placeholder for handling generic CIMPictureGraphic elements.
    (Not currently used by the factory, but ready for future expansion)
    """
    def create(self, element):
        x, y, w, h = self.geo_converter.get_qgis_rect(element)
        
        picture = QgsLayoutItemPicture(self.layout)
        # Logic to decode Base64 image data from PAGX or link external file would go here
        
        self._set_common_properties(picture, x, y, w, h, element)