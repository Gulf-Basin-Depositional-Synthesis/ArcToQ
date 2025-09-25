import re
from typing import List, Dict

def translate_arcade_expression(arcade_expr: str) -> str:
    """
    Translates any supported ArcGIS Arcade expression into a QGIS expression.
    This version handles variable declarations and substitutions.
    """
    if 'if' in arcade_expr.lower() and 'return' in arcade_expr.lower():
        return _translate_arcade_to_case(arcade_expr)
    else:
        return _translate_simple_arcade_with_vars(arcade_expr)

def _translate_simple_arcade_with_vars(arcade_expr: str) -> str:
    """
    Translates a simple Arcade expression, handling variable assignments.
    """
    lines = arcade_expr.strip().split(';')
    variables: Dict[str, str] = {}
    return_statement = ""

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Clean up comments
        line = re.sub(r'//.*', '', line).strip()

        # Handle variable assignments (e.g., "var x = $feature.Longitude * 0.017")
        if match := re.match(r'var\s+([a-zA-Z0-9_]+)\s*=\s*(.*)', line, re.IGNORECASE):
            var_name = match.group(1)
            var_value = match.group(2)
            
            # Translate any Arcade features/functions in the value
            translated_value = _translate_arcade_line(var_value)
            
            # Substitute any previously defined variables
            for prev_var, prev_val in variables.items():
                translated_value = re.sub(r'\b' + re.escape(prev_var) + r'\b', f'({prev_val})', translated_value)
            
            variables[var_name] = translated_value

        # Handle the final return statement
        elif line.lower().startswith('return'):
            return_statement = _translate_arcade_line(line.lower().replace('return', '').strip())

    if not return_statement:
        return ""

    # Substitute all found variables into the return statement
    final_expression = return_statement
    for var_name, var_value in variables.items():
        # Use regex for whole-word replacement to avoid replacing parts of other words
        final_expression = re.sub(r'\b' + re.escape(var_name) + r'\b', f'({var_value})', final_expression)

    return final_expression.strip()

def _translate_arcade_line(line: str) -> str:
    """Translates a single line of an Arcade expression."""
    # $feature.FieldName -> "FieldName"
    qgis_expr = re.sub(r"\$feature\.(\w+)", r'"\1"', line)
    # Functions (case-insensitive)
    qgis_expr = re.sub(r'Sin\(', 'sin(', qgis_expr, flags=re.IGNORECASE)
    qgis_expr = re.sub(r'Cos\(', 'cos(', qgis_expr, flags=re.IGNORECASE)
    qgis_expr = re.sub(r'Tan\(', 'tan(', qgis_expr, flags=re.IGNORECASE)
    return qgis_expr

# --- Functions for handling conditional (if/else) logic ---

def _translate_arcade_to_case(arcade_expr: str) -> str:
    """Translates a full Arcade if/else if/else block into a QGIS CASE statement."""
    rules = _parse_arcade_if_else(arcade_expr)
    if not rules: return ""
    
    case_parts = ["CASE"]
    else_rule = rules.pop() if rules and rules[-1][0].lower() == 'true' else None

    for condition, return_value in rules:
        qgis_condition = _translate_arcade_condition_to_qgis(condition)
        case_parts.append(f"    WHEN {qgis_condition} THEN '{return_value}'")
    if else_rule:
        case_parts.append(f"    ELSE '{else_rule[1]}'")
    case_parts.append("END")
    return "\n".join(case_parts)

def _parse_arcade_if_else(expression: str) -> List[tuple]:
    """Parses an if/else if/else Arcade expression into (condition, return_value) tuples."""
    rules = []
    pattern = re.compile(r"(?:if|else if)\s*\((.*?)\)\s*\{.*?return\s*['\"](.*?)['\"].*?\}", re.DOTALL | re.IGNORECASE)
    rules.extend((m.group(1).strip(), m.group(2).strip()) for m in pattern.finditer(expression))
    
    if else_match := re.search(r"else\s*\{.*?return\s*['\"](.*?)['\"].*?\}", expression, re.DOTALL | re.IGNORECASE):
        rules.append(('True', else_match.group(1).strip()))
    return rules

def _translate_arcade_condition_to_qgis(condition: str) -> str:
    """Translates a single Arcade condition string into a QGIS expression string."""
    qgis_expr = re.sub(r"\$feature\.(\w+)", r'"\1"', condition)
    return qgis_expr.replace("&&", "AND").replace("||", "OR").replace("==", "=")