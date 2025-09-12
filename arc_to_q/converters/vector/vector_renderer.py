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
    QgsExpression
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
                return self._create_categorized_renderer(renderer_def, layer)
            elif renderer_type == "CIMClassBreaksRenderer":
                return self._create_graduated_renderer(renderer_def, layer)
            elif renderer_type == "CIMRuleBasedRenderer":
                return self._create_rule_based_renderer(renderer_def, layer)
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
    
    def _translate_arcade_if_else_to_case(self, arcade_expr: str) -> str:
        """
        Translates a specific pattern of Arcade if/else if/else expression
        into a QGIS CASE WHEN expression using regular expressions.
        """
        # Step 1: Extract the variable and field name (e.g., "var val = $feature.OBJECTID;")
        field_match = re.search(r"var\s+(?P<var>\w+)\s*=\s*\$feature\.(?P<field>\w+);", arcade_expr)
        if not field_match:
            logger.error("Could not find field name in Arcade expression.")
            return ""
        
        var_name = field_match.group('var')
        field_name = f'"{field_match.group('field')}"'
        
        # Step 2: Find all 'if' and 'else if' blocks and their return values
        pattern = re.compile(
            r"if\s*\((?P<condition>.*?)\)\s*\{\s*return\s*\"(?P<retval>.*?)\";\s*\}",
            re.DOTALL
        )
        matches = pattern.finditer(arcade_expr)

        # Step 3: Find the final 'else' block's return value
        else_match = re.search(r"else\s*\{\s*return\s*\"(.*?)\";\s*\}", arcade_expr, re.DOTALL)
        if not else_match:
            logger.error("Could not find final 'else' block in Arcade expression.")
            return ""

        # Step 4: Build the QGIS CASE statement from the extracted parts
        case_parts = ["CASE"]
        for match in matches:
            # Replace the Arcade variable with the QGIS field name and '&&' with 'AND'
            condition = match.group('condition').replace(var_name, field_name).replace("&&", "AND")
            retval = match.group('retval')
            case_parts.append(f"    WHEN {condition} THEN '{retval}'")
        
        case_parts.append(f"    ELSE '{else_match.group(1)}'")
        case_parts.append("END")
        
        return "\n".join(case_parts)
    
    def _create_categorized_renderer(self, renderer_def: Dict[str, Any], 
                                    layer: QgsVectorLayer) -> QgsFeatureRenderer:
        """
        Create a QGIS categorized or rule-based renderer from a CIMUniqueValueRenderer definition.
        
        If the renderer uses a simple field, it creates a QgsCategorizedSymbolRenderer.
        If it uses an Arcade expression, it translates the expression and creates a categorized renderer.
        """
        # --- HANDLE SIMPLE FIELD-BASED RENDERER (Unchanged) ---
        field_names = renderer_def.get("fieldNames", [])
        if field_names:
            if len(field_names) > 1:
                logger.warning(f"Multiple field names found: {field_names}. Only the first will be used.")
            
            field_name = field_names[0]
            if not self._validate_field_exists(layer, field_name):
                raise RendererCreationError(f"Field '{field_name}' not found in layer '{layer.name()}'")

            categories = []
            for uv_def in renderer_def.get("uniqueValues", []):
                category = self._create_renderer_category(uv_def, layer)
                if category:
                    categories.append(category)

            if not categories:
                return self._create_default_categorized_renderer(layer, field_name)
            
            renderer = QgsCategorizedSymbolRenderer(field_name, categories)
            default_symbol_def = renderer_def.get("defaultSymbol")
            if default_symbol_def:
                default_symbol = self.symbol_factory.create_symbol(default_symbol_def)
                if default_symbol:
                    renderer.setSourceSymbol(default_symbol)
            
            self._apply_common_renderer_properties(renderer, renderer_def)
            return renderer

        # --- NEW: DYNAMICALLY HANDLE ARCADE EXPRESSION ---
        expression_info = renderer_def.get("valueExpressionInfo")
        if expression_info:
            arcade_expr = expression_info.get("expression", "")
            qgis_expr = self._translate_arcade_if_else_to_case(arcade_expr)

            if not qgis_expr:
                raise RendererCreationError(f"Failed to translate Arcade expression: {arcade_expr}")
            
            logger.info("Successfully translated Arcade expression to a dynamic QGIS CASE statement.")

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
                        logger.warning(f"Could not parse a unique value class within group '{group.get('heading')}'. Skipping.")
                        continue
            
            if not categories:
                raise RendererCreationError("Found expression but failed to create any categories from 'groups'.")
            
            renderer = QgsCategorizedSymbolRenderer(qgis_expr, categories)
            
            default_symbol_def = renderer_def.get("defaultSymbol")
            if default_symbol_def and renderer_def.get("useDefaultSymbol"):
                default_symbol = self.symbol_factory.create_symbol(default_symbol_def)
                if default_symbol:
                    renderer.setSourceSymbol(default_symbol)

            self._apply_common_renderer_properties(renderer, renderer_def)
            return renderer

        raise RendererCreationError("No 'fieldNames' or 'valueExpressionInfo' key found in the renderer definition.")
    
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