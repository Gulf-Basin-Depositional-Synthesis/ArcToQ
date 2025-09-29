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


def _get_lyrx_in_folder(folder, recursive=True):
    """Get all .lyrx files in a folder."""
    lyrx_files = []
    if recursive:
        for root, dirs, files in os.walk(folder):
            for file in files:
                if file.endswith('.lyrx'):
                    lyrx_files.append(os.path.join(root, file))
    else:
        for file in os.listdir(folder):
            if file.endswith('.lyrx'):
                lyrx_files.append(os.path.join(folder, file))
    return lyrx_files


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
    mag = r'D:\GBDS\Map_Layers\Basemap\Magnetic Anomaly.lyrx'
    tapestry = r'D:\GBDS\Map_Layers\Basemap\Tapestry of Time and Terrain.lyrx'
    utop_grid = r'D:\GBDS\Map_Layers\Data_For_Each_Unit\64_SH\Unit Top (seismic + wells).lyrx'
    test = r'D:\GBDS\Map_Layers\test.lyrx'

    layers = [
        test,
        # well_lyrx,
        # plss_lyrx,
        # tops_all_wells,
        # mag,
        # tapestry,
        # utop_grid,
        # ithk,
        # cthk,
        # sthk,
        # utop,
        # depo,
    ]

    layers = _get_lyrx_in_folder(r'D:\GBDS\Map_Layers', False)

    qgs = QgsApplication([], False)
    qgs.initQgis()

    try:
        for lyrx in layers:
            print(f"Processing {lyrx}...")
            convert_lyrx(lyrx, output_folder, qgs)
    except Exception as e:
        print(f"oops: {e}")
    finally:
        qgs.exitQgis()

    print('done')