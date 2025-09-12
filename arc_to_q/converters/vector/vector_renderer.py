"""
Vector renderer creation module for ArcGIS to QGIS conversion.

This module provides factories for creating QGIS renderers from ArcGIS CIM renderer definitions.
It handles the three main renderer types: Simple, Categorized (Unique Values), and Graduated (Class Breaks).
"""

from typing import Optional, List, Dict, Any, Union
import logging
import re

from qgis.core import (
    QgsVectorLayer,
    QgsSingleSymbolRenderer,
    QgsCategorizedSymbolRenderer,
    QgsGraduatedSymbolRenderer,
    QgsRendererCategory,
    QgsRendererRange,
    QgsFeatureRenderer,
    QgsMarkerSymbol,
    QgsLineSymbol,
    QgsFillSymbol,
    QgsRuleBasedRenderer,
    QgsSymbol,
    QgsExpression,
    QgsProperty,          
    QgsSymbolLayer,       
    QgsUnitTypes,         
    QgsHeatmapRenderer,  
    QgsGradientColorRamp,
)
from qgis.PyQt.QtGui import QColor
from arc_to_q.converters.vector.symbols import SymbolFactory
from arc_to_q.converters.utils import parse_color

logger = logging.getLogger(__name__)


class RendererCreationError(Exception):
    """Raised when renderer creation fails."""
    pass


class UnsupportedRendererError(RendererCreationError):
    """Raised when renderer type is not supported."""
    pass


