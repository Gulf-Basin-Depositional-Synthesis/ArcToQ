import sys
import os
import tempfile
import shutil
import json
from datetime import datetime
import textwrap
import platform
import urllib.parse
from qgis.PyQt.QtCore import Qt, QEventLoop, QUrl, QThread, pyqtSignal
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


class BatchWorker(QThread):
    """Worker thread for batch LYRX conversion."""
    progress = pyqtSignal(int)                        # current file index (1-based)
    file_result = pyqtSignal(str, str, bool, str)     # input, output, success, error
    finished = pyqtSignal()

    def __init__(self, files, out_dir, save_in_place, mirror_structure, allow_overwrite, common_base):
        super().__init__()
        self.files = files
        self.out_dir = out_dir
        self.save_in_place = save_in_place
        self.mirror_structure = mirror_structure
        self.allow_overwrite = allow_overwrite
        self.common_base = common_base
        self._cancel = False
        self._generated_destinations = set()

    def stop(self):
        self._cancel = True

    def run(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            for index, lyrx_path in enumerate(self.files):
                if self._cancel:
                    break

                lyrx_path = os.path.normpath(lyrx_path)
                base_name = os.path.basename(lyrx_path)
                name_only = base_name[:-5] if base_name.lower().endswith(".lyrx") else base_name

                # Determine output directory
                if self.save_in_place:
                    current_out_dir = os.path.dirname(lyrx_path)
                elif self.mirror_structure and self.common_base:
                    rel_path = os.path.relpath(os.path.dirname(lyrx_path), self.common_base)
                    current_out_dir = os.path.join(self.out_dir, rel_path) if rel_path != '.' else self.out_dir
                    os.makedirs(current_out_dir, exist_ok=True)
                else:
                    current_out_dir = self.out_dir

                out_file = os.path.join(current_out_dir, f"{name_only}.qlr")

                # Handle naming conflicts
                needs_rename = (not self.allow_overwrite and os.path.exists(out_file)) or (out_file in self._generated_destinations)
                if needs_rename:
                    counter = 1
                    while True:
                        test_out_file = os.path.join(current_out_dir, f"{name_only} ({counter}).qlr")
                        if test_out_file not in self._generated_destinations:
                            if self.allow_overwrite or not os.path.exists(test_out_file):
                                out_file = test_out_file
                                break
                        counter += 1

                self._generated_destinations.add(out_file)

                try:
                    convert_lyrx(lyrx_path, temp_dir, qgs=QgsApplication.instance())
                    temp_generated_file = os.path.join(temp_dir, base_name.replace(".lyrx", ".qlr"))

                    if os.path.exists(temp_generated_file):
                        if os.path.exists(out_file):
                            os.remove(out_file)
                        shutil.move(temp_generated_file, out_file)
                        self.file_result.emit(lyrx_path, out_file, True, "")
                    else:
                        raise Exception("No output file generated.")
                except Exception as e:
                    # Clean up any partial temp file
                    temp_generated_file = os.path.join(temp_dir, base_name.replace(".lyrx", ".qlr"))
                    if os.path.exists(temp_generated_file):
                        try:
                            os.remove(temp_generated_file)
                        except Exception:
                            pass
                    self.file_result.emit(lyrx_path, "", False, str(e))

                self.progress.emit(index + 1)

        self.finished.emit()


class ConvertDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Convert LYRX to QLR")
        self.resize(650, 600)
        self._worker = None
        self._batch_job_data = None
        
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
        
        self.include_subdirs_cb = QCheckBox("Include subdirectories when adding folders")
        self.include_subdirs_cb.setChecked(True)
        self.batch_layout.addWidget(self.include_subdirs_cb)
        
        self.batch_layout.addSpacing(10)

        self.save_in_place_cb = QCheckBox("Save converted files in their original directories")
        self.batch_layout.addWidget(self.save_in_place_cb)

        self.mirror_structure_cb = QCheckBox("Recreate original folder structure in destination")
        self.batch_layout.addWidget(self.mirror_structure_cb)

        self.overwrite_cb = QCheckBox("Overwrite existing QLR files")
        self.overwrite_cb.setChecked(False)
        self.batch_layout.addWidget(self.overwrite_cb)
        
        self.batch_layout.addWidget(QLabel("Destination Folder"))
        self.out_dir_widget = QgsFileWidget()
        self.out_dir_widget.setStorageMode(QgsFileWidget.GetDirectory)
        self.batch_layout.addWidget(self.out_dir_widget)
        
        self.batch_layout.addSpacing(10)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.batch_layout.addWidget(self.progress_bar)
        
        self.tabs.addTab(self.batch_tab, "Batch Process")

        # --- TAB 3: Jobs (History) ---
        self.jobs_tab = QWidget()
        self.jobs_layout = QVBoxLayout(self.jobs_tab)
        
        self.history_tree = QTreeWidget()
        self.history_tree.setHeaderLabels(["Date/Time", "Job / File", "Status", "Details"])
        self.history_tree.setTextElideMode(Qt.ElideNone) 
        self.history_tree.header().setSectionResizeMode(1, QHeaderView.Interactive)
        self.history_tree.header().setSectionResizeMode(3, QHeaderView.Interactive)
        self.history_tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
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
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setVisible(False)
        self.close_btn = QPushButton("Close")
        btn_layout.addStretch()
        btn_layout.addWidget(self.run_btn)
        btn_layout.addWidget(self.cancel_btn)
        btn_layout.addWidget(self.close_btn)
        layout.addLayout(btn_layout)
        
        # Connections
        self.close_btn.clicked.connect(self.reject)
        self.cancel_btn.clicked.connect(self._cancel_batch)
        self.input_widget.fileChanged.connect(self.on_input_changed)
        self.add_files_btn.clicked.connect(self.add_batch_files)
        self.add_folder_btn.clicked.connect(self.add_batch_folder)
        self.remove_files_btn.clicked.connect(self.remove_batch_files)
        self.clear_files_btn.clicked.connect(self.file_list.clear)
        self.save_in_place_cb.toggled.connect(self.on_save_in_place_toggled)
        self.open_dest_btn.clicked.connect(self.open_destination)
        self.clear_history_btn.clicked.connect(self.clear_history)

        self.history_file = os.path.join(QgsApplication.qgisSettingsDirPath(), "arctoq_history.json")
        self.load_history()

    # --- Batch threading ---

    def _start_batch(self, files, out_dir, save_in_place, mirror_structure, allow_overwrite, common_base, total_files):
        self._batch_job_data = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "type": "Batch",
            "total": total_files,
            "success": 0,
            "files": [],
            "successes": [],
            "errors": [],
        }

        self.progress_bar.setMaximum(total_files)
        self.progress_bar.setValue(0)
        self.run_btn.setVisible(False)
        self.cancel_btn.setVisible(True)
        self.close_btn.setEnabled(False)
        self._set_batch_controls_enabled(False)

        self._worker = BatchWorker(files, out_dir, save_in_place, mirror_structure, allow_overwrite, common_base)
        self._worker.progress.connect(self.progress_bar.setValue)
        self._worker.file_result.connect(self._on_file_result)
        self._worker.finished.connect(self._on_batch_finished, Qt.QueuedConnection)
        self._worker.start()

    def _cancel_batch(self):
        if self._worker:
            self._worker.stop()
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setText("Cancelling...")

    def _on_file_result(self, input_path, output_path, success, error):
        job = self._batch_job_data
        if success:
            job["success"] += 1
            job["successes"].append(output_path)
            job["files"].append({"input": input_path, "output": output_path, "status": "Success", "error": ""})
        else:
            job["errors"].append(f"{os.path.basename(input_path)}: {error}")
            job["files"].append({"input": input_path, "output": "", "status": "Failed", "error": error})

    def _on_batch_finished(self):
        self.run_btn.setVisible(True)
        self.cancel_btn.setVisible(False)
        self.cancel_btn.setEnabled(True)
        self.cancel_btn.setText("Cancel")
        self.close_btn.setEnabled(True)
        self._set_batch_controls_enabled(True)

        job = self._batch_job_data
        self.append_job_to_history({k: v for k, v in job.items() if k not in ("successes", "errors")})

        from qgis.PyQt.QtCore import QTimer
        QTimer.singleShot(0, self._show_batch_summary)

    def _show_batch_summary(self):
        job = self._batch_job_data
        if not job:
            return

        successes = job["successes"]
        errors = job["errors"]
        total = job["total"]

        if successes:
            msg = f"Successfully converted {len(successes)} of {total} files."
            if errors:
                msg += " Some files had errors."

            reply = QMessageBox.question(
                self,
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

        if errors:
            err_msg = "\n".join(errors)
            QMessageBox.warning(
                self,
                "Batch Conversion Notice",
                f"The following files were not converted:\n\n{err_msg}"
            )

        self._worker = None
        self._batch_job_data = None

    def _set_batch_controls_enabled(self, enabled):
        for widget in [self.add_files_btn, self.add_folder_btn, self.remove_files_btn,
                       self.clear_files_btn, self.out_dir_widget, self.save_in_place_cb,
                       self.mirror_structure_cb, self.overwrite_cb, self.include_subdirs_cb,
                       self.file_list]:
            widget.setEnabled(enabled)

    # --- History / Jobs Methods ---

    def show_item_details(self, item, column):
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
        
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        if item.parent() is not None and item.text(2) == "Failed":
            report_btn = QPushButton("Report Issue on GitHub")
            report_btn.setStyleSheet("background-color: #2ea44f; color: white; font-weight: bold;")
            file_name = item.text(1)
            error_msg = item.text(3)
            report_btn.clicked.connect(lambda checked=False, f=file_name, e=error_msg: self.report_to_github(f, e))
            btn_layout.addWidget(report_btn)
        
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dialog.accept)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)
        dialog.exec_()

    def report_to_github(self, file_name, error_msg, max_error_chars=2000):
        os_info = f"{platform.system()} {platform.release()}"
        qgis_ver = Qgis.QGIS_VERSION
        code_block = "```"
        truncated = error_msg[:max_error_chars] + ("\n... (truncated)" if len(error_msg) > max_error_chars else "")
        
        body = "**Describe the issue**\n"
        body += f"Failed to convert `{file_name}`.\n\n"
        body += "More Details:\n\n"
        body += "Error trace:\n"
        body += f"{code_block}python\n"
        body += f"{truncated}\n"
        body += f"{code_block}\n\n"
        body += "**To Reproduce**\n"
        body += "Steps to reproduce the behavior:\n"
        body += f"1. Attempt to convert `{file_name}` using ArcToQ.\n"
        body += "2. Conversion fails with the error above.\n\n"
        body += "**Environment:**\n"
        body += f" - OS: {os_info}\n"
        body += f" - QGIS Version: {qgis_ver}\n"
        body += " - ArcGIS Pro Version (if known): \n\n"
        body += "**Attachments**\n"
        body += f"Please drop the problematic `{file_name}` file and any relevant screenshots here.\n"
        
        title = urllib.parse.quote(f"[Bug] Conversion failed for {file_name}")
        body_encoded = urllib.parse.quote(body)
        url = f"https://github.com/Gulf-Basin-Depositional-Synthesis/ArcToQ/issues/new?labels=bug&title={title}&body={body_encoded}"
        QDesktopServices.openUrl(QUrl(url))

    def load_history(self):
        self.history_tree.clear()
        if not os.path.exists(self.history_file):
            return

        try:
            with open(self.history_file, 'r', encoding='utf-8') as f:
                history = json.load(f)
        except Exception:
            history = []

        def wrap_tooltip(text):
            return "\n".join(textwrap.wrap(text, width=80, break_long_words=True))

        for job in reversed(history):
            job_item = QTreeWidgetItem(self.history_tree)
            job_item.setText(0, job.get("timestamp", ""))
            
            j_type = job.get("type", "Unknown")
            total = job.get("total", 0)
            success = job.get("success", 0)
            file_word = "file" if total == 1 else "files"
            job_item.setText(1, f"{j_type} ({total} {file_word})")
            
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

        if item.parent() is not None:
            path_to_open = item.data(0, Qt.UserRole)
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
        self.out_dir_widget.setDisabled(checked)
        self.mirror_structure_cb.setDisabled(checked)
        if checked:
            self.mirror_structure_cb.setChecked(False)

    def on_input_changed(self, file_path):
        if file_path and os.path.exists(file_path):
            suggested_out = file_path.replace(".lyrx", ".qlr")
            self.output_widget.setFilePath(suggested_out)

    def add_batch_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Select LYRX Files", "", "Layer Files (*.lyrx)")
        if files:
            for f in files:
                f_norm = os.path.normpath(f)
                if not self.file_list.findItems(f_norm, Qt.MatchExactly):
                    self.file_list.addItem(f_norm)

    def add_batch_folder(self):
        folder_path = QFileDialog.getExistingDirectory(self, "Select Folder Containing LYRX Files")
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
            QMessageBox.information(self, "No Files Found", "No LYRX files were found in the selected folder.")
            return

        added_count = 0
        for f in files_to_add:
            f_norm = os.path.normpath(f)
            if not self.file_list.findItems(f_norm, Qt.MatchExactly):
                self.file_list.addItem(f_norm)
                added_count += 1
                
        if added_count == 0:
            QMessageBox.information(self, "No New Files", "All LYRX files found in the folder are already in the list.")

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
        dialog.show()  

    def _process_conversion(self, dialog):
        is_batch_mode = dialog.tabs.currentIndex() == 1
        if not is_batch_mode:
            dialog.run_btn.setEnabled(False)
            try:
                self._run_single(dialog)
            finally:
                dialog.run_btn.setEnabled(True)
        else:
            self._run_batch(dialog)

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

        common_base = None
        if mirror_structure and not save_in_place:
            try:
                dirs = [os.path.dirname(f) for f in files_to_convert]
                common_base = os.path.commonpath(dirs)
            except ValueError:
                self.iface.messageBar().pushWarning("ArcToQ", "Cannot mirror folder structure across different drives. Saving flatly.")
                mirror_structure = False

        dialog._start_batch(
            files_to_convert, out_dir, save_in_place, mirror_structure,
            allow_overwrite, common_base, len(files_to_convert)
        )