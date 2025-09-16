"""Tim's testing script.
    PowerShell
    CD to ArcToQ folder
    & "C:\Program Files\QGIS 3.40.10\bin\python-qgis-ltr.bat" .\tests\tim_test.py
"""

import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from qgis.core import (
    QgsApplication
)

from arc_to_q.converters.lyrx_converter import convert_lyrx


if __name__ == "__main__":
    output_folder = r'D:\GBDS\Map_Layers_QGIS'
    ithk_lyrx = r'D:\GBDS\Map_Layers\Data_For_Each_Unit\22_UM\Well Interval Thickness.lyrx'
    well_lyrx = r'D:\GBDS\Map_Layers\GBDS Well.lyrx'
    topo_lyrx = r'D:\GBDS\Map_Layers\Basemap\Topography and Bathmetry Contours.lyrx'  # [Feet]+ " ft (" + [Meters] + " m)"
    plss_lyrx = r'D:\GBDS\Map_Layers\Basemap\Public Land Survey System.lyrx'
    cnt_lyrx = r'D:\GBDS\Map_Layers\contour with expr.lyrx'
    pgeo = r'D:\GBDS\Map_Layers\Data_For_Each_Unit\22_UM\Paleogeography.lyrx'
    salt_lyrx = r'D:\GBDS\Map_Layers\salt_test.lyrx'
    anticline_lyrx = r'D:\GBDS\Map_Layers\anticline.lyrx'
    depo_lyrx = r'D:\GBDS\Map_Layers\Data_For_Each_Unit\10_PS\Well Depofacies.lyrx'

    layers = [
        cnt_lyrx,
        well_lyrx,
        salt_lyrx,
        depo_lyrx,
        anticline_lyrx,
        # pgeo,
        # plss_lyrx,
        ithk_lyrx,
        # topo_lyrx,
    ]

    qgs = QgsApplication([], False)
    qgs.initQgis()

    try:
        for lyrx in layers:
            convert_lyrx(lyrx, output_folder, qgs)
    except Exception as e:
        print(f"oops: {e}")
    finally:
        qgs.exitQgis()

    print('done')