class RendererFactory:
    """Factory class for creating QGIS renderers from ArcGIS CIM definitions."""
    
    def __init__(self):
        self.symbol_factory = SymbolFactory()
    
    def create_renderer(self, renderer_def: Dict[str, Any], layer: QgsVectorLayer) -> QgsFeatureRenderer:
        """
        Create a QGIS renderer from an ArcGIS renderer definition.
        
        Args:
            renderer_def: The ArcGIS CIM renderer definition dictionary
            layer: The QGIS vector layer this renderer will be applied to
            
        Returns:
            QgsFeatureRenderer: The created QGIS renderer
            
        Raises:
            RendererCreationError: If renderer creation fails
            UnsupportedRendererError: If renderer type is not supported
        """
        if not renderer_def or not isinstance(renderer_def, dict):
            raise RendererCreationError("Renderer definition is required and must be a dictionary")
        
        if not isinstance(layer, QgsVectorLayer):
            raise RendererCreationError("Layer must be a QgsVectorLayer")
        
        renderer_type = renderer_def.get("type")
        if not renderer_type:
            raise RendererCreationError("Renderer type is missing from definition")
        
        try:
            if renderer_type == "CIMSimpleRenderer":
                return self._create_single_symbol_renderer(renderer_def, layer)
            elif renderer_type == "CIMUniqueValueRenderer":
                return self._create_categorized_or_rule_based_renderer(renderer_def, layer)
            elif renderer_type == "CIMClassBreaksRenderer":
                return self._create_graduated_renderer(renderer_def, layer)
            elif renderer_type == "CIMProportionalRenderer":
                return self._create_proportional_renderer(renderer_def, layer)
            elif renderer_type == "CIMHeatMapRenderer":
                return self._create_heatmap_renderer(renderer_def, layer)
            else:
                raise UnsupportedRendererError(f"Unsupported renderer type: {renderer_type}")
                
        except Exception as e:
            logger.error(f"Failed to create renderer of type {renderer_type}: {e}")
            # Return a default single symbol renderer as fallback
            return self._create_default_renderer(layer)
    
    def _create_single_symbol_renderer(self, renderer_def: Dict[str, Any], 
                                      layer: QgsVectorLayer) -> QgsSingleSymbolRenderer:
        """
        Create a QGIS single symbol renderer from a CIMSimpleRenderer definition.
        
        Args:
            renderer_def: ArcGIS CIMSimpleRenderer definition
            layer: The target QGIS vector layer
            
        Returns:
            QgsSingleSymbolRenderer: The created renderer
        """
        symbol_ref = renderer_def.get("symbol", {})
        
        if not symbol_ref:
            logger.warning("No symbol found in simple renderer, using default")
            symbol = self._create_default_symbol(layer)
        else:
            symbol = self.symbol_factory.create_symbol(symbol_ref)
            if not symbol:
                logger.warning("Failed to create symbol from definition, using default")
                symbol = self._create_default_symbol(layer)
        
        renderer = QgsSingleSymbolRenderer(symbol)
        
        # Apply renderer-level properties if available
        self._apply_common_renderer_properties(renderer, renderer_def)
        
        logger.info(f"Created single symbol renderer for layer '{layer.name()}'")
        return renderer
    
    def _create_categorized_or_rule_based_renderer(self, renderer_def: Dict[str, Any],
                                                   layer: QgsVectorLayer) -> QgsFeatureRenderer:
        """
        Decides whether to create a Bivariate, Expression-based, or standard Categorized renderer.
        """
        authoring_info = renderer_def.get("authoringInfo", {})
        if authoring_info.get("type") == "CIMBivariateRendererAuthoringInfo":
            logger.info("Bivariate authoring info found, creating QGIS Bivariate-style Renderer.")
            return self._create_bivariate_renderer(renderer_def, layer)

        if "valueExpressionInfo" in renderer_def:
            logger.info("Expression found, creating QGIS Categorized Renderer with a CASE expression.")
            return self._create_categorized_renderer_from_expression(renderer_def, layer)

        else:
            logger.info("No expression or bivariate info, creating standard QGIS Categorized Renderer.")
            return self._create_categorized_renderer(renderer_def, layer)
    
    
    def _create_bivariate_renderer(self, renderer_def: Dict[str, Any],
                                   layer: QgsVectorLayer) -> QgsCategorizedSymbolRenderer:
        """
        Creates a QGIS categorized renderer from an ArcGIS Bivariate Renderer definition.
        
        This reads the clean data from the 'authoringInfo' block instead of parsing
        the complex Arcade expression.
        """
        logger.info("Bivariate renderer detected. Building from 'authoringInfo'.")
        
        try:
            # 1. Extract the clean field and break info
            authoring_info = renderer_def["authoringInfo"]
            field_infos = authoring_info["fieldInfos"]
            
            field1_info = field_infos[0]
            field2_info = field_infos[1]
            
            field1_name = f'"{field1_info["field"]}"'
            field2_name = f'"{field2_info["field"]}"'
            
            breaks1 = field1_info["upperBounds"]
            breaks2 = field2_info["upperBounds"]
            
            class_codes = ["L", "M", "H"] # Low, Medium, High

            # 2. Build the QGIS CASE statement for the first field
            case1_parts = ["CASE"]
            for i, bound in enumerate(breaks1):
                case1_parts.append(f'    WHEN {field1_name} <= {bound} THEN \'{class_codes[i]}\'')
            case1_parts.append("END")
            qgis_expr1 = "\n".join(case1_parts)
            
            # 3. Build the QGIS CASE statement for the second field
            case2_parts = ["CASE"]
            for i, bound in enumerate(breaks2):
                case2_parts.append(f'    WHEN {field2_name} <= {bound} THEN \'{class_codes[i]}\'')
            case2_parts.append("END")
            qgis_expr2 = "\n".join(case2_parts)
            
            # 4. Combine the two expressions
            combined_expr = f"({qgis_expr1}) || ({qgis_expr2})"
            logger.info(f"Generated Bivariate Expression: {combined_expr}")

        except (KeyError, IndexError) as e:
            raise RendererCreationError(f"Failed to parse bivariate 'authoringInfo': {e}")

        # 5. Extract categories and symbols (this logic is the same as before)
        categories = []
        for group in renderer_def.get("groups", []):
            for uv_class in group.get("classes", []):
                try:
                    value = uv_class["values"][0]["fieldValues"][0]
                    label = uv_class.get("label")
                    symbol_def = uv_class.get("symbol")
                    
                    symbol = self.symbol_factory.create_symbol(symbol_def)
                    if not symbol:
                        symbol = self._create_default_symbol(layer)

                    categories.append(QgsRendererCategory(value, symbol, label))
                except (KeyError, IndexError):
                    continue
        
        if not categories:
            raise RendererCreationError("Failed to create any categories for bivariate renderer.")

        # 6. Create and return the final renderer
        renderer = QgsCategorizedSymbolRenderer(combined_expr, categories)
        self._apply_common_renderer_properties(renderer, renderer_def)
        return renderer
    
    def _create_categorized_renderer_from_expression(self, renderer_def: Dict[str, Any],
                                                     layer: QgsVectorLayer) -> QgsCategorizedSymbolRenderer:
        """
        Creates a QGIS categorized renderer by translating an Arcade expression
        into a single QGIS CASE...WHEN...END expression.
        """
        arcade_expr = renderer_def["valueExpressionInfo"]["expression"]
        qgis_case_expression = self._translate_arcade_to_case(arcade_expr)

        if not qgis_case_expression:
             raise RendererCreationError("Failed to translate Arcade expression to CASE statement.")
        
        categories = []
        for group in renderer_def.get("groups", []):
            for u_class in group.get("classes", []):
                try:
                    value = u_class["values"][0]["fieldValues"][0]
                    label = u_class.get("label", str(value))
                    symbol_def = u_class.get("symbol")
                    symbol = self.symbol_factory.create_symbol(symbol_def) or self._create_default_symbol(layer)
                    categories.append(QgsRendererCategory(value, symbol.clone(), label))
                except (KeyError, IndexError):
                    continue
        
        renderer = QgsCategorizedSymbolRenderer(qgis_case_expression, categories)
        
        if renderer_def.get("useDefaultSymbol", False):
            default_symbol_def = renderer_def.get("defaultSymbol")
            if default_symbol_def:
                default_symbol = self.symbol_factory.create_symbol(default_symbol_def)
                if default_symbol:
                    renderer.setSourceSymbol(default_symbol.clone())

        return renderer

    def _translate_arcade_to_case(self, arcade_expr: str) -> str:
        """
        Translates a full Arcade if/else if/else block into a QGIS CASE statement.
        """
        rules = self._parse_arcade_if_else(arcade_expr)
        if not rules:
            return ""

        case_parts = ["CASE"]
        
        else_rule = None
        if rules and rules[-1][0].lower() == 'true':
            else_rule = rules.pop()

        for condition, return_value in rules:
            qgis_condition = self._translate_arcade_condition_to_qgis(condition)
            case_parts.append(f"    WHEN {qgis_condition} THEN '{return_value}'")
    
        if else_rule:
            case_parts.append(f"    ELSE '{else_rule[1]}'")
    
        case_parts.append("END")
        
        full_expression = "\n".join(case_parts)
        logger.info(f"Translated Arcade to CASE statement:\n{full_expression}")
        return full_expression

    def _parse_arcade_if_else(self, expression: str) -> List[tuple]:
        """
        Parses an if/else if/else Arcade expression into a list of
        (condition, return_value) tuples. The 'else' case has a condition of 'True'.
        """
        rules = []
        pattern = re.compile(
            r"(?:if|else if)\s*\((.*?)\)\s*\{.*?return\s*['\"](.*?)['\"].*?\}",
            re.DOTALL | re.IGNORECASE
        )
        for match in pattern.finditer(expression):
            rules.append((match.group(1).strip(), match.group(2).strip()))
            
        else_pattern = re.compile(r"else\s*\{.*?return\s*['\"](.*?)['\"].*?\}", re.DOTALL | re.IGNORECASE)
        if else_match := else_pattern.search(expression):
            rules.append(('True', else_match.group(1).strip()))
            
        return rules

    def _translate_arcade_condition_to_qgis(self, condition: str) -> str:
        """
        Translates a single Arcade condition string into a QGIS expression string.
        """
        qgis_expr = re.sub(r"\$feature\.(\w+)", r'"\1"', condition)
        qgis_expr = qgis_expr.replace("&&", "AND").replace("||", "OR")
        qgis_expr = qgis_expr.replace("==", "=")
        return qgis_expr
        
    def _create_categorized_renderer(self, renderer_def: Dict[str, Any],
                                     layer: QgsVectorLayer) -> QgsCategorizedSymbolRenderer:
        """
        Creates a QGIS categorized renderer from a CIMUniqueValueRenderer definition
        that uses a simple field, not an expression.
        """
        field_names = renderer_def.get("fields", renderer_def.get("fieldNames", []))
        if not field_names:
            raise RendererCreationError("No 'fields' key found in the categorized renderer definition.")
        
        field_name = field_names[0]
        if len(field_names) > 1:
            logger.warning(f"Multiple fields found ({field_names}). Only the first, '{field_name}', will be used.")

        categories = []
        for group in renderer_def.get("groups", []):
            for u_class in group.get("classes", []):
                try:
                    value = u_class["values"][0]["fieldValues"][0]
                    label = u_class.get("label", str(value))
                    symbol_def = u_class.get("symbol")
                    symbol = self.symbol_factory.create_symbol(symbol_def) or self._create_default_symbol(layer)
                    categories.append(QgsRendererCategory(value, symbol, label))
                except (KeyError, IndexError):
                    continue
        
        renderer = QgsCategorizedSymbolRenderer(field_name, categories)
        
        # Handle the default symbol for values that don't match any category
        if renderer_def.get("useDefaultSymbol", False):
            default_symbol_def = renderer_def.get("defaultSymbol")
            if default_symbol_def:
                default_symbol = self.symbol_factory.create_symbol(default_symbol_def)
                renderer.setSourceSymbol(default_symbol)

        return renderer
    
    def _create_proportional_renderer(self, renderer_def: Dict[str, Any],
                                      layer: QgsVectorLayer) -> QgsSingleSymbolRenderer:
        """
        Creates a QGIS single symbol renderer with a data-defined size override
        from an ArcGIS CIMProportionalRenderer definition.
        """
        

        logger.info("Detected Proportional Renderer. Creating data-defined size override.")

        # 1. Create the base symbol (ArcGIS uses the 'minSymbol' as the template)
        base_symbol_def = renderer_def.get("minSymbol", {})
        base_symbol = self.symbol_factory.create_symbol(base_symbol_def)
        if not base_symbol:
            logger.warning("Could not create base symbol for proportional renderer. Using default.")
            base_symbol = self._create_default_symbol(layer)

        # 2. Extract sizing parameters from the JSON
        try:
            field = renderer_def.get("field")
            min_data = renderer_def.get("minDataValue")
            max_data = renderer_def.get("maxDataValue")
            
            # The min/max sizes are nested inside the 'visualVariables'
            visual_var = renderer_def["visualVariables"][0]
            min_size = visual_var.get("minSize")
            max_size = visual_var.get("maxSize")
            
            if None in [field, min_data, max_data, min_size, max_size]:
                raise KeyError("One or more required parameters for proportional sizing is missing.")

        except (KeyError, IndexError) as e:
            logger.error(f"Failed to parse proportional renderer definition: {e}")
            return QgsSingleSymbolRenderer(base_symbol) # Fallback to a simple renderer

        # 3. Build the QGIS expression for scaling
        # The format is: scale_linear(input, domain_min, domain_max, range_min, range_max)
        expression_string = f'scale_linear("{field}", {min_data}, {max_data}, {min_size}, {max_size})'
        logger.info(f"Generated size expression: {expression_string}")

        # 4. Apply the expression as a data-defined override for the symbol's size
        size_property = QgsProperty.fromExpression(expression_string)
        for i in range(base_symbol.symbolLayerCount()):
            symbol_layer = base_symbol.symbolLayer(i)
            symbol_layer.setDataDefinedProperty(QgsSymbolLayer.PropertySize, size_property)

        # 5. Create and return the single symbol renderer
        renderer = QgsSingleSymbolRenderer(base_symbol)
        self._apply_common_renderer_properties(renderer, renderer_def)
        return renderer
    
    def _create_heatmap_renderer(self, renderer_def: Dict[str, Any],
                                 layer: QgsVectorLayer) -> QgsHeatmapRenderer:
        """
        Creates a QGIS Heatmap renderer from an ArcGIS CIMHeatMapRenderer definition.
        
        NOTE: Creates a simplified two-color gradient due to API limitations
        in older QGIS versions.
        """
        logger.info("Detected Heat Map Renderer.")

        renderer = QgsHeatmapRenderer()

        # 1. Set the radius
        radius_points = renderer_def.get("radius", 10.0)
        renderer.setRadius(radius_points)
        renderer.setRadiusUnit(QgsUnitTypes.RenderPoints)

        # 2. Set the weight field (if one is used)
        weight_field = renderer_def.get("weightField")
        if weight_field:
            renderer.setWeightExpression(f'"{weight_field}"')
            logger.info(f"Set heatmap weight field to: {weight_field}")

        # 3. Parse the color ramp (Simplified for older QGIS versions)
        arc_color_scheme = renderer_def.get("colorScheme")
        if arc_color_scheme and arc_color_scheme.get("colorRamps"):
            color_ramp_segments = arc_color_scheme["colorRamps"]
            
            if color_ramp_segments:
                # Get the very first "from" color of the entire ramp
                start_color_def = color_ramp_segments[0].get("fromColor")
                start_color = parse_color(start_color_def)
                
                # Get the very last "to" color of the entire ramp
                end_color_def = color_ramp_segments[-1].get("toColor")
                end_color = parse_color(end_color_def)

                if start_color and end_color:
                    # Create a simple two-color gradient ramp
                    gradient_ramp = QgsGradientColorRamp(start_color, end_color)
                    renderer.setColorRamp(gradient_ramp)
                    logger.info("Created a simplified two-color gradient ramp (multi-stop not supported in this QGIS version).")

        # 4. Set render quality to maximum
        quality = renderer_def.get("rendererQuality", 4)
        renderer.setRenderQuality(quality)
        logger.info(f"Set heatmap render quality to {quality}.")
        
        return renderer
    
    def _create_graduated_renderer(self, renderer_def: Dict[str, Any], 
                                 layer: QgsVectorLayer) -> QgsGraduatedSymbolRenderer:
        """
        Create a QGIS graduated renderer from a CIMClassBreaksRenderer definition.
        
        Args:
            renderer_def: ArcGIS CIMClassBreaksRenderer definition
            layer: The target QGIS vector layer
            
        Returns:
            QgsGraduatedSymbolRenderer: The created renderer
        """
        # Get the field name for classification
        field_name = renderer_def.get("field")
        if not field_name:
            raise RendererCreationError("No field name found for class breaks renderer")
        
        # Validate field exists in layer
        if not self._validate_field_exists(layer, field_name):
            raise RendererCreationError(f"Field '{field_name}' not found in layer '{layer.name()}'")
        
        # Get class breaks
        breaks = renderer_def.get("breaks", [])
        if not breaks:
            logger.warning("No breaks found in class breaks renderer definition")
            return self._create_default_graduated_renderer(layer, field_name)
        
        # Sort breaks by upper bound to ensure proper ordering
        breaks = sorted(breaks, key=lambda b: b.get("upperBound", float("inf")))
        
        # Create ranges from breaks
        ranges = []
        min_value = renderer_def.get("minValue")
        if min_value is None:
            # Use the first break's lower bound or negative infinity
            min_value = breaks[0].get("lowerBound", float("-inf"))
        
        lower_bound = min_value
        
        for break_def in breaks:
            range_obj = self._create_renderer_range(break_def, lower_bound, layer)
            if range_obj:
                ranges.append(range_obj)
                lower_bound = break_def.get("upperBound", lower_bound)
        
        if not ranges:
            logger.warning("No valid ranges created, using default")
            return self._create_default_graduated_renderer(layer, field_name)
        
        # Create the renderer
        renderer = QgsGraduatedSymbolRenderer(field_name, ranges)
        
        # Set classification method if specified
        classification_method = renderer_def.get("classificationMethod", "")
        if classification_method:
            # Map ArcGIS classification methods to QGIS if needed
            # This is a future enhancement opportunity
            pass
        
        # Apply common renderer properties
        self._apply_common_renderer_properties(renderer, renderer_def)
        
        logger.info(f"Created graduated renderer for layer '{layer.name()}' with {len(ranges)} ranges")
        return renderer
    
    def _create_rule_based_renderer(self, renderer_def: Dict[str, Any], 
                                  layer: QgsVectorLayer) -> QgsRuleBasedRenderer:
        """
        Create a QGIS rule-based renderer from a CIMRuleBasedRenderer definition.
        
        This is a future enhancement - currently returns a default renderer.
        
        Args:
            renderer_def: ArcGIS CIMRuleBasedRenderer definition
            layer: The target QGIS vector layer
            
        Returns:
            QgsRuleBasedRenderer: The created renderer
        """
        logger.warning("Rule-based renderers not yet implemented, using default single symbol")
        return self._create_default_renderer(layer)
    
    def _create_renderer_category(self, uv_def: Dict[str, Any], 
                                layer: QgsVectorLayer) -> Optional[QgsRendererCategory]:
        """Create a QgsRendererCategory from a unique value definition."""
        try:
            value = uv_def.get("value")
            if value is None:
                logger.warning("No value found in unique value definition")
                return None
            
            label = uv_def.get("label", str(value))
            symbol_def = uv_def.get("symbol", {})
            
            symbol = self.symbol_factory.create_symbol(symbol_def)
            if not symbol:
                logger.warning(f"Failed to create symbol for value '{value}'")
                symbol = self._create_default_symbol(layer)
            
            return QgsRendererCategory(value, symbol, label)
            
        except Exception as e:
            logger.error(f"Failed to create renderer category: {e}")
            return None
    
    def _create_renderer_range(self, break_def: Dict[str, Any], lower_bound: float,
                             layer: QgsVectorLayer) -> Optional[QgsRendererRange]:
        """Create a QgsRendererRange from a class break definition."""
        try:
            upper_bound = break_def.get("upperBound")
            if upper_bound is None:
                logger.warning("No upper bound found in class break definition")
                return None
            
            label = break_def.get("label", f"{lower_bound} - {upper_bound}")
            symbol_def = break_def.get("symbol", {})
            
            symbol = self.symbol_factory.create_symbol(symbol_def)
            if not symbol:
                logger.warning(f"Failed to create symbol for range '{label}'")
                symbol = self._create_default_symbol(layer)
            
            return QgsRendererRange(lower_bound, upper_bound, symbol, label)
            
        except Exception as e:
            logger.error(f"Failed to create renderer range: {e}")
            return None
    
    def _validate_field_exists(self, layer: QgsVectorLayer, field_name: str) -> bool:
        """Validate that a field exists in the layer."""
        field_names = [field.name() for field in layer.fields()]
        return field_name in field_names
    
    def _create_default_symbol(self, layer: QgsVectorLayer):
        """Create a default symbol based on layer geometry type."""
        from qgis.core import QgsWkbTypes
        
        geom_type = layer.geometryType()
        
        if geom_type == QgsWkbTypes.PointGeometry:
            symbol = QgsMarkerSymbol()
        elif geom_type == QgsWkbTypes.LineGeometry:
            symbol = QgsLineSymbol()
        elif geom_type == QgsWkbTypes.PolygonGeometry:
            symbol = QgsFillSymbol()
        else:
            # Default to marker symbol
            symbol = QgsMarkerSymbol()
        
        return symbol
    
    def _create_default_renderer(self, layer: QgsVectorLayer) -> QgsSingleSymbolRenderer:
        """Create a default single symbol renderer."""
        symbol = self._create_default_symbol(layer)
        return QgsSingleSymbolRenderer(symbol)
    
    def _create_default_categorized_renderer(self, layer: QgsVectorLayer, 
                                           field_name: str) -> QgsCategorizedSymbolRenderer:
        """Create a default categorized renderer with basic categories."""
        categories = []
        default_symbol = self._create_default_symbol(layer)
        
        # Create a single "All other values" category
        categories.append(QgsRendererCategory("", default_symbol, "All other values"))
        
        return QgsCategorizedSymbolRenderer(field_name, categories)
    
    def _create_default_graduated_renderer(self, layer: QgsVectorLayer, 
                                         field_name: str) -> QgsGraduatedSymbolRenderer:
        """Create a default graduated renderer with basic ranges."""
        ranges = []
        default_symbol = self._create_default_symbol(layer)
        
        # Create a single range covering all values
        ranges.append(QgsRendererRange(float("-inf"), float("inf"), default_symbol, "All values"))
        
        return QgsGraduatedSymbolRenderer(field_name, ranges)
    
    def _apply_common_renderer_properties(self, renderer: QgsFeatureRenderer, 
                                        renderer_def: Dict[str, Any]):
        """Apply common properties that are available on all renderer types."""
        # Set ordering (if supported by renderer)
        if hasattr(renderer, 'setOrderBy'):
            order_by = renderer_def.get("orderBy")
            if order_by:
                # This would need more complex implementation to handle ArcGIS ordering
                pass
        
        # Set rotation field (for marker symbols)
        if hasattr(renderer, 'setRotationField'):
            rotation_field = renderer_def.get("rotationField")
            if rotation_field:
                renderer.setRotationField(rotation_field)
        
        # Set size scale field (for marker symbols)
        if hasattr(renderer, 'setSizeScaleField'):
            size_field = renderer_def.get("sizeField")
            if size_field:
                renderer.setSizeScaleField(size_field)


