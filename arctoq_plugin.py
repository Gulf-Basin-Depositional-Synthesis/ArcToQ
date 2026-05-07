import sys
import os
import tempfile
import shutil
from qgis.PyQt.QtCore import QEventLoop
from qgis.PyQt.QtGui import QIcon  
from qgis.PyQt.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, 
                                 QLabel, QPushButton, QTabWidget, QWidget, 
                                 QMessageBox, QAction, QApplication)
from qgis.gui import QgsFileWidget
from qgis.core import QgsApplication, QgsProject, QgsLayerDefinition

# Dynamically add the plugin folder to the Python path so the 
# arc_to_q logic can be imported without hardcoded local paths.
plugin_dir = os.path.dirname(__file__)
if plugin_dir not in sys.path:
    sys.path.insert(0, plugin_dir)

from arc_to_q.converters.lyrx_converter import convert_lyrx


class ConvertDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Convert LYRX to QLR")
        self.resize(550, 350)
        
        # Main Layout
        layout = QVBoxLayout(self)
        
        # Tabs
        self.tabs = QTabWidget()
        self.param_tab = QWidget()
        self.param_layout = QVBoxLayout(self.param_tab)
        
        # Input Widget
        self.param_layout.addWidget(QLabel("Input LYRX file"))
        self.input_widget = QgsFileWidget()
        self.input_widget.setFilter("Layer Files (*.lyrx)")
        self.input_widget.setStorageMode(QgsFileWidget.GetFile)
        self.param_layout.addWidget(self.input_widget)
        
        self.param_layout.addSpacing(10)
        
        # Output Widget
        self.param_layout.addWidget(QLabel("Destination QLR file"))
        self.output_widget = QgsFileWidget()
        self.output_widget.setFilter("QGIS Layer Definition (*.qlr)")
        self.output_widget.setStorageMode(QgsFileWidget.SaveFile)
        self.param_layout.addWidget(self.output_widget)
        
        self.param_layout.addStretch()
        self.tabs.addTab(self.param_tab, "Parameters")
        
        # You can add a Log tab here later if you want to route stdout to a QTextEdit
        # log_tab = QWidget()
        # self.tabs.addTab(log_tab, "Log")
        
        layout.addWidget(self.tabs)
        
        # Buttons
        btn_layout = QHBoxLayout()
        self.run_btn = QPushButton("Run")
        self.cancel_btn = QPushButton("Cancel")
        btn_layout.addStretch()
        btn_layout.addWidget(self.run_btn)
        btn_layout.addWidget(self.cancel_btn)
        
        layout.addLayout(btn_layout)
        
        # Connections
        self.run_btn.clicked.connect(self.accept)
        self.cancel_btn.clicked.connect(self.reject)
        
        # Auto-fill output path when input is selected
        self.input_widget.fileChanged.connect(self.on_input_changed)

    def on_input_changed(self, file_path):
        if file_path and os.path.exists(file_path):
            # Automatically suggest an output path based on the input
            suggested_out = file_path.replace(".lyrx", ".qlr")
            self.output_widget.setFilePath(suggested_out)

class ArcToQPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = plugin_dir
        self.action = None

    def initGui(self):
        # 1. Define the path to your new icon
        icon_path = os.path.join(self.plugin_dir, "icon.png")
        
        # 2. Pass the QIcon to the QAction
        self.action = QAction(QIcon(icon_path), "Convert LYRX to QLR", self.iface.mainWindow())
        
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
        # 1. Launch the unified dialog
        dialog = ConvertDialog(self.iface.mainWindow())
        
        if not dialog.exec_():
            return  # User clicked Cancel
            
        # 2. Retrieve and strictly normalize paths
        lyrx_path = os.path.normpath(dialog.input_widget.filePath().strip())
        out_file = os.path.normpath(dialog.output_widget.filePath().strip())
        
        if not lyrx_path or not out_file:
            self.iface.messageBar().pushWarning("ArcToQ", "Input and Output paths must be defined.")
            return
            
        output_dir = os.path.dirname(out_file)

        # 3. Run the conversion
        try:
            # Clear previous messages so they don't stack
            self.iface.messageBar().clearWidgets()
            self.iface.messageBar().pushInfo("ArcToQ", f"Converting {os.path.basename(lyrx_path)}...")
            QApplication.processEvents(QEventLoop.ExcludeUserInputEvents) 
            
            with tempfile.TemporaryDirectory() as temp_dir:
                
                # Run the conversion into the temporary folder so it can't overwrite existing files
                convert_lyrx(lyrx_path, temp_dir, qgs=QgsApplication.instance()) 
                
                # Predict the file path convert_lyrx generated inside the temp folder
                temp_generated_file = os.path.normpath(
                    os.path.join(temp_dir, os.path.basename(lyrx_path).replace(".lyrx", ".qlr"))
                )
                
                # If it succeeded, move it to the user's actual destination
                if os.path.exists(temp_generated_file):
                    if os.path.exists(out_file):
                        os.remove(out_file)  # Remove the destination file only if the user explicitly chose to overwrite it
                    
                    # Move and rename the file out of the temp folder to the final destination
                    shutil.move(temp_generated_file, out_file)
                else:
                    raise Exception("Conversion process finished but no file was generated.")
            
            # Clear the old "Converting..." message before showing success
            self.iface.messageBar().clearWidgets()
            self.iface.messageBar().pushSuccess("ArcToQ", "Conversion successful!")
            
            # 4. Prompt the user to load the newly converted layer
            reply = QMessageBox.question(
                self.iface.mainWindow(), 
                "Success", 
                f"Successfully converted layer.\nSaved to: {out_file}\n\nWould you like to load the QLR into the current project?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes
            )
            
            # 5. Load the correctly named file
            if reply == QMessageBox.Yes:
                QgsLayerDefinition.loadLayerDefinition(
                    out_file, 
                    QgsProject.instance(), 
                    QgsProject.instance().layerTreeRoot()
                )
            
        except Exception as e:
            self.iface.messageBar().clearWidgets()
            self.iface.messageBar().pushCritical("ArcToQ", f"Conversion failed: {str(e)}")
            QMessageBox.critical(
                self.iface.mainWindow(), 
                "Conversion Error", 
                f"Failed to convert {os.path.basename(lyrx_path)}:\n\n{str(e)}"
            )