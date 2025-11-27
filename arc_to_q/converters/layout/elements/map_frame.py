import math
import logging
from qgis.core import (
    QgsLayoutItemMap, 
    QgsRectangle, 
    QgsCoordinateReferenceSystem,
    QgsUnitTypes,
    QgsLayoutPoint,
    QgsLayoutSize
)
from .base import BaseElementHandler

logger = logging.getLogger("MapFrameHandler")

class MapFrameHandler(BaseElementHandler):
    """
    Handles the creation of Map Frames (CIMMapFrame).
    Includes logic for converting ArcGIS Camera/View settings into QGIS Extents and CRS.
    """

    def create(self, element):
        # 1. Calculate Geometry
        x, y, w, h = self.geo_converter.get_qgis_rect(element)
        
        # 2. Initialize Map Item
        map_item = QgsLayoutItemMap(self.layout)
        map_item.setFrameEnabled(True)
        
        # CRITICAL FIX: Set Size & Position BEFORE setting Extent/View
        # QGIS needs the physical dimensions (mm) to correctly calculate scale from a geographic extent.
        # If extent is set while size is 0x0, scale becomes NaN.
        self._set_common_properties(map_item, x, y, w, h, element)
        
        # 3. Add Layers (All layers in project)
        layers = list(self.project.mapLayers().values())
        if layers:
            map_item.setLayers(layers)
            
            # 4. Handle CRS and Extent
            self._setup_map_view(map_item, element, layers)
            
        # 5. Set Scale (if explicit overrides are needed)
        self._apply_scale(map_item, element)
        
        # Force an update to ensure scale is calculated immediately
        map_item.refresh()
        
        logger.info(f"✓ Map Frame created: '{element.get('name')}' (Scale: 1:{map_item.scale():,.0f})")

    def _setup_map_view(self, map_item, element, layers):
        """
        Determines CRS and Extent from the ArcGIS Camera definition.
        """
        target_crs = None
        
        if "view" in element and "camera" in element["view"]:
            camera = element["view"]["camera"]
            x_coord = camera.get("x")
            y_coord = camera.get("y")
            
            # Viewport dimensions are usually in meters (ground distance) 
            # regardless of whether the CRS is geographic or projected.
            viewport_width = camera.get("viewportWidth")
            viewport_height = camera.get("viewportHeight")
            
            if x_coord is not None and y_coord is not None:
                # Check for Geographic Coordinates (Lat/Lon)
                if -180 <= x_coord <= 180 and -90 <= y_coord <= 90:
                    logger.debug(f"Camera coordinates suggest Geographic CRS: ({x_coord:.2f}, {y_coord:.2f})")
                    target_crs = QgsCoordinateReferenceSystem("EPSG:4326")  # WGS84
                    
                    if viewport_width and viewport_height:
                        extent = self._calculate_geographic_extent(
                            x_coord, y_coord, viewport_width, viewport_height
                        )
                        map_item.setExtent(extent)
                else:
                    logger.debug(f"Camera coordinates suggest Projected CRS: ({x_coord:.2f}, {y_coord:.2f})")
                    # For projected, we might need to find the CRS from the layers or JSON
                    if layers:
                        target_crs = layers[0].crs()
                    
                    if viewport_width and viewport_height:
                        extent = self._calculate_projected_extent(
                            x_coord, y_coord, viewport_width, viewport_height
                        )
                        map_item.setExtent(extent)

        # Fallback: Use first layer CRS if we couldn't determine one
        if not target_crs or not target_crs.isValid():
            if layers:
                target_crs = layers[0].crs()
                logger.warning(f"Using layer CRS as fallback: {target_crs.authid()}")
        
        # Apply CRS
        if target_crs and target_crs.isValid():
            # Ideally, we set the project CRS to match the main map
            self.project.setCrs(target_crs)
            map_item.setCrs(target_crs)

    def _calculate_geographic_extent(self, center_x, center_y, width_m, height_m):
        """
        Converts a metric viewport centered at (long, lat) into a Degree Extent.
        """
        # Meters per degree calculation
        # At the equator, 1 degree longitude ≈ 111,320 meters
        # Longitude distance shrinks as we move towards poles: cos(latitude)
        lat_rad = math.radians(abs(center_y))
        meters_per_deg_lon = 111320 * math.cos(lat_rad)
        meters_per_deg_lat = 111320  # Roughly constant
        
        # Avoid division by zero at poles
        if meters_per_deg_lon < 1: 
            meters_per_deg_lon = 1
            
        width_deg = width_m / meters_per_deg_lon
        height_deg = height_m / meters_per_deg_lat
        
        half_w = width_deg / 2
        half_h = height_deg / 2
        
        return QgsRectangle(
            center_x - half_w, center_y - half_h,
            center_x + half_w, center_y + half_h
        )

    def _calculate_projected_extent(self, center_x, center_y, width, height):
        """
        Simple extent calculation for projected coordinates (units match).
        """
        half_w = width / 2
        half_h = height / 2
        return QgsRectangle(
            center_x - half_w, center_y - half_h,
            center_x + half_w, center_y + half_h
        )

    def _apply_scale(self, map_item, element):
        """
        Sets the map scale if provided in the camera/view settings.
        """
        scale = None
        if "view" in element and "camera" in element["view"]:
            scale = element["view"]["camera"].get("scale")
        elif "autoCamera" in element:
            scale = element["autoCamera"].get("scale")
        
        if scale:
            map_item.setScale(scale)