import logging
from qgis.core import (
    QgsLayoutItemScaleBar,
    QgsScaleBarSettings,
    QgsLayoutItemMap,
    QgsUnitTypes,
    QgsLayoutSize,
    QgsLayoutPoint
)
from .base import BaseElementHandler

logger = logging.getLogger("ScaleBarHandler")

class ScaleBarHandler(BaseElementHandler):
    """
    Handles Scale Bar elements (CIMScaleBar, CIMScaleLine).
    """

    def create(self, element):
        # 1. Calculate Geometry
        x, y, w, h = self.geo_converter.get_qgis_rect(element)
        
        # 2. Find Linked Map Frame
        map_item = self._get_linked_map(element)
        if not map_item:
            logger.warning(f"Skipping scale bar - no map frame found.")
            return

        # FORCE UPDATE: Ensure map has calculated its scale/extent before the scale bar attaches
        map_item.update()
        
        # 3. Create Scale Bar Item
        sb = QgsLayoutItemScaleBar(self.layout)
        sb.setLinkedMap(map_item)
        sb.setStyle("Single Box")  # Default style
        
        # 4. Extract & Configure Units
        unit_label, meters_per_unit, division_val = self._extract_unit_info(element)
        
        # DEBUG: Log exactly what we found to trace the "m" vs "km" issue
        logger.info(f"Scale Bar Config: Label='{unit_label}', Division={division_val}, Meters/Unit={meters_per_unit}")

        self._configure_units(sb, map_item, unit_label, meters_per_unit)
        
        # 5. Configure Segments
        if division_val <= 0:
            division_val = 100.0
            
        sb.setUnitsPerSegment(division_val)
        
        num_divisions = element.get("divisions", 2)
        sb.setNumberOfSegments(int(num_divisions))
        sb.setNumberOfSegmentsLeft(0)

        # 6. Configure Subdivisions
        subdivisions = element.get("subdivisions", 0)
        if subdivisions > 1:
            sb.setNumberOfSubdivisions(int(subdivisions))

        # 7. Apply Sizing
        # CRITICAL ORDER: Apply default size first, THEN force the Fixed mode logic.
        sb.applyDefaultSize()
        sb.update()
        
        # FORCE FIXED MODE: Explicitly tell QGIS to respect our 950 value
        sb.setSegmentSizeMode(QgsScaleBarSettings.SegmentSizeMode.Fixed)
        sb.setUnitsPerSegment(division_val) 
        sb.update()

        # --- HEIGHT FIX ---
        # The imported height 'h' (e.g., 6mm) is often just the bar thickness from ArcGIS.
        # QGIS needs height for Bar + Text + Margins.
        # We check what QGIS thinks it needs (sb.rect().height()) and use the larger value.
        needed_height = sb.rect().height()
        final_height = max(h, needed_height)
        
        # --- WIDTH FIX ---
        final_width = sb.rect().width()
        
        # If QGIS reports a collapsed width, force it to the original box width
        if final_width < 10:
             logger.debug(f"Scale bar width small ({final_width:.2f}mm), resizing to original box ({w:.2f}mm)")
             final_width = w

        sb.attemptMove(QgsLayoutPoint(x, y, QgsUnitTypes.LayoutMillimeters))
        sb.attemptResize(QgsLayoutSize(final_width, final_height, QgsUnitTypes.LayoutMillimeters))
        
        # RE-APPLY LABEL: Just in case applyDefaultSize() reset it
        sb.setUnitLabel(unit_label)
            
        # Add to layout
        self.layout.addLayoutItem(sb)
        if element.get("name"):
            sb.setId(element.get("name"))

        logger.info(f"✓ Scale bar created: {unit_label} (Segs: {num_divisions}, Div: {division_val}, H: {final_height:.1f}mm)")

    def _get_linked_map(self, element):
        """Finds the map frame associated with this scale bar."""
        map_frame_name = element.get("mapFrame")
        
        if map_frame_name:
            item = self.layout.itemById(map_frame_name)
            if isinstance(item, QgsLayoutItemMap):
                return item
        
        for item in self.layout.items():
            if isinstance(item, QgsLayoutItemMap):
                return item
                
        return None

    def _extract_unit_info(self, element):
        """
        Parses CIM unit definitions.
        Returns: (unit_label, meters_per_unit, division_value)
        """
        units_value = element.get("units", {})
        division = element.get("division", 100.0)
        
        unit_label = "m"
        meters_per_unit = 1.0
        units_str = ""

        # Handle WKID dictionary or string
        if isinstance(units_value, str):
            units_str = units_value.lower()
        elif isinstance(units_value, dict):
            # Check for value key
            if "value" in units_value:
                units_str = str(units_value["value"]).lower()
            
            # Check for WKID (both standard and uwkid)
            wkid = units_value.get("wkid") or units_value.get("uwkid")
            if wkid:
                if wkid == 9036: units_str = "kilometer"
                elif wkid == 9093: units_str = "mile"
                elif wkid == 9003: units_str = "foot_us"
                elif wkid == 9002: units_str = "foot"
                elif wkid == 9001: units_str = "meter"
        
        # Fallback to unitLabel property
        if not units_str:
            units_str = element.get("unitLabel", "").lower()

        # Determine conversion factor (meters per unit)
        if "kilometer" in units_str or "km" in units_str:
            unit_label, meters_per_unit = "km", 1000.0
        elif "mile" in units_str or "mi" in units_str:
            unit_label, meters_per_unit = "mi", 1609.34
        elif "foot" in units_str or "feet" in units_str or "ft" in units_str:
            unit_label, meters_per_unit = "ft", 0.3048
        elif "meter" in units_str or "m" in units_str:
            unit_label, meters_per_unit = "m", 1.0
            
        return unit_label, meters_per_unit, division

    def _configure_units(self, sb, map_item, unit_label, meters_per_unit):
        """
        Sets the QGIS MapUnitsPerScaleBarUnit based on Map CRS and target units.
        """
        sb.setUnitLabel(unit_label)
        
        map_crs = map_item.crs()
        is_geographic = False
        
        if map_crs.isValid():
            # QgsUnitTypes.DistanceDegrees is 6
            if map_crs.mapUnits() == QgsUnitTypes.DistanceDegrees:
                is_geographic = True

        if is_geographic:
            # Map Unit = 1 Degree.
            # 1 Degree ≈ 111,320 meters (at equator).
            # We use 111319.49 as standard equator constant
            meters_per_degree = 111319.49
            conversion = meters_per_unit / meters_per_degree
            
            # Avoid extremely small numbers failing validation
            if conversion < 0.0000001:
                conversion = 0.0000001
                
            sb.setMapUnitsPerScaleBarUnit(conversion)
        else:
            # Map Unit = 1 Meter (usually).
            # We assume map is in meters if not geographic.
            sb.setMapUnitsPerScaleBarUnit(meters_per_unit)