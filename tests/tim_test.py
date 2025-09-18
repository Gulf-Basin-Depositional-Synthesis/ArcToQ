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

    ithk = r'D:\GBDS\Map_Layers\Data_For_Each_Unit\24_MM\Well Interval Thickness.lyrx'
    cthk = r'D:\GBDS\Map_Layers\Data_For_Each_Unit\54_PW\Well Carbonate Thickness.lyrx'
    sthk = r'D:\GBDS\Map_Layers\Data_For_Each_Unit\54_PW\Well Sandstone Thickness.lyrx'
    utop = r'D:\GBDS\Map_Layers\Data_For_Each_Unit\54_PW\Well Unit Top.lyrx'
    depo = r'D:\GBDS\Map_Layers\Data_For_Each_Unit\54_PW\Well Depofacies.lyrx'
    tops_all_wells = r'D:\GBDS\Map_Layers\Tops for All Wells.lyrx'
    well_lyrx = r'D:\GBDS\Map_Layers\GBDS Well.lyrx'
    plss_lyrx = r'D:\GBDS\Map_Layers\Basemap\Public Land Survey System.lyrx'
    braun_top = r'D:\GBDS\Map_Layers\1388_Top SH Qualifiers.lyrx'
    braun_iso = r'D:\GBDS\Map_Layers\1388_Iso PW.lyrx'
    pitman = r'D:\GBDS\Map_Layers\1421_LS_Rooted_Salt_Stock_Turtle_Structure_Pitman_USGS.lyrx'
    zarra = r'D:\GBDS\Map_Layers\Wilcox Isopach.lyrx'
    padilla_cuat = r'D:\GBDS\Map_Layers\Cuaternary_Pacific_Ocean_Crust.lyrx'
    padilla_iso = r'D:\GBDS\Map_Layers\PacificOceanCrust_Isochron.lyrx'
    topobathy = r'D:\GBDS\Map_Layers\Topography and Bathmetry Contours_8M.lyrx'
    off_collapsed = r'D:\GBDS\Map_Layers\off_collapsed.lyrx'
    on_expanded = r'D:\GBDS\Map_Layers\on_expanded.lyrx'

    layers = [
        # well_lyrx,
        # plss_lyrx,
        # tops_all_wells,
        # topobathy,
        # zarra,
        # padilla_cuat,
        # padilla_iso,
        off_collapsed,
        on_expanded,
        # ithk,
        # cthk,
        # sthk,
        # utop,
        # depo,
        # braun_top,
        # braun_iso,
        # pitman,
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