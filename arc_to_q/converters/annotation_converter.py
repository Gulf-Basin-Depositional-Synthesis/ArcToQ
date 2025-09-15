"""
Converts ArcGIS Pro Annotation Layers to QGIS Layers with data-defined labeling.
"""
from qgis.core import (
    QgsVectorLayer,
    QgsPalLayerSettings,
    QgsProperty,
    QgsVectorLayerSimpleLabeling,
    QgsTextFormat,
    QgsUnitTypes  # Ensure QgsUnitTypes is imported
)
from PyQt5.QtGui import QColor

def set_annotation_labels(layer: QgsVectorLayer):
    """
    Configures a QGIS vector layer to mimic an ArcGIS Annotation Layer
    by setting up extensive data-defined label properties.

    Args:
        layer (QgsVectorLayer): The QGIS layer to configure.
    """
    if not layer.isValid():
        print("Cannot apply annotation settings to an invalid layer.")
        return

    print("Configuring layer for data-defined annotation labeling...")

    # 1. Initialize label settings
    labeling = QgsPalLayerSettings()
    labeling.enabled = True
    labeling.placement = QgsPalLayerSettings.Horizontal
    
    # Use the raw field name for the label content and enable HTML
    labeling.isExpression = False
    labeling.fieldName = "TextString" 
    text_format = labeling.format()
    text_format.setAllowHtmlFormatting(True) 
    text_format.setColor(QColor('black')) 
    
    # 2. Get the property collection to set data-defined overrides
    props = labeling.dataDefinedProperties()
    
    # Font properties
    props.setProperty(QgsPalLayerSettings.Property.Family, QgsProperty.fromField("FontName"))
    props.setProperty(QgsPalLayerSettings.Property.Size, QgsProperty.fromField("FontSize"))
    
    # Style (Bold, Italic, Underline)
    style_expression = """
        CASE 
            WHEN "Bold" > 0 AND "Italic" > 0 THEN 'Bold Italic'
            WHEN "Bold" > 0 THEN 'Bold'
            WHEN "Italic" > 0 THEN 'Italic'
            ELSE 'Normal'
        END
    """
    props.setProperty(QgsPalLayerSettings.Property.FontStyle, QgsProperty.fromExpression(style_expression))
    props.setProperty(QgsPalLayerSettings.Property.Underline, QgsProperty.fromExpression('"Underline" > 0'))

    # --- THIS IS THE CORRECT FIX ---
    # Explicitly set the DATA-DEFINED units for Size and Offset to MAP UNITS.
    # This forces QGIS to interpret the values from the fields as map coordinates, not screen points.
    props.setProperty(QgsPalLayerSettings.Property.FontSizeUnit, QgsProperty.fromValue(QgsUnitTypes.RenderMapUnits))
    props.setProperty(QgsPalLayerSettings.Property.OffsetUnits, QgsProperty.fromValue(QgsUnitTypes.RenderMapUnits))
    # --- END OF FIX ---

    # Use combined OffsetXY property for positioning in MAP UNITS
    props.setProperty(QgsPalLayerSettings.Property.OffsetXY, QgsProperty.fromExpression('make_point("XOffset", "YOffset")'))
    
    # Rotation
    props.setProperty(QgsPalLayerSettings.Property.LabelRotation, QgsProperty.fromField("Angle"))

    # Alignment
    h_align_expression = "CASE WHEN \"HorizontalAlignment\" = 1 THEN 'Center' WHEN \"HorizontalAlignment\" = 2 THEN 'Right' ELSE 'Left' END"
    props.setProperty(QgsPalLayerSettings.Property.Hali, QgsProperty.fromExpression(h_align_expression))
    
    v_align_expression = "CASE WHEN \"VerticalAlignment\" = 0 THEN 'Top' WHEN \"VerticalAlignment\" = 1 THEN 'VCenter' WHEN \"VerticalAlignment\" = 3 THEN 'Bottom' ELSE 'Base' END"
    props.setProperty(QgsPalLayerSettings.Property.Vali, QgsProperty.fromExpression(v_align_expression))

    # 3. Apply the fully configured labeling settings to the layer
    layer.setLabeling(QgsVectorLayerSimpleLabeling(labeling))
    layer.setLabelsEnabled(True)