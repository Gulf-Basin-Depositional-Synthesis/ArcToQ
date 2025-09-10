from colorsys import hsv_to_rgb

from qgis.PyQt.QtGui import QColor


def parse_color(cim_color):
    """
    Parse ArcGIS CIM color into QColor.

    Supports:
      - CIMRGBColor: values = [R, G, B, A] (A in 0–100)
      - CIMHSVColor: values = [H, S, V, A] (H in degrees, S/V/A in 0–100)
      - List/Tuple: [R, G, B, A] or [R, G, B]

    Example CIM color dicts:
    "color" : {
        "type" : "CIMRGBColor",
        "values" : [
            169,
            0,
            230,
            100
        ]
    }

    "color" : {
        "type" : "CIMHSVColor",
        "values" : [
            360,
            100,
            100,
            100
        ]
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
