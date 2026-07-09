#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2D XANES Data Viewer
--------------------
Viewer for HDF5 master files written by xanes_gui.gui_2d.

Expected layout (per xanes_gui.gui_2d.MasterH5):
  /exchange/data          (N, H, W)  — sample frames
  /exchange/data_flat     (N, H, W)  — reference / flat frames
  /exchange/energy        (N,)       [eV]

Two tabs:
  * Image Viewer   — slider over N frames, energy readout, on-the-fly
                     data/flat division, contrast presets, X/Y flat shift,
                     stats. Optionally uses flats from an EXTERNAL file
                     (must have the same /exchange/data_flat layout;
                     matched by index).
  * Metadata       — HDF5 attribute/dataset browser (from tomogui).

Standalone entry point:
  python viewer_2d.py [master.h5]
"""

import sys
import os
import csv

import numpy as np
import h5py
from PyQt5 import QtWidgets, QtCore, QtGui
import pyqtgraph as pg

pg.setConfigOptions(imageAxisOrder='row-major')


# ── Metadata helpers (adapted from tomogui/src/tomogui/hdf5_viewer.py) ────

class _Hdf5MetadataReader:
    """Walks an HDF5 file and collects dataset values (excluding /exchange
    and /defaults, which hold bulk arrays)."""

    def __init__(self, h5file, excludedSections=('exchange', 'defaults')):
        self.file = h5file
        self.metadataDict = {}
        self.excludedSections = set(excludedSections)

    def read(self):
        self.file.visititems(self._visit)
        return self.metadataDict

    def _visit(self, name, obj):
        if not isinstance(obj, h5py.Dataset):
            return
        rootName = name.split('/')[0]
        if rootName in self.excludedSections:
            return
        try:
            data = obj[()]
        except Exception:
            return
        units = obj.attrs.get('units')
        if isinstance(units, bytes):
            try:
                units = units.decode('utf-8')
            except Exception:
                units = str(units)
        try:
            if hasattr(data, 'shape') and data.shape == (1,):
                value = data[0]
                if isinstance(value, bytes):
                    value = value.decode('utf-8', errors='ignore')
            elif isinstance(data, bytes):
                value = data.decode('utf-8', errors='ignore')
            else:
                value = data
        except Exception:
            value = data
        self.metadataDict[obj.name] = [value, units]


def _extract_metadata(h5file):
    """Return [(path, value_str, dtype_str), ...] for /measurement/* etc."""
    reader = _Hdf5MetadataReader(h5file)
    md = reader.read()
    rows = []
    for path, (value, units) in md.items():
        if units:
            value_str = f"{value} {units}"
        else:
            value_str = str(value)
        dtype = type(value).__name__
        if isinstance(value, np.ndarray):
            dtype = f"ndarray({value.dtype})"
        elif isinstance(value, (np.integer, np.floating)):
            dtype = str(value.dtype)
        rows.append((path, value_str, dtype))
    return rows


def _extract_structure(h5file):
    """Return [(path, kind, shape, dtype), ...] for the whole file."""
    out = []

    def visit(name, obj):
        if isinstance(obj, h5py.Dataset):
            out.append((name, 'Dataset', obj.shape, obj.dtype))
        elif isinstance(obj, h5py.Group):
            out.append((name, 'Group', None, None))

    h5file.visititems(visit)
    return out


class MetadataViewer(QtWidgets.QWidget):
    """Table of attribute values + tree of file structure with a text filter."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._all_metadata = []
        self._build_ui()

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(10)

        self.tab_widget = QtWidgets.QTabWidget()

        # Attributes tab
        meta_widget = QtWidgets.QWidget()
        meta_layout = QtWidgets.QVBoxLayout(meta_widget)

        filter_layout = QtWidgets.QHBoxLayout()
        filter_layout.addWidget(QtWidgets.QLabel("Filter:"))
        self.filter_input = QtWidgets.QLineEdit()
        self.filter_input.setPlaceholderText("Type to filter by path…")
        self.filter_input.textChanged.connect(self._filter_metadata)
        filter_layout.addWidget(self.filter_input)
        meta_layout.addLayout(filter_layout)

        self.metadata_table = QtWidgets.QTableWidget()
        self.metadata_table.setColumnCount(3)
        self.metadata_table.setHorizontalHeaderLabels(['Path', 'Value', 'Type'])
        self.metadata_table.horizontalHeader().setStretchLastSection(False)
        self.metadata_table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        self.metadata_table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.Interactive)
        self.metadata_table.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)
        self.metadata_table.setAlternatingRowColors(True)
        self.metadata_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.metadata_table.setSortingEnabled(True)
        meta_layout.addWidget(self.metadata_table)

        export_btn = QtWidgets.QPushButton("Export Metadata to CSV")
        export_btn.clicked.connect(self._export_metadata)
        meta_layout.addWidget(export_btn)

        self.tab_widget.addTab(meta_widget, "Attributes")

        # Structure tab
        struct_widget = QtWidgets.QWidget()
        struct_layout = QtWidgets.QVBoxLayout(struct_widget)
        self.structure_tree = QtWidgets.QTreeWidget()
        self.structure_tree.setHeaderLabels(['Path', 'Type', 'Shape', 'Dtype'])
        self.structure_tree.setAlternatingRowColors(True)
        struct_layout.addWidget(self.structure_tree)
        self.tab_widget.addTab(struct_widget, "File Structure")

        layout.addWidget(self.tab_widget)

        self.status_label = QtWidgets.QLabel("No metadata loaded")
        self.status_label.setStyleSheet("color: #999; padding: 5px;")
        layout.addWidget(self.status_label)

    def load(self, h5file):
        try:
            self._all_metadata = _extract_metadata(h5file)
            self._populate_table(self._all_metadata)
            structure = _extract_structure(h5file)
            self._populate_tree(structure)
            self.status_label.setText(
                f"Loaded {len(self._all_metadata)} attributes "
                f"from {len(structure)} objects"
            )
            self.status_label.setStyleSheet("color: #4a4; padding: 5px;")
        except Exception as e:
            self.status_label.setText(f"Error loading metadata: {e}")
            self.status_label.setStyleSheet("color: #f44; padding: 5px;")

    def clear(self):
        self._all_metadata = []
        self.metadata_table.setRowCount(0)
        self.structure_tree.clear()
        self.status_label.setText("No metadata loaded")
        self.status_label.setStyleSheet("color: #999; padding: 5px;")

    def _populate_table(self, rows):
        self.metadata_table.setSortingEnabled(False)
        self.metadata_table.setRowCount(len(rows))
        for row, (path, value, dtype) in enumerate(rows):
            path_item = QtWidgets.QTableWidgetItem(path)
            path_item.setFlags(path_item.flags() & ~QtCore.Qt.ItemIsEditable)
            self.metadata_table.setItem(row, 0, path_item)

            value_str = str(value)
            if len(value_str) > 500:
                value_str = value_str[:500] + "…"
            value_item = QtWidgets.QTableWidgetItem(value_str)
            value_item.setFlags(value_item.flags() & ~QtCore.Qt.ItemIsEditable)
            value_item.setToolTip(str(value))
            self.metadata_table.setItem(row, 1, value_item)

            type_item = QtWidgets.QTableWidgetItem(dtype)
            type_item.setFlags(type_item.flags() & ~QtCore.Qt.ItemIsEditable)
            self.metadata_table.setItem(row, 2, type_item)
        self.metadata_table.setSortingEnabled(True)
        self.metadata_table.resizeColumnsToContents()
        cur = self.metadata_table.columnWidth(1)
        self.metadata_table.setColumnWidth(1, max(200, cur))

    def _populate_tree(self, structure):
        self.structure_tree.clear()
        root = QtWidgets.QTreeWidgetItem(self.structure_tree)
        root.setText(0, '/')
        root.setText(1, 'Group')
        root.setExpanded(True)
        items = {'/': root}
        for path, kind, shape, dtype in sorted(structure):
            parent_path = '/' + '/'.join(path.split('/')[:-1]) if '/' in path else '/'
            parent_path = parent_path.replace('//', '/')
            item = QtWidgets.QTreeWidgetItem()
            item.setText(0, path)
            item.setText(1, kind)
            if shape is not None:
                item.setText(2, str(shape))
            if dtype is not None:
                item.setText(3, str(dtype))
            if parent_path in items:
                items[parent_path].addChild(item)
            else:
                root.addChild(item)
            items[path] = item
        self.structure_tree.expandAll()
        self.structure_tree.resizeColumnToContents(0)
        self.structure_tree.resizeColumnToContents(1)

    def _filter_metadata(self, text):
        if not text:
            self._populate_table(self._all_metadata)
            return
        text_lower = text.lower()
        filtered = [r for r in self._all_metadata if text_lower in r[0].lower()]
        self._populate_table(filtered)

    def _export_metadata(self):
        if not self._all_metadata:
            QtWidgets.QMessageBox.warning(self, "No Data", "No metadata to export.")
            return
        filename, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export Metadata", "", "CSV Files (*.csv)"
        )
        if not filename:
            return
        try:
            with open(filename, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['Path', 'Value', 'Type'])
                writer.writerows(self._all_metadata)
            QtWidgets.QMessageBox.information(
                self, "Success", f"Metadata exported to {filename}"
            )
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self, "Error", f"Failed to export metadata: {e}"
            )


# ── Main viewer window ───────────────────────────────────────────────────

DATA_PATH = 'exchange/data'
FLAT_PATH = 'exchange/data_flat'
ENERGY_PATH = 'exchange/energy'


class Viewer2D(QtWidgets.QMainWindow):
    """Main 2D XANES viewer window."""

    def __init__(self, file_path=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("XANES 2D Data Viewer")
        self.resize(1600, 900)

        # File handles
        self.hdf5_file = None       # primary data file
        self.ext_file = None        # external flats file (optional)

        # Datasets
        self.data_ds = None
        self.flat_ds = None
        self.ext_flat_ds = None
        self.energies = None

        # Cached current frames
        self.current_index = 0
        self.current_data = None
        self.current_flat = None

        # Shift on the flat before division
        self.shift_x = 0
        self.shift_y = 0

        # Config
        self.normalization_enabled = True
        self.use_external_flat = False

        self.result_image = None

        self._build_ui()

        if file_path:
            self._load_primary_path(file_path)

    # ── UI ──────────────────────────────────────────────────────────────
    def _build_ui(self):
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        main_layout = QtWidgets.QVBoxLayout(central)
        main_layout.setSpacing(10)

        self.main_tabs = QtWidgets.QTabWidget()

        # Image tab
        image_tab = QtWidgets.QWidget()
        self._build_image_tab(image_tab)
        self.main_tabs.addTab(image_tab, "Image Viewer")

        # Metadata tab
        self.metadata_viewer = MetadataViewer()
        self.main_tabs.addTab(self.metadata_viewer, "Metadata")

        main_layout.addWidget(self.main_tabs)

    def _build_image_tab(self, parent):
        layout = QtWidgets.QHBoxLayout(parent)
        layout.setSpacing(10)

        # Left — controls
        left = QtWidgets.QWidget()
        left.setMaximumWidth(380)
        ctrl = QtWidgets.QVBoxLayout(left)
        ctrl.setSpacing(10)

        title = QtWidgets.QLabel("2D XANES Data Viewer")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        ctrl.addWidget(title)

        # File selection
        file_group = QtWidgets.QGroupBox("Data File")
        f_layout = QtWidgets.QVBoxLayout()
        self.file_path_label = QtWidgets.QLabel("No file loaded")
        self.file_path_label.setWordWrap(True)
        self.file_path_label.setStyleSheet("color: #999;")
        f_layout.addWidget(self.file_path_label)
        load_btn = QtWidgets.QPushButton("Load HDF5 File…")
        load_btn.clicked.connect(self._load_primary)
        f_layout.addWidget(load_btn)
        file_group.setLayout(f_layout)
        ctrl.addWidget(file_group)

        # Info
        info_group = QtWidgets.QGroupBox("Dataset Information")
        info_layout = QtWidgets.QFormLayout()
        self.data_shape_label = QtWidgets.QLabel("N/A")
        self.flat_shape_label = QtWidgets.QLabel("N/A")
        self.num_frames_label = QtWidgets.QLabel("N/A")
        info_layout.addRow("Data shape:", self.data_shape_label)
        info_layout.addRow("Flat shape:", self.flat_shape_label)
        info_layout.addRow("Number of frames:", self.num_frames_label)
        info_group.setLayout(info_layout)
        ctrl.addWidget(info_group)

        # Frame selector
        sel_group = QtWidgets.QGroupBox("Frame Selection")
        sel_layout = QtWidgets.QVBoxLayout()

        idx_row = QtWidgets.QHBoxLayout()
        idx_row.addWidget(QtWidgets.QLabel("Index:"))
        self.index_spin = QtWidgets.QSpinBox()
        self.index_spin.setRange(0, 0)
        self.index_spin.setEnabled(False)
        self.index_spin.valueChanged.connect(self._on_index_spin)
        idx_row.addWidget(self.index_spin)
        idx_row.addStretch()
        self.energy_label = QtWidgets.QLabel("E = N/A")
        self.energy_label.setStyleSheet(
            "font-weight: bold; padding: 4px 8px; "
            "background-color: #2a2a2a; border-radius: 3px;"
        )
        idx_row.addWidget(self.energy_label)
        sel_layout.addLayout(idx_row)

        self.image_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.image_slider.setMinimum(0)
        self.image_slider.setMaximum(0)
        self.image_slider.setEnabled(False)
        self.image_slider.valueChanged.connect(self._on_slider_changed)
        sel_layout.addWidget(self.image_slider)

        sel_group.setLayout(sel_layout)
        ctrl.addWidget(sel_group)

        # Normalization
        norm_group = QtWidgets.QGroupBox("Normalization")
        norm_layout = QtWidgets.QVBoxLayout()
        self.norm_checkbox = QtWidgets.QCheckBox("Enable normalization (data / flat)")
        self.norm_checkbox.setChecked(True)
        self.norm_checkbox.stateChanged.connect(self._on_normalization_changed)
        norm_layout.addWidget(self.norm_checkbox)

        # Flat source
        self.internal_flat_radio = QtWidgets.QRadioButton("Use flats from this file")
        self.internal_flat_radio.setChecked(True)
        self.internal_flat_radio.toggled.connect(self._on_flat_source_changed)
        norm_layout.addWidget(self.internal_flat_radio)

        self.external_flat_radio = QtWidgets.QRadioButton("Use flats from external file")
        self.external_flat_radio.toggled.connect(self._on_flat_source_changed)
        norm_layout.addWidget(self.external_flat_radio)

        ext_row = QtWidgets.QHBoxLayout()
        self.ext_flat_label = QtWidgets.QLabel("(no external file)")
        self.ext_flat_label.setWordWrap(True)
        self.ext_flat_label.setStyleSheet("color: #999;")
        ext_row.addWidget(self.ext_flat_label, stretch=1)
        self.ext_flat_btn = QtWidgets.QPushButton("Browse…")
        self.ext_flat_btn.setEnabled(False)
        self.ext_flat_btn.clicked.connect(self._load_external_flat)
        ext_row.addWidget(self.ext_flat_btn)
        norm_layout.addLayout(ext_row)

        self.ext_flat_status = QtWidgets.QLabel("")
        self.ext_flat_status.setWordWrap(True)
        norm_layout.addWidget(self.ext_flat_status)

        norm_group.setLayout(norm_layout)
        ctrl.addWidget(norm_group)

        # Contrast
        contrast_group = QtWidgets.QGroupBox("Contrast")
        contrast_layout = QtWidgets.QVBoxLayout()
        c_row = QtWidgets.QHBoxLayout()
        c_row.addWidget(QtWidgets.QLabel("Auto Level:"))
        self.auto_level_combo = QtWidgets.QComboBox()
        self.auto_level_combo.addItems([
            "Per Image (default)",
            "Min/Max",
            "Percentile 1-99%",
            "Percentile 2-98%",
            "Percentile 5-95%",
            "Manual",
        ])
        self.auto_level_combo.currentIndexChanged.connect(self._on_contrast_changed)
        c_row.addWidget(self.auto_level_combo)
        contrast_layout.addLayout(c_row)

        manual_widget = QtWidgets.QWidget()
        manual_layout = QtWidgets.QFormLayout()
        manual_layout.setContentsMargins(0, 0, 0, 0)
        self.min_spin = QtWidgets.QDoubleSpinBox()
        self.min_spin.setRange(-1e10, 1e10)
        self.min_spin.setDecimals(4)
        self.min_spin.setValue(0.0)
        self.min_spin.valueChanged.connect(self._on_manual_levels_changed)
        manual_layout.addRow("Min:", self.min_spin)
        self.max_spin = QtWidgets.QDoubleSpinBox()
        self.max_spin.setRange(-1e10, 1e10)
        self.max_spin.setDecimals(4)
        self.max_spin.setValue(1.0)
        self.max_spin.valueChanged.connect(self._on_manual_levels_changed)
        manual_layout.addRow("Max:", self.max_spin)
        manual_widget.setLayout(manual_layout)
        manual_widget.setVisible(False)
        self.manual_controls = manual_widget
        contrast_layout.addWidget(manual_widget)

        reset_btn = QtWidgets.QPushButton("Auto Adjust Now")
        reset_btn.clicked.connect(self._auto_adjust_contrast)
        contrast_layout.addWidget(reset_btn)
        contrast_group.setLayout(contrast_layout)
        ctrl.addWidget(contrast_group)

        # Shift
        shift_group = QtWidgets.QGroupBox("Flat Shift (before division)")
        shift_layout = QtWidgets.QFormLayout()
        self.shift_x_label = QtWidgets.QLabel("0")
        self.shift_x_label.setStyleSheet("font-weight: bold;")
        shift_layout.addRow("X Shift (pixels):", self.shift_x_label)
        self.shift_y_label = QtWidgets.QLabel("0")
        self.shift_y_label.setStyleSheet("font-weight: bold;")
        shift_layout.addRow("Y Shift (pixels):", self.shift_y_label)
        reset_shift_btn = QtWidgets.QPushButton("Reset Shift")
        reset_shift_btn.clicked.connect(self._reset_shift)
        shift_layout.addRow("", reset_shift_btn)
        instructions = QtWidgets.QLabel(
            "<b>Keyboard:</b><br>"
            "← → ↑ ↓  1 pixel<br>"
            "Shift+arrows  10 pixels<br>"
            "Ctrl+arrows  50 pixels"
        )
        instructions.setWordWrap(True)
        instructions.setStyleSheet(
            "padding: 8px; background-color: #2a2a2a; border-radius: 5px;"
        )
        shift_layout.addRow(instructions)
        shift_group.setLayout(shift_layout)
        ctrl.addWidget(shift_group)

        # Stats
        stats_group = QtWidgets.QGroupBox("Image Statistics")
        stats_layout = QtWidgets.QFormLayout()
        self.min_val_label = QtWidgets.QLabel("N/A")
        self.max_val_label = QtWidgets.QLabel("N/A")
        self.mean_val_label = QtWidgets.QLabel("N/A")
        self.std_val_label = QtWidgets.QLabel("N/A")
        stats_layout.addRow("Min:", self.min_val_label)
        stats_layout.addRow("Max:", self.max_val_label)
        stats_layout.addRow("Mean:", self.mean_val_label)
        stats_layout.addRow("Std Dev:", self.std_val_label)
        stats_group.setLayout(stats_layout)
        ctrl.addWidget(stats_group)

        ctrl.addStretch()
        layout.addWidget(left)

        # Right — image
        right = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self.image_view = pg.ImageView()
        self.image_view.ui.roiBtn.hide()
        self.image_view.ui.menuBtn.hide()
        right_layout.addWidget(self.image_view)
        layout.addWidget(right)
        layout.setStretch(1, 1)

    # ── File loading ────────────────────────────────────────────────────
    def _load_primary(self):
        filename, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Open 2D XANES HDF5 File", "",
            "HDF5 Files (*.h5 *.hdf5);;All Files (*)"
        )
        if filename:
            self._load_primary_path(filename)

    def _load_primary_path(self, filename):
        try:
            new_file = h5py.File(filename, 'r')
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self, "Error", f"Failed to open file:\n{e}"
            )
            return

        if DATA_PATH not in new_file or FLAT_PATH not in new_file:
            new_file.close()
            QtWidgets.QMessageBox.warning(
                self, "Invalid File",
                f"File does not contain expected datasets:\n"
                f"  /{DATA_PATH}\n  /{FLAT_PATH}"
            )
            return

        # Only replace state once we know the new file is valid.
        if self.hdf5_file is not None:
            self.hdf5_file.close()
        self.hdf5_file = new_file

        self.data_ds = self.hdf5_file[DATA_PATH]
        self.flat_ds = self.hdf5_file[FLAT_PATH]
        self.energies = None
        if ENERGY_PATH in self.hdf5_file:
            try:
                self.energies = np.array(self.hdf5_file[ENERGY_PATH][:])
            except Exception:
                self.energies = None

        n = self.data_ds.shape[0]
        self.file_path_label.setText(os.path.basename(filename))
        self.file_path_label.setToolTip(filename)
        self.file_path_label.setStyleSheet("color: white;")
        self.data_shape_label.setText(str(self.data_ds.shape))
        self.flat_shape_label.setText(str(self.flat_ds.shape))
        self.num_frames_label.setText(str(n))

        # Reset state
        self.shift_x = 0
        self.shift_y = 0
        self._update_shift_labels()

        max_index = max(0, n - 1)
        self.image_slider.blockSignals(True)
        self.index_spin.blockSignals(True)
        self.image_slider.setMaximum(max_index)
        self.image_slider.setValue(0)
        self.image_slider.setEnabled(n > 0)
        self.index_spin.setRange(0, max_index)
        self.index_spin.setValue(0)
        self.index_spin.setEnabled(n > 0)
        self.image_slider.blockSignals(False)
        self.index_spin.blockSignals(False)

        # Re-validate external flat against new data shape
        if self.use_external_flat and self.ext_flat_ds is not None:
            self._validate_external_flat()

        # Load metadata
        self.metadata_viewer.load(self.hdf5_file)

        if n > 0:
            self._load_and_display(0)

    def _load_external_flat(self):
        filename, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Open External Flat File", "",
            "HDF5 Files (*.h5 *.hdf5);;All Files (*)"
        )
        if not filename:
            return
        try:
            new_file = h5py.File(filename, 'r')
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self, "Error", f"Failed to open external file:\n{e}"
            )
            return
        if FLAT_PATH not in new_file:
            new_file.close()
            QtWidgets.QMessageBox.warning(
                self, "Invalid File",
                f"External file has no /{FLAT_PATH} dataset."
            )
            return

        if self.ext_file is not None:
            self.ext_file.close()
        self.ext_file = new_file
        self.ext_flat_ds = new_file[FLAT_PATH]
        self.ext_flat_label.setText(os.path.basename(filename))
        self.ext_flat_label.setToolTip(filename)
        self.ext_flat_label.setStyleSheet("color: white;")

        if self._validate_external_flat():
            self._update_display()

    def _validate_external_flat(self):
        """Confirm the external flat is index-compatible with the current data.
        Sets self.ext_flat_status and returns True if usable."""
        if self.ext_flat_ds is None or self.data_ds is None:
            self.ext_flat_status.setText("")
            return False
        n_data = self.data_ds.shape[0]
        n_ext = self.ext_flat_ds.shape[0]
        data_hw = tuple(self.data_ds.shape[-2:])
        ext_hw = tuple(self.ext_flat_ds.shape[-2:])
        if data_hw != ext_hw:
            self.ext_flat_status.setText(
                f"<span style='color:#f66;'>Shape mismatch: "
                f"data is {data_hw}, external is {ext_hw}. Normalization disabled.</span>"
            )
            return False
        if n_ext < n_data:
            self.ext_flat_status.setText(
                f"<span style='color:#f66;'>External file has fewer frames "
                f"({n_ext}) than data ({n_data}). Normalization disabled.</span>"
            )
            return False
        if n_ext > n_data:
            self.ext_flat_status.setText(
                f"<span style='color:#fc6;'>External file has more frames "
                f"({n_ext}) than data ({n_data}); extra frames ignored.</span>"
            )
            return True
        self.ext_flat_status.setText(
            f"<span style='color:#6f6;'>External flats OK "
            f"({n_ext} frames, {ext_hw}).</span>"
        )
        return True

    # ── Display pipeline ────────────────────────────────────────────────
    def _load_and_display(self, index):
        if self.data_ds is None:
            return
        try:
            self.current_index = int(index)
            self.index_spin.blockSignals(True)
            self.index_spin.setValue(self.current_index)
            self.index_spin.blockSignals(False)

            self.current_data = np.array(self.data_ds[self.current_index])
            self.current_flat = self._select_flat(self.current_index)

            if self.energies is not None and 0 <= self.current_index < len(self.energies):
                e = float(self.energies[self.current_index])
                self.energy_label.setText(f"E = {e:.2f} eV")
            else:
                self.energy_label.setText("E = N/A")

            self._update_display()
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self, "Error", f"Failed to load image:\n{e}"
            )

    def _select_flat(self, index):
        """Return the flat frame to use for `index`, honoring the external-flat
        mode. Returns None if no usable flat is available."""
        if self.use_external_flat:
            if self.ext_flat_ds is None:
                return None
            if not (0 <= index < self.ext_flat_ds.shape[0]):
                return None
            return np.array(self.ext_flat_ds[index])
        if self.flat_ds is None:
            return None
        # Clamp to the last available flat, matching tomogui's behavior.
        idx = min(index, self.flat_ds.shape[0] - 1)
        if idx < 0:
            return None
        return np.array(self.flat_ds[idx])

    def _update_display(self):
        if self.current_data is None:
            return
        try:
            if self.normalization_enabled and self.current_flat is not None \
                    and self.current_flat.shape == self.current_data.shape:
                shifted = self._apply_shift(self.current_flat,
                                            self.shift_x, self.shift_y)
                epsilon = 1e-10
                data_f = self.current_data.astype(np.float32, copy=False)
                flat_f = shifted.astype(np.float32, copy=False)
                self.result_image = data_f / (flat_f + epsilon)
                self.result_image = np.nan_to_num(
                    self.result_image, nan=0.0, posinf=0.0, neginf=0.0
                )
            else:
                self.result_image = self.current_data.copy()
            self._update_statistics()
            self._apply_contrast_settings()
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self, "Error", f"Failed to update display:\n{e}"
            )

    def _apply_contrast_settings(self):
        if self.result_image is None:
            return
        mode = self.auto_level_combo.currentIndex()
        img = self.result_image
        if mode == 0:  # per image auto
            self.image_view.setImage(img, autoLevels=True, autoRange=False)
        elif mode == 1:  # min/max
            self.image_view.setImage(
                img, autoLevels=False, autoRange=False,
                levels=(float(np.min(img)), float(np.max(img)))
            )
        elif mode == 2:  # 1-99
            vmin, vmax = np.percentile(img, [1, 99])
            self.image_view.setImage(
                img, autoLevels=False, autoRange=False,
                levels=(float(vmin), float(vmax))
            )
        elif mode == 3:  # 2-98
            vmin, vmax = np.percentile(img, [2, 98])
            self.image_view.setImage(
                img, autoLevels=False, autoRange=False,
                levels=(float(vmin), float(vmax))
            )
        elif mode == 4:  # 5-95
            vmin, vmax = np.percentile(img, [5, 95])
            self.image_view.setImage(
                img, autoLevels=False, autoRange=False,
                levels=(float(vmin), float(vmax))
            )
        elif mode == 5:  # manual
            self.image_view.setImage(
                img, autoLevels=False, autoRange=False,
                levels=(self.min_spin.value(), self.max_spin.value())
            )

    def _update_statistics(self):
        if self.result_image is None:
            return
        img = self.result_image
        self.min_val_label.setText(f"{np.min(img):.4f}")
        self.max_val_label.setText(f"{np.max(img):.4f}")
        self.mean_val_label.setText(f"{np.mean(img):.4f}")
        self.std_val_label.setText(f"{np.std(img):.4f}")

    @staticmethod
    def _apply_shift(image, shift_x, shift_y):
        if shift_x == 0 and shift_y == 0:
            return image
        shifted = np.zeros_like(image)
        src_x0 = max(0, -shift_x)
        src_x1 = image.shape[1] - max(0, shift_x)
        src_y0 = max(0, -shift_y)
        src_y1 = image.shape[0] - max(0, shift_y)
        dst_x0 = max(0, shift_x)
        dst_x1 = image.shape[1] - max(0, -shift_x)
        dst_y0 = max(0, shift_y)
        dst_y1 = image.shape[0] - max(0, -shift_y)
        shifted[dst_y0:dst_y1, dst_x0:dst_x1] = image[src_y0:src_y1, src_x0:src_x1]
        return shifted

    # ── Callbacks ───────────────────────────────────────────────────────
    def _on_slider_changed(self, value):
        if self.index_spin.value() != value:
            self.index_spin.blockSignals(True)
            self.index_spin.setValue(value)
            self.index_spin.blockSignals(False)
        self._load_and_display(value)

    def _on_index_spin(self, value):
        if self.image_slider.value() != value:
            self.image_slider.blockSignals(True)
            self.image_slider.setValue(value)
            self.image_slider.blockSignals(False)
        self._load_and_display(value)

    def _on_normalization_changed(self, state):
        self.normalization_enabled = (state == QtCore.Qt.Checked)
        self._update_display()

    def _on_flat_source_changed(self):
        self.use_external_flat = self.external_flat_radio.isChecked()
        self.ext_flat_btn.setEnabled(self.use_external_flat)
        if self.use_external_flat:
            self._validate_external_flat()
        else:
            self.ext_flat_status.setText("")
        # Reload current frame's flat and redraw
        if self.current_data is not None:
            self.current_flat = self._select_flat(self.current_index)
            self._update_display()

    def _on_contrast_changed(self, index):
        is_manual = (index == 5)
        self.manual_controls.setVisible(is_manual)
        if is_manual and self.result_image is not None:
            self.min_spin.setValue(float(np.min(self.result_image)))
            self.max_spin.setValue(float(np.max(self.result_image)))
        self._update_display()

    def _on_manual_levels_changed(self):
        if self.auto_level_combo.currentIndex() == 5:
            self._update_display()

    def _auto_adjust_contrast(self):
        self._update_display()

    def _reset_shift(self):
        self.shift_x = 0
        self.shift_y = 0
        self._update_shift_labels()
        self._update_display()

    def _update_shift_labels(self):
        self.shift_x_label.setText(str(self.shift_x))
        self.shift_y_label.setText(str(self.shift_y))

    # ── Keyboard shift on the flat ──────────────────────────────────────
    def keyPressEvent(self, event):
        if self.current_data is None or not self.normalization_enabled:
            super().keyPressEvent(event)
            return
        step = 1
        if event.modifiers() & QtCore.Qt.ShiftModifier:
            step = 10
        elif event.modifiers() & QtCore.Qt.ControlModifier:
            step = 50
        key = event.key()
        if key == QtCore.Qt.Key_Left:
            self.shift_x -= step
        elif key == QtCore.Qt.Key_Right:
            self.shift_x += step
        elif key == QtCore.Qt.Key_Up:
            self.shift_y -= step
        elif key == QtCore.Qt.Key_Down:
            self.shift_y += step
        else:
            super().keyPressEvent(event)
            return
        self._update_shift_labels()
        self._update_display()

    # ── Cleanup ─────────────────────────────────────────────────────────
    def closeEvent(self, event):
        if self.hdf5_file is not None:
            try:
                self.hdf5_file.close()
            except Exception:
                pass
            self.hdf5_file = None
        if self.ext_file is not None:
            try:
                self.ext_file.close()
            except Exception:
                pass
            self.ext_file = None
        super().closeEvent(event)


def main(argv=None):
    argv = list(sys.argv if argv is None else argv)
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(argv)
    file_path = argv[1] if len(argv) > 1 else None
    win = Viewer2D(file_path=file_path)
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
