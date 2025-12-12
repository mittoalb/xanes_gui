#!/usr/bin/env python3

import sys
import os
import time
import signal
import subprocess
import json
import numpy as np
import pvaccess as pva
import epics

from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                              QTabWidget, QLabel, QLineEdit, QPushButton, QTextEdit,
                              QProgressBar, QListWidget, QRadioButton, QCheckBox, QGroupBox,
                              QMessageBox, QFileDialog, QComboBox, QFrame, QSplitter, QDialog,
                              QScrollArea, QButtonGroup)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, pyqtSlot, QTimer
from PyQt5.QtGui import QPalette, QColor

import pyqtgraph as pg

# -------------------------
# Defaults / Config
# -------------------------
DEFAULTS = {
    # PVA / EPICS for Calibrate
    "detector_pv": "32idbSP1:Pva1:Image",
    "cam_acquire_pv": "32idbSP1:cam1:Acquire",
    "cam_acquire_rbv_pv": "32idbSP1:cam1:Acquire_RBV",
    "energy_pv": "32id:TXMOptics:Energy",  # Target energy value
    "energy_set_pv": "32id:TXMOptics:EnergySet",  # Button to trigger move
    "energy_rb_pv": "32id:TXMOptics:Energy_RBV",
    "settle_s": 0.15,
    # XANES PVs to prefill fields
    "xanes_start_pv":  "32id:TXMOptics:XanesStart",
    "xanes_end_pv":    "32id:TXMOptics:XanesEnd",
    "xanes_step_pv":   "32id:TXMOptics:XanesStep",  # step size in eV
    # Calibration files
    "calib_file1_pv": "32id:TXMOptics:EnergyCalibrationFileOne",
    "calib_file2_pv": "32id:TXMOptics:EnergyCalibrationFileTwo",
    "calib_base_dir": "/home/beams/USERTXM/epics/synApps/support/txmoptics/iocBoot/iocTXMOptics/",
    # Custom energies file (for non-linear scans)
    "custom_energies_file": os.path.expanduser("~/energies.npy"),
    # Optional safety PVs (only used when pressing Stop; set to "" to disable)
    "epid_h_on_pv": "32idbSoft:epidH:on",
    "epid_v_on_pv": "32idbSoft:epidV:on",
    "shaker_run_pv": "32idbSoft:epidShaker:shaker:run",
    # Reference curve files (auto-load on element click)
    "curve_dir_calibrated": "",
    "curve_dir_simulated": "",
    "curve_ext": ".npy",  # ".npy" or ".csv"
    # Remote SSH configuration
    "remote_user": "usertxm",
    "remote_host": "gauss",
    "conda_env": "tomoscan",
    "work_dir": "/home/beams/USERTXM/epics/synApps/support/tomoscan/iocBoot/iocTomoScan_32ID/",
    "conda_path": "/home/beams/USERTXM/conda/anaconda",
    "script_name": "/home/beams/USERTXM/Software/xanes_gui/xanes_energy.py",
}

# K-edges and L-edges approx. 6–16 keV (rounded to 3 decimals)
K_EDGES_6_16_KEV = [
    ("Mn",  6.539), ("Fe",  7.112), ("Co",  7.709), ("Ni",  8.333),
    ("Cu",  8.979), ("Zn",  9.659), ("Ga", 10.367), ("Ge", 11.103),
    ("Pt", 11.564), ("As", 11.867), ("Se", 12.658), ("Br", 13.474),
    ("Kr", 14.327), ("Rb", 15.200), ("Sr", 16.105),
]
ELEMENT_TO_EDGE = {el: e for el, e in K_EDGES_6_16_KEV}

