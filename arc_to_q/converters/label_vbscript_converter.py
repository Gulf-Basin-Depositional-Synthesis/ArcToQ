import re
import html
from typing import List, Tuple, Callable, Optional

# -----------------------------
# Regex definitions (helpers)
# -----------------------------
FIELD_REF_RE = re.compile(r"\[([^\]\[]+)\]")    # [FieldName]
ASSIGN_RE = re.compile(r'^\s*(\w+)\s*=\s*(.+?)\s*$')

FUNCTION_START_RE = re.compile(r'^\s*Function\s+(\w+)\s*\((.*?)\)\s*$', re.IGNORECASE)
FUNCTION_END_RE = re.compile(r'^\s*End\s+Function\s*$', re.IGNORECASE)

# Conditionals
IF_RE = re.compile(r'^\s*If\s+(.+?)\s+Then\s*$', re.IGNORECASE)
ELSEIF_RE = re.compile(r'^\s*ElseIf\s+(.+?)\s+Then\s*$', re.IGNORECASE)
ELSE_RE = re.compile(r'^\s*Else\s*$', re.IGNORECASE)
END_IF_RE = re.compile(r'^\s*End\s+If\s*$', re.IGNORECASE)

# Select Case
SELECT_CASE_RE = re.compile(r'^\s*Select\s+Case\s+(.+?)\s*$', re.IGNORECASE)
CASE_RE = re.compile(r'^\s*Case\s+(.+?)\s*$', re.IGNORECASE)
END_SELECT_RE = re.compile(r'^\s*End\s+Select\s*$', re.IGNORECASE)

# Return (e.g., FindLabel = label)
RETURN_RE = re.compile(r'^\s*(\w+)\s*=\s*(\w+)\s*$')

# Quoted segments (on a single line)
QUOTED_ANY_RE = re.compile(r'(".*?"|\'.*?\')')
DOUBLE_QUOTED_RE = re.compile(r'"([^"]*)"')

# -----------------------------
# Core string transforms
# -----------------------------
def _unescape(s: str) -> str:
    """Decode HTML entities (e.g., &lt; &gt;)."""
    return html.unescape(s)

def _apply_outside_quotes(s: str, fn: Callable[[str], str]) -> str:
    """
    Apply a transformation function only to segments outside quoted strings.
    Preserves both "double-quoted" and 'single-quoted' segments as-is.
    """
    out = []
    pos = 0
    for m in QUOTED_ANY_RE.finditer(s):
        out.append(fn(s[pos:m.start()]))
        out.append(m.group(0))  # quoted segment unchanged
        pos = m.end()
    out.append(fn(s[pos:]))
    return ''.join(out)

def _convert_vb_double_quoted_strings_to_single(expr: str) -> str:
    """
    Convert VBScript string literals "..." into QGIS string literals '...'.
    (Run this BEFORE inserting field refs to avoid touching them.)
    """
    def repl(m):
        inner = m.group(1).replace("'", "''")  # escape single quotes for QGIS
        return f"'{inner}'"
    return DOUBLE_QUOTED_RE.sub(repl, expr)

def _to_qgis_field_refs(expr: str) -> str:
    """Convert [Field] -> \"Field\" (QGIS field reference)."""
    return FIELD_REF_RE.sub(r'"\1"', expr)

def _normalize_ops(expr: str) -> str:
    """Convert VBScript ops to QGIS ops OUTSIDE quotes."""
    def ops(seg: str) -> str:
        seg = re.sub(r'\s*&\s*', ' || ', seg)     # concat
        seg = seg.replace('<>', '!=')             # inequality
        seg = re.sub(r'\bAnd\b', ' AND ', seg, flags=re.IGNORECASE)
        seg = re.sub(r'\bOr\b', ' OR ', seg, flags=re.IGNORECASE)
        seg = re.sub(r'\bNot\b', ' NOT ', seg, flags=re.IGNORECASE)
        return seg
    return _apply_outside_quotes(expr, ops)

def _replace_identifier_outside_quotes(expr: str, name: str, replacement: str, already_prefixed_ok: bool = False) -> str:
    """
    Replace whole-word occurrences of 'name' with 'replacement' OUTSIDE quotes.
    If already_prefixed_ok=False, avoid replacing '@name'.
    """
    if already_prefixed_ok:
        pattern = re.compile(rf'\b{re.escape(name)}\b')
    else:
        pattern = re.compile(rf'(?<!@)\b{re.escape(name)}\b')
    def sub(seg: str) -> str:
        return pattern.sub(replacement, seg)
    return _apply_outside_quotes(expr, sub)

