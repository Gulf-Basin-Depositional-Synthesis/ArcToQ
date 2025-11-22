"""
 APRX conversion test 

Run this TWICE:
1. First in ArcGIS Pro Python Command Prompt:
   cd G:\Projects\QGIS Support\ArcToQ
   python tests\test_aprx_converter.py

2. Then in QGIS:
   & "C:\Program Files\QGIS 3.40.10\bin\python-qgis-ltr.bat" .\tests\test_aprx_converter.py

The script auto-detects which environment it's in and runs the appropriate stage.
"""

import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# ============================================================================
# Configuration
# ============================================================================

APRX_PATH = r"G:\Working\Students\Undergraduate\For_Vince\ArcGIS_AddOn\ArcGISPaleo_AddOn\ArcGISPaleo_AddOn.aprx"
OUTPUT_FOLDER = r"G:\Projects\QGIS Support\test_results"

# ============================================================================
# Main
# ============================================================================

if __name__ == "__main__":
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)
    
    # Detect which environment we're in
    try:
        import arcpy
        print("\n" + "="*60)
        print("Detected: ArcGIS Pro Python Environment")
        print("Running: STAGE 1 (Extraction)")
        print("="*60 + "\n")
        
        from arc_to_q.converters.aprx_converter import AprxExtractor
        
        extractor = AprxExtractor(APRX_PATH)
        json_path = extractor.extract(OUTPUT_FOLDER)
        
        print("\n" + "="*60)
        print("✓ Stage 1 Complete!")
        print(f"Data saved to: {json_path}")
        print("\nNow run this script again in QGIS Python:")
        print('  & "C:\\Program Files\\QGIS 3.40.10\\bin\\python-qgis-ltr.bat" .\\tests\\test_aprx_converter.py')
        print("="*60 + "\n")
        
    except ImportError:
        try:
            from qgis.core import QgsApplication
            print("\n" + "="*60)
            print("Detected: QGIS Python Environment")
            print("Running: STAGE 2 (Building)")
            print("="*60 + "\n")
            
            qgs = QgsApplication([], False)
            qgs.initQgis()
            
            try:
                from arc_to_q.converters.aprx_converter import QgzBuilder
                
                # Find JSON file
                project_name = Path(APRX_PATH).stem
                json_path = os.path.join(OUTPUT_FOLDER, f"{project_name}_data.json")
                
                if not os.path.exists(json_path):
                    print(f"ERROR: JSON file not found: {json_path}")
                    print("\nYou need to run Stage 1 first in ArcGIS Pro Python:")
                    print("  python tests\\test_aprx_converter.py")
                    sys.exit(1)
                
                builder = QgzBuilder()
                builder.build(json_path, OUTPUT_FOLDER)
                
                output_file = os.path.join(OUTPUT_FOLDER, f"{project_name}.qgz")
                
                print("\n" + "="*60)
                print("✓ Stage 2 Complete!")
                print(f"QGIS project saved to: {output_file}")
                print("="*60 + "\n")
                
            finally:
                qgs.exitQgis()
                
        except ImportError:
            print("\nERROR: Could not import arcpy or qgis modules.")
            print("This script must be run in either:")
            print("  1. ArcGIS Pro Python Command Prompt, OR")
            print("  2. QGIS Python (via python-qgis-ltr.bat)")
            sys.exit(1)