import logging

# These imports assume the existence of sibling modules which we will create next.
# If testing piecemeal, these files must exist (even as stubs).
from .map_frame import MapFrameHandler
from .text import TextHandler
from .scale_bar import ScaleBarHandler
from .graphics import NorthArrowHandler

logger = logging.getLogger("ElementFactory")

class ElementFactory:
    """
    Factory class to dispatch CIM elements to their specific handlers.
    """

    @staticmethod
    def get_handler(element, project, layout, geo_converter):
        """
        Determines the correct handler for a given CIM element.

        Args:
            element (dict): The CIM element dictionary.
            project (QgsProject): The active QGIS project.
            layout (QgsPrintLayout): The layout being built.
            geo_converter (GeometryConverter): Helper for coordinate transforms.

        Returns:
            BaseElementHandler or None: An instantiated handler ready to .create(), 
                                        or None if the type is unsupported.
        """
        el_type = element.get("type")
        
        # 1. Map Frames (Priority items)
        if el_type == "CIMMapFrame":
            return MapFrameHandler(project, layout, geo_converter)
        
        # 2. Text Elements (Direct)
        if el_type in ["CIMTextGraphic", "CIMParagraphTextGraphic"]:
            return TextHandler(project, layout, geo_converter)

        # 3. Graphic Elements (Wrappers)
        # ArcGIS often wraps text or basic shapes inside a generic CIMGraphicElement
        if el_type == "CIMGraphicElement":
            graphic = element.get("graphic", {})
            graphic_type = graphic.get("type")
            
            # Un-wrap text graphics
            if graphic_type in ["CIMTextGraphic", "CIMParagraphTextGraphic"]:
                return TextHandler(project, layout, geo_converter)
            
            # Future: Add support for CIMPointGraphic (Pictures), CIMPolygonGraphic (Rectangles) here
            # if graphic_type == "CIMPictureGraphic": return PictureHandler(...)

        # 4. Scale Bars
        if el_type in ["CIMScaleLine", "CIMScaleBar"]:
            return ScaleBarHandler(project, layout, geo_converter)

        # 5. North Arrows
        if el_type in ["CIMMarkerNorthArrow", "CIMNorthArrow"]:
            return NorthArrowHandler(project, layout, geo_converter)

        # Log ignored types for debugging purposes
        # Common ignored types: CIMPictureGraphic (if not handled), CIMLegend, etc.
        logger.debug(f"No handler found for element type: {el_type} (Name: {element.get('name')})")
        return None