def _replace_scope_vars(expr: str, scope_vars: List[str]) -> str:
    """Replace all scoped variable identifiers with @vars (outside quotes)."""
    for v in sorted(set(scope_vars), key=len, reverse=True):
        expr = _replace_identifier_outside_quotes(expr, v, f'@{v}', already_prefixed_ok=False)
    return expr

def _vb_expr_to_qgis(expr: str, scope_vars: List[str]) -> str:
    """
    Convert a VB RHS into a QGIS RHS:
      - Unescape HTML entities
      - "..." -> '...'
      - [Field] -> "Field"
      - & -> ||, <> -> !=, And/Or/Not
      - Replace scoped variables with @vars (outside quotes)
    """
    expr = _unescape(expr)
    expr = _convert_vb_double_quoted_strings_to_single(expr)
    expr = _to_qgis_field_refs(expr)
    expr = _normalize_ops(expr)
    expr = _replace_scope_vars(expr, scope_vars)
    return expr.strip()

def _vb_expr_to_qgis_with_current(expr: str, scope_vars: List[str], var_name: str, current_expr: str) -> str:
    """
    Like _vb_expr_to_qgis, but if the RHS references the same variable (e.g., label = label & '/x'),
    we substitute that identifier with the CURRENT branch expression (not @label), so concatenations
    build on the branch's accumulated value.
    """
    expr = _unescape(expr)
    expr = _convert_vb_double_quoted_strings_to_single(expr)
    expr = _to_qgis_field_refs(expr)
    expr = _normalize_ops(expr)
    # First replace target variable with the branch's current expression
    expr = _replace_identifier_outside_quotes(expr, var_name, f'({current_expr})', already_prefixed_ok=False)
    # Then replace other scoped vars with @vars
    other_vars = [v for v in scope_vars if v != var_name]
    expr = _replace_scope_vars(expr, other_vars)
    return expr.strip()

# -----------------------------
# Select Case helpers
# -----------------------------
def _parse_case_values(token: str) -> List[str]:
    """Parse 'Case 1,2,"A"' -> ['1', '2', '\'A\'']."""
    parts = [p.strip() for p in token.split(',')]
    out = []
    for p in parts:
        if p.startswith('"') and p.endswith('"'):
            out.append("'" + p[1:-1].replace("'", "''") + "'")
        elif re.fullmatch(r'-?\d+(\.\d+)?', p):
            out.append(p)
        else:
            out.append("'" + p.replace("'", "''") + "'")
    return out

def _build_case_expr(selector: str, cases: List[Tuple[List[str], str]], var_name: str, else_expr: Optional[str] = None) -> str:
    lines = ["CASE"]
    for values, rhs in cases:
        cond = f'{selector} = {values[0]}' if len(values) == 1 else f'{selector} IN ({", ".join(values)})'
        lines.append(f'  WHEN {cond} THEN {rhs}')
    lines.append(f'  ELSE {else_expr if else_expr is not None else f"@{var_name}"}')
    lines.append("END")
    return "\n".join(lines)

def _parse_if_block(lines: List[str], start: int, var_name: str, scope_vars: List[str], base_rhs: str) -> Tuple[str, int]:
    """
    Parse a single 'If <cond> Then ... End If' inside a case/branch.
    Returns a CASE WHEN that updates var_name, building on base_rhs.
    """
    m = IF_RE.match(lines[start])
    if not m:
        raise ValueError("Expected If ... Then")
    cond_qgis = _vb_expr_to_qgis(m.group(1).strip(), scope_vars)
    i = start + 1
    rhs_expr = base_rhs
    while i < len(lines) and not END_IF_RE.match(lines[i]):
        line = lines[i].strip()
        if not line:
            i += 1; continue
        if IF_RE.match(line):  # nested If
            nested, i = _parse_if_block(lines, i, var_name, scope_vars, base_rhs=rhs_expr)
            rhs_expr = nested
            continue
        ma = ASSIGN_RE.match(line)
        if ma and ma.group(1) == var_name:
            rhs_expr = _vb_expr_to_qgis_with_current(ma.group(2), scope_vars, var_name, rhs_expr)
            i += 1; continue
        i += 1
    if i < len(lines) and END_IF_RE.match(lines[i]):
        i += 1
    return f'CASE WHEN {cond_qgis} THEN {rhs_expr} ELSE {base_rhs} END', i

