from qgis.core import QgsUnitTypes, QgsLayoutPoint, QgsLayoutSize
import logging

logger = logging.getLogger("BaseElement")

class BaseElementHandler:
    """
    Abstract base class for all layout element handlers.
    """
    def __init__(self, project, layout, geo_converter):
        self.project = project
        self.layout = layout
        self.geo_converter = geo_converter

    def create(self, element):
        """
        Creates the QGIS layout item from the CIM element definition.
        Must be implemented by subclasses.
        """
        raise NotImplementedError("Subclasses must implement create()")

    def _set_common_properties(self, item, x, y, w, h, element):
        """
        Applies standard position, size, and identification to a QGIS layout item.
        
        Args:
            item (QgsLayoutItem): The QGIS item instance.
            x (float): X position in mm.
            y (float): Y position in mm.
            w (float): Width in mm.
            h (float): Height in mm.
            element (dict): The original CIM element (for extracting name/ID).
        """
        # Set Geometry
        item.attemptMove(QgsLayoutPoint(x, y, QgsUnitTypes.LayoutMillimeters))
        item.attemptResize(QgsLayoutSize(w, h, QgsUnitTypes.LayoutMillimeters))
        
        # Set Item ID (useful for referencing in dynamic text)
        name = element.get("name")
        if name:
            item.setId(name)
        
        # Add to layout
        self.layout.addLayoutItem(item)