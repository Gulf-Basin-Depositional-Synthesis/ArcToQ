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

## Installation & How To Use

The easiest way to use ArcToQ is through the native QGIS plugin

### 1. Install the Plugin
1. Download the latest **`ArcToQ.zip`** file from the [Releases page](https://github.com/Gulf-Basin-Depositional-Synthesis/ArcToQ/releases)
2. Open **QGIS**.
3. From the top menu, go to **Plugins > Manage and Install Plugins...**
4. Select the **Install from ZIP** tab on the left panel.
5. Click the `...` button to browse for the `ArcToQ.zip` file you downloaded, and click **Install Plugin**.

### 2. Convert a Layer
1. Click the new **"Convert LYRX to QLR"** button on your QGIS toolbar (you can also find it under the `Plugins` menu at the top).
2. A file browser will open. Select the ArcGIS `.lyrx` file you want to convert.
3. Choose the output directory where you want the new `.qlr` file to be saved.
4. The converter will run safely in the background. Once finished, a prompt will appear asking if you want to instantly load the converted layer directly into your current active map canvas.
