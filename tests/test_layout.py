"""
Test script for Layout Conversion.

& "C:\Program Files\QGIS 3.40.10\bin\python-qgis-ltr.bat" .\tests\test_layout.py
"""
import sys
import os
# Adjust path to find your package
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from qgis.core import (
    QgsApplication, QgsVectorLayer, QgsProject, QgsLayoutExporter
)
from arc_to_q.converters.layout_converter import LayoutConverter

if __name__ == "__main__":
    # 1. Setup paths
    # Replace this with your actual exported .pagx file
    pagx_file = r"G:\Working\Students\Undergraduate\For_Vince\ArcGIS_AddOn\ArcGISPaleo_AddOn\Layout.pagx" 
    output_pdf = r"G:\Projects\QGIS Support\test_results"

    # 2. Init QGIS
    qgs = QgsApplication([], False)
    qgs.initQgis()
    project = QgsProject.instance()

    try:
        print("--- Starting Layout Test ---")

        # 3. "I have the layer needed in QGIS" - Create a Dummy Layer
        # This simulates your real workflow where you've already loaded data.
        layer = QgsVectorLayer("Point?crs=epsg:4326", "My Test Layer", "memory")
        if not layer.isValid():
            print("Error: Failed to create dummy layer.")
        else:
            project.addMapLayer(layer)
            print(f"Loaded dummy layer: {layer.name()}")

        # 4. Run Converter
        converter = LayoutConverter(pagx_file, project)
        layout = converter.convert()

        if layout:
            # 5. Export to PDF to verify visually
            exporter = QgsLayoutExporter(layout)
            result = exporter.exportToPdf(output_pdf, QgsLayoutExporter.PdfExportSettings())
            
            if result == QgsLayoutExporter.Success:
                print(f"SUCCESS: Layout exported to {output_pdf}")
            else:
                print(f"WARNING: Layout created, but PDF export failed code: {result}")
        else:
            print("ERROR: Layout conversion failed.")

    except Exception as e:
        print(f"CRASH: {e}")
        import traceback
        traceback.print_exc()

    finally:
        qgs.exitQgis()
        print("--- Done ---")