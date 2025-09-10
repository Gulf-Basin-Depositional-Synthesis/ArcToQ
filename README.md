# ArcToQ

Python package to convert from ArcGIS to QGIS

ArcToQ converts ArcGIS formats (LYRX, APRX) to QGIS-compatible equivalents. It is designed for environments where both ArcGIS Pro and QGIS are installed.

This project is in its early stages, so don't expect working code of files that make sense yet.

## Features

- Convert ArcGIS Pro layer files (LYRX) to QGIS layer files (QLR)
- Convert ArcGIS Pro projects to QGIS projects

## Requirements

- ArcGIS Pro version 3.4 or greater (for arcpy)
- QGIS version 3.40 or greater (for PyQGIS)

## How To

Currently only one file works: our layer converter.

To convert layer files, run the layer converter from the QGIS Python environment, e.g., for Windows:

1. Start PowerShell.
2. cd to the **ArcToQ** folder.
3. Run your test script, e.g., `& "C:\Program Files\QGIS 3.40.10\bin\python-qgis-ltr.bat" .\tests\tim_test.py`