def _parse_case_branch_body(lines: List[str], start: int, var_name: str, scope_vars: List[str], base_rhs: str) -> Tuple[str, int]:
    """
    Parse one Case body:
      - may include direct assignment:    var = <...>
      - may include nested If ... End If
      - may include self-referential updates (var += ...)
    Returns (rhs_expr, next_index)
    """
    i = start
    rhs = base_rhs
    while i < len(lines) and not (CASE_RE.match(lines[i]) or END_SELECT_RE.match(lines[i])):
        line = lines[i].strip()
        if not line:
            i += 1; continue
        if IF_RE.match(line):
            nested_rhs, i = _parse_if_block(lines, i, var_name, scope_vars, base_rhs=rhs)
            rhs = nested_rhs
            continue
        ma = ASSIGN_RE.match(line)
        if ma and ma.group(1) == var_name:
            rhs = _vb_expr_to_qgis_with_current(ma.group(2), scope_vars, var_name, rhs)
            i += 1; continue
        i += 1
    return rhs, i

def _parse_select_case_block(lines: List[str], start: int, var_name: str, scope_vars: List[str]) -> Tuple[str, int]:
    m = SELECT_CASE_RE.match(lines[start])
    if not m:
        raise ValueError("Expected Select Case")
    selector_qgis = _vb_expr_to_qgis(m.group(1).strip(), scope_vars)
    i = start + 1

    cases: List[Tuple[List[str], str]] = []
    else_rhs = None

    while i < len(lines):
        line = lines[i]
        if END_SELECT_RE.match(line):
            i += 1
            break
        cm = CASE_RE.match(line)
        if cm:
            token = cm.group(1).strip()
            if token.lower() == 'else':
                rhs, i = _parse_case_branch_body(lines, i + 1, var_name, scope_vars, base_rhs=f'@{var_name}')
                else_rhs = rhs
            else:
                values = _parse_case_values(token)
                rhs, i = _parse_case_branch_body(lines, i + 1, var_name, scope_vars, base_rhs=f'@{var_name}')
                cases.append((values, rhs))
            continue
        i += 1

    case_expr = _build_case_expr(selector_qgis, cases, var_name, else_expr=else_rhs)
    return case_expr, i

# -----------------------------
# If / ElseIf / Else chain
# -----------------------------
def _parse_if_chain(lines: List[str], start: int, var_name: str, scope_vars: List[str], base_rhs: str) -> Tuple[str, int]:
    """
    Parse:
        If cond1 Then  ... (updates to var_name)
        ElseIf cond2 Then ...
        Else ...
        End If
    Compose into a CASE WHEN chain which updates var_name based on base_rhs.
    """
    m = IF_RE.match(lines[start])
    if not m:
        raise ValueError("Expected If ... Then")
    branches: List[Tuple[str, str]] = []
    i = start

    def parse_branch_body(j: int, current_base: str) -> Tuple[str, int]:
        rhs = current_base
        while j < len(lines) and not (ELSEIF_RE.match(lines[j]) or ELSE_RE.match(lines[j]) or END_IF_RE.match(lines[j])):
            line = lines[j].strip()
            if not line:
                j += 1; continue
            if IF_RE.match(line):  # nested If
                nested, j = _parse_if_block(lines, j, var_name, scope_vars, base_rhs=rhs)
                rhs = nested
                continue
            ma = ASSIGN_RE.match(line)
            if ma and ma.group(1) == var_name:
                rhs = _vb_expr_to_qgis_with_current(ma.group(2), scope_vars, var_name, rhs)
                j += 1; continue
            j += 1
        return rhs, j

    # initial If
    m_if = IF_RE.match(lines[i]); i += 1
    cond_if = _vb_expr_to_qgis(m_if.group(1).strip(), scope_vars)
    rhs_if, i = parse_branch_body(i, base_rhs)
    branches.append((cond_if, rhs_if))

    # zero or more ElseIf
    while i < len(lines) and ELSEIF_RE.match(lines[i]):
        m_ei = ELSEIF_RE.match(lines[i]); i += 1
        cond_ei = _vb_expr_to_qgis(m_ei.group(1).strip(), scope_vars)
        rhs_ei, i = parse_branch_body(i, base_rhs)
        branches.append((cond_ei, rhs_ei))

    # optional Else
    else_rhs = base_rhs
    if i < len(lines) and ELSE_RE.match(lines[i]):
        i += 1
        else_rhs, i = parse_branch_body(i, base_rhs)

    # End If
    if i < len(lines) and END_IF_RE.match(lines[i]):
        i += 1

    # Build CASE chain
    out_lines = ["CASE"]
    for cond, rhs in branches:
        out_lines.append(f"  WHEN {cond} THEN {rhs}")
    out_lines.append(f"  ELSE {else_rhs}")
    out_lines.append("END")
    return "\n".join(out_lines), i


