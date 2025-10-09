"""
Two-stage test for APRX conversion.

This script should be run from the QGIS Python environment.
It will automatically launch the ArcGIS environment for Stage 1 via subprocess.

Usage:
    & "C:\Program Files\QGIS 3.40.10\bin\python-qgis-ltr.bat" .\tests\test_aprx_converter.py
"""

import sys
import os
import subprocess
from pathlib import Path

# Add project to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from qgis.core import QgsApplication

# ============================================================================
# Configuration
# ============================================================================

# Paths to test
SAMPLE_APRX_PATH = r"G:\Working\Students\Undergraduate\For_Vince\ArcGIS_AddOn\ArcGISPaleo_AddOn\ArcGISPaleo_AddOn.aprx"
TEST_OUTPUT_DIR = r"G:\Projects\QGIS Support\test_results"

# Path to ArcGIS Pro Python
ARCGIS_PYTHON = r"C:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe"

# ============================================================================
# Stage 1: Extract (runs in ArcGIS environment via subprocess)
# ============================================================================

def run_extraction():
    """Run Stage 1 extraction in ArcGIS environment."""
    print("=" * 70)
    print("STAGE 1: Extracting from .aprx (ArcGIS Environment)")
    print("=" * 70)
    
    # Create inline Python script for extraction
    extraction_script = f'''
import sys
import os
sys.path.insert(0, r"{os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))}")

from arc_to_q.converters.aprx_converter import AprxExtractor

extractor = AprxExtractor(r"{SAMPLE_APRX_PATH}")
json_path = extractor.extract(r"{TEST_OUTPUT_DIR}")
print(f"JSON saved to: {{json_path}}")
'''
    
    # Run in ArcGIS Python subprocess
    result = subprocess.run(
        [ARCGIS_PYTHON, "-c", extraction_script],
        capture_output=True,
        text=True
    )
    
    print(result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr)
    
    if result.returncode != 0:
        raise RuntimeError(f"Extraction failed with code {result.returncode}")
    
    print("\n✓ Stage 1 complete\n")

# ============================================================================
# Stage 2: Build (runs in current QGIS environment)
# ============================================================================

def run_building():
    """Run Stage 2 building in QGIS environment."""
    print("=" * 70)
    print("STAGE 2: Building .qgz (QGIS Environment)")
    print("=" * 70)
    
    from arc_to_q.converters.aprx_converter import QgzBuilder
    
    # Find JSON file
    project_name = Path(SAMPLE_APRX_PATH).stem
    json_path = os.path.join(TEST_OUTPUT_DIR, f"{project_name}_data.json")
    
    if not os.path.exists(json_path):
        raise FileNotFoundError(f"JSON not found: {json_path}")
    
    # Build QGIS project
    builder = QgzBuilder()
    builder.build(json_path, TEST_OUTPUT_DIR)
    
    print("\n✓ Stage 2 complete\n")

# ============================================================================
# Main Test
# ============================================================================

def main():
    print("\n" + "=" * 70)
    print("APRX TO QGZ CONVERSION TEST")
    print("=" * 70)
    print(f"Input:  {SAMPLE_APRX_PATH}")
    print(f"Output: {TEST_OUTPUT_DIR}")
    print("=" * 70 + "\n")
    
    # Verify paths exist
    if not os.path.exists(SAMPLE_APRX_PATH):
        print(f"ERROR: APRX file not found: {SAMPLE_APRX_PATH}")
        return 1
    
    if not os.path.exists(ARCGIS_PYTHON):
        print(f"ERROR: ArcGIS Python not found: {ARCGIS_PYTHON}")
        print("Update ARCGIS_PYTHON path in this script.")
        return 1
    
    os.makedirs(TEST_OUTPUT_DIR, exist_ok=True)
    
    # Initialize QGIS (needed for Stage 2)
    qgs = QgsApplication([], False)
    qgs.initQgis()
    
    try:
        # Run Stage 1 (extraction)
        run_extraction()
        
        # Run Stage 2 (building)
        run_building()
        
        print("=" * 70)
        print("SUCCESS! Conversion complete.")
        print("=" * 70)
        
        # Verify output
        project_name = Path(SAMPLE_APRX_PATH).stem
        output_file = os.path.join(TEST_OUTPUT_DIR, f"{project_name}.qgz")
        if os.path.exists(output_file):
            size_mb = os.path.getsize(output_file) / (1024 * 1024)
            print(f"Output file: {output_file}")
            print(f"Size: {size_mb:.2f} MB")
        
        return 0
    
    except Exception as e:
        print("\n" + "=" * 70)
        print(f"ERROR: {e}")
        print("=" * 70)
        import traceback
        traceback.print_exc()
        return 1
    
    finally:
        qgs.exitQgis()

if __name__ == "__main__":
    sys.exit(main())