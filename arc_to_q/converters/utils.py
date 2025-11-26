from colorsys import hsv_to_rgb
from typing import List, Dict, Any, Optional

from qgis.PyQt.QtGui import QColor

def parse_color(cim_color: Optional[Dict[str, Any]]) -> QColor:
    """
    Parse ArcGIS CIM color into QColor.
    Returns fully opaque black if parsing fails.
    """
    if not cim_color:
        return QColor(0, 0, 0, 255)

    # --- ArcGIS CIM dict form ---
    if isinstance(cim_color, dict) and "values" in cim_color:
        vals = cim_color["values"]
        ctype = cim_color.get("type", "")

        if ctype == "CIMRGBColor" and len(vals) >= 3:
            r, g, b = vals[0], vals[1], vals[2]
            a = vals[3] if len(vals) > 3 else 100
            return QColor(int(r), int(g), int(b), int(a * 2.55))

        elif ctype == "CIMHSVColor" and len(vals) >= 3:
            h, s, v = vals[0], vals[1], vals[2]
            a = vals[3] if len(vals) > 3 else 100
            # Convert HSV (degrees, %, %, %) to RGB 0–255
            r, g, b = hsv_to_rgb(h / 360.0, s / 100.0, v / 100.0)
            return QColor(int(r * 255), int(g * 255), int(b * 255), int(a * 2.55))

        elif ctype == "CIMCMYKColor" and len(vals) >= 4:
            # Simple CMYK to RGB conversion
            c, m, y, k = vals[0], vals[1], vals[2], vals[3]
            a = vals[4] if len(vals) > 4 else 100
            r = 255 * (1 - c / 100) * (1 - k / 100)
            g = 255 * (1 - m / 100) * (1 - k / 100)
            b = 255 * (1 - y / 100) * (1 - k / 100)
            return QColor(int(r), int(g), int(b), int(a * 2.55))

        elif ctype == "CIMLABColor" and len(vals) >= 3:
            L, a_val, b_val = vals[0], vals[1], vals[2]
            alpha = vals[3] if len(vals) > 3 else 100
            return _convert_lab_to_rgb(L, a_val, b_val, alpha)

        # Fallback: treat as RGB list if type is unknown but values exist
        elif len(vals) >= 3:
            return QColor(int(vals[0]), int(vals[1]), int(vals[2]))

    # --- Already a list/tuple ---
    elif isinstance(cim_color, (list, tuple)):
        if len(cim_color) >= 3:
            r, g, b = int(cim_color[0]), int(cim_color[1]), int(cim_color[2])
            a = int(cim_color[3]) if len(cim_color) > 3 else 255
            # If alpha is 0-100 (ArcGIS style list), scale it. If 0-255, keep it.
            # Heuristic: if it's exactly 100, might be percent. But QColor uses 0-255.
            # Safest to assume if it came from a raw list, it might already be QColor compatible, 
            # but ArcGIS lists usually use 0-255 for RGB and 0-100 for Alpha? 
            # Actually, raw lists in simple definitions often are [r,g,b,a].
            return QColor(r, g, b, a)

    # Default: opaque black
    return QColor(0, 0, 0, 255)


def _convert_lab_to_rgb(L, a, b, alpha):
    """Convert LAB color values to RGB QColor."""
    try:
        # LAB to XYZ conversion (D65 illuminant)
        fy = (L + 16.0) / 116.0
        fx = fy + (a / 500.0)
        fz = fy - (b / 200.0)
        
        def f_inv(t):
            delta = 6.0 / 29.0
            if t > delta:
                return t ** 3
            else:
                return 3 * (delta ** 2) * (t - 4.0 / 29.0)
        
        # XYZ values 
        X = 95.047 * f_inv(fx)
        Y = 100.000 * f_inv(fy)
        Z = 108.883 * f_inv(fz)
        
        # XYZ to RGB conversion (sRGB color space)
        X /= 100.0
        Y /= 100.0
        Z /= 100.0
        
        R = X * 3.2406 + Y * -1.5372 + Z * -0.4986
        G = X * -0.9689 + Y * 1.8758 + Z * 0.0415
        B = X * 0.0557 + Y * -0.2040 + Z * 1.0570
        
        def gamma_correct(c):
            if c > 0.0031308:
                return 1.055 * (c ** (1.0 / 2.4)) - 0.055
            else:
                return 12.92 * c
        
        R = gamma_correct(R)
        G = gamma_correct(G)
        B = gamma_correct(B)
        
        R = max(0, min(255, int(R * 255)))
        G = max(0, min(255, int(G * 255)))
        B = max(0, min(255, int(B * 255)))
        A = max(0, min(255, int(alpha * 2.55))) 
        
        return QColor(R, G, B, A)
    except Exception:
        return QColor(0, 0, 0, 255)
    