def _parse_findlabel(text: str) -> str:
    raw_lines = [l.rstrip() for l in text.splitlines()]

    # Skip Function signature if present; drop End Function
    i = 0
    if raw_lines and FUNCTION_START_RE.match(raw_lines[0]):
        i = 1
    lines = [l for l in raw_lines if not FUNCTION_END_RE.match(l)]

    # Gather initial assignments (in order) until first conditional
    inits: List[Tuple[str, str]] = []
    while i < len(lines):
        s = lines[i].strip()
        if not s:
            i += 1; continue
        if IF_RE.match(s) or SELECT_CASE_RE.match(s):
            break
        ma = ASSIGN_RE.match(s)
        if ma:
            inits.append((ma.group(1), ma.group(2)))
            i += 1; continue
        i += 1

    if not inits:
        raise ValueError("No initial assignments found.")

    # Target variable = last assigned variable
    var_name = inits[-1][0]
    scope_vars = [name for name, _ in inits]

    # Build with_variable wrappers for all initial variables
    init_wrappers: List[Tuple[str, str]] = []
    for name, rhs in inits:
        rhs_qgis = _vb_expr_to_qgis(rhs, scope_vars)
        init_wrappers.append((name, rhs_qgis))

    # Parse updates from conditionals
    updates: List[str] = []
    while i < len(lines):
        s = lines[i]
        if IF_RE.match(s):
            update, i = _parse_if_chain(lines, i, var_name, scope_vars, base_rhs=f'@{var_name}')
            updates.append(update)
            continue
        if SELECT_CASE_RE.match(s):
            update, i = _parse_select_case_block(lines, i, var_name, scope_vars)
            updates.append(update)
            continue
        if RETURN_RE.match(s):  # e.g., FindLabel = var
            i += 1; continue
        i += 1

    # Construct final expression: wrap initial vars, apply sequential updates to target var, return @var_name
    expr = f'@{var_name}'
    for upd in reversed(updates):
        expr = f"with_variable('{var_name}', {upd}, {expr})"
    for name, rhs_qgis in reversed(init_wrappers):
        expr = f"with_variable('{name}', {rhs_qgis}, {expr})"

    return expr


# def _parse_simple_expression(text: str) -> str:
#     expr = text.strip()

#     # Replace VBScript string literals "..." -> '...'
#     expr = re.sub(r'"([^"]*)"', r"'\1'", expr)

#     # Replace VBScript field refs [Field] -> "Field"
#     expr = re.sub(r"\[([A-Za-z0-9_]+)\]", r'"\1"', expr)

#     # Replace concatenation (& or +) with QGIS ||
#     expr = expr.replace("&", "||")
#     expr = re.sub(r"\+", "||", expr)   # catch stray +

#     return expr.strip()


import re

def _parse_simple_expression(text: str) -> str:
    expr = text.strip()

    # Handle escaped double quotes \" -> '
    expr = expr.replace(r'\"', "'")

    # Replace VBScript string literals "..." with '...'
    # But if it's a single quote inside double quotes (like "'"), 
    # turn it into '\'' so QGIS reads it as a single quote character.
    def repl_string(m):
        inner = m.group(1)
        if inner == "'":
            return r"'\''"   # special case: literal single quote
        return f"'{inner}'"

    expr = re.sub(r'"([^"]*)"', repl_string, expr)

    # Replace VBScript field refs [Field] -> "Field"
    expr = re.sub(r"\[([A-Za-z0-9_]+)\]", r'"\1"', expr)

    # Replace concatenation (& or +) with QGIS ||
    expr = re.sub(r"\s*&\s*", "||", expr)  # clean spacing around &
    expr = re.sub(r"\s*\+\s*", "||", expr) # clean spacing around +

    return expr.strip()


