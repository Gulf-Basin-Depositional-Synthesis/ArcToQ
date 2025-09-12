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
    QgsClassificationRange,
    QgsSimpleMarkerSymbolLayer,
    QgsSimpleFillSymbolLayer,
    QgsSimpleLineSymbolLayer

)
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtCore import Qt
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
        This now handles both standard class breaks and those using a discrete color ramp.
        """
        # --- Check for Unclassed (Continuous) renderer first ---
        if renderer_def.get("classBreakType") == "UnclassedColor":
            return self._create_unclassed_color_renderer(renderer_def, layer)

        # --- Proceed with standard discrete class breaks ---
        field_name = renderer_def.get("field")
        if not field_name:
            raise RendererCreationError("No field name found for class breaks renderer")
        if not self._validate_field_exists(layer, field_name):
            raise RendererCreationError(f"Field '{field_name}' not found in layer '{layer.name()}'")

        breaks = renderer_def.get("breaks", [])
        if not breaks:
            logger.warning("No breaks found in class breaks renderer definition")
            return self._create_default_graduated_renderer(layer, field_name)

        # --- Enhanced color ramp parsing for multi-color ramps ---
        discrete_colors = []
        color_ramp_def = renderer_def.get("colorRamp")
        
        if color_ramp_def and color_ramp_def.get("type") == "CIMMultipartColorRamp":
            logger.info("Parsing CIMMultipartColorRamp")
            color_ramp_segments = color_ramp_def.get("colorRamps", [])
            
            # For multi-color ramps with multiple segments, extract all unique colors
            all_colors = []
            for i, ramp_part in enumerate(color_ramp_segments):
                # Use the enhanced parse_color from utils
                from_color = parse_color(ramp_part.get("fromColor"))
                to_color = parse_color(ramp_part.get("toColor"))
                
                # Add fromColor (but avoid duplicates)
                if from_color and not self._color_already_exists(from_color, all_colors):
                    all_colors.append(from_color)
                
                # Add toColor (but avoid duplicates)  
                if to_color and not self._color_already_exists(to_color, all_colors):
                    all_colors.append(to_color)
            
            logger.info(f"Extracted {len(all_colors)} unique colors from ramp")
            
            # Now interpolate between these colors to create enough colors for all breaks
            if len(all_colors) >= 2:
                discrete_colors = self._create_interpolated_colors(all_colors, len(breaks))
                logger.info(f"Created {len(discrete_colors)} interpolated colors for {len(breaks)} breaks")

        # --- Alternative: Simple continuous color ramp ---
        elif color_ramp_def and color_ramp_def.get("type") == "CIMLinearContinuousColorRamp":
            logger.info("Parsing CIMLinearContinuousColorRamp")
            from_color = parse_color(color_ramp_def.get("fromColor"))
            to_color = parse_color(color_ramp_def.get("toColor"))
            if from_color and to_color:
                discrete_colors = self._interpolate_colors(from_color, to_color, len(breaks))
                logger.info(f"Interpolated {len(discrete_colors)} colors")

        # Fallback: extract from symbols if color ramp parsing failed
        if not discrete_colors:
            logger.info("Fallback: extracting colors from break symbols")
            for i, break_def in enumerate(breaks):
                symbol_def = break_def.get("symbol", {})
                symbol_color = self._extract_color_from_symbol_def(symbol_def)
                if symbol_color:
                    discrete_colors.append(symbol_color)

        logger.info(f"Final: Using {len(discrete_colors)} colors for {len(breaks)} breaks")

        # Create ranges from breaks
        ranges = []
        lower_bound = renderer_def.get("minimumBreak", 0.0)

        for i, break_def in enumerate(breaks):
            override_color = discrete_colors[i] if i < len(discrete_colors) else None
            range_obj = self._create_renderer_range(break_def, lower_bound, layer, override_color)
            if range_obj:
                ranges.append(range_obj)
            lower_bound = break_def.get("upperBound", lower_bound)

        if not ranges:
            return self._create_default_graduated_renderer(layer, field_name)

        renderer = QgsGraduatedSymbolRenderer(field_name, ranges)
        self._apply_common_renderer_properties(renderer, renderer_def)
        return renderer

    def _color_already_exists(self, color: QColor, color_list: List[QColor]) -> bool:
        """Check if a color already exists in the list (comparing RGB values)."""
        for existing_color in color_list:
            if (color.red() == existing_color.red() and 
                color.green() == existing_color.green() and 
                color.blue() == existing_color.blue()):
                return True
        return False

    def _create_interpolated_colors(self, base_colors: List[QColor], num_needed: int) -> List[QColor]:
        """
        Create interpolated colors from a list of base colors.
        """
        if num_needed <= len(base_colors):
            return base_colors[:num_needed]
        
        if len(base_colors) < 2:
            # Can't interpolate with less than 2 colors
            return base_colors * num_needed  # Repeat the colors
        
        result_colors = []
        segments = len(base_colors) - 1  # Number of segments between colors
        colors_per_segment = (num_needed - 1) / segments
        
        for segment in range(segments):
            start_color = base_colors[segment]
            end_color = base_colors[segment + 1]
            
            # Calculate how many colors this segment should contribute
            if segment < segments - 1:
                segment_colors = int(colors_per_segment)
            else:
                # Last segment gets any remaining colors
                segment_colors = num_needed - len(result_colors) - 1
            
            # Create interpolated colors for this segment
            for i in range(segment_colors):
                ratio = i / max(1, segment_colors)
                interpolated = self._interpolate_single_color(start_color, end_color, ratio)
                result_colors.append(interpolated)
        
        # Always add the final color
        result_colors.append(base_colors[-1])
        
        # Ensure we have exactly the right number of colors
        while len(result_colors) < num_needed:
            result_colors.append(base_colors[-1])
        
        return result_colors[:num_needed]

    def _interpolate_single_color(self, color1: QColor, color2: QColor, ratio: float) -> QColor:
        """Interpolate between two colors."""
        r = int(color1.red() + (color2.red() - color1.red()) * ratio)
        g = int(color1.green() + (color2.green() - color1.green()) * ratio)
        b = int(color1.blue() + (color2.blue() - color1.blue()) * ratio)
        a = int(color1.alpha() + (color2.alpha() - color1.alpha()) * ratio)
        return QColor(r, g, b, a)

    # Add this helper method to extract colors from symbol definitions
    def _extract_color_from_symbol_def(self, symbol_def: Dict[str, Any]) -> Optional[QColor]:
        """
        Extract color from a symbol definition for use in discrete color ramps.
        """
        try:
            # Look for color in symbol layers
            symbol_layers = symbol_def.get("symbolLayers", [])
            for layer in symbol_layers:
                if "color" in layer:
                    return self._parse_color_safe(layer["color"])
                # Also check for fill color in case it's nested differently
                if "fillColor" in layer:
                    return self._parse_color_safe(layer["fillColor"])
            return None
        except Exception as e:
            logger.debug(f"Could not extract color from symbol definition: {e}")
            return None
        
    def _create_unclassed_color_renderer(self, renderer_def: Dict[str, Any],
                                        layer: QgsVectorLayer) -> QgsGraduatedSymbolRenderer:
        """
        Creates a QGIS Graduated renderer to replicate ArcGIS's "Unclassed Colors"
        by creating a single range and instructing the renderer to apply a color ramp.
        """
        try:
            field = renderer_def.get("field")
            if not field:
                raise RendererCreationError("Field not specified for UnclassedColor renderer.")

            color_var = next((var for var in renderer_def.get("visualVariables", [])
                            if var.get("type") == "CIMColorVisualVariable"), None)
            if not color_var:
                raise RendererCreationError("CIMColorVisualVariable not found for UnclassedColor renderer.")

            min_value = color_var.get("minValue")
            max_value = color_var.get("maxValue")

            arc_color_ramps = color_var.get("colorRamp", {}).get("colorRamps", [])
            if not arc_color_ramps:
                raise RendererCreationError("Color ramp definition is missing.")

            # Use the enhanced parse_color from utils
            start_color = parse_color(arc_color_ramps[0].get("fromColor"))
            end_color = parse_color(arc_color_ramps[-1].get("toColor"))
            
            if not start_color or not end_color:
                raise RendererCreationError("Could not parse start or end color of the ramp.")

            qgis_color_ramp = QgsGradientColorRamp(start_color, end_color)

            # Create the base symbol
            base_symbol_def = renderer_def["breaks"][0]["symbol"]
            base_symbol = self.symbol_factory.create_symbol(base_symbol_def) or self._create_default_symbol(layer)

        except (KeyError, IndexError, TypeError) as e:
            logger.error(f"Failed to parse UnclassedColor renderer definition: {e}")
            return self._create_default_graduated_renderer(layer, renderer_def.get("field", ""))

        # Create renderer with single range and apply color ramp
        label = f"{min_value:.2f} - {max_value:.2f}"
        single_range = [QgsRendererRange(min_value, max_value, base_symbol, label)]
        renderer = QgsGraduatedSymbolRenderer(field, single_range)
        renderer.setSourceColorRamp(qgis_color_ramp)
        renderer.setGraduatedMethod(QgsGraduatedSymbolRenderer.GraduatedColor)
        renderer.updateColorRamp(qgis_color_ramp)

        return renderer
    
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
                            layer: QgsVectorLayer, override_color: QColor = None) -> Optional[QgsRendererRange]:
        """
        Create a QgsRendererRange from a class break definition.
        Includes improved color override logic with better debugging.
        """
        try:
            upper_bound = break_def.get("upperBound")
            if upper_bound is None:
                return None

            label = break_def.get("label", f"{lower_bound} - {upper_bound}")
            symbol_def = break_def.get("symbol", {})
            symbol = self.symbol_factory.create_symbol(symbol_def)
            if not symbol:
                symbol = self._create_default_symbol(layer)

            # --- Apply the override color with improved logic ---
            if override_color:
                logger.info(f"Applying override color {override_color.name()} to range {label}")
                
                # Clone the symbol to avoid modifying the original
                symbol = symbol.clone()
                
                # Apply color to all symbol layers
                for i in range(symbol.symbolLayerCount()):
                    symbol_layer = symbol.symbolLayer(i)
                    layer_type = type(symbol_layer).__name__
                    logger.debug(f"Processing symbol layer {i} of type: {layer_type}")
                    
                    # Handle different symbol layer types
                    if hasattr(symbol_layer, 'setColor'):
                        original_color = symbol_layer.color()
                        symbol_layer.setColor(override_color)
                        logger.debug(f"Set color from {original_color.name()} to {override_color.name()}")
                    
                    # Ensure outline/stroke is visible for filled symbols
                    if hasattr(symbol_layer, 'setStrokeColor') and hasattr(symbol_layer, 'strokeColor'):
                        current_stroke = symbol_layer.strokeColor()
                        # If stroke is transparent or the same as the old fill, make it visible
                        if current_stroke.alpha() == 0 or current_stroke == original_color:
                            # Set a contrasting outline color
                            if override_color.lightness() > 128:
                                outline_color = QColor(0, 0, 0, 255)  # Black outline for light fill
                            else:
                                outline_color = QColor(255, 255, 255, 255)  # White outline for dark fill
                            
                            symbol_layer.setStrokeColor(outline_color)
                            logger.debug(f"Set stroke color to {outline_color.name()}")
                            
                            # Make sure stroke style is solid
                            if hasattr(symbol_layer, 'setStrokeStyle'):
                                symbol_layer.setStrokeStyle(Qt.SolidLine)
                                logger.debug("Set stroke style to solid line")

            else:
                logger.debug(f"No override color provided for range {label}")

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


