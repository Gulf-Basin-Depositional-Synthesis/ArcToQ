"""Vince's testing script with debugging.
    PowerShell
    CD to ArcToQ folder
    & "C:\Program Files\QGIS 3.40.10\bin\python-qgis-ltr.bat" .\tests\vince_test.py
"""

import sys
import os
from pathlib import Path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from qgis.core import (
    QgsApplication
)

from arc_to_q.converters.lyrx_converter import convert_lyrx


if __name__ == "__main__":
    
    output_folder = r"G:\Projects\QGIS Support\ArcToQ\tests\expected_qlr\polygon_unique_values"
    in_lyrx = r"G:\Projects\QGIS Support\ArcToQ\tests\test_data\polygon_unique_values\dummyfill.lyrx"

    qgs = QgsApplication([], False)
    qgs.initQgis()

    try:
        convert_lyrx(in_lyrx, output_folder, qgs)
    except Exception as e:
        print(f"oops: {e}")
    finally:
        qgs.exitQgis()

    print('done')