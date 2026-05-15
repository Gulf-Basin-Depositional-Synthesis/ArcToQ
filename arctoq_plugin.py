import sys
import os
import tempfile
import shutil
import json
from datetime import datetime
import textwrap
from qgis.PyQt.QtCore import Qt, QEventLoop, QUrl
from qgis.PyQt.QtGui import QIcon, QDesktopServices
from qgis.PyQt.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, 
                                 QLabel, QPushButton, QTabWidget, QWidget, 
                                 QMessageBox, QAction, QApplication,
                                 QFileDialog, QListWidget, QProgressBar, QCheckBox,
                                 QTreeWidget, QTreeWidgetItem, QHeaderView, QTextEdit)
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
        self.resize(650, 600) # Slightly larger to accommodate the history tree
        
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
        
        self.file_list.setSelectionMode(QListWidget.ExtendedSelection) 
        
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
        self.mirror_structure_cb = QCheckBox("Recreate original folder structure in destination")
        self.batch_layout.addWidget(self.mirror_structure_cb)

        # Checkbox for Overwriting
        self.overwrite_cb = QCheckBox("Overwrite existing QLR files")
        self.overwrite_cb.setChecked(False) # Safe default
        self.batch_layout.addWidget(self.overwrite_cb)
        
        self.batch_layout.addWidget(QLabel("Destination Folder"))
        self.out_dir_widget = QgsFileWidget()
        self.out_dir_widget.setStorageMode(QgsFileWidget.GetDirectory)
        self.batch_layout.addWidget(self.out_dir_widget)
        
        self.batch_layout.addSpacing(10)
        
        # Progress Bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.batch_layout.addWidget(self.progress_bar)
        
        self.tabs.addTab(self.batch_tab, "Batch Process")

        # --- TAB 3: Jobs (History) ---
        self.jobs_tab = QWidget()
        self.jobs_layout = QVBoxLayout(self.jobs_tab)
        
        self.history_tree = QTreeWidget()
        self.history_tree.setHeaderLabels(["Date/Time", "Job / File", "Status", "Details"])
        self.history_tree.header().setSectionResizeMode(1, QHeaderView.Interactive)
        
        # Force the Details column (Index 3) to stretch and fill remaining space
        self.history_tree.header().setSectionResizeMode(3, QHeaderView.Stretch)
        self.history_tree.setWordWrap(True) 
        
        self.history_tree.itemDoubleClicked.connect(self.show_item_details)
        
        self.jobs_layout.addWidget(self.history_tree)

        jobs_btn_layout = QHBoxLayout()
        self.open_dest_btn = QPushButton("Open Destination Folder")
        self.clear_history_btn = QPushButton("Clear History")
        jobs_btn_layout.addWidget(self.open_dest_btn)
        jobs_btn_layout.addStretch()
        jobs_btn_layout.addWidget(self.clear_history_btn)
        self.jobs_layout.addLayout(jobs_btn_layout)

        self.tabs.addTab(self.jobs_tab, "Jobs")
        
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

        # Jobs tab connections
        self.open_dest_btn.clicked.connect(self.open_destination)
        self.clear_history_btn.clicked.connect(self.clear_history)

        # Load history on startup
        self.history_file = os.path.join(QgsApplication.qgisSettingsDirPath(), "arctoq_history.json")
        self.load_history()

    # --- History / Jobs Methods ---

    def show_item_details(self, item, column):
        """Opens a scrollable, resizable popup when an item is double-clicked."""
        text = item.text(column)
        if not text:
            return
            
        dialog = QDialog(self)
        dialog.setWindowTitle("Item Details")
        dialog.resize(500, 200)
        
        layout = QVBoxLayout(dialog)
        
        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setPlainText(text)
        
        layout.addWidget(text_edit)
        
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn)
        
        dialog.exec_()

    def load_history(self):
        self.history_tree.clear()
        if not os.path.exists(self.history_file):
            return

        try:
            with open(self.history_file, 'r', encoding='utf-8') as f:
                history = json.load(f)
        except Exception:
            history = []

        # Helper to wrap long tooltips
        def wrap_tooltip(text):
            return "\n".join(textwrap.wrap(text, width=80, break_long_words=True))

        # Load in reverse so newest is on top
        for job in reversed(history):
            job_item = QTreeWidgetItem(self.history_tree)
            job_item.setText(0, job.get("timestamp", ""))
            
            j_type = job.get("type", "Unknown")
            total = job.get("total", 0)
            success = job.get("success", 0)
            
            job_item.setText(1, f"{j_type} ({total} files)")
            
            if success == total and total > 0:
                job_item.setText(2, "Success")
                job_item.setForeground(2, Qt.darkGreen)
            elif success == 0:
                job_item.setText(2, "Failed")
                job_item.setForeground(2, Qt.red)
            else:
                job_item.setText(2, "Partial Success")
                job_item.setForeground(2, Qt.darkYellow)
                
            details_text = f"{success} Success, {total - success} Failed"
            job_item.setText(3, details_text)
            job_item.setToolTip(3, wrap_tooltip(details_text))

            # Child file items
            for f_data in job.get("files", []):
                file_item = QTreeWidgetItem(job_item)
                file_item.setText(1, os.path.basename(f_data.get("input", "")))
                
                f_status = f_data.get("status", "")
                file_item.setText(2, f_status)
                if f_status == "Success":
                    file_item.setForeground(2, Qt.darkGreen)
                    file_item.setData(0, Qt.UserRole, f_data.get("output", "")) 
                    
                    out_dir = os.path.dirname(f_data.get("output", ""))
                    file_item.setText(3, out_dir)
                    file_item.setToolTip(3, wrap_tooltip(out_dir))
                else:
                    file_item.setForeground(2, Qt.red)
                    
                    err_msg = f_data.get("error", "")
                    file_item.setText(3, err_msg)
                    file_item.setToolTip(3, wrap_tooltip(err_msg))

    def append_job_to_history(self, job_data):
        history = []
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    history = json.load(f)
            except Exception:
                pass
        
        history.append(job_data)
        
        try:
            with open(self.history_file, 'w', encoding='utf-8') as f:
                json.dump(history, f, indent=4)
            self.load_history()
        except Exception as e:
            print(f"Failed to write history: {e}")

    def clear_history(self):
        reply = QMessageBox.question(self, "Clear History", "Are you sure you want to clear the entire job history?", QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            if os.path.exists(self.history_file):
                os.remove(self.history_file)
            self.load_history()

    def open_destination(self):
        selected = self.history_tree.selectedItems()
        if not selected:
            return

        item = selected[0]
        path_to_open = None

        # Check if it's a file item (child)
        if item.parent() is not None:
            path_to_open = item.data(0, Qt.UserRole)
        # Check if it's a job item (parent)
        else:
            for i in range(item.childCount()):
                child = item.child(i)
                if child.data(0, Qt.UserRole):
                    path_to_open = child.data(0, Qt.UserRole)
                    break
        
        if path_to_open and os.path.exists(os.path.dirname(path_to_open)):
            dir_path = os.path.dirname(path_to_open)
            QDesktopServices.openUrl(QUrl.fromLocalFile(dir_path))
        else:
            QMessageBox.information(self, "Not Found", "The destination folder could not be found or no files succeeded in this job.")

    # --- General Tab Methods ---

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
                "No LYRX files were found in the selected folder."
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
                "All LYRX files found in the folder are already in the list."
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
            
        job_data = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "type": "Single",
            "total": 1,
            "files": []
        }

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
                    
                    job_data["success"] = 1
                    job_data["files"].append({
                        "input": lyrx_path, "output": out_file, "status": "Success", "error": ""
                    })
                else:
                    raise Exception("Conversion process finished but no file was generated.")
            
            self.iface.messageBar().clearWidgets()
            self.iface.messageBar().pushSuccess("ArcToQ", "Conversion successful!")
            dialog.append_job_to_history(job_data)
            
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
            job_data["success"] = 0
            job_data["files"].append({
                "input": lyrx_path, "output": "", "status": "Failed", "error": str(e)
            })
            dialog.append_job_to_history(job_data)

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
            self.iface.messageBar().pushWarning("ArcToQ", "Please select a destination folder.")
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
        
        job_data = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "type": "Batch",
            "total": total_files,
            "success": 0,
            "files": []
        }
        
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
                    rel_path = os.path.relpath(os.path.dirname(lyrx_path), common_base)
                    current_out_dir = os.path.join(out_dir, rel_path) if rel_path != '.' else out_dir
                    os.makedirs(current_out_dir, exist_ok=True) 
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
                        
                        job_data["files"].append({
                            "input": lyrx_path, "output": out_file, "status": "Success", "error": ""
                        })
                        job_data["success"] += 1
                    else:
                        raise Exception("No output file generated.")
                except Exception as e:
                    errors.append(f"{base_name}: {str(e)}")
                    job_data["files"].append({
                        "input": lyrx_path, "output": "", "status": "Failed", "error": str(e)
                    })
                    temp_generated_file = os.path.join(temp_dir, base_name.replace(".lyrx", ".qlr"))
                    if os.path.exists(temp_generated_file):
                        try:
                            os.remove(temp_generated_file)
                        except:
                            pass
                            
                dialog.progress_bar.setValue(index + 1)
                QApplication.processEvents(QEventLoop.ExcludeUserInputEvents)

        # Save Job history
        dialog.append_job_to_history(job_data)

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