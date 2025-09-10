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
    in_lyrx = r'D:\GBDS\Map_Layers\GBDS Well.lyrx'

    qgs = QgsApplication([], False)
    qgs.initQgis()

    try:
        convert_lyrx(in_lyrx, output_folder, qgs)
    except Exception as e:
        print(f"oops: {e}")
    finally:
        qgs.exitQgis()

    print('done')