def _parse_field_name(text: str) -> str:
    # Remove brackets used in VBScript for field names
    text = text.replace("[", "").replace("]", "")
    # If "." in expression, it might be a table.field reference; remove table prefix
    if "." in text:
        text = text.split(".")[-1]
    return text


# -----------------------------
# Public API
# -----------------------------
def convert_label_expression(vb_expr: str) -> str:
    """
    Convert a VBScript ArcGIS label expression to a QGIS label expression.

    Supported features (tailored to provided examples):
      - Function wrapper (ignored)
      - Multiple initial assignments -> nested with_variable('<name>', <rhs>, ...)
      - Top-level If / ElseIf / Else (with nested If/End If in branches)
      - Select Case (with multiple comma-separated values and Case Else)
      - Field references [Field] -> "Field"
      - Strings "..." -> '...'
      - Operators: & -> ||, <> -> !=, And/Or/Not
      - Self-referential updates within branches: var = var || '...' are accumulated

    Returns:
      - The QGIS expression string
      - A boolean indicating whether the expression is complex (True) or a simple field name (False)
    """
    text = _unescape(vb_expr).strip()
    if text.startswith('Function FindLabel'):
        # Advanced function
        return _parse_findlabel(text), True
    elif ' ' in text:
        # Assume a simple expression
        return _parse_simple_expression(text), True
    else:
        # Assume a single field name
        return _parse_field_name(text), False


