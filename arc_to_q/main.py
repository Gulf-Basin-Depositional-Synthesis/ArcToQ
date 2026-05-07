import sys
import os
import subprocess
import glob
import argparse

# Ensure the parent directory is in the path so arc_to_q imports work
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

def find_qgis_python_exec():
    """Attempt to find the QGIS python executable across different OS."""
    search_paths = []
    
    if sys.platform == "darwin":
        # macOS paths
        search_paths = [
            "/Applications/QGIS*.app/Contents/MacOS/bin/python3",
            "/Applications/QGIS*.app/Contents/MacOS/python",
        ]
    elif sys.platform.startswith("linux"):
        # Linux paths - often just the system python3 if qgis is installed system-wide
        search_paths = [
            "/usr/bin/python3",
        ]
    else:
        # Windows paths
        search_paths = [
            r"C:\Program Files\QGIS *\bin\python-qgis-ltr.bat",
            r"C:\Program Files\QGIS *\bin\python-qgis.bat",
            r"C:\OSGeo4W64\bin\python-qgis-ltr.bat",
            r"C:\OSGeo4W64\bin\python-qgis.bat",
        ]
    
    for pattern in search_paths:
        matches = glob.glob(pattern)
        if matches:
            # Return the newest/highest version found
            return sorted(matches)[-1]
    return None

def execute_conversion(lyrx_path, output_dir=None):
    """The actual conversion logic that runs INSIDE the QGIS environment."""
    from qgis.core import QgsApplication
    from arc_to_q.converters.lyrx_converter import convert_lyrx
    
    print(f"Running inside QGIS Environment...")
    qgs = QgsApplication([], False)
    qgs.initQgis()
    
    try:
        convert_lyrx(lyrx_path, output_dir, qgs)
        print("Conversion successful!")
    except Exception as e:
        print(f"Error during conversion: {e}")
    finally:
        qgs.exitQgis()

def main():
    parser = argparse.ArgumentParser(description="Convert ArcGIS .lyrx to QGIS .qlr")
    parser.add_argument("input", help="Path to the .lyrx file")
    parser.add_argument("-o", "--output", help="Output directory (optional)", default=None)
    args = parser.parse_args()

    input_path = os.path.abspath(args.input)
    output_path = os.path.abspath(args.output) if args.output else None

    # Check if we are already in the QGIS environment
    try:
        import qgis.core
        # If this succeeds, we are in the QGIS environment. Run the conversion.
        execute_conversion(input_path, output_path)
    except ImportError as e:
        # Prevent infinite loop if the bat file fails to set up the environment properly
        if os.environ.get("ARCTOQ_RELAUNCHED") == "1":
            print(f"CRITICAL ERROR: Failed to import qgis.core even after relaunching.")
            print(f"Underlying error: {e}")
            print("Your QGIS Python environment may be broken or requires manual setup.")
            sys.exit(1)

        print("QGIS environment not detected. Searching for QGIS installation...")
        qgis_exec = find_qgis_python_exec()
        
        if not qgis_exec:
            print("ERROR: Could not find QGIS installation. Please run this script from the OSGeo4W shell or equivalent QGIS environment.")
            sys.exit(1)
            
        print(f"Found QGIS at: {qgis_exec}")
        print("Relaunching script in QGIS environment...\n" + "-"*40)
        
        # Set an environment variable to prevent looping
        env = os.environ.copy()
        env["ARCTOQ_RELAUNCHED"] = "1"
        
        # Relaunch THIS script using the QGIS executable
        cmd = [qgis_exec, __file__, input_path]
        if output_path:
            cmd.extend(["-o", output_path])
            
        subprocess.run(cmd, env=env)

if __name__ == "__main__":
    main()