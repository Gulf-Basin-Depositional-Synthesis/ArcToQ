import sys
import os
import subprocess
import glob
import argparse

# Ensure the parent directory is in the path so arc_to_q imports work
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

def find_qgis_python_exec():
    """Attempt to find the QGIS python executable across different OS."""
    
    # 1. Allow users to force a specific QGIS install path via env variables
    env_path = os.environ.get("QGIS_PYTHON_PATH")
    if env_path and os.path.exists(env_path):
        return env_path
        
    search_paths = []
    
    if sys.platform == "darwin":
        search_paths = [
            "/Applications/QGIS*.app/Contents/MacOS/bin/python3",
            "/Applications/QGIS*.app/Contents/MacOS/python",
        ]
    elif sys.platform.startswith("linux"):
        search_paths = [
            "/usr/bin/python3",
        ]
    else:
        search_paths = [
            r"C:\Program Files\QGIS *\bin\python-qgis-ltr.bat",
            r"C:\Program Files\QGIS *\bin\python-qgis.bat",
            r"C:\OSGeo4W64\bin\python-qgis-ltr.bat",
            r"C:\OSGeo4W64\bin\python-qgis.bat",
        ]
    
    for pattern in search_paths:
        matches = glob.glob(pattern)
        if matches:
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

    try:
        import qgis.core
        execute_conversion(input_path, output_path)
    except ImportError as e:
        if os.environ.get("ARCTOQ_RELAUNCHED") == "1":
            print(f"CRITICAL ERROR: Failed to import qgis.core even after relaunching.")
            print(f"Underlying error: {e}")
            print("Your QGIS Python environment may be broken or requires manual setup.")
            sys.exit(1)

        print("QGIS environment not detected. Searching for QGIS installation...")
        qgis_exec = find_qgis_python_exec()
        
        if not qgis_exec:
            print("ERROR: Could not find QGIS installation.")
            print("Please set the 'QGIS_PYTHON_PATH' environment variable to point to your QGIS python executable.")
            print("Example (Windows): set QGIS_PYTHON_PATH=C:\\Program Files\\QGIS 3.44.6\\bin\\python-qgis.bat")
            sys.exit(1)
            
        print(f"Found QGIS at: {qgis_exec}")
        print("Relaunching script in QGIS environment...\n" + "-"*40)
        
        env = os.environ.copy()
        env["ARCTOQ_RELAUNCHED"] = "1"
        
        cmd = [qgis_exec, __file__, input_path]
        if output_path:
            cmd.extend(["-o", output_path])
            
        subprocess.run(cmd, env=env)

if __name__ == "__main__":
    main()