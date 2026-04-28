import sys
import os
from qgis.PyQt.QtWidgets import QAction, QFileDialog, QMessageBox
from qgis.core import QgsApplication, QgsProject, QgsLayerDefinition

# Dynamically add the plugin folder to the Python path so the 
# arc_to_q logic can be imported without hardcoded local paths.
plugin_dir = os.path.dirname(__file__)
if plugin_dir not in sys.path:
    sys.path.insert(0, plugin_dir)

from arc_to_q.converters.lyrx_converter import convert_lyrx

class ArcToQPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = plugin_dir
        self.action = None

    def initGui(self):
        # Create the action (button)
        self.action = QAction("Convert LYRX to QLR", self.iface.mainWindow())
        self.action.setObjectName("ArcToQAction")
        self.action.setToolTip("Select an ArcGIS .lyrx file to convert")
        
        # Connect the button click to our run function
        self.action.triggered.connect(self.run)

        # Add the button to the QGIS Toolbar and Menu
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu("&ArcToQ", self.action)

    def unload(self):
        # Clean up the UI when the plugin is disabled
        self.iface.removePluginMenu("&ArcToQ", self.action)
        self.iface.removeToolBarIcon(self.action)

    def run(self):
        # 1. Open the file browser dialog for the input LYRX
        lyrx_path, _ = QFileDialog.getOpenFileName(
            self.iface.mainWindow(),
            "Select ArcGIS Layer File",
            "",
            "Layer Files (*.lyrx)"
        )

        if not lyrx_path:
            return  # The user clicked Cancel

        # 2. Ask for the output directory (defaults to the input file's folder)
        output_dir = QFileDialog.getExistingDirectory(
            self.iface.mainWindow(),
            "Select Output Directory",
            os.path.dirname(lyrx_path)
        )

        if not output_dir:
            return  # The user clicked Cancel

        # The converter creates the output file by swapping the extension
        out_file = os.path.join(output_dir, os.path.basename(lyrx_path).replace(".lyrx", ".qlr"))

        # 3. Run the conversion
        try:
            self.iface.messageBar().pushInfo("ArcToQ", f"Converting {os.path.basename(lyrx_path)}...")
            
            # Pass the running QGIS instance so it doesn't trigger exitQgis()
            convert_lyrx(lyrx_path, output_dir, qgs=QgsApplication.instance()) 
            
            self.iface.messageBar().pushSuccess("ArcToQ", "Conversion successful!")
            
            # 4. Prompt the user to load the newly converted layer
            reply = QMessageBox.question(
                self.iface.mainWindow(), 
                "Success", 
                f"Successfully converted layer.\nSaved to: {out_file}\n\nWould you like to load the QLR into the current project?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes
            )
            
            # 5. If Yes, load the QLR directly into the active map canvas
            if reply == QMessageBox.Yes:
                QgsLayerDefinition.loadLayerDefinition(
                    out_file, 
                    QgsProject.instance(), 
                    QgsProject.instance().layerTreeRoot()
                )
            
        except Exception as e:
            self.iface.messageBar().pushCritical("ArcToQ", f"Conversion failed: {str(e)}")
            QMessageBox.critical(
                self.iface.mainWindow(), 
                "Conversion Error", 
                f"Failed to convert {os.path.basename(lyrx_path)}:\n\n{str(e)}"
            )