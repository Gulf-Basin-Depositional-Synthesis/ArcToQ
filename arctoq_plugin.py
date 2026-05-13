import sys
import os
import tempfile
import shutil
from qgis.PyQt.QtCore import Qt, QEventLoop
from qgis.PyQt.QtGui import QIcon  
from qgis.PyQt.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, 
                                 QLabel, QPushButton, QTabWidget, QWidget, 
                                 QMessageBox, QAction, QApplication,
                                 QFileDialog, QListWidget, QProgressBar, QCheckBox)
from qgis.gui import QgsFileWidget
from qgis.core import QgsApplication, QgsProject, QgsLayerDefinition, QgsTask, Qgis

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
        self.resize(550, 580) # Slightly taller to fit new checkbox
        
        # Main Layout
        layout = QVBoxLayout(self)
        
        # Tabs
        self.tabs = QTabWidget()
        
        # --- TAB 1: Single File ---
        self.single_tab = QWidget()
        self.single_layout = QVBoxLayout(self.single_tab)
        
        self.single_layout.addWidget(QLabel("Input LYRX file"))
        self.input_widget = QgsFileWidget()
        self.input_widget.setFilter("Layer Files (*.lyrx)")
        self.input_widget.setStorageMode(QgsFileWidget.GetFile)
        self.single_layout.addWidget(self.input_widget)
        
        self.single_layout.addSpacing(10)
        
        self.single_layout.addWidget(QLabel("Destination QLR file"))
        self.output_widget = QgsFileWidget()
        self.output_widget.setFilter("QGIS Layer Definition (*.qlr)")
        self.output_widget.setStorageMode(QgsFileWidget.SaveFile)
        self.single_layout.addWidget(self.output_widget)
        
        self.single_layout.addStretch()
        self.tabs.addTab(self.single_tab, "Single File")
        
        # --- TAB 2: Batch Process ---
        self.batch_tab = QWidget()
        self.batch_layout = QVBoxLayout(self.batch_tab)
        
        self.batch_layout.addWidget(QLabel("Select LYRX files to convert:"))
        self.file_list = QListWidget()
        self.batch_layout.addWidget(self.file_list)
        
        # Buttons to manage the batch list (Files & Folders)
        list_btn_layout = QHBoxLayout()
        self.add_files_btn = QPushButton("Add Files...")
        self.add_folder_btn = QPushButton("Add Folder...")
        self.remove_files_btn = QPushButton("Remove Selected")
        self.clear_files_btn = QPushButton("Clear All")
        
        list_btn_layout.addWidget(self.add_files_btn)
        list_btn_layout.addWidget(self.add_folder_btn)
        list_btn_layout.addWidget(self.remove_files_btn)
        list_btn_layout.addWidget(self.clear_files_btn)
        self.batch_layout.addLayout(list_btn_layout)
        
        # Checkbox for recursive folder search
        self.include_subdirs_cb = QCheckBox("Include subdirectories when adding folders")
        self.include_subdirs_cb.setChecked(True)
        self.batch_layout.addWidget(self.include_subdirs_cb)
        
        self.batch_layout.addSpacing(10)

        # Checkbox for Save in Place
        self.save_in_place_cb = QCheckBox("Save converted files in their original directories")
        self.batch_layout.addWidget(self.save_in_place_cb)

        # Checkbox for Mirror Structure
        self.mirror_structure_cb = QCheckBox("Mirror original folder structure in destination")
        self.batch_layout.addWidget(self.mirror_structure_cb)

        # Checkbox for Overwriting
        self.overwrite_cb = QCheckBox("Overwrite existing QLR files")
        self.overwrite_cb.setChecked(False) # Safe default
        self.batch_layout.addWidget(self.overwrite_cb)
        
        self.batch_layout.addWidget(QLabel("Destination Directory"))
        self.out_dir_widget = QgsFileWidget()
        self.out_dir_widget.setStorageMode(QgsFileWidget.GetDirectory)
        self.batch_layout.addWidget(self.out_dir_widget)
        
        self.batch_layout.addSpacing(10)
        
        # Progress Bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.batch_layout.addWidget(self.progress_bar)
        
        self.tabs.addTab(self.batch_tab, "Batch Process")
        
        layout.addWidget(self.tabs)
        
        # Run / Close Buttons
        btn_layout = QHBoxLayout()
        self.run_btn = QPushButton("Run")
        self.close_btn = QPushButton("Close")
        btn_layout.addStretch()
        btn_layout.addWidget(self.run_btn)
        btn_layout.addWidget(self.close_btn)
        
        layout.addLayout(btn_layout)
        
        # Connections
        self.close_btn.clicked.connect(self.reject)
        self.input_widget.fileChanged.connect(self.on_input_changed)
        
        # Batch tab connections
        self.add_files_btn.clicked.connect(self.add_batch_files)
        self.add_folder_btn.clicked.connect(self.add_batch_folder)
        self.remove_files_btn.clicked.connect(self.remove_batch_files)
        self.clear_files_btn.clicked.connect(self.file_list.clear)
        self.save_in_place_cb.toggled.connect(self.on_save_in_place_toggled)

    def on_save_in_place_toggled(self, checked):
        # Disable Destination elements if Save In Place is active
        self.out_dir_widget.setDisabled(checked)
        self.mirror_structure_cb.setDisabled(checked)
        if checked:
            self.mirror_structure_cb.setChecked(False)

    def on_input_changed(self, file_path):
        if file_path and os.path.exists(file_path):
            suggested_out = file_path.replace(".lyrx", ".qlr")
            self.output_widget.setFilePath(suggested_out)

    def add_batch_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Select LYRX Files", "", "Layer Files (*.lyrx)"
        )
        if files:
            for f in files:
                f_norm = os.path.normpath(f)
                if not self.file_list.findItems(f_norm, Qt.MatchExactly):
                    self.file_list.addItem(f_norm)

    def add_batch_folder(self):
        folder_path = QFileDialog.getExistingDirectory(
            self, "Select Folder Containing LYRX Files"
        )
        if not folder_path:
            return
            
        recursive = self.include_subdirs_cb.isChecked()
        files_to_add = []
        
        if recursive:
            for root, dirs, files in os.walk(folder_path):
                for file in files:
                    if file.lower().endswith('.lyrx'):
                        files_to_add.append(os.path.join(root, file))
        else:
            for file in os.listdir(folder_path):
                full_path = os.path.join(folder_path, file)
                if os.path.isfile(full_path) and file.lower().endswith('.lyrx'):
                    files_to_add.append(full_path)
                    
        if not files_to_add:
            QMessageBox.information(
                self, "No Files Found", 
                "No LYRX files were found in the selected directory."
            )
            return

        added_count = 0
        for f in files_to_add:
            f_norm = os.path.normpath(f)
            if not self.file_list.findItems(f_norm, Qt.MatchExactly):
                self.file_list.addItem(f_norm)
                added_count += 1
                
        if added_count == 0:
            QMessageBox.information(
                self, "No New Files", 
                "All LYRX files found in the directory are already in the list."
            )

    def remove_batch_files(self):
        for item in self.file_list.selectedItems():
            self.file_list.takeItem(self.file_list.row(item))


class ArcToQPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = plugin_dir
        self.action = None

    def initGui(self):
        icon_path = os.path.join(self.plugin_dir, "icon.png")
        self.action = QAction(QIcon(icon_path), "Convert LYRX to QLR", self.iface.mainWindow())
        self.action.setObjectName("ArcToQAction")
        self.action.setToolTip("Select ArcGIS .lyrx file(s) to convert")
        self.action.triggered.connect(self.run)

        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu("&ArcToQ", self.action)

    def unload(self):
        self.iface.removePluginMenu("&ArcToQ", self.action)
        self.iface.removeToolBarIcon(self.action)

    def run(self):
        if Qgis.QGIS_VERSION_INT < 34400:
            self.iface.messageBar().pushInfo(
                "ArcToQ", 
                "Your QGIS version is older. Some complex layer styling may not convert perfectly. Consider updating QGIS if you notice issues."
            )

        dialog = ConvertDialog(self.iface.mainWindow())
        dialog.progress_bar.setValue(0)
        dialog.run_btn.clicked.connect(lambda: self._process_conversion(dialog))
        dialog.exec_()

    def _process_conversion(self, dialog):
        dialog.run_btn.setEnabled(False)
        is_batch_mode = dialog.tabs.currentIndex() == 1

        try:
            if not is_batch_mode:
                self._run_single(dialog)
            else:
                self._run_batch(dialog)
        finally:
            dialog.run_btn.setEnabled(True)

    def _run_single(self, dialog):
        lyrx_path = os.path.normpath(dialog.input_widget.filePath().strip())
        out_file = os.path.normpath(dialog.output_widget.filePath().strip())
        
        if not lyrx_path or not out_file or out_file == ".":
            self.iface.messageBar().pushWarning("ArcToQ", "Input and Output paths must be defined.")
            return
            
        try:
            self.iface.messageBar().clearWidgets()
            self.iface.messageBar().pushInfo("ArcToQ", f"Converting {os.path.basename(lyrx_path)}...")
            QApplication.processEvents(QEventLoop.ExcludeUserInputEvents) 
            
            with tempfile.TemporaryDirectory() as temp_dir:
                convert_lyrx(lyrx_path, temp_dir, qgs=QgsApplication.instance()) 
                temp_generated_file = os.path.normpath(
                    os.path.join(temp_dir, os.path.basename(lyrx_path).replace(".lyrx", ".qlr"))
                )
                
                if os.path.exists(temp_generated_file):
                    if os.path.exists(out_file):
                        os.remove(out_file) 
                    shutil.move(temp_generated_file, out_file)
                else:
                    raise Exception("Conversion process finished but no file was generated.")
            
            self.iface.messageBar().clearWidgets()
            self.iface.messageBar().pushSuccess("ArcToQ", "Conversion successful!")
            
            reply = QMessageBox.question(
                self.iface.mainWindow(), 
                "Success", 
                f"Successfully converted layer.\nSaved to: {out_file}\n\nWould you like to load the QLR into the current project?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes
            )
            
            if reply == QMessageBox.Yes:
                QgsLayerDefinition.loadLayerDefinition(
                    out_file, 
                    QgsProject.instance(), 
                    QgsProject.instance().layerTreeRoot()
                )
            
            dialog.accept()
            
        except Exception as e:
            self.iface.messageBar().clearWidgets()
            self.iface.messageBar().pushCritical("ArcToQ", f"Conversion failed: {str(e)}")
            QMessageBox.critical(
                self.iface.mainWindow(), 
                "Conversion Error", 
                f"Failed to convert {os.path.basename(lyrx_path)}:\n\n{str(e)}"
            )

    def _run_batch(self, dialog):
        files_to_convert = [dialog.file_list.item(i).text() for i in range(dialog.file_list.count())]
        out_dir = os.path.normpath(dialog.out_dir_widget.filePath().strip())
        
        save_in_place = dialog.save_in_place_cb.isChecked()
        mirror_structure = dialog.mirror_structure_cb.isChecked()
        allow_overwrite = dialog.overwrite_cb.isChecked()
        
        if not files_to_convert:
            self.iface.messageBar().pushWarning("ArcToQ", "Please add at least one LYRX file to convert.")
            return
        if not save_in_place and (not out_dir or out_dir == "."):
            self.iface.messageBar().pushWarning("ArcToQ", "Please select a destination directory.")
            return

        # Determine the base common path if we are mirroring
        common_base = None
        if mirror_structure and not save_in_place:
            try:
                # Find the deepest shared folder path of all selected files
                dirs = [os.path.dirname(f) for f in files_to_convert]
                common_base = os.path.commonpath(dirs)
            except ValueError:
                # Fallback if files span across different drives (Windows)
                self.iface.messageBar().pushWarning("ArcToQ", "Cannot mirror folder structure across different drives. Saving flatly.")
                mirror_structure = False

        total_files = len(files_to_convert)
        
        dialog.progress_bar.setMaximum(total_files)
        dialog.progress_bar.setValue(0)

        self.iface.messageBar().clearWidgets()
        self.iface.messageBar().pushInfo("ArcToQ", f"Batch converting {total_files} files...")
        QApplication.processEvents(QEventLoop.ExcludeUserInputEvents) 

        successes = []
        errors = []
        renamed_files = [] 
        generated_destinations = set()

        with tempfile.TemporaryDirectory() as temp_dir:
            for index, lyrx_path in enumerate(files_to_convert):
                lyrx_path = os.path.normpath(lyrx_path)
                base_name = os.path.basename(lyrx_path)
                name_only = base_name[:-5] if base_name.lower().endswith(".lyrx") else base_name
                
                # Determine destination directory for this specific file
                if save_in_place:
                    current_out_dir = os.path.dirname(lyrx_path)
                elif mirror_structure and common_base:
                    # Calculate its relative place and append it to the chosen destination output
                    rel_path = os.path.relpath(os.path.dirname(lyrx_path), common_base)
                    current_out_dir = os.path.join(out_dir, rel_path) if rel_path != '.' else out_dir
                    os.makedirs(current_out_dir, exist_ok=True) # Dynamically generate the folder tree!
                else:
                    current_out_dir = out_dir
                
                out_file = os.path.join(current_out_dir, f"{name_only}.qlr")
                
                needs_rename = (not allow_overwrite and os.path.exists(out_file)) or (out_file in generated_destinations)
                
                if needs_rename:
                    counter = 1
                    while True:
                        test_out_file = os.path.join(current_out_dir, f"{name_only} ({counter}).qlr")
                        if test_out_file not in generated_destinations:
                            if allow_overwrite or not os.path.exists(test_out_file):
                                out_file = test_out_file
                                break
                        counter += 1
                    
                    renamed_files.append(f"{base_name}  ->  {os.path.basename(out_file)}")
                
                generated_destinations.add(out_file)
                
                try:
                    convert_lyrx(lyrx_path, temp_dir, qgs=QgsApplication.instance()) 
                    temp_generated_file = os.path.join(temp_dir, base_name.replace(".lyrx", ".qlr"))
                    
                    if os.path.exists(temp_generated_file):
                        if os.path.exists(out_file):
                            os.remove(out_file)
                        shutil.move(temp_generated_file, out_file)
                        successes.append(out_file)
                    else:
                        errors.append(f"{base_name}: No output file generated.")
                except Exception as e:
                    errors.append(f"{base_name}: {str(e)}")
                    temp_generated_file = os.path.join(temp_dir, base_name.replace(".lyrx", ".qlr"))
                    if os.path.exists(temp_generated_file):
                        try:
                            os.remove(temp_generated_file)
                        except:
                            pass
                            
                dialog.progress_bar.setValue(index + 1)
                QApplication.processEvents(QEventLoop.ExcludeUserInputEvents)

        self.iface.messageBar().clearWidgets()
        
        if successes:
            msg = f"Successfully converted {len(successes)} of {total_files} files."
            
            if errors:
                msg += " Some files had errors."
                self.iface.messageBar().pushWarning("ArcToQ", msg)
            else:
                self.iface.messageBar().pushSuccess("ArcToQ", msg)
                
            if renamed_files:
                rename_msg = "\n".join(renamed_files)
                QMessageBox.information(
                    self.iface.mainWindow(), 
                    "Files Renamed", 
                    f"To prevent overwriting existing files or duplicate names, the following QLRs were automatically renamed:\n\n{rename_msg}"
                )
                
            reply = QMessageBox.question(
                self.iface.mainWindow(), 
                "Batch Conversion Complete", 
                f"{msg}\n\nWould you like to load the successfully converted QLRs into the current project?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes
            )
            
            if reply == QMessageBox.Yes:
                for qlr in successes:
                    QgsLayerDefinition.loadLayerDefinition(
                        qlr, 
                        QgsProject.instance(), 
                        QgsProject.instance().layerTreeRoot()
                    )
            
            dialog.accept()
                    
        if errors:
            err_msg = "\n".join(errors)
            QMessageBox.warning(
                self.iface.mainWindow(), 
                "Batch Conversion Notice", 
                f"The following files were not converted:\n\n{err_msg}"
            )