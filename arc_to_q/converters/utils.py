from colorsys import hsv_to_rgb
from typing import List, Dict, Any

from qgis.PyQt.QtGui import QColor

def parse_color(cim_color):
    """
    Parse ArcGIS CIM color into QColor.

    Supports:
      - CIMRGBColor: values = [R, G, B, A] (A in 0–100)
      - CIMHSVColor: values = [H, S, V, A] (H in degrees, S/V/A in 0–100)
      - CIMLABColor: values = [L, a, b, A] (LAB color space with alpha 0–100)
      - List/Tuple: [R, G, B, A] or [R, G, B]

    Example CIM color dicts:
    "color" : {
        "type" : "CIMRGBColor",
        "values" : [169, 0, 230, 100]
    }

    "color" : {
        "type" : "CIMHSVColor",
        "values" : [360, 100, 100, 100]
    }
    
    "color" : {
        "type" : "CIMLABColor",
        "values" : [87.08, -50.27, -15.90, 100]
    }

    Returns fully opaque black if parsing fails.
    """
    if not cim_color:
        return QColor(0, 0, 0, 255)

    # --- ArcGIS CIM dict form ---
    if isinstance(cim_color, dict) and "values" in cim_color:
        vals = cim_color["values"]
        ctype = cim_color.get("type", "")

        if ctype == "CIMRGBColor" and len(vals) >= 4:
            r, g, b, a = vals[0], vals[1], vals[2], vals[3]
            return QColor(int(r), int(g), int(b), int(a * 2.55))

        elif ctype == "CIMHSVColor" and len(vals) >= 4:
            h, s, v, a = vals[0], vals[1], vals[2], vals[3]
            # Convert HSV (degrees, %, %, %) to RGB 0–255
            r, g, b = hsv_to_rgb(h / 360.0, s / 100.0, v / 100.0)
            return QColor(int(r * 255), int(g * 255), int(b * 255), int(a * 2.55))

        elif ctype == "CIMLABColor" and len(vals) >= 4:
            L, a, b, alpha = vals[0], vals[1], vals[2], vals[3]
            return _convert_lab_to_rgb(L, a, b, alpha)

        # Fallback: treat as RGB list
        elif len(vals) == 4:
            return QColor(int(vals[0]), int(vals[1]), int(vals[2]), int(vals[3] * 2.55))
        elif len(vals) == 3:
            return QColor(int(vals[0]), int(vals[1]), int(vals[2]))

    # --- Already a list/tuple ---
    elif isinstance(cim_color, (list, tuple)):
        if len(cim_color) == 4:
            return QColor(int(cim_color[0]), int(cim_color[1]), int(cim_color[2]), int(cim_color[3]))
        elif len(cim_color) == 3:
            return QColor(int(cim_color[0]), int(cim_color[1]), int(cim_color[2]))

    # Default: opaque black
    return QColor(0, 0, 0, 255)


def _convert_lab_to_rgb(L, a, b, alpha):
    """
    Convert LAB color values to RGB QColor.
    
    Args:
        L: Lightness (0-100)
        a: Green-Red axis (-128 to 127, typically)
        b: Blue-Yellow axis (-128 to 127, typically) 
        alpha: Alpha (0-100)
    
    Returns:
        QColor: Converted color
    """
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
        
        # XYZ values (relative to D65 illuminant)
        X = 95.047 * f_inv(fx)
        Y = 100.000 * f_inv(fy)
        Z = 108.883 * f_inv(fz)
        
        # XYZ to RGB conversion (sRGB color space)
        X /= 100.0
        Y /= 100.0
        Z /= 100.0
        
        R = X *  3.2406 + Y * -1.5372 + Z * -0.4986
        G = X * -0.9689 + Y *  1.8758 + Z *  0.0415
        B = X *  0.0557 + Y * -0.2040 + Z *  1.0570
        
        # Gamma correction for sRGB
        def gamma_correct(c):
            if c > 0.0031308:
                return 1.055 * (c ** (1.0 / 2.4)) - 0.055
            else:
                return 12.92 * c
        
        R = gamma_correct(R)
        G = gamma_correct(G)
        B = gamma_correct(B)
        
        # Clamp values to valid range and convert to 0-255
        R = max(0, min(255, int(R * 255)))
        G = max(0, min(255, int(G * 255)))
        B = max(0, min(255, int(B * 255)))
        A = max(0, min(255, int(alpha * 2.55)))  # Convert 0-100 to 0-255
        
        return QColor(R, G, B, A)
        
    except Exception:
        # Return black if conversion fails
        return QColor(0, 0, 0, 255)
    
def extract_colors_from_ramp(color_ramp: Dict[str, Any]) -> List[QColor]:
        """
        Extract colors from an ArcGIS color ramp definition.
        Handles both single segment and multi-segment color ramps.
        """
        colors = []
        
        if not color_ramp:
            return colors
        
        # Handle multipart color ramps
        color_ramps = color_ramp.get("colorRamps", [])
        
        if color_ramps:
            # Get the first color from the first ramp
            if color_ramps[0].get("fromColor"):
                first_color = parse_color(color_ramps[0]["fromColor"])
                if first_color:
                    colors.append(first_color)
            
            # Get intermediate colors (to colors from each ramp except the last)
            for ramp in color_ramps[:-1]:
                if ramp.get("toColor"):
                    color = parse_color(ramp["toColor"])
                    if color:
                        colors.append(color)
            
            # Get the final color from the last ramp
            if color_ramps[-1].get("toColor"):
                last_color = parse_color(color_ramps[-1]["toColor"])
                if last_color:
                    colors.append(last_color)

        return colors

def create_interpolated_colors(base_colors: List[QColor], num_needed: int) -> List[QColor]:
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
                interpolated = interpolate_single_color(start_color, end_color, ratio)
                result_colors.append(interpolated)
        
        # Always add the final color
        result_colors.append(base_colors[-1])
        
        # Ensure we have exactly the right number of colors
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