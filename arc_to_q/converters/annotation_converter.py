"""
Enhanced ArcGIS Pro Annotation Converter for QGIS 3.4+

Converts ArcGIS Pro Annotation Layers to QGIS with:
- Map-unit scaling for fixed geographic size (annotations scale with zoom)
- HTML formatting support with Esri tag conversion
- Universal visibility at all zoom levels
- Proper character encoding and font substitution
- Complete data-defined property mapping
"""

import re
from typing import Dict, Any, Optional, Tuple
from qgis.core import (
    QgsVectorLayer,
    QgsPalLayerSettings,
    QgsProperty,
    QgsVectorLayerSimpleLabeling,
    QgsTextFormat,
    QgsUnitTypes,
    QgsPropertyCollection,
    QgsFeature,
    QgsMessageLog,
    Qgis,
    edit
)
from PyQt5.QtGui import QColor, QFont
from PyQt5.QtCore import QVariant

class EsriTextConverter:
    """Converts Esri-specific formatting tags to QGIS-compatible HTML"""
    
    def __init__(self):
        # Esri font to open-source font mappings
        self.font_substitutions = {
            'ESRI Cartography': 'Font-GIS',
            'ESRI Default Marker': 'Font-GIS',
            'ESRI Environmental & Icons': 'Font-GIS',
            'ESRI North': 'Font-GIS',
            'ESRI Weather': 'Font-GIS',
            'Arial': 'Arial',  # Keep if available
            'Times New Roman': 'Times New Roman',
            'Calibri': 'Liberation Sans',
            'Tahoma': 'Liberation Sans'
        }
        
        # Common problematic Unicode characters from ArcGIS
        self.unicode_replacements = {
            '\u2019': "'",   # Right single quotation mark
            '\u201c': '"',   # Left double quotation mark
            '\u201d': '"',   # Right double quotation mark
            '\u2013': '-',   # En dash
            '\u2014': '--',  # Em dash
            '\u2026': '...',  # Horizontal ellipsis
            '\u00b0': '°',   # Degree symbol
        }
    
    def clean_unicode(self, text: str) -> str:
        """Clean problematic Unicode characters"""
        if not text:
            return text
            
        try:
            # Handle bytes to string conversion
            if isinstance(text, bytes):
                text = text.decode('utf-8', errors='replace')
            
            # Replace problematic Unicode characters
            for old, new in self.unicode_replacements.items():
                text = text.replace(old, new)
                
            return text
        except (UnicodeDecodeError, AttributeError):
            return str(text) if text else ""
    
    def convert_fnt_tag(self, match) -> str:
        """Convert <FNT> tag to plain text - let QGIS handle ALL styling"""
        font_name = match.group(1) if match.group(1) else "Arial"
        font_size = match.group(2) if match.group(2) else "12"
        content = match.group(3) if match.group(3) else ""
        
        # Return plain text - no HTML styling at all
        # Let QGIS data-defined properties handle font and size
        return content
    
    def convert_clr_tag(self, match) -> str:
        """Convert <CLR> tag to HTML span with color"""
        r, g, b = match.group(1), match.group(2), match.group(3)
        content = match.group(4) if match.group(4) else ""
        
        return f'<span style="color: rgb({r},{g},{b});">{content}</span>'
    
    def convert_esri_to_html(self, text: str) -> str:
        """Convert Esri formatting tags to QGIS-compatible HTML"""
        if not text:
            return text
        
        # Clean Unicode first
        text = self.clean_unicode(text)
        
        # REMOVE ALL existing span tags with font styling
        text = re.sub(r'<span\s+style="[^"]*font-family:[^"]*"[^>]*>(.*?)</span>', r'\1', text, flags=re.IGNORECASE | re.DOTALL)
        
        # Define conversion patterns - BUT skip font conversion
        patterns = [
            # Skip FNT tag conversion - just extract content
            (r'<FNT\s+[^>]*>(.*?)</FNT>', r'\1'),
            
            # Keep color tags
            (r'<CLR\s+red\s*=\s*["\'](\d+)["\']\s+green\s*=\s*["\'](\d+)["\']\s+blue\s*=\s*["\'](\d+)["\'][^>]*>(.*?)</CLR>',
            self.convert_clr_tag),
            
            # Simple formatting tags
            (r'<BOL>(.*?)</BOL>', r'<b>\1</b>'),
            (r'<ITA>(.*?)</ITA>', r'<i>\1</i>'),
            (r'<UND>(.*?)</UND>', r'<u>\1</u>'),
            (r'<SUP>(.*?)</SUP>', r'<sup>\1</sup>'),
            (r'<SUB>(.*?)</SUB>', r'<sub>\1</sub>'),
        ]
        
        # Apply conversions
        for pattern, replacement in patterns:
            if callable(replacement):
                text = re.sub(pattern, replacement, text, flags=re.IGNORECASE | re.DOTALL)
            else:
                text = re.sub(pattern, replacement, text, flags=re.IGNORECASE | re.DOTALL)
        
        return text