# -------------------------
# Helpers
# -------------------------
def pva_get_ndarray(det_pv):
    """Fetch NTNDArray via pvaccess and return numpy HxW array."""
    ch = pva.Channel(det_pv)
    st = ch.get()
    val = st['value'][0]  # union
    for key in ('ushortValue','shortValue','intValue','floatValue','doubleValue','ubyteValue','byteValue'):
        if key in val:
            flat = np.asarray(val[key])
            break
    else:
        raise RuntimeError("Unsupported NTNDArray numeric type")

    # Try multiple methods to get dimensions
    dims = []

    # Method 1: Try 'dimension' field
    try:
        dims = st['dimension']
    except Exception:
        pass

    # Method 2: Try to get dims from attributes
    if len(dims) < 2:
        try:
            attrs = st['attribute']
            width = None
            height = None
            for attr in attrs:
                name = attr['name']
                # Try common attribute names for array dimensions
                if name in ('ArraySize0_Y', 'ArraySizeY', 'dimY'):
                    height = int(attr['value'])
                elif name in ('ArraySize1_X', 'ArraySizeX', 'dimX'):
                    width = int(attr['value'])
            if width and height and width * height == flat.size:
                return flat.reshape(height, width)
        except Exception:
            pass

    # Method 2b: Try 'dims' field directly (some NTNDArray versions)
    if len(dims) < 2:
        try:
            if 'dims' in st:
                dim_list = st['dims']
                if len(dim_list) >= 2:
                    h = int(dim_list[0])
                    w = int(dim_list[1])
                    if h * w == flat.size:
                        return flat.reshape(h, w)
        except Exception:
            pass

    # Method 3: Use dimension field if available
    if len(dims) >= 2:
        h = int(dims[0]['size'])
        w = int(dims[1]['size'])
        if h*w == flat.size:
            return flat.reshape(h, w)

    # Method 4: Try to get ROI dimensions from TXM crop PVs
    if len(dims) < 2:
        try:
            left = int(epics.caget('32id:TXMOptics:CropLeft.VAL'))
            right = int(epics.caget('32id:TXMOptics:CropRight.VAL'))
            top = int(epics.caget('32id:TXMOptics:CropTop.VAL'))
            bottom = int(epics.caget('32id:TXMOptics:CropBottom.VAL'))

            width = right - left
            height = bottom - top

            if width > 0 and height > 0 and width * height == flat.size:
                return flat.reshape(height, width)
        except Exception:
            pass

    # Method 5: Try to get ArraySize from EPICS CA (not PVA)
    # Extract base PV name from detector PV (e.g., "32idbSP1:Pva1:Image" -> "32idbSP1:cam1:")
    if len(dims) < 2:
        try:
            # Common pattern: PvaX:Image -> camX:ArraySizeY_RBV, ArraySizeX_RBV
            base_pv = det_pv.replace(':Pva1:Image', ':cam1:').replace(':Pva2:Image', ':cam2:')
            if base_pv != det_pv:  # We found a pattern
                height = int(epics.caget(base_pv + 'ArraySizeY_RBV'))
                width = int(epics.caget(base_pv + 'ArraySizeX_RBV'))
                if width and height and width * height == flat.size:
                    return flat.reshape(height, width)
        except Exception:
            pass

    # Method 6: Fallback - try all factor pairs to find best rectangular fit
    # This handles ROI cases where image is not square
    n = flat.size
    best_h, best_w = None, None
    for h in range(int(np.sqrt(n)), 0, -1):
        if n % h == 0:
            w = n // h
            best_h, best_w = h, w
            break

    if best_h and best_w:
        return flat.reshape(best_h, best_w)

    # Last resort: square root method (will likely fail)
    side = int(np.sqrt(flat.size))
    return flat.reshape(side, flat.size // side)

def epics_get(pv):
    v = epics.caget(pv, as_string=True)
    if v is None:
        raise RuntimeError(f"caget failed: {pv}")
    return str(v)

def epics_put(pv, val, wait=True):
    if not pv:
        return
    ok = epics.caput(pv, val, wait=wait, timeout=10.0)
    if not ok:
        raise RuntimeError(f"caput failed: {pv}={val}")

def _load_curve_file(path):
    """Load (E, Y) from .npy or .csv. Robust to 2xN or Nx2 arrays."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".npy":
        try:
            # Try to load as binary numpy array first
            arr = np.load(path, allow_pickle=False)
            if arr.ndim != 2:
                raise ValueError("NPY must be 2D array with 2 columns/rows")
            if arr.shape[0] == 2:
                E, Y = arr[0], arr[1]
            elif arr.shape[1] == 2:
                E, Y = arr[:, 0], arr[:, 1]
            else:
                raise ValueError("NPY shape must be 2xN or Nx2")
        except (ValueError, OSError) as e:
            # If binary load fails, try loading as text file (some .npy files are actually text)
            try:
                data = np.loadtxt(path)
                if data.ndim == 1:
                    raise ValueError("File must have at least 2 columns")
                if data.shape[1] < 2:
                    raise ValueError("File must have >=2 columns")
                E, Y = data[:, 0], data[:, 1]
            except Exception:
                raise ValueError(f"Could not load .npy file as binary or text: {e}")
    else:
        # CSV/TXT: try comma first; fallback to any whitespace
        try:
            data = np.loadtxt(path, delimiter=",")
        except Exception:
            data = np.loadtxt(path)
        if data.ndim == 1:
            raise ValueError("File must have at least 2 columns")
        if data.shape[1] < 2:
            raise ValueError("File must have >=2 columns")
        E, Y = data[:, 0], data[:, 1]
    return np.asarray(E, dtype=float), np.asarray(Y, dtype=float)

# -------------------------
# Worker Threads
# -------------------------
class PrefillWorker(QThread):
    """Thread to prefill scan fields from EPICS PVs."""
    result = pyqtSignal(str, str, str)  # start, end, step
    error = pyqtSignal(str)

    def run(self):
        try:
            s = epics_get(DEFAULTS["xanes_start_pv"])
            e = epics_get(DEFAULTS["xanes_end_pv"])
            step = epics_get(DEFAULTS["xanes_step_pv"])
            self.result.emit(s, e, step)
        except Exception as ex:
            self.error.emit(str(ex))

class CalibrationWorker(QThread):
    """Thread to perform calibration scan."""
    progress = pyqtSignal(int)  # progress index
    log = pyqtSignal(str)  # log messages
    plot_update = pyqtSignal(object, object)  # energies, sums for plotting
    completed = pyqtSignal(object, object)  # final energies, sums
    error = pyqtSignal(str)

    def __init__(self, energies, det_pv, acq_pv, acq_rbv_pv, e_pv, e_set_pv, e_rb_pv, settle):
        super().__init__()
        self.energies = energies
        self.det_pv = det_pv
        self.acq_pv = acq_pv
        self.acq_rbv_pv = acq_rbv_pv
        self.e_pv = e_pv  # Target energy value PV
        self.e_set_pv = e_set_pv  # Button to trigger move
        self.e_rb_pv = e_rb_pv
        self.settle = settle
        self._stop_requested = False

    def stop(self):
        self._stop_requested = True

    def run(self):
        sums = []
        npts = len(self.energies)

        try:
            for i, E in enumerate(self.energies, start=1):
                if self._stop_requested:
                    self.log.emit("Calibration aborted by user.")
                    break

                self.log.emit(f"Set energy → {E:.4f} keV")
                try:
                    # Step 1: Write target energy value
                    epics_put(self.e_pv, E, wait=True)
                    # Step 2: Press the button to trigger move
                    epics_put(self.e_set_pv, 1, wait=False)
                except Exception as ex:
                    self.log.emit(f"WARNING: Energy set failed: {ex}")

                # Wait for energy readback to reach target
                t0 = time.time()
                if self.e_rb_pv:
                    energy_reached = False
                    for attempt in range(100):  # Up to 5 seconds
                        try:
                            rb = float(epics_get(self.e_rb_pv))
                            if abs(rb - E) <= 0.001:  # ~1 eV tolerance in keV
                                energy_reached = True
                                elapsed = time.time() - t0
                                self.log.emit(f"Energy reached {rb:.4f} keV in {elapsed:.2f}s")
                                break
                        except Exception:
                            pass
                        time.sleep(0.05)
                    if not energy_reached:
                        self.log.emit(f"WARNING: Energy may not have reached {E:.4f} keV")

                # Additional settle time after reaching target
                dt = max(0.0, self.settle - (time.time() - t0))
                if dt > 0:
                    time.sleep(dt)

                self.log.emit("Acquire one frame")
                try:
                    epics_put(self.acq_pv, 1, wait=False)
                except Exception:
                    pass
                for _ in range(80):
                    if self._stop_requested:
                        break
                    try:
                        if float(epics_get(self.acq_rbv_pv)) == 0.0:
                            break
                    except Exception:
                        pass
                    time.sleep(0.05)

                img = pva_get_ndarray(self.det_pv)
                s = float(np.sum(img))
                sums.append(s)
                self.log.emit(f"Sum @ {E:.4f} keV = {s:.6g}")

                self.progress.emit(i)

                # Emit plot update
                self.plot_update.emit(self.energies[:i], np.array(sums, dtype=float))

            # Emit final result
            if not self._stop_requested:
                self.completed.emit(self.energies, np.array(sums, dtype=float))

        except Exception as ex:
            self.error.emit(f"ERROR (calibrate): {ex}")

class StartScriptWorker(QThread):
    """Thread to run the XANES script locally or via SSH in embedded terminal."""
    log = pyqtSignal(str)
    finished = pyqtSignal(int)  # exit code
    error = pyqtSignal(str)

    def __init__(self, remote_config=None):
        super().__init__()
        self.remote_config = remote_config or {}
        self._stop_requested = False
        self._proc = None
        self._proc_pgid = None

    def stop(self):
        self._stop_requested = True
        if self._proc and self._proc.poll() is None and self._proc_pgid:
            try:
                os.killpg(self._proc_pgid, signal.SIGTERM)
            except Exception as ex:
                self.log.emit(f"Terminate failed: {ex}")

    def run(self):
        try:
            # Extract configuration from remote_config
            remote_user = self.remote_config.get("remote_user", "usertxm")
            remote_host = self.remote_config.get("remote_host", "gauss")
            conda_env = self.remote_config.get("conda_env", "tomoscan")
            work_dir = self.remote_config.get("work_dir", "/home/beams/USERTXM/epics/synApps/support/tomoscan/iocBoot/iocTomoScan_32ID/")
            conda_path = self.remote_config.get("conda_path", "/home/beams/USERTXM/conda/anaconda")
            script_name = self.remote_config.get("script_name", "/home/beams/USERTXM/Software/xanes_gui/xanes_energy.py")

            # Check if we're already on the target machine or if script exists locally
            import socket
            current_hostname = socket.gethostname()
            current_hostname_short = current_hostname.split('.')[0]  # Get short hostname

            # Check if local: exact match, short name match, localhost, or script file exists locally
            is_local = (
                current_hostname == remote_host or
                current_hostname_short == remote_host or
                remote_host in ["localhost", "127.0.0.1", ""] or
                os.path.exists(script_name)  # If script exists locally, run locally
            )

            if is_local:
                # Run locally
                self.log.emit(f"Running locally on {current_hostname}")
                self.log.emit(f"Executing: {script_name}")

                # Build local command with conda activation
                cmd = [
                    "bash", "-l", "-c",
                    f"cd {work_dir} && "
                    f"source {conda_path}/etc/profile.d/conda.sh && "
                    f"conda activate {conda_env} && "
                    f"python {script_name}"
                ]
            else:
                # Run via SSH
                self.log.emit(f"Connecting to {remote_user}@{remote_host}...")
                self.log.emit(f"Running: {script_name}")

                # Build SSH command
                cmd = [
                    "ssh", "-t", f"{remote_user}@{remote_host}",
                    f"bash -l -c \"cd {work_dir} && hostname && "
                    f"source {conda_path}/etc/profile.d/conda.sh && "
                    f"conda activate {conda_env} && "
                    f"python {script_name}\""
                ]

            # Run command
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,  # Line buffered
                preexec_fn=os.setsid
            )
            self._proc_pgid = os.getpgid(self._proc.pid)

            # Stream output line by line
            for line in self._proc.stdout:
                if self._stop_requested:
                    break
                self.log.emit(line.rstrip())

            rc = self._proc.wait()
            if rc == 0:
                self.log.emit("Script completed successfully")
            else:
                self.log.emit(f"Script exited with code: {rc}")
            self.finished.emit(rc)

        except Exception as ex:
            self.error.emit(f"ERROR: {str(ex)}")

# -------------------------
# GUI
# -------------------------
class XANESGui(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("XANES Control")
        self.resize(1500, 1200)

        # Settings file path
        self.settings_file = os.path.expanduser("~/.xanes_gui_settings.json")

        # Dark theme
        self.set_dark_theme()

        # State variables
        self._last_calib = None  # (energies, sums)
        self._linear_region = None
        self._selected_range = None
        self._custom_energies = None
        self._calib_worker = None
        self._start_worker = None

        # Main widget and layout
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Tab widget
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)

        # Build tabs
        self.build_scan_tab()
        self.build_pv_tab()

        # Load saved settings
        self.load_settings()

        # Welcome message
        self.log("XANES Control GUI initialized")
        self.log("Ready to calibrate or start XANES scan")

        # Start prefill worker
        self.prefill_worker = PrefillWorker()
        self.prefill_worker.result.connect(self.on_prefill_result)
        self.prefill_worker.error.connect(self.on_prefill_error)
        self.prefill_worker.start()

    def set_dark_theme(self):
        """Apply dark theme to the application."""
        dark_palette = QPalette()
        dark_palette.setColor(QPalette.Window, QColor(43, 43, 43))
        dark_palette.setColor(QPalette.WindowText, Qt.white)
        dark_palette.setColor(QPalette.Base, QColor(30, 30, 30))
        dark_palette.setColor(QPalette.AlternateBase, QColor(43, 43, 43))
        dark_palette.setColor(QPalette.ToolTipBase, Qt.white)
        dark_palette.setColor(QPalette.ToolTipText, Qt.white)
        dark_palette.setColor(QPalette.Text, Qt.white)
        dark_palette.setColor(QPalette.Button, QColor(43, 43, 43))
        dark_palette.setColor(QPalette.ButtonText, Qt.white)
        dark_palette.setColor(QPalette.BrightText, Qt.red)
        dark_palette.setColor(QPalette.Link, QColor(42, 130, 218))
        dark_palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
        dark_palette.setColor(QPalette.HighlightedText, Qt.black)
        self.setPalette(dark_palette)

    # ---------- Scan Tab ----------
    def build_scan_tab(self):
        scan_widget = QWidget()
        scan_layout = QVBoxLayout(scan_widget)

        # Top splitter: plot (left) + side panel (right)
        top_splitter = QSplitter(Qt.Horizontal)
        top_splitter.setHandleWidth(10)  # Make splitter handle wider for easier dragging
        scan_layout.addWidget(top_splitter, stretch=1)

        # LEFT: Plot
        plot_widget = QWidget()
        plot_layout = QVBoxLayout(plot_widget)
        self.plot_widget = pg.PlotWidget(background='#1e1e1e')
        self.plot_widget.setLabel('bottom', 'Energy (keV)', color='white', size='12pt')
        self.plot_widget.setLabel('left', 'Signal (a.u.)', color='white', size='12pt')
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.plot_widget.getAxis('bottom').setPen('white')
        self.plot_widget.getAxis('left').setPen('white')
        self.plot_widget.getAxis('bottom').setTextPen('white')
        self.plot_widget.getAxis('left').setTextPen('white')

        # Add legend
        self.plot_legend = self.plot_widget.addLegend()

        # Store calibration plot item for live updates
        self._calib_plot_item = None

        plot_layout.addWidget(self.plot_widget)
        top_splitter.addWidget(plot_widget)

        # RIGHT: Side panel
        side_panel = QWidget()
        side_layout = QVBoxLayout(side_panel)
        side_layout.setContentsMargins(10, 10, 10, 10)

        # Title
        side_layout.addWidget(QLabel("Edges (6–16 keV)"))

        # Curve source selection
        curve_source_group = QGroupBox("Reference Curves")
        curve_source_layout = QVBoxLayout()
        self.curve_source_calibrated = QRadioButton("Calibrated (measured)")
        self.curve_source_simulated = QRadioButton("Simulated")
        self.curve_source_calibrated.setChecked(True)
        curve_source_layout.addWidget(self.curve_source_calibrated)
        curve_source_layout.addWidget(self.curve_source_simulated)
        curve_source_group.setLayout(curve_source_layout)
        side_layout.addWidget(curve_source_group)

        # Search/filter
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("Filter:"))
        self.edge_filter = QLineEdit()
        self.edge_filter.setMaximumWidth(120)
        self.edge_filter.textChanged.connect(self.filter_edges)
        filter_layout.addWidget(self.edge_filter)
        filter_layout.addStretch()
        side_layout.addLayout(filter_layout)

        # Edge listbox
        self.edge_list = QListWidget()
        self.edge_list.setMaximumHeight(300)
        self._all_edge_labels = [f"{el:>2s}  {E:>6.3f} keV" for el, E in K_EDGES_6_16_KEV]
        for label in self._all_edge_labels:
            self.edge_list.addItem(label)
        self.edge_list.itemClicked.connect(self.on_edge_click)
        side_layout.addWidget(self.edge_list)

        # Separator
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        side_layout.addWidget(line)

        # Selected element info
        self.sel_el_label = QLabel("Element: —")
        self.sel_e_label = QLabel("Edge: — keV")
        side_layout.addWidget(self.sel_el_label)
        side_layout.addWidget(self.sel_e_label)

        # Auto-fill configuration
        autofill_group = QGroupBox("Auto-fill scan around edge")
        autofill_layout = QVBoxLayout()

        win_layout = QHBoxLayout()
        win_layout.addWidget(QLabel("± window (keV):"))
        self.win_entry = QLineEdit("0.20")
        self.win_entry.setMaximumWidth(80)
        win_layout.addWidget(self.win_entry)
        win_layout.addStretch()
        autofill_layout.addLayout(win_layout)

        npts_layout = QHBoxLayout()
        npts_layout.addWidget(QLabel("# points:"))
        self.npts_entry = QLineEdit("121")
        self.npts_entry.setMaximumWidth(80)
        npts_layout.addWidget(self.npts_entry)
        npts_layout.addStretch()
        autofill_layout.addLayout(npts_layout)

        autofill_group.setLayout(autofill_layout)
        side_layout.addWidget(autofill_group)

        # Apply button
        self.apply_edge_btn = QPushButton("Apply to fields")
        self.apply_edge_btn.clicked.connect(self.apply_edge_to_fields)
        side_layout.addWidget(self.apply_edge_btn)

        # Overlay toggle
        self.overlay_checkbox = QCheckBox("Overlay on existing plot")
        side_layout.addWidget(self.overlay_checkbox)

        # Load curve button
        self.load_curve_btn = QPushButton("Load curve (CSV/NPY)")
        self.load_curve_btn.clicked.connect(self.load_curve_dialog)
        side_layout.addWidget(self.load_curve_btn)

        side_layout.addStretch()
        top_splitter.addWidget(side_panel)
        top_splitter.setStretchFactor(0, 3)
        top_splitter.setStretchFactor(1, 1)

        # Energy method selection
        method_group = QGroupBox("Energy Range Method")
        method_layout = QHBoxLayout()

        self.method_manual = QRadioButton("Manual (Start/End/Step)")
        self.method_plot = QRadioButton("Select range on plot")
        self.method_custom = QRadioButton("Import custom energy array")
        self.method_manual.setChecked(True)

        self.method_manual.toggled.connect(self.on_method_change)
        self.method_plot.toggled.connect(self.on_method_change)
        self.method_custom.toggled.connect(self.on_method_change)

        method_layout.addWidget(self.method_manual)
        method_layout.addWidget(self.method_plot)
        method_layout.addWidget(self.method_custom)
        method_layout.addStretch()
        method_group.setLayout(method_layout)
        scan_layout.addWidget(method_group)

        # Manual method frame
        self.manual_frame = QWidget()
        manual_layout = QHBoxLayout(self.manual_frame)
        manual_layout.setContentsMargins(10, 5, 10, 5)
        manual_layout.addWidget(QLabel("Start energy (keV):"))
        self.e_start = QLineEdit()
        self.e_start.setMaximumWidth(100)
        self.e_start.textChanged.connect(self.update_manual_points)
        manual_layout.addWidget(self.e_start)
        manual_layout.addWidget(QLabel("End energy (keV):"))
        self.e_end = QLineEdit()
        self.e_end.setMaximumWidth(100)
        self.e_end.textChanged.connect(self.update_manual_points)
        manual_layout.addWidget(self.e_end)
        manual_layout.addWidget(QLabel("Step (eV):"))
        self.e_step = QLineEdit()
        self.e_step.setMaximumWidth(80)
        self.e_step.textChanged.connect(self.update_manual_points)
        manual_layout.addWidget(self.e_step)
        self.manual_info = QLabel("")
        self.manual_info.setStyleSheet("color: cyan;")
        manual_layout.addWidget(self.manual_info)
        manual_layout.addStretch()
        scan_layout.addWidget(self.manual_frame)

        # Plot selection frame
        self.plot_select_frame = QWidget()
        plot_select_layout = QHBoxLayout(self.plot_select_frame)
        plot_select_layout.setContentsMargins(10, 5, 10, 5)
        plot_select_layout.addWidget(QLabel("Click 'Enable Selection' then drag on the plot to select energy range"))
        self.btn_enable_select = QPushButton("Enable Selection")
        self.btn_enable_select.clicked.connect(self.enable_plot_selection)
        plot_select_layout.addWidget(self.btn_enable_select)
        plot_select_layout.addWidget(QLabel("Step (eV):"))
        self.plot_step = QLineEdit("1")
        self.plot_step.setMaximumWidth(60)
        self.plot_step.textChanged.connect(self.update_plot_selection_points)
        plot_select_layout.addWidget(self.plot_step)
        self.plot_range_label = QLabel("Range: Not selected")
        self.plot_range_label.setStyleSheet("color: cyan;")
        plot_select_layout.addWidget(self.plot_range_label)
        plot_select_layout.addStretch()
        self.plot_select_frame.hide()
        scan_layout.addWidget(self.plot_select_frame)

        # Custom energy frame
        self.custom_frame = QWidget()
        custom_layout = QHBoxLayout(self.custom_frame)
        custom_layout.setContentsMargins(10, 5, 10, 5)
        custom_layout.addWidget(QLabel("Energy table (one value per row):"))
        self.btn_load_custom = QPushButton("Load from CSV/TXT")
        self.btn_load_custom.clicked.connect(self.load_custom_energies)
        custom_layout.addWidget(self.btn_load_custom)
        self.btn_edit_table = QPushButton("Edit Table")
        self.btn_edit_table.clicked.connect(self.edit_energy_table)
        custom_layout.addWidget(self.btn_edit_table)
        self.custom_info_label = QLabel("No custom energies loaded")
        self.custom_info_label.setStyleSheet("color: cyan;")
        custom_layout.addWidget(self.custom_info_label)
        custom_layout.addStretch()
        self.custom_frame.hide()
        scan_layout.addWidget(self.custom_frame)

        # Progress bar
        self.progress = QProgressBar()
        scan_layout.addWidget(self.progress)

        # Buttons
        btn_layout = QHBoxLayout()
        self.btn_calibrate = QPushButton("Calibrate")
        self.btn_calibrate.setStyleSheet("background-color: #FFA500; color: black; font-weight: bold; min-height: 40px;")
        self.btn_calibrate.clicked.connect(self.on_calibrate)
        btn_layout.addWidget(self.btn_calibrate)

        self.btn_start = QPushButton("Start XANES")
        self.btn_start.setStyleSheet("background-color: #32CD32; color: black; font-weight: bold; min-height: 40px;")
        self.btn_start.clicked.connect(self.on_start)
        btn_layout.addWidget(self.btn_start)

        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setStyleSheet("background-color: #FF3B30; color: white; font-weight: bold; min-height: 40px;")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.on_stop)
        btn_layout.addWidget(self.btn_stop)

        scan_layout.addLayout(btn_layout)

        # Terminal/Log
        terminal_layout = QHBoxLayout()
        terminal_label = QLabel("Terminal:")
        terminal_layout.addWidget(terminal_label)
        terminal_layout.addStretch()
        self.btn_clear_terminal = QPushButton("Clear")
        self.btn_clear_terminal.setMaximumWidth(80)
        self.btn_clear_terminal.clicked.connect(self.clear_terminal)
        terminal_layout.addWidget(self.btn_clear_terminal)
        scan_layout.addLayout(terminal_layout)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(300)
        # Terminal styling
        self.log_text.setStyleSheet("""
            QTextEdit {
                background-color: #000000;
                color: #00ff00;
                font-family: 'Courier New', 'Monospace', monospace;
                font-size: 10pt;
                padding: 5px;
            }
        """)
        scan_layout.addWidget(self.log_text)

        self.tabs.addTab(scan_widget, "Scan")

    # ---------- PV Settings Tab ----------
    def build_pv_tab(self):
        pv_widget = QWidget()
        pv_layout = QVBoxLayout(pv_widget)

        # Scroll area for settings
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)

        # PV configuration group
        pv_group = QGroupBox("EPICS / PVA Configuration")
        pv_grid = QVBoxLayout()

        # Create all PV entry fields
        self.detector_pv = QLineEdit(DEFAULTS["detector_pv"])
        self.cam_acquire_pv = QLineEdit(DEFAULTS["cam_acquire_pv"])
        self.cam_acquire_rbv_pv = QLineEdit(DEFAULTS["cam_acquire_rbv_pv"])
        self.energy_pv = QLineEdit(DEFAULTS["energy_pv"])
        self.energy_set_pv = QLineEdit(DEFAULTS["energy_set_pv"])
        self.energy_rb_pv = QLineEdit(DEFAULTS["energy_rb_pv"])
        self.settle_time = QLineEdit(str(DEFAULTS["settle_s"]))
        self.curve_dir_calibrated = QLineEdit(DEFAULTS["curve_dir_calibrated"])
        self.curve_dir_simulated = QLineEdit(DEFAULTS["curve_dir_simulated"])
        self.curve_ext = QComboBox()
        self.curve_ext.addItems([".npy", ".csv"])
        self.curve_ext.setCurrentText(DEFAULTS["curve_ext"])

        # Remote SSH configuration fields
        self.remote_user = QLineEdit(DEFAULTS["remote_user"])
        self.remote_host = QLineEdit(DEFAULTS["remote_host"])
        self.conda_env = QLineEdit(DEFAULTS["conda_env"])
        self.work_dir = QLineEdit(DEFAULTS["work_dir"])
        self.conda_path = QLineEdit(DEFAULTS["conda_path"])
        self.script_name = QLineEdit(DEFAULTS["script_name"])

        # Add rows
        rows = [
            ("Detector PVA (NTNDArray):", self.detector_pv, None),
            ("cam:Acquire PV:", self.cam_acquire_pv, None),
            ("cam:Acquire_RBV PV:", self.cam_acquire_rbv_pv, None),
            ("Energy PV (target value):", self.energy_pv, None),
            ("Energy set PV (button):", self.energy_set_pv, None),
            ("Energy RB PV (opt):", self.energy_rb_pv, None),
            ("Settle (s):", self.settle_time, None),
            ("Calibrated curves folder:", self.curve_dir_calibrated, "browse_calib"),
            ("Simulated curves folder:", self.curve_dir_simulated, "browse_sim"),
            ("Ref curve extension:", self.curve_ext, "combo"),
        ]

        for label_text, widget, kind in rows:
            row_layout = QHBoxLayout()
            label = QLabel(label_text)
            label.setMinimumWidth(200)
            row_layout.addWidget(label)

            if kind == "browse_calib":
                row_layout.addWidget(widget, stretch=1)
                browse_btn = QPushButton("Browse...")
                browse_btn.clicked.connect(lambda checked, w=widget: self.browse_curve_dir(w, "calibrated"))
                row_layout.addWidget(browse_btn)
            elif kind == "browse_sim":
                row_layout.addWidget(widget, stretch=1)
                browse_btn = QPushButton("Browse...")
                browse_btn.clicked.connect(lambda checked, w=widget: self.browse_curve_dir(w, "simulated"))
                row_layout.addWidget(browse_btn)
            elif kind == "combo":
                row_layout.addWidget(widget)
                row_layout.addStretch()
            else:
                row_layout.addWidget(widget, stretch=1)

            pv_grid.addLayout(row_layout)

        pv_group.setLayout(pv_grid)
        scroll_layout.addWidget(pv_group)

        # Remote SSH configuration group
        remote_group = QGroupBox("Remote Execution Configuration (SSH)")
        remote_grid = QVBoxLayout()

        remote_rows = [
            ("Remote user:", self.remote_user),
            ("Remote host:", self.remote_host),
            ("Conda environment:", self.conda_env),
            ("Working directory:", self.work_dir),
            ("Conda path:", self.conda_path),
            ("Python script path:", self.script_name),
        ]

        for label_text, widget in remote_rows:
            row_layout = QHBoxLayout()
            label = QLabel(label_text)
            label.setMinimumWidth(200)
            row_layout.addWidget(label)
            row_layout.addWidget(widget, stretch=1)
            remote_grid.addLayout(row_layout)

        remote_group.setLayout(remote_grid)
        scroll_layout.addWidget(remote_group)
        scroll_layout.addStretch()

        scroll.setWidget(scroll_content)
        pv_layout.addWidget(scroll)

        # Save button
        save_btn = QPushButton("Save Settings")
        save_btn.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold; min-height: 35px;")
        save_btn.clicked.connect(self.save_settings)
        pv_layout.addWidget(save_btn)

        self.tabs.addTab(pv_widget, "PV Settings")

    # ---------- Logging ----------
    def log(self, msg):
        """Add a message to the terminal with timestamp."""
        ts = time.strftime("%H:%M:%S")
        # Color codes for different message types
        if msg.startswith("ERROR") or "error" in msg.lower() or "failed" in msg.lower():
            color = "#ff0000"  # Red for errors
        elif msg.startswith("WARNING") or "warning" in msg.lower():
            color = "#ffaa00"  # Orange for warnings
        elif "Set energy" in msg or "Acquire" in msg:
            color = "#00aaff"  # Blue for operations
        elif "Sum @" in msg or "points" in msg:
            color = "#ffff00"  # Yellow for data
        elif "Loaded" in msg or "saved" in msg.lower() or "completed" in msg.lower():
            color = "#00ff00"  # Green for success
        else:
            color = "#00ff00"  # Default green

        self.log_text.append(f'<span style="color: #888888;">[{ts}]</span> <span style="color: {color};">{msg}</span>')
        # Auto-scroll to bottom
        self.log_text.verticalScrollBar().setValue(self.log_text.verticalScrollBar().maximum())

    def clear_terminal(self):
        """Clear the terminal output."""
        self.log_text.clear()
        self.log("Terminal cleared")

    # ---------- Prefill ----------
    def on_prefill_result(self, s, e, step):
        """Handle prefill result from worker."""
        self.e_start.setText(s)
        self.e_end.setText(e)
        try:
            step_val = float(step)
        except Exception:
            step_val = 1.0
        self.e_step.setText(str(step_val))
        self.update_manual_points()
        self.log(f"Prefilled from EPICS: start={s} end={e} step={step} eV")

    def on_prefill_error(self, error):
        """Handle prefill error."""
        self.log(f"Prefill failed: {error}")

    def update_manual_points(self):
        """Calculate and display number of points based on start, end, step."""
        try:
            emin = float(self.e_start.text())
            emax = float(self.e_end.text())
            step = float(self.e_step.text())
            if step <= 0:
                self.manual_info.setText("Step must be > 0")
                return
            if step < 1.0:
                self.manual_info.setText("⚠ Step < 1 eV (min recommended)")
                return
            npts = int((emax*1000 - emin*1000)/step) + 1
            self.manual_info.setText(f"→ {npts} points")
        except ValueError:
            self.manual_info.setText("")

    # ---------- Side Panel Actions ----------
    def filter_edges(self):
        """Filter edge list based on search term."""
        term = self.edge_filter.text().strip().lower()
        self.edge_list.clear()
        for el, E in K_EDGES_6_16_KEV:
            label = f"{el:>2s}  {E:>6.3f} keV"
            if not term or term in el.lower() or term in f"{E:.3f}":
                self.edge_list.addItem(label)

    def on_edge_click(self, item):
        """Handle edge selection from list."""
        label = item.text()
        el = label.split()[0]
        E_edge = ELEMENT_TO_EDGE[el]
        self.sel_el_label.setText(f"Element: {el}")
        self.sel_e_label.setText(f"Edge: {E_edge:.3f} keV")

        # Auto-load and plot curve
        try:
            self.load_element_curve(el, mark_edge=E_edge)
        except Exception as ex:
            QMessageBox.critical(self, "Load reference curve", str(ex))
            self.log(f"Error loading curve for {el}: {ex}")

    def build_curve_filepath(self, symbol):
        """Build filepath for element curve based on selected source."""
        # Get the selected curve source (calibrated or simulated)
        source = "calibrated" if self.curve_source_calibrated.isChecked() else "simulated"

        # Choose directory based on source
        if source == "calibrated":
            curve_dir = self.curve_dir_calibrated.text().strip() or DEFAULTS["curve_dir_calibrated"]
        else:  # simulated
            curve_dir = self.curve_dir_simulated.text().strip() or DEFAULTS["curve_dir_simulated"]

        ext = self.curve_ext.currentText() or DEFAULTS["curve_ext"]
        if not ext.startswith("."):
            ext = "." + ext

        # For calibrated files, try with "_calibrated" suffix first
        if source == "calibrated":
            fname_calib = f"{symbol}_calibrated{ext}"
            path_calib = os.path.join(curve_dir, fname_calib)
            if os.path.exists(path_calib):
                return path_calib

        # Standard filename without suffix
        fname = f"{symbol}{ext}"
        path = os.path.join(curve_dir, fname)

        # If file doesn't exist in selected source, try the other one
        if not os.path.exists(path):
            if source == "calibrated":
                other_dir = self.curve_dir_simulated.text().strip() or DEFAULTS["curve_dir_simulated"]
                other_fname = f"{symbol}{ext}"
            else:
                other_dir = self.curve_dir_calibrated.text().strip() or DEFAULTS["curve_dir_calibrated"]
                # Try both naming conventions for calibrated
                other_fname_calib = f"{symbol}_calibrated{ext}"
                other_path_calib = os.path.join(other_dir, other_fname_calib)
                if os.path.exists(other_path_calib):
                    other_source = 'calibrated'
                    self.log(f"Note: {symbol} not found in {source} directory, using {other_source} version")
                    return other_path_calib
                other_fname = f"{symbol}{ext}"

            other_path = os.path.join(other_dir, other_fname)
            if os.path.exists(other_path):
                other_source = 'calibrated' if source == 'simulated' else 'simulated'
                self.log(f"Note: {symbol} not found in {source} directory, using {other_source} version")
                return other_path

        return path

    def load_element_curve(self, symbol, mark_edge=None):
        """Load and plot element curve from file."""
        path = self.build_curve_filepath(symbol)
        if not os.path.exists(path):
            raise FileNotFoundError(f"Curve file not found:\n{path}")
        E, Y = _load_curve_file(path)

        if not self.overlay_checkbox.isChecked():
            self.plot_widget.clear()
            # Re-add legend after clearing
            try:
                self.plot_widget.removeItem(self.plot_legend)
            except:
                pass
            self.plot_legend = self.plot_widget.addLegend()

        # Determine which source was used for the label
        source = "calibrated" if self.curve_source_calibrated.isChecked() else "simulated"

        # Calculate edge position shift for calibrated data
        edge_shift_text = ""
        if source == "calibrated" and mark_edge is not None:
            # Find maximum slope (edge position) - use absolute value to catch steepest descent
            Y_norm = (Y - Y.min()) / (Y.max() - Y.min())
            derivative = np.gradient(Y_norm, E)
            max_deriv_idx = np.argmax(np.abs(derivative))
            measured_edge = E[max_deriv_idx]
            shift_ev = (measured_edge - mark_edge) * 1000
            edge_shift_text = f" [Δ={shift_ev:+.1f}eV]"
            self.log(f"Edge shift for {symbol}: {shift_ev:+.1f} eV (measured: {measured_edge:.4f} keV)")

        label = f"{symbol} ({source}){edge_shift_text}"

        # Plot curve
        pen = pg.mkPen(color='c', width=2)
        self.plot_widget.plot(E, Y, pen=pen, name=label)

        # Plot edge marker
        if mark_edge is not None:
            edge_line = pg.InfiniteLine(pos=mark_edge, angle=90,
                                       pen=pg.mkPen('orange', style=Qt.DashLine, width=2))
            self.plot_widget.addItem(edge_line)

        self.log(f"Loaded {source} curve for {symbol}: {os.path.basename(path)}  (N={E.size})")

    def apply_edge_to_fields(self):
        """Apply selected edge to manual energy fields."""
        item = self.edge_list.currentItem()
        if not item:
            QMessageBox.information(self, "Select", "Select an element from the list first.")
            return
        el = item.text().split()[0]
        E = ELEMENT_TO_EDGE[el]
        try:
            win = float(self.win_entry.text())
            npts = int(float(self.npts_entry.text()))
        except Exception as ex:
            QMessageBox.critical(self, "Invalid window/points", str(ex))
            return
        emin = E - win
        emax = E + win
        # Calculate step size from desired number of points
        step = (emax - emin) * 1000 / (npts - 1)  # convert to eV

        # Enforce 1 eV minimum step
        if step < 1.0:
            step = 1.0
            # Recalculate number of points
            npts = int((emax - emin) * 1000 / step) + 1
            self.log(f"Note: Adjusted to 1 eV minimum step → {npts} points")

        self.e_start.setText(f"{emin:.6f}")
        self.e_end.setText(f"{emax:.6f}")
        self.e_step.setText(f"{step:.3f}")
        self.update_manual_points()
        self.log(f"Applied {el} edge: start={emin:.3f} end={emax:.3f} step={step:.3f} eV ({npts} pts)")

    def load_curve_dialog(self):
        """Open dialog to load curve file."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Select curve file", "",
            "Curve files (*.csv *.npy);;All files (*.*)"
        )
        if not path:
            return
        try:
            E, Y = _load_curve_file(path)
            if not self.overlay_checkbox.isChecked():
                self.plot_widget.clear()
                # Re-add legend after clearing
                try:
                    self.plot_widget.removeItem(self.plot_legend)
                except:
                    pass
                self.plot_legend = self.plot_widget.addLegend()

            pen = pg.mkPen(color='c', width=2)
            self.plot_widget.plot(E, Y, pen=pen, name=os.path.basename(path))
            self.log(f"Loaded curve: {path}  (N={E.size})")
        except Exception as ex:
            QMessageBox.critical(self, "Load curve error", str(ex))

    # ---------- Energy Method Management ----------
    def on_method_change(self):
        """Show/hide appropriate frames based on selected energy method."""
        if self.method_manual.isChecked():
            self.manual_frame.show()
            self.plot_select_frame.hide()
            self.custom_frame.hide()
            self.disable_linear_region()
        elif self.method_plot.isChecked():
            self.manual_frame.hide()
            self.plot_select_frame.show()
            self.custom_frame.hide()
        elif self.method_custom.isChecked():
            self.manual_frame.hide()
            self.plot_select_frame.hide()
            self.custom_frame.show()
            self.disable_linear_region()

    def enable_plot_selection(self):
        """Enable interactive linear region selection on the plot."""
        if self._linear_region is not None:
            self.disable_linear_region()
            return

        # Get current selected element's K-edge, or use default mid-range
        item = self.edge_list.currentItem()
        if item:
            el = item.text().split()[0]
            center_energy = ELEMENT_TO_EDGE[el]
        else:
            center_energy = 8.0  # Default to mid-range of 6-16 keV

        # Create LinearRegionItem centered on K-edge ± 20 eV
        region_min = center_energy - 0.020
        region_max = center_energy + 0.020
        self._linear_region = pg.LinearRegionItem(values=(region_min, region_max), brush=(255, 0, 0, 50))
        self._linear_region.sigRegionChanged.connect(self.on_region_changed)
        self.plot_widget.addItem(self._linear_region)

        self.btn_enable_select.setText("Disable Selection")
        self.log("Linear region selector enabled. Drag on plot to select energy range.")

    def disable_linear_region(self):
        """Disable linear region selector."""
        if self._linear_region is not None:
            self.plot_widget.removeItem(self._linear_region)
            self._linear_region = None
            self.btn_enable_select.setText("Enable Selection")

    def on_region_changed(self):
        """Callback when user changes the linear region selection."""
        if self._linear_region is None:
            return

        xmin, xmax = self._linear_region.getRegion()
        if xmin == xmax:
            return

        self._selected_range = (min(xmin, xmax), max(xmin, xmax))
        self.update_plot_selection_points()

    def update_plot_selection_points(self):
        """Update the plot selection range label based on step size."""
        if self._selected_range is None:
            return

        xmin, xmax = self._selected_range
        try:
            step_ev = int(float(self.plot_step.text()))
            if step_ev <= 0:
                self.plot_range_label.setText("Step must be > 0")
                return
        except ValueError:
            self.plot_range_label.setText("Invalid step value")
            return

        # Calculate number of points to include both extremes
        range_ev = abs(xmax - xmin) * 1000  # Convert keV to eV
        npts = int(range_ev / step_ev) + 1

        self.plot_range_label.setText(f"Range: {xmin:.4f} - {xmax:.4f} keV ({npts} pts @ {step_ev}eV)")
        self.log(f"Selected energy range: {xmin:.4f} - {xmax:.4f} keV → {npts} points ({step_ev} eV step)")

    def load_custom_energies(self):
        """Load custom energy values from a file."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Select energy file (one value per line)", "",
            "Text files (*.txt *.csv *.dat);;All files (*.*)"
        )
        if not path:
            return

        try:
            # Try to load as simple list of energies
            energies = np.loadtxt(path)
            if energies.ndim == 2 and energies.shape[1] >= 1:
                energies = energies[:, 0]  # Take first column if multiple
            energies = np.asarray(energies, dtype=float).flatten()

            if len(energies) == 0:
                raise ValueError("No energy values found in file")

            self._custom_energies = energies
            self.custom_info_label.setText(
                f"Loaded {len(energies)} points: {energies[0]:.4f} - {energies[-1]:.4f} keV"
            )
            self.log(f"Loaded {len(energies)} custom energy points from {os.path.basename(path)}")
        except Exception as ex:
            QMessageBox.critical(self, "Load error", f"Failed to load energy file:\n{ex}")
            self.log(f"Error loading custom energies: {ex}")

    def edit_energy_table(self):
        """Open a dialog to manually edit energy values."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Edit Energy Table")
        dialog.resize(400, 500)

        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("Enter energy values (one per line, in keV):"))

        text_edit = QTextEdit()

        # Pre-fill with existing values if any
        if self._custom_energies is not None:
            for e in self._custom_energies:
                text_edit.append(f"{e:.6f}")

        layout.addWidget(text_edit)

        # Buttons
        btn_layout = QHBoxLayout()
        save_btn = QPushButton("Save")
        cancel_btn = QPushButton("Cancel")

        def save_and_close():
            try:
                content = text_edit.toPlainText().strip()
                if not content:
                    QMessageBox.warning(dialog, "Empty", "No energy values entered")
                    return

                lines = content.split('\n')
                energies = []
                for i, line in enumerate(lines, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        energies.append(float(line))
                    except ValueError:
                        raise ValueError(f"Line {i}: '{line}' is not a valid number")

                if len(energies) == 0:
                    raise ValueError("No valid energy values found")

                self._custom_energies = np.array(energies, dtype=float)
                self.custom_info_label.setText(
                    f"{len(energies)} points: {energies[0]:.4f} - {energies[-1]:.4f} keV"
                )
                self.log(f"Set {len(energies)} custom energy points")
                dialog.accept()

            except Exception as ex:
                QMessageBox.critical(dialog, "Parse error", str(ex))

        save_btn.clicked.connect(save_and_close)
        cancel_btn.clicked.connect(dialog.reject)

        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

        dialog.exec_()

    def get_energy_array(self):
        """Get energy array based on selected method. Returns np.array or raises exception."""
        if self.method_manual.isChecked():
            # Manual method: start, end, step (in eV)
            try:
                emin = float(self.e_start.text())
                emax = float(self.e_end.text())
                step = float(self.e_step.text())
                if step <= 0:
                    raise ValueError("Step must be > 0")
                npts = int((emax*1000 - emin*1000)/step) + 1
                if npts <= 1:
                    raise ValueError("Number of points must be > 1")
                return np.linspace(emin, emax, npts)
            except Exception as ex:
                raise ValueError(f"Manual method error: {ex}")

        elif self.method_plot.isChecked():
            # Plot selection method
            if self._selected_range is None:
                raise ValueError("No energy range selected on plot. Enable selection and drag on plot.")
            try:
                step_ev = int(float(self.plot_step.text()))
                if step_ev <= 0:
                    raise ValueError("Step must be > 0")
                emin, emax = self._selected_range
                # Use arange to ensure exact step size, then ensure endpoint is included
                step_kev = step_ev / 1000.0  # Convert eV to keV
                energies = np.arange(emin, emax + step_kev/2, step_kev)
                if len(energies) <= 1:
                    raise ValueError("Number of points must be > 1")
                return energies
            except ValueError as ex:
                raise ValueError(f"Plot selection method error: {ex}")

        elif self.method_custom.isChecked():
            # Custom energy array
            if self._custom_energies is None:
                raise ValueError("No custom energies loaded. Load from file or edit table.")
            return self._custom_energies.copy()

        else:
            raise ValueError("Unknown energy method")

    # ---------- Calibrate ----------
    def on_calibrate(self):
        """Start calibration scan."""
        try:
            energies = self.get_energy_array()
        except Exception as ex:
            QMessageBox.critical(self, "Invalid input", str(ex))
            return

        npts = len(energies)
        self.btn_calibrate.setEnabled(False)
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.progress.setMaximum(npts)
        self.progress.setValue(0)

        # Reset calibration plot item for new scan
        self._calib_plot_item = None

        # Get PV settings
        det_pv = self.detector_pv.text()
        acq_pv = self.cam_acquire_pv.text()
        acq_rbv_pv = self.cam_acquire_rbv_pv.text()
        e_pv = self.energy_pv.text()
        e_set_pv = self.energy_set_pv.text()
        e_rb_pv = self.energy_rb_pv.text().strip()
        try:
            settle = float(self.settle_time.text())
        except Exception:
            settle = DEFAULTS["settle_s"]

        # Create and start worker
        self._calib_worker = CalibrationWorker(energies, det_pv, acq_pv, acq_rbv_pv,
                                               e_pv, e_set_pv, e_rb_pv, settle)
        self._calib_worker.progress.connect(self.on_calib_progress)
        self._calib_worker.log.connect(self.log)
        self._calib_worker.plot_update.connect(self.on_calib_plot_update)
        self._calib_worker.completed.connect(self.on_calib_finished)
        self._calib_worker.error.connect(self.on_calib_error)
        self._calib_worker.start()

    @pyqtSlot(int)
    def on_calib_progress(self, value):
        """Update progress bar."""
        self.progress.setValue(value)

    @pyqtSlot(object, object)
    def on_calib_plot_update(self, energies, sums):
        """Update calibration plot."""
        if not self.overlay_checkbox.isChecked():
            # Clear and reset plot for calibration
            if self._calib_plot_item is None:
                self.plot_widget.clear()
                # Re-add legend after clearing
                try:
                    self.plot_widget.removeItem(self.plot_legend)
                except:
                    pass
                self.plot_legend = self.plot_widget.addLegend()
                self.plot_widget.setLabel('bottom', 'Energy (keV)', color='white', size='12pt')
                self.plot_widget.setLabel('left', 'Sum of pixels', color='white', size='12pt')

        # Update or create calibration plot item
        if self._calib_plot_item is None:
            pen = pg.mkPen(color='g', width=2)
            self._calib_plot_item = self.plot_widget.plot(energies, sums, pen=pen,
                                                          symbol='o', symbolSize=4,
                                                          symbolBrush='g', name="Calibration")
        else:
            # Update existing plot data
            self._calib_plot_item.setData(energies, sums)

    @pyqtSlot(object, object)
    def on_calib_finished(self, energies, sums):
        """Handle calibration completion."""
        self._last_calib = (energies, sums)
        self.btn_calibrate.setEnabled(True)
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.progress.setValue(0)

    @pyqtSlot(str)
    def on_calib_error(self, error):
        """Handle calibration error."""
        self.log(error)
        QMessageBox.critical(self, "Calibration error", error)
        self.btn_calibrate.setEnabled(True)
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.progress.setValue(0)

    # ---------- Start / Stop ----------
    def on_start(self):
        """Launch the start script via SSH in embedded terminal."""
        # Get energy array and validate
        try:
            energies = self.get_energy_array()
        except Exception as ex:
            QMessageBox.critical(self, "Invalid energy configuration", str(ex))
            return

        # Prime the PVs
        try:
            if self.method_manual.isChecked():
                # For manual mode, set the PVs directly
                epics_put(DEFAULTS["xanes_start_pv"],  float(self.e_start.text()))
                epics_put(DEFAULTS["xanes_end_pv"],    float(self.e_end.text()))
                epics_put(DEFAULTS["xanes_step_pv"],   float(self.e_step.text()))
                self.log(f"Manual mode: {len(energies)} points from {energies[0]:.4f} to {energies[-1]:.4f} keV")
            else:
                # For plot_select and custom methods, save energies to file
                outfile = DEFAULTS["custom_energies_file"]
                np.save(outfile, energies)
                self.log(f"Saved {len(energies)} custom energies to {outfile}")

                # Still set the PVs for the range (for display/logging purposes)
                epics_put(DEFAULTS["xanes_start_pv"],  float(energies[0]))
                epics_put(DEFAULTS["xanes_end_pv"],    float(energies[-1]))
                # Calculate equivalent step size for info
                if len(energies) > 1:
                    avg_step = (energies[-1] - energies[0]) * 1000 / (len(energies) - 1)
                    epics_put(DEFAULTS["xanes_step_pv"], avg_step)

                method = "plot_select" if self.method_plot.isChecked() else "custom"
                self.log(f"Using {method} method: {len(energies)} points from {energies[0]:.4f} to {energies[-1]:.4f} keV")
        except Exception as ex:
            self.log(f"WARNING: could not prime XANES PVs: {ex}")

        self.btn_start.setEnabled(False)
        self.btn_calibrate.setEnabled(True)
        self.btn_stop.setEnabled(True)
        self.progress.setValue(0)
        self.progress.setMaximum(100)

        # Build remote configuration
        remote_config = {
            "remote_user": self.remote_user.text(),
            "remote_host": self.remote_host.text(),
            "conda_env": self.conda_env.text(),
            "work_dir": self.work_dir.text(),
            "conda_path": self.conda_path.text(),
            "script_name": self.script_name.text(),
        }

        self.log("=" * 60)
        self.log("Starting XANES scan via SSH...")
        self.log("=" * 60)

        # Create and start worker with remote configuration
        self._start_worker = StartScriptWorker(remote_config)
        self._start_worker.log.connect(self.log)
        self._start_worker.finished.connect(self.on_start_finished)
        self._start_worker.error.connect(self.on_start_error)
        self._start_worker.start()

    def on_start_finished(self, exit_code):
        """Handle start script completion."""
        self.reset_buttons()

    def on_start_error(self, error):
        """Handle start script error."""
        self.log(error)
        QMessageBox.critical(self, "Start error", error)
        self.reset_buttons()

    def on_stop(self):
        """Stop running operations."""
        # Stop calibration worker
        if self._calib_worker and self._calib_worker.isRunning():
            self._calib_worker.stop()
            self._calib_worker.wait()

        # Stop start script worker
        if self._start_worker and self._start_worker.isRunning():
            self._start_worker.stop()
            self._start_worker.wait()

        # Optional safety PVs
        try:
            epics_put(DEFAULTS["epid_h_on_pv"], "off")
            epics_put(DEFAULTS["epid_v_on_pv"], "off")
            epics_put(DEFAULTS["shaker_run_pv"], "Stop")
            self.log("Feedback/shaker: OFF/STOP sent.")
        except Exception as ex:
            self.log(f"NOTE: safety PVs not touched or unavailable: {ex}")

        self.reset_buttons()

    def reset_buttons(self):
        """Reset button states."""
        self.btn_stop.setEnabled(False)
        self.btn_start.setEnabled(True)
        self.btn_calibrate.setEnabled(True)
        self.progress.setValue(0)

    # ---------- PV Tab Helpers ----------
    def browse_curve_dir(self, widget, label):
        """Browse for curve directory."""
        d = QFileDialog.getExistingDirectory(
            self, f"Select {label} curves folder",
            widget.text() or os.getcwd()
        )
        if d:
            widget.setText(d)

    # ---------- Settings ----------
    def save_settings(self, show_popup=True):
        """Save current settings to JSON file."""
        settings = {
            "detector_pv": self.detector_pv.text(),
            "cam_acquire_pv": self.cam_acquire_pv.text(),
            "cam_acquire_rbv_pv": self.cam_acquire_rbv_pv.text(),
            "energy_pv": self.energy_pv.text(),
            "energy_set_pv": self.energy_set_pv.text(),
            "energy_rb_pv": self.energy_rb_pv.text(),
            "settle_time": self.settle_time.text(),
            "curve_dir_calibrated": self.curve_dir_calibrated.text(),
            "curve_dir_simulated": self.curve_dir_simulated.text(),
            "curve_ext": self.curve_ext.currentText(),
            "remote_user": self.remote_user.text(),
            "remote_host": self.remote_host.text(),
            "conda_env": self.conda_env.text(),
            "work_dir": self.work_dir.text(),
            "conda_path": self.conda_path.text(),
            "script_name": self.script_name.text(),
        }
        try:
            with open(self.settings_file, 'w') as f:
                json.dump(settings, f, indent=2)
            self.log(f"Settings saved to {self.settings_file}")
            if show_popup:
                QMessageBox.information(self, "Settings Saved", f"Settings saved to:\n{self.settings_file}")
        except Exception as ex:
            self.log(f"Error saving settings: {ex}")
            if show_popup:
                QMessageBox.critical(self, "Save Error", f"Failed to save settings:\n{ex}")

    def load_settings(self):
        """Load settings from JSON file."""
        if not os.path.exists(self.settings_file):
            self.log(f"No saved settings found, using defaults")
            return

        try:
            with open(self.settings_file, 'r') as f:
                settings = json.load(f)

            self.detector_pv.setText(settings.get("detector_pv", DEFAULTS["detector_pv"]))
            self.cam_acquire_pv.setText(settings.get("cam_acquire_pv", DEFAULTS["cam_acquire_pv"]))
            self.cam_acquire_rbv_pv.setText(settings.get("cam_acquire_rbv_pv", DEFAULTS["cam_acquire_rbv_pv"]))
            self.energy_pv.setText(settings.get("energy_pv", DEFAULTS["energy_pv"]))
            self.energy_set_pv.setText(settings.get("energy_set_pv", DEFAULTS["energy_set_pv"]))
            self.energy_rb_pv.setText(settings.get("energy_rb_pv", DEFAULTS["energy_rb_pv"]))
            self.settle_time.setText(settings.get("settle_time", str(DEFAULTS["settle_s"])))
            self.curve_dir_calibrated.setText(settings.get("curve_dir_calibrated", DEFAULTS["curve_dir_calibrated"]))
            self.curve_dir_simulated.setText(settings.get("curve_dir_simulated", DEFAULTS["curve_dir_simulated"]))
            self.curve_ext.setCurrentText(settings.get("curve_ext", DEFAULTS["curve_ext"]))
            self.remote_user.setText(settings.get("remote_user", DEFAULTS["remote_user"]))
            self.remote_host.setText(settings.get("remote_host", DEFAULTS["remote_host"]))
            self.conda_env.setText(settings.get("conda_env", DEFAULTS["conda_env"]))
            self.work_dir.setText(settings.get("work_dir", DEFAULTS["work_dir"]))
            self.conda_path.setText(settings.get("conda_path", DEFAULTS["conda_path"]))
            self.script_name.setText(settings.get("script_name", DEFAULTS["script_name"]))

            self.log(f"Settings loaded from {self.settings_file}")
        except Exception as ex:
            self.log(f"Error loading settings: {ex}")
            QMessageBox.warning(self, "Load Error", f"Failed to load settings:\n{ex}\n\nUsing defaults.")

    # ---------- Cleanup ----------
    def closeEvent(self, event):
        """Handle window close event."""
        # Auto-save settings on close (no popup)
        try:
            self.save_settings(show_popup=False)
        except Exception:
            pass  # Don't block closing if save fails

        # Stop any running workers
        if self._calib_worker and self._calib_worker.isRunning():
            self._calib_worker.stop()
            self._calib_worker.wait()
        if self._start_worker and self._start_worker.isRunning():
            self._start_worker.stop()
            self._start_worker.wait()
        event.accept()

# -------------------------
# Main
# -------------------------
def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')  # Use Fusion style for consistent dark theme
    window = XANESGui()
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