class RendererUtils:
    """Utility functions for working with renderers."""
    
    @staticmethod
    def get_renderer_summary(renderer: QgsFeatureRenderer) -> str:
        """Get a human-readable summary of a renderer."""
        if isinstance(renderer, QgsSingleSymbolRenderer):
            return "Single Symbol Renderer"
        elif isinstance(renderer, QgsCategorizedSymbolRenderer):
            return f"Categorized Renderer ({len(renderer.categories())} categories on '{renderer.classAttribute()}')"
        elif isinstance(renderer, QgsGraduatedSymbolRenderer):
            return f"Graduated Renderer ({len(renderer.ranges())} ranges on '{renderer.classAttribute()}')"
        elif isinstance(renderer, QgsRuleBasedRenderer):
            return f"Rule-based Renderer ({len(renderer.rootRule().children())} rules)"
        else:
            return f"Unknown Renderer Type: {type(renderer).__name__}"
    
    @staticmethod
    def validate_renderer_field(layer: QgsVectorLayer, field_name: str) -> bool:
        """Validate that a field exists and is suitable for rendering."""
        if not field_name:
            return False
        
        field = layer.fields().field(field_name)
        if not field.isValid():
            return False
        
        # Check if field has any values (basic validation)
        if layer.featureCount() == 0:
            return True  # Empty layer is valid
        
        # Could add more sophisticated validation here
        return True
    
    @staticmethod
    def copy_renderer_properties(source: QgsFeatureRenderer, target: QgsFeatureRenderer):
        """Copy common properties from one renderer to another."""
        if hasattr(source, 'rotationField') and hasattr(target, 'setRotationField'):
            target.setRotationField(source.rotationField())
        
        if hasattr(source, 'sizeScaleField') and hasattr(target, 'setSizeScaleField'):
            target.setSizeScaleField(source.sizeScaleField())