def calculate_map_unit_size(font_size_points: float, map_scale: float = 50000) -> float:
    """
    Calculate appropriate map unit size for annotation scaling
    
    Args:
        font_size_points: Original font size in points
        map_scale: Reference map scale (default 1:50000)
        
    Returns:
        Size in map units for geographic scaling
    """
    # Convert points to map units based on reference scale
    # 1 point = 0.352778 mm, adjust for map scale
    points_to_mm = 0.352778
    mm_to_map_units = map_scale / 1000.0
    
    return font_size_points * points_to_mm * mm_to_map_units

def preprocess_annotation_text(layer: QgsVectorLayer, text_field: str = "TextString") -> bool:
    """
    Preprocess annotation layer to convert Esri formatting tags
    
    Args:
        layer: QGIS vector layer containing annotations
        text_field: Name of the text field to process
        
    Returns:
        True if successful, False otherwise
    """
    if not layer.isValid():
        QgsMessageLog.logMessage("Invalid layer provided", "AnnotationConverter", Qgis.Critical)
        return False
    
    converter = EsriTextConverter()
    
    try:
        with edit(layer):
            for feature in layer.getFeatures():
                original_text = feature[text_field]
                if original_text:
                    converted_text = converter.convert_esri_to_html(str(original_text))
                    feature[text_field] = converted_text
                    layer.updateFeature(feature)
        
        QgsMessageLog.logMessage(f"Successfully preprocessed {layer.featureCount()} annotations", 
                                "AnnotationConverter", Qgis.Info)
        return True
        
    except Exception as e:
        QgsMessageLog.logMessage(f"Error preprocessing annotations: {str(e)}", 
                                "AnnotationConverter", Qgis.Critical)
        return False

def configure_annotation_properties(settings: QgsPalLayerSettings, layer: QgsVectorLayer) -> QgsPalLayerSettings:
    """
    Configure comprehensive data-defined properties for annotation attributes
    
    Args:
        settings: QGIS label settings object
        layer: Vector layer containing annotation data
        
    Returns:
        Configured label settings
    """
    properties = QgsPropertyCollection()
    
    # Get available field names
    field_names = [field.name() for field in layer.fields()]
    
    # Basic text properties
    if "FontName" in field_names:
        properties.setProperty(QgsPalLayerSettings.FontFamily, QgsProperty.fromField("FontName"))
    
    if "FontSize" in field_names:
        # Use expression to convert points to map units dynamically
        size_expression = f'''
        CASE 
            WHEN "FontSize" IS NOT NULL AND "FontSize" > 0 
            THEN "FontSize" * 0.352778 * (@map_scale / 50000)
            ELSE 100
        END
        '''
        properties.setProperty(QgsPalLayerSettings.Size, QgsProperty.fromExpression(size_expression))
    
    # Font style combining Bold and Italic
    if "Bold" in field_names and "Italic" in field_names:
        style_expression = '''
        CASE 
            WHEN "Bold" > 0 AND "Italic" > 0 THEN 'Bold Italic'
            WHEN "Bold" > 0 THEN 'Bold'
            WHEN "Italic" > 0 THEN 'Italic'
            ELSE 'Normal'
        END
        '''
        properties.setProperty(QgsPalLayerSettings.FontStyle, QgsProperty.fromExpression(style_expression))
    
    # Underline
    if "Underline" in field_names:
        properties.setProperty(QgsPalLayerSettings.Underline, 
                             QgsProperty.fromExpression('"Underline" > 0'))
    
    # Rotation - handle different coordinate systems
    if "Angle" in field_names:
        # ArcGIS typically uses geographic rotation (0° = North, clockwise)
        # QGIS uses mathematical rotation (0° = East, counter-clockwise)
        rotation_expression = '''
        CASE 
            WHEN "Angle" IS NOT NULL THEN 90 - "Angle"
            ELSE 0
        END
        '''
        properties.setProperty(QgsPalLayerSettings.LabelRotation, 
                             QgsProperty.fromExpression(rotation_expression))
    
    # Position offsets
    if "XOffset" in field_names and "YOffset" in field_names:
        offset_expression = 'array("XOffset", "YOffset")'
        properties.setProperty(QgsPalLayerSettings.OffsetXY, 
                             QgsProperty.fromExpression(offset_expression))
    
    # Horizontal alignment
    if "HorizontalAlignment" in field_names:
        h_align_expression = '''
        CASE 
            WHEN "HorizontalAlignment" = 1 THEN 'Center'
            WHEN "HorizontalAlignment" = 2 THEN 'Right'
            ELSE 'Left'
        END
        '''
        properties.setProperty(QgsPalLayerSettings.Hali, 
                             QgsProperty.fromExpression(h_align_expression))
    
    # Vertical alignment
    if "VerticalAlignment" in field_names:
        v_align_expression = '''
        CASE 
            WHEN "VerticalAlignment" = 0 THEN 'Top'
            WHEN "VerticalAlignment" = 1 THEN 'VCenter'
            WHEN "VerticalAlignment" = 3 THEN 'Bottom'
            ELSE 'Base'
        END
        '''
        properties.setProperty(QgsPalLayerSettings.Vali, 
                             QgsProperty.fromExpression(v_align_expression))
    
    # Critical: Set units to map units for geographic scaling
    properties.setProperty(QgsPalLayerSettings.FontSizeUnit, 
                         QgsProperty.fromValue(QgsUnitTypes.RenderMapUnits))
    properties.setProperty(QgsPalLayerSettings.OffsetUnits, 
                         QgsProperty.fromValue(QgsUnitTypes.RenderMapUnits))
    
    settings.setDataDefinedProperties(properties)
    return settings