def extract_colors_from_ramp(color_ramp: Dict[str, Any]) -> List[QColor]:
    """
    Extract colors from an ArcGIS color ramp definition.
    Handles CIMMultipartColorRamp (lists) and CIMLinearContinuousColorRamp (start/end).
    """
    colors = []
    
    if not color_ramp:
        return colors
    
    ramp_type = color_ramp.get("type")

    # 1. Handle Continuous Ramp (The one failing in your JSON)
    if ramp_type == "CIMLinearContinuousColorRamp":
        from_color_def = color_ramp.get("fromColor")
        to_color_def = color_ramp.get("toColor")
        
        if from_color_def:
            colors.append(parse_color(from_color_def))
        if to_color_def:
            colors.append(parse_color(to_color_def))
            
        return colors

    # 2. Handle Multipart Color Ramps (e.g., complex gradients)
    elif "colorRamps" in color_ramp:
        sub_ramps = color_ramp.get("colorRamps", [])
        
        if sub_ramps:
            # Get the first color from the first ramp
            if sub_ramps[0].get("fromColor"):
                colors.append(parse_color(sub_ramps[0]["fromColor"]))
            
            # Get intermediate colors
            for ramp in sub_ramps[:-1]:
                if ramp.get("toColor"):
                    colors.append(parse_color(ramp["toColor"]))
            
            # Get the final color
            if sub_ramps[-1].get("toColor"):
                colors.append(parse_color(sub_ramps[-1]["toColor"]))
    
    # 3. Fallback: Prectral/Fixed (If encountered, try to find keys)
    elif "fromColor" in color_ramp and "toColor" in color_ramp:
        colors.append(parse_color(color_ramp["fromColor"]))
        colors.append(parse_color(color_ramp["toColor"]))

    return colors


def create_interpolated_colors(base_colors: List[QColor], num_needed: int) -> List[QColor]:
    """
    Create interpolated colors from a list of base colors.
    """
    if not base_colors:
        return []

    if num_needed <= len(base_colors):
        return base_colors[:num_needed]
    
    if len(base_colors) < 2:
        return base_colors * num_needed
    
    result_colors = []
    segments = len(base_colors) - 1
    colors_per_segment = (num_needed - 1) / segments
    
    for segment in range(segments):
        start_color = base_colors[segment]
        end_color = base_colors[segment + 1]
        
        if segment < segments - 1:
            segment_colors = int(colors_per_segment)
        else:
            segment_colors = num_needed - len(result_colors) - 1
        
        for i in range(segment_colors):
            ratio = i / max(1, segment_colors)
            interpolated = interpolate_single_color(start_color, end_color, ratio)
            result_colors.append(interpolated)
    
    result_colors.append(base_colors[-1])
    
    while len(result_colors) < num_needed:
        result_colors.append(base_colors[-1])
    
    return result_colors[:num_needed]


def interpolate_single_color(color1: QColor, color2: QColor, ratio: float) -> QColor:
    """Interpolate between two colors."""
    r = int(color1.red() + (color2.red() - color1.red()) * ratio)
    g = int(color1.green() + (color2.green() - color1.green()) * ratio)
    b = int(color1.blue() + (color2.blue() - color1.blue()) * ratio)
    a = int(color1.alpha() + (color2.alpha() - color1.alpha()) * ratio)
    return QColor(r, g, b, a)