# Convenience functions for common renderer creation patterns
def create_simple_renderer(symbol, layer: QgsVectorLayer) -> QgsSingleSymbolRenderer:
    """Create a simple single symbol renderer."""
    return QgsSingleSymbolRenderer(symbol)


def create_categorized_renderer_from_values(layer: QgsVectorLayer, field_name: str, 
                                          values_symbols: Dict[Any, Any]) -> QgsCategorizedSymbolRenderer:
    """
    Create a categorized renderer from a dictionary of values and symbols.
    
    Args:
        layer: The target layer
        field_name: The field to categorize on  
        values_symbols: Dictionary mapping values to symbols {value: symbol}
    """
    categories = []
    for value, symbol in values_symbols.items():
        label = str(value)
        categories.append(QgsRendererCategory(value, symbol, label))
    
    return QgsCategorizedSymbolRenderer(field_name, categories)


def create_graduated_renderer_from_breaks(layer: QgsVectorLayer, field_name: str,
                                        breaks_symbols: List[tuple]) -> QgsGraduatedSymbolRenderer:
    """
    Create a graduated renderer from a list of breaks and symbols.
    
    Args:
        layer: The target layer
        field_name: The field to classify on
        breaks_symbols: List of tuples (lower, upper, symbol, label)
    """
    ranges = []
    for lower, upper, symbol, label in breaks_symbols:
        ranges.append(QgsRendererRange(lower, upper, symbol, label))
    
    return QgsGraduatedSymbolRenderer(field_name, ranges)