def set_annotation_labels(layer: QgsVectorLayer, 
                         text_field: str = "TextString",
                         preprocess_text: bool = True,
                         reference_scale: float = 50000) -> bool:
    """
    Configure a QGIS vector layer for annotation-like labeling with:
    - Map-unit scaling (fixed geographic size)
    - HTML formatting support
    - Universal visibility
    - Complete ArcGIS attribute mapping
    
    Args:
        layer: The QGIS layer to configure
        text_field: Name of the field containing text content
        preprocess_text: Whether to convert Esri formatting tags
        reference_scale: Reference map scale for size calculations
        
    Returns:
        True if successful, False otherwise
    """
    if not layer.isValid():
        QgsMessageLog.logMessage("Cannot apply annotation settings to an invalid layer", 
                                "AnnotationConverter", Qgis.Critical)
        return False

    QgsMessageLog.logMessage(f"Configuring annotation labeling for layer: {layer.name()}", 
                            "AnnotationConverter", Qgis.Info)

    try:
        # Step 1: Preprocess Esri formatting tags if requested
        if preprocess_text:
            if not preprocess_annotation_text(layer, text_field):
                QgsMessageLog.logMessage("Text preprocessing failed, continuing with raw text", 
                                        "AnnotationConverter", Qgis.Warning)

        # Step 2: Initialize label settings for annotation-like behavior
        labeling = QgsPalLayerSettings()
        labeling.enabled = True
        
        # Use field name directly (not expression) for better performance
        labeling.isExpression = False
        labeling.fieldName = text_field
        
        # Step 3: Configure text format with map units for geographic scaling
        text_format = QgsTextFormat()
        text_format.setFont(QFont("Arial", 12))
        text_format.setSize(100)  # Default size in map units
        text_format.setSizeUnit(QgsUnitTypes.RenderMapUnits)  # Critical for scaling behavior
        text_format.setColor(QColor('black'))
        text_format.setAllowHtmlFormatting(True)  # Enable HTML parsing
        
        labeling.setFormat(text_format)
        
        # Step 4: Configure placement for annotation-like positioning
        labeling.placement = QgsPalLayerSettings.OffsetFromPoint
        labeling.offsetType = QgsPalLayerSettings.FromPoint
        labeling.dist = 0  # No automatic offset
        labeling.distUnits = QgsUnitTypes.RenderMapUnits
        
        # Step 5: Configure data-defined properties
        labeling = configure_annotation_properties(labeling, layer)
        
        # Step 6: Ensure universal visibility at all zoom levels
        labeling.scaleVisibility = False  # Disable scale-based visibility
        labeling.displayAll = True  # Force display of all labels
        labeling.obstacle = False  # Don't treat as obstacles
        labeling.priority = 10  # Highest priority
        
        # Step 7: Configure advanced placement options
        labeling.placementFlags = QgsPalLayerSettings.AboveLine | QgsPalLayerSettings.BelowLine | QgsPalLayerSettings.OnLine
        labeling.maxNumLabels = 2000  # Increase label limit
        labeling.limitNumLabels = False  # Don't limit number of labels
        
        # Step 8: Handle overlapping labels
        labeling.upsidedownLabels = QgsPalLayerSettings.Upright  # Keep labels upright
        labeling.overrunDistance = 0  # No overrun for precise positioning
        labeling.overrunDistanceUnit = QgsUnitTypes.RenderMapUnits
        
        # Step 9: Apply labeling to layer
        layer.setLabeling(QgsVectorLayerSimpleLabeling(labeling))
        layer.setLabelsEnabled(True)
        
        # Step 10: Configure layer properties for optimal annotation display
        layer.setScaleBasedVisibility(False)  # Always visible
        
        QgsMessageLog.logMessage(f"Successfully configured annotation labeling for {layer.featureCount()} features", 
                                "AnnotationConverter", Qgis.Info)
        
        return True
        
    except Exception as e:
        QgsMessageLog.logMessage(f"Error configuring annotation labels: {str(e)}", 
                                "AnnotationConverter", Qgis.Critical)
        return False