if __name__ == "__main__":
    cthk = r'''
Function FindLabel ( [WellData_CarbThk], [WellData_Penetration], [WellData_GeoSetting], [WellData_Carbonate] )
  t = [WellData_CarbThk]
  Select Case [WellData_Penetration]
    Case 1500
      t = t & "g+"
    Case 3444
      t = t & "c+"
    Case 7666
      If t <> 0 Then
        t = "<" & t
      End If
    Case 1222,3144
      t = t & "+"
    Case 1599
      t = ">1"
    Case 1333
      t = t & "f+"
    Case 1444
      t = t & "s+"
    Case 1666
      t = t & "f-"
    Case 1777
      t = t & "r+"
    Case 1888
      t = t & "t+"
    Case 1999
      t = t & "Lp+"
    Case 9001
      t = "lp"
    Case 9002
      t = "0tr"
    Case 9003
      t = "0f"
    Case 9999
      t = "0"
  End Select
  Select Case [WellData_GeoSetting]
    Case 1
      t = t & ",a"
    Case 2
      t = t & ",b"
    Case 3
      t = t & ",se"
    Case 11
      t = t & ",rs"
    Case 12
      t = t & ",cp"
    Case 13
      t = t & ",so"
  End Select
  Select Case [WellData_Carbonate]
    Case 1
      t = t & ",d"
    Case 2
      t = t & ",da"
    Case 3
      t = t & ",lda"
    Case 4
      t = t & ",ld"
    Case 5
      t = t & ",la"
    Case 6
      t = t & ",l"
    Case 7
      t = t & ",c"
    Case 8
      t = t & ",a"
  End Select
  FindLabel = t 
End Function
'''.strip()
    depo = r'''
Function FindLabel ( [WellData_Depofacies1], [WellData_Depofacies2] , [WellData_Depofacies3], [WellData_Penetration] )
  d1 = [WellData_Depofacies1]
  d2 = [WellData_Depofacies2]
  d3 = [WellData_Depofacies3]
  pen = [WellData_Penetration]
  label = d1
  If pen = 9001 Then
    label = "(lp)"
  ElseIf pen = 9002 Then
    label = "(tr)"
  ElseIf pen = 9003 Then
    label = "(f)"
  ElseIf pen = 9999 Then
    label = "(m)"
  ElseIf d2 <> "-" Then
      label = d1 & "/" & d2
      if d3 <> "-" Then
        label = label & "/" & d3
      End If
  End If
  FindLabel = label
End Function'''
    ithk = r'''
Function FindLabel ( [WellData_UnitThk], [WellData_Penetration], [WellData_GeoSetting] )
  t = [WellData_UnitThk]
  Select Case [WellData_Penetration]
    Case 3444
      t = t & "c+"
    Case 7666
      t = "<" & t
    Case 1222
      t = t & "+"
    Case 1599
      t = ">1"
    Case 1333
      t = t & "f+"
    Case 1444
      t = t & "s+"
    Case 1666
      t = t & "f-"
    Case 1777
      t = t & "r+"
    Case 1888
      t = t & "t+"
    Case 1999
      t = t & "Lp+"
    Case 9001
      t = "lp"
    Case 9002
      t = "0tr"
    Case 9003
      t = "0f"
    Case 9999
      t = "0"
  End Select
  Select Case [WellData_GeoSetting]
    Case 1
      t = t & ",a"
    Case 2
      t = t & ",b"
    Case 3
      t = t & ",se"
    Case 11
      t = t & ",rs"
    Case 12
      t = t & ",cp"
    Case 13
      t = t & ",so"
  End Select
  FindLabel = t 
End Function
'''.strip()
    sthk = r'''
    Function FindLabel ( [WellData_SandThk], [WellData_Penetration], [WellData_GeoSetting] )
  t = [WellData_SandThk]
  Select Case [WellData_Penetration]
    Case 1500
      t = t & "g+"
    Case 3444
      t = t & "c+"
    Case 7666
      If t <> 0 Then
        t = "<" & t
      End If
    Case 1222,3144
      t = t & "+"
    Case 1599
      t = ">1"
    Case 1333
      t = t & "f+"
    Case 1444
      t = t & "s+"
    Case 1666
      t = t & "f-"
    Case 1777
      t = t & "r+"
    Case 1888
      t = t & "t+"
    Case 1999
      t = t & "Lp+"
    Case 9001
      t = "lp"
    Case 9002
      t = "0tr"
    Case 9003
      t = "0f"
    Case 9999
      t = "0"
  End Select
  Select Case [WellData_GeoSetting]
    Case 1
      t = t & ",a"
    Case 2
      t = t & ",b"
    Case 3
      t = t & ",se"
    Case 11
      t = t & ",rs"
    Case 12
      t = t & ",cp"
    Case 13
      t = t & ",so"
  End Select
  FindLabel = t 
End Function
'''.strip()
    utop = r'''
Function FindLabel ( [WellData_TopElev], [WellData_Penetration], [WellData_GeoSetting]  )
  t =  [WellData_TopElev] 
  Select Case [WellData_Penetration]
    Case 7666
      t = t & "u"
    Case 9001
      t = t & " lp"
    Case 9002
      t = t & "tr"
    Case 9003
      t = t & "f"
    Case 9999
      t = t & "m"
  End Select
  Select Case [WellData_GeoSetting]
    Case 12
      t = t & ",cp"
  End Select
  FindLabel = t
End Function
'''.strip()
    tops_all_wells = r'''
Function FindLabel ( [WellData_TopElev], [WellData_Penetration]  )
  t =  [WellData_TopElev] 
  Select Case [WellData_Penetration]
    Case 9001
      t = "lp"
    Case 9999
      t = "m"
  End Select
  FindLabel = t
End Function
'''.strip()
    braun_iso = r'''
Function FindLabel ( [Iso_PW],[Iso_PW_Q]  )
  t = [Iso_PW]
  if [Iso_PW_Q] = "gt" then
    t = t & "+"
  end if
  FindLabel = t
End Function
'''.strip()
    braun_top = r'''
Function FindLabel ( [Top_SH_SS] )
  t = [Top_SH_SS]
  if t = "-1" then
    t = "not penetrated"
  elseif t = "-2" then
    t = "lapout"
  else
    t = ""
  end if
  FindLabel = t
End Function
'''.strip()
    pitman = r'''
Function FindLabel ( [NAME] )
  x = [NAME]
  If x = "Salt Dome" Then
      x = ""
  End If
  FindLabel = x
End Function

'''.strip()
    topobathy = r'[Feet]+ " ft (" + [Meters] + " m)"'
    zarra = r"[Thickness] & \"'\""
    padilla_cuat = '"Continental crust under Neogene cover - " & [Label]'
    padilla_iso = '[Name]  & "   " & [Isochron]'
    result, is_complex = convert_label_expression(topobathy)
    print(result)
    result, is_complex = convert_label_expression(padilla_cuat)
    print(result)
    result, is_complex = convert_label_expression(padilla_iso)
    print(result)
    result, is_complex = convert_label_expression(zarra)
    print(result)