def validate_annotation_layer(layer: QgsVectorLayer) -> Tuple[bool, str]:
    """
    Validate that a layer contains the necessary fields for annotation conversion
    
    Args:
        layer: Vector layer to validate
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not layer.isValid():
        return False, "Layer is not valid"
    
    field_names = [field.name() for field in layer.fields()]
    required_fields = ["TextString"]
    optional_fields = ["FontName", "FontSize", "Bold", "Italic", "Underline", 
                      "Angle", "XOffset", "YOffset", "HorizontalAlignment", "VerticalAlignment"]
    
    # Check for required fields
    missing_required = [field for field in required_fields if field not in field_names]
    if missing_required:
        return False, f"Missing required fields: {', '.join(missing_required)}"
    
    # Report missing optional fields
    missing_optional = [field for field in optional_fields if field not in field_names]
    if missing_optional:
        QgsMessageLog.logMessage(f"Missing optional fields (will use defaults): {', '.join(missing_optional)}", 
                                "AnnotationConverter", Qgis.Warning)
    
    return True, "Layer validation successful"

# Main function for easy integration
def convert_arcgis_annotations(layer: QgsVectorLayer, **kwargs) -> bool:
    """
    Main function to convert ArcGIS Pro annotations to QGIS
    
    Args:
        layer: QGIS vector layer containing annotation data
        **kwargs: Optional configuration parameters
            - text_field: Name of text field (default: "TextString")
            - preprocess_text: Convert Esri tags (default: True)
            - reference_scale: Reference scale for sizing (default: 50000)
            - validate: Validate layer first (default: True)
            
    Returns:
        True if conversion successful, False otherwise
    """
    # Extract configuration
    text_field = kwargs.get('text_field', 'TextString')
    preprocess_text = kwargs.get('preprocess_text', True)
    reference_scale = kwargs.get('reference_scale', 50000)
    validate = kwargs.get('validate', True)
    
    # Validate layer if requested
    if validate:
        is_valid, message = validate_annotation_layer(layer)
        if not is_valid:
            QgsMessageLog.logMessage(f"Layer validation failed: {message}", 
                                    "AnnotationConverter", Qgis.Critical)
            return False
    
    # Apply annotation configuration
    return set_annotation_labels(layer, text_field, preprocess_text, reference_scale)

def create_robust_annotation_labeling(layer: QgsVectorLayer) -> bool:
    """
    Create robust annotation labeling that works with different QGIS versions
    """
    try:
        # Step 1: Create base label settings
        settings = QgsPalLayerSettings()
        settings.fieldName = "TextString"
        settings.isExpression = False
        
        # Step 2: Configure text format
        text_format = QgsTextFormat()
        text_format.setFont(QFont("Arial", 12))
        text_format.setColor(QColor('black'))
        text_format.setAllowHtmlFormatting(True)
        
        # Step 3: Handle CRS-specific sizing
        crs_authid = layer.crs().authid()
        if "4326" in crs_authid:
            # Geographic CRS - larger base size for fixed geographic scaling
            text_format.setSize(0.01)
            text_format.setSizeUnit(QgsUnitTypes.RenderMapUnits)
            print(f"Using geographic coordinate scaling for {crs_authid}")
        else:
            # Projected CRS
            text_format.setSize(100)
            text_format.setSizeUnit(QgsUnitTypes.RenderMapUnits)
            print(f"Using projected coordinate scaling for {crs_authid}")
        
        settings.setFormat(text_format)
        
        # Step 4: Configure placement
        settings.placement = QgsPalLayerSettings.AroundPoint
        settings.priority = 10
        
        # Step 5: Add data-defined properties
        field_names = [field.name() for field in layer.fields()]
        properties = QgsPropertyCollection()
        
       # FIXED Font size - much larger multiplier for visibility
        if "FontSize" in field_names:
            if "4326" in crs_authid:
                # Geographic - much larger multiplier for visibility
                size_expr = '"FontSize" * 0.04'  # 100x larger than before
            else:
                # Projected - fixed size conversion
                size_expr = '"FontSize" * 10'
            
            try:
                properties.setProperty(QgsPalLayerSettings.Property.Size, 
                                     QgsProperty.fromExpression(size_expr))
                print("Applied font size data-defined property")
            except Exception as e:
                print(f"Could not set font size property: {e}")
        
        # Font family
        if "FontName" in field_names:
            try:
                # Create expression to map ESRI fonts to available fonts
                font_expr = '''
                CASE 
                    WHEN "FontName" LIKE '%ESRI%' THEN 'Arial'
                    WHEN "FontName" = 'ESRI AMFM Water' THEN 'Arial'
                    WHEN "FontName" = 'ESRI Hazardous Materials' THEN 'Arial'
                    ELSE "FontName"
                END
                '''
                properties.setProperty(QgsPalLayerSettings.Property.Family, 
                                    QgsProperty.fromExpression(font_expr))
                print("Applied font family mapping")
            except Exception as e:
                print(f"Could not set font family property: {e}")
                
        # FIXED Rotation - flipped direction
        if "Angle" in field_names:
            try:
                # Flipped direction - removed negative sign
                rotation_expr = '"Angle"'
                properties.setProperty(QgsPalLayerSettings.Property.LabelRotation, 
                                     QgsProperty.fromExpression(rotation_expr))
                print("Applied corrected rotation data-defined property")
            except Exception as e:
                print(f"Could not set rotation property: {e}")
        
        # Positioning offsets
        if "XOffset" in field_names and "YOffset" in field_names:
            try:
                offset_expr = 'array("XOffset", "YOffset")'
                properties.setProperty(QgsPalLayerSettings.Property.OffsetXY, 
                                     QgsProperty.fromExpression(offset_expr))
                print("Applied offset data-defined property")
            except Exception as e:
                print(f"Could not set offset property: {e}")
        
        # Font styling
        if "Bold" in field_names and "Italic" in field_names:
            try:
                style_expr = '''
                CASE 
                    WHEN "Bold" > 0 AND "Italic" > 0 THEN 'Bold Italic'
                    WHEN "Bold" > 0 THEN 'Bold'
                    WHEN "Italic" > 0 THEN 'Italic'
                    ELSE 'Normal'
                END
                '''
                properties.setProperty(QgsPalLayerSettings.Property.FontStyle, 
                                     QgsProperty.fromExpression(style_expr))
                print("Applied font style data-defined property")
            except Exception as e:
                print(f"Could not set font style property: {e}")
        
        # Apply properties to settings
        if properties.count() > 0:
            settings.setDataDefinedProperties(properties)
            print(f"Applied {properties.count()} data-defined properties")
        
        # Step 6: Apply to layer
        layer.setLabeling(QgsVectorLayerSimpleLabeling(settings))
        layer.setLabelsEnabled(True)
        
        print(f"Successfully applied robust annotation labeling")
        return True
        
    except Exception as e:
        print(f"Error in robust annotation conversion: {e}")
        return False

def apply_enhanced_annotation_converter(layer: QgsVectorLayer) -> bool:
    """
    Apply the enhanced annotation converter with better error handling
    """
    print(f"Applying enhanced annotation converter to {layer.name()}")
    print(f"Layer CRS: {layer.crs().authid()}")
    print(f"Feature count: {layer.featureCount()}")
    
    # Enable labeling first
    layer.setLabelsEnabled(True)
    
    # Try robust conversion
    success = create_robust_annotation_labeling(layer)
    
    if success:
        print("Enhanced annotation conversion completed successfully")
        
        # Verify final state
        if layer.labeling():
            settings = layer.labeling().settings()
            print(f"Final settings - Field: {settings.fieldName}")
            print(f"Final settings - Size: {settings.format().size()}")
            print(f"Final settings - Size unit: {settings.format().sizeUnit()}")
            print(f"Final settings - Color: {settings.format().color().name()}")
    else:
        print("Enhanced annotation conversion failed")
    
    return success