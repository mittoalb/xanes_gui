#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import threading
import queue
import time
import os
import signal
import subprocess
import numpy as np
import pvaccess as pva
import epics

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from matplotlib.widgets import SpanSelector

# -------------------------
# Defaults / Config
# -------------------------
DEFAULTS = {
    # PVA / EPICS for Calibrate
    "detector_pv": "32idbSP1:Pva1:Image",
    "cam_acquire_pv": "32idbSP1:cam1:Acquire",
    "cam_acquire_rbv_pv": "32idbSP1:cam1:Acquire_RBV",
    "energy_set_pv": "32id:TXMOptics:EnergySet",
    "energy_rb_pv": "32id:TXMOptics:Energy_RBV",
    "settle_s": 0.15,
    # Start launcher (.sh)
    "start_script": "/path/to/xanes_start.sh",   # <-- set your script path or edit in PV Settings tab
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
    "curve_dir_calibrated": os.path.join(os.path.dirname(__file__), "Calibrated"),
    "curve_dir_simulated": os.path.join(os.path.dirname(__file__), "Curves"),
    "curve_ext": ".npy",  # ".npy" or ".csv"
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
    dims = st.get('dimension', [])
    if len(dims) >= 2:
        h = int(dims[0]['size']); w = int(dims[1]['size'])
        if h*w != flat.size:
            raise RuntimeError("Size mismatch (dims vs data length)")
        return flat.reshape(h, w)
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
# GUI
# -------------------------
class XANESGui(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("XANES Control")
        self.geometry("1500x1200")  # a bit wider to fit the side panel
        self._log_q = queue.Queue()
        self._proc = None
        self._proc_pgid = None
        self._stop_requested = False
        self._last_calib = None  # (energies, sums)
        self._span_selector = None
        self._selected_range = None
        self._custom_energies = None

        # Notebook
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill=tk.BOTH, expand=True)
        self.tab_scan = ttk.Frame(self.nb)
        self.tab_pv   = ttk.Frame(self.nb)
        self.nb.add(self.tab_scan, text="Scan")
        self.nb.add(self.tab_pv,   text="PV Settings")

        self._build_scan_tab()
        self._build_pv_tab()

        # Prefill fields
        threading.Thread(target=self._prefill_scan_fields, daemon=True).start()

        # Log pump
        self.after(100, self._pump_log)

        # Clean close (do NOT touch safety PVs here)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------- Scan tab ----------
    def _build_scan_tab(self):
        # Top split: plot (left) + side panel (right)
        top = tk.Frame(self.tab_scan)
        top.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        # LEFT: plot
        plot_frame = tk.Frame(top, padx=8, pady=8)
        plot_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.fig = Figure(figsize=(5, 3.5), dpi=100, facecolor='#2b2b2b')
        self.ax = self.fig.add_subplot(111, facecolor='#1e1e1e')

        # Create canvas BEFORE any draw
        self.canvas = FigureCanvasTkAgg(self.fig, master=plot_frame)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        # Now safe to set/reset axes and draw
        self._reset_plot_axes()

        # RIGHT: side panel with edges & utilities
        side = tk.Frame(top, padx=10, pady=8)
        side.pack(side=tk.RIGHT, fill=tk.Y)

        ttk.Label(side, text="Edges (6–16 keV)").pack(anchor="w", pady=(0,6))

        # Curve source selection
        curve_source_frame = tk.LabelFrame(side, text="Reference Curves", padx=5, pady=5)
        curve_source_frame.pack(fill=tk.X, pady=(0,6))
        self.curve_source = tk.StringVar(value="calibrated")
        ttk.Radiobutton(curve_source_frame, text="Calibrated (measured)",
                       variable=self.curve_source, value="calibrated").pack(anchor="w")
        ttk.Radiobutton(curve_source_frame, text="Simulated",
                       variable=self.curve_source, value="simulated").pack(anchor="w")

        # Search/filter
        search_frame = tk.Frame(side)
        search_frame.pack(fill=tk.X, pady=(0,6))
        tk.Label(search_frame, text="Filter: ").pack(side=tk.LEFT)
        self.edge_filter = ttk.Entry(search_frame, width=12)
        self.edge_filter.pack(side=tk.LEFT, padx=(2,0), fill=tk.X, expand=True)
        self.edge_filter.bind("<KeyRelease>", self._filter_edges)

        # Listbox
        self.edge_list = tk.Listbox(side, height=18, exportselection=False)
        self._all_edge_labels = [f"{el:>2s}  {E:>6.3f} keV" for el, E in K_EDGES_6_16_KEV]
        for s in self._all_edge_labels:
            self.edge_list.insert(tk.END, s)
        self.edge_list.pack(fill=tk.Y, expand=False)
        self.edge_list.bind("<<ListboxSelect>>", self._on_edge_click)

        # Selected info + controls
        ttk.Separator(side, orient="horizontal").pack(fill=tk.X, pady=8)
        self.sel_el_var = tk.StringVar(value="Element: —")
        self.sel_e_var  = tk.StringVar(value="Edge: — keV")
        ttk.Label(side, textvariable=self.sel_el_var).pack(anchor="w")
        ttk.Label(side, textvariable=self.sel_e_var).pack(anchor="w")

        cfg = tk.LabelFrame(side, text="Auto-fill scan around edge")
        cfg.pack(fill=tk.X, pady=(8,6))
        tk.Label(cfg, text="± window (keV):").grid(row=0, column=0, sticky="e", padx=4, pady=2)
        tk.Label(cfg, text="# points:").grid(row=1, column=0, sticky="e", padx=4, pady=2)
        self.win_var  = tk.StringVar(value="0.20")
        self.npts_var = tk.StringVar(value="121")
        ttk.Entry(cfg, textvariable=self.win_var, width=8).grid(row=0, column=1, sticky="w", padx=4, pady=2)
        ttk.Entry(cfg, textvariable=self.npts_var, width=8).grid(row=1, column=1, sticky="w", padx=4, pady=2)
        ttk.Button(side, text="Apply to fields", command=self._apply_edge_to_fields).pack(fill=tk.X, pady=(6,3))

        # Overlay toggle (controls whether loaded curves/calibration replace or overlay)
        self.overlay_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(side, text="Overlay on existing plot", variable=self.overlay_var).pack(anchor="w", pady=(6,3))

        # Manual load (optional extra)
        ttk.Button(side, text="Load curve (CSV/NPY)", command=self._load_curve_dialog).pack(fill=tk.X, pady=(3,3))

        # Energy method selection
        method_frame = tk.LabelFrame(self.tab_scan, text="Energy Range Method", padx=8, pady=8)
        method_frame.pack(side=tk.TOP, fill=tk.X, padx=8, pady=(8,4))

        self.energy_method = tk.StringVar(value="manual")

        method_row1 = tk.Frame(method_frame)
        method_row1.pack(fill=tk.X, pady=2)
        ttk.Radiobutton(method_row1, text="Manual (Start/End/Step)",
                       variable=self.energy_method, value="manual",
                       command=self._on_method_change).pack(side=tk.LEFT, padx=5)

        ttk.Radiobutton(method_row1, text="Select range on plot",
                       variable=self.energy_method, value="plot_select",
                       command=self._on_method_change).pack(side=tk.LEFT, padx=5)

        ttk.Radiobutton(method_row1, text="Import custom energy array",
                       variable=self.energy_method, value="custom",
                       command=self._on_method_change).pack(side=tk.LEFT, padx=5)

        # Fields row - Manual method
        self.manual_frame = tk.Frame(self.tab_scan, padx=8, pady=4)
        self.manual_frame.pack(side=tk.TOP, fill=tk.X)
        tk.Label(self.manual_frame, text="Start energy (keV):").pack(side=tk.LEFT)
        self.e_start = ttk.Entry(self.manual_frame, width=10); self.e_start.pack(side=tk.LEFT, padx=(4,12))
        tk.Label(self.manual_frame, text="End energy (keV):").pack(side=tk.LEFT)
        self.e_end = ttk.Entry(self.manual_frame, width=10); self.e_end.pack(side=tk.LEFT, padx=(4,12))
        tk.Label(self.manual_frame, text="Step (eV):").pack(side=tk.LEFT)
        self.e_step = ttk.Entry(self.manual_frame, width=8); self.e_step.pack(side=tk.LEFT, padx=(4,12))
        self.manual_info = tk.Label(self.manual_frame, text="", fg="blue")
        self.manual_info.pack(side=tk.LEFT, padx=5)

        # Bind to update points calculation
        self.e_start.bind("<KeyRelease>", self._update_manual_points)
        self.e_end.bind("<KeyRelease>", self._update_manual_points)
        self.e_step.bind("<KeyRelease>", self._update_manual_points)

        # Plot selection frame
        self.plot_select_frame = tk.Frame(self.tab_scan, padx=8, pady=4)
        tk.Label(self.plot_select_frame, text="Click 'Enable Selection' then drag on the plot to select energy range").pack(side=tk.LEFT, padx=5)
        self.btn_enable_select = ttk.Button(self.plot_select_frame, text="Enable Selection",
                                           command=self._enable_plot_selection)
        self.btn_enable_select.pack(side=tk.LEFT, padx=5)
        tk.Label(self.plot_select_frame, text="# Points:").pack(side=tk.LEFT, padx=(15,2))
        self.plot_npts = ttk.Entry(self.plot_select_frame, width=8)
        self.plot_npts.insert(0, "121")
        self.plot_npts.pack(side=tk.LEFT, padx=(4,5))
        self.plot_range_label = tk.Label(self.plot_select_frame, text="Range: Not selected", fg="blue")
        self.plot_range_label.pack(side=tk.LEFT, padx=5)

        # Custom energy frame
        self.custom_frame = tk.Frame(self.tab_scan, padx=8, pady=4)
        tk.Label(self.custom_frame, text="Energy table (one value per row):").pack(side=tk.LEFT, padx=5)
        ttk.Button(self.custom_frame, text="Load from CSV/TXT",
                  command=self._load_custom_energies).pack(side=tk.LEFT, padx=5)
        ttk.Button(self.custom_frame, text="Edit Table",
                  command=self._edit_energy_table).pack(side=tk.LEFT, padx=5)
        self.custom_info_label = tk.Label(self.custom_frame, text="No custom energies loaded", fg="blue")
        self.custom_info_label.pack(side=tk.LEFT, padx=5)

        # Progress
        self.progress = ttk.Progressbar(self.tab_scan, mode='determinate')
        self.progress.pack(side=tk.TOP, fill=tk.X, padx=10, pady=(0,8))

        # Bottom buttons bar
        btnbar = tk.Frame(self.tab_scan, padx=8, pady=10)
        btnbar.pack(side=tk.BOTTOM, fill=tk.X)
        btn_w = 18
        self.btn_cal = tk.Button(btnbar, text="Calibrate", bg="#FFA500", fg="black",
                                 width=btn_w, height=2, command=self.on_calibrate)
        self.btn_start = tk.Button(btnbar, text="Start XANES", bg="#32CD32", fg="black",
                                   width=btn_w, height=2, command=self.on_start)
        self.btn_stop = tk.Button(btnbar, text="Stop", bg="#FF3B30", fg="white",
                                  width=btn_w, height=2, state=tk.DISABLED, command=self.on_stop)
        self.btn_cal.pack(side=tk.LEFT, padx=6)
        self.btn_start.pack(side=tk.LEFT, padx=6)
        self.btn_stop.pack(side=tk.LEFT, padx=6)

        # Log
        log_frame = tk.Frame(self.tab_scan, padx=8, pady=4)
        log_frame.pack(side=tk.TOP, fill=tk.BOTH)
        tk.Label(log_frame, text="Log:").pack(anchor="w")
        self.txt = tk.Text(log_frame, height=8)
        self.txt.pack(fill=tk.BOTH, expand=True)

    # ---------- PV Settings tab ----------
    def _build_pv_tab(self):
        pvf = tk.LabelFrame(self.tab_pv, text="EPICS / PVA Configuration", padx=10, pady=10)
        pvf.pack(side=tk.TOP, fill=tk.X, padx=10, pady=10)

        self.detector_var = tk.StringVar(value=DEFAULTS["detector_pv"])
        self.cam_acq_var = tk.StringVar(value=DEFAULTS["cam_acquire_pv"])
        self.cam_acq_rbv_var = tk.StringVar(value=DEFAULTS["cam_acquire_rbv_pv"])
        self.energy_set_var = tk.StringVar(value=DEFAULTS["energy_set_pv"])
        self.energy_rb_var = tk.StringVar(value=DEFAULTS["energy_rb_pv"])
        self.settle_var = tk.StringVar(value=str(DEFAULTS["settle_s"]))
        self.start_script_var = tk.StringVar(value=DEFAULTS["start_script"])

        # Reference curves config
        self.curve_dir_calibrated_var = tk.StringVar(value=DEFAULTS["curve_dir_calibrated"])
        self.curve_dir_simulated_var = tk.StringVar(value=DEFAULTS["curve_dir_simulated"])
        self.curve_ext_var = tk.StringVar(value=DEFAULTS["curve_ext"])

        rows = [
            ("Detector PVA (NTNDArray):", self.detector_var, 50, None),
            ("cam:Acquire PV:",           self.cam_acq_var, 30, None),
            ("cam:Acquire_RBV PV:",       self.cam_acq_rbv_var, 30, None),
            ("Energy set PV:",            self.energy_set_var, 30, None),
            ("Energy RB PV (opt):",       self.energy_rb_var, 30, None),
            ("Settle (s):",               self.settle_var, 10, None),
            ("Start .sh path:",           self.start_script_var, 60, None),
            ("Calibrated curves folder:", self.curve_dir_calibrated_var, 60, "browse_dir_calib"),
            ("Simulated curves folder:",  self.curve_dir_simulated_var, 60, "browse_dir_sim"),
            ("Ref curve extension:",      self.curve_ext_var, 10, "ext_combo"),
        ]
        for r, (lab, var, width, kind) in enumerate(rows):
            ttk.Label(pvf, text=lab).grid(row=r, column=0, sticky="e", padx=4, pady=3)
            if kind == "browse_dir_calib":
                rowf = tk.Frame(pvf)
                rowf.grid(row=r, column=1, sticky="we", padx=4, pady=3)
                e = ttk.Entry(rowf, textvariable=var, width=width)
                e.pack(side=tk.LEFT, fill=tk.X, expand=True)
                ttk.Button(rowf, text="Browse…", command=lambda: self._browse_curve_dir(self.curve_dir_calibrated_var, "calibrated")).pack(side=tk.LEFT, padx=(6,0))
            elif kind == "browse_dir_sim":
                rowf = tk.Frame(pvf)
                rowf.grid(row=r, column=1, sticky="we", padx=4, pady=3)
                e = ttk.Entry(rowf, textvariable=var, width=width)
                e.pack(side=tk.LEFT, fill=tk.X, expand=True)
                ttk.Button(rowf, text="Browse…", command=lambda: self._browse_curve_dir(self.curve_dir_simulated_var, "simulated")).pack(side=tk.LEFT, padx=(6,0))
            elif kind == "ext_combo":
                cb = ttk.Combobox(pvf, textvariable=var, values=[".npy", ".csv"], width=8, state="readonly")
                cb.grid(row=r, column=1, sticky="w", padx=4, pady=3)
            else:
                ttk.Entry(pvf, textvariable=var, width=width).grid(row=r, column=1, sticky="w", padx=4, pady=3)

        pvf.columnconfigure(1, weight=1)

    # ---------- PV tab helpers ----------
    def _browse_curve_dir(self, var, label):
        d = filedialog.askdirectory(initialdir=var.get() or os.getcwd(), title=f"Select {label} curves folder")
        if d:
            var.set(d)

    # ---------- Logging / prefill ----------
    def _log(self, msg):
        ts = time.strftime("%H:%M:%S")
        self._log_q.put(f"[{ts}] {msg}\n")

    def _pump_log(self):
        try:
            while True:
                self.txt.insert("end", self._log_q.get_nowait())
                self.txt.see("end")
        except queue.Empty:
            pass
        self.after(100, self._pump_log)

    def _prefill_scan_fields(self):
        try:
            s = epics_get(DEFAULTS["xanes_start_pv"])
            e = epics_get(DEFAULTS["xanes_end_pv"])
            step = epics_get(DEFAULTS["xanes_step_pv"])
            self.after(0, lambda: self._fill_fields(s, e, step))
            self._log(f"Prefilled from EPICS: start={s} end={e} step={step} eV")
        except Exception as ex:
            self._log(f"Prefill failed: {ex}")

    def _fill_fields(self, s, e, step):
        self.e_start.delete(0, "end"); self.e_start.insert(0, str(s))
        self.e_end.delete(0, "end");   self.e_end.insert(0, str(e))
        try:
            step = float(step)
        except Exception:
            step = 1.0
        self.e_step.delete(0, "end");  self.e_step.insert(0, str(step))
        self._update_manual_points()

    def _update_manual_points(self, event=None):
        """Calculate and display number of points based on start, end, step."""
        try:
            emin = float(self.e_start.get())
            emax = float(self.e_end.get())
            step = float(self.e_step.get())
            if step <= 0:
                self.manual_info.config(text="Step must be > 0")
                return
            if step < 1.0:
                self.manual_info.config(text="⚠ Step < 1 eV (min recommended)")
                return
            npts = int((emax*1000 - emin*1000)/step) + 1
            self.manual_info.config(text=f"→ {npts} points")
        except ValueError:
            self.manual_info.config(text="")

    def _reset_plot_axes(self):
        self.ax.clear()
        self.ax.set_title("Calibration / Reference", color='white')
        self.ax.set_xlabel("Energy (keV)", color='white')
        self.ax.set_ylabel("Signal (a.u.)", color='white')
        self.ax.tick_params(colors='white', which='both')
        self.ax.grid(True, alpha=0.3, color='gray')
        self.ax.spines['bottom'].set_color('white')
        self.ax.spines['top'].set_color('white')
        self.ax.spines['left'].set_color('white')
        self.ax.spines['right'].set_color('white')
        self.fig.canvas.draw_idle()  # safe: figure's canvas exists

    # ---------- Side panel actions ----------
    def _filter_edges(self, event=None):
        term = self.edge_filter.get().strip().lower()
        self.edge_list.delete(0, tk.END)
        for el, E in K_EDGES_6_16_KEV:
            label = f"{el:>2s}  {E:>6.3f} keV"
            if not term or term in el.lower() or term in f"{E:.3f}":
                self.edge_list.insert(tk.END, label)

    def _on_edge_click(self, event=None):
        sel = self.edge_list.curselection()
        if not sel:
            return
        label = self.edge_list.get(sel[0])  # e.g. "Fe   7.112 keV"
        el = label.split()[0]
        E_edge = ELEMENT_TO_EDGE[el]
        self.sel_el_var.set(f"Element: {el}")
        self.sel_e_var.set(f"Edge: {E_edge:.3f} keV")

        # Auto-load and plot curve from file: <curve_dir>/<Element><ext>
        try:
            self._load_element_curve(el, mark_edge=E_edge)
        except Exception as ex:
            messagebox.showerror("Load reference curve", str(ex))
            self._log(f"Error loading curve for {el}: {ex}")

    def _build_curve_filepath(self, symbol):
        # Get the selected curve source (calibrated or simulated)
        source = self.curve_source.get()

        # Choose directory based on source (use PV settings or defaults)
        if source == "calibrated":
            curve_dir = (self.curve_dir_calibrated_var.get() or "").strip() or DEFAULTS["curve_dir_calibrated"]
        else:  # simulated
            curve_dir = (self.curve_dir_simulated_var.get() or "").strip() or DEFAULTS["curve_dir_simulated"]

        ext = (self.curve_ext_var.get() or "").strip() or DEFAULTS["curve_ext"]
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
                other_dir = (self.curve_dir_simulated_var.get() or "").strip() or DEFAULTS["curve_dir_simulated"]
                # Simulated files use standard naming
                other_fname = f"{symbol}{ext}"
            else:
                other_dir = (self.curve_dir_calibrated_var.get() or "").strip() or DEFAULTS["curve_dir_calibrated"]
                # Try both naming conventions for calibrated
                other_fname_calib = f"{symbol}_calibrated{ext}"
                other_path_calib = os.path.join(other_dir, other_fname_calib)
                if os.path.exists(other_path_calib):
                    other_source = 'calibrated'
                    self._log(f"Note: {symbol} not found in {source} directory, using {other_source} version")
                    return other_path_calib
                other_fname = f"{symbol}{ext}"

            other_path = os.path.join(other_dir, other_fname)
            if os.path.exists(other_path):
                other_source = 'calibrated' if source == 'simulated' else 'simulated'
                self._log(f"Note: {symbol} not found in {source} directory, using {other_source} version")
                return other_path

        return path

    def _load_element_curve(self, symbol, mark_edge=None):
        path = self._build_curve_filepath(symbol)
        if not os.path.exists(path):
            raise FileNotFoundError(f"Curve file not found:\n{path}")
        E, Y = _load_curve_file(path)

        if not self.overlay_var.get():
            self._reset_plot_axes()

        # Determine which source was used for the label
        source = self.curve_source.get()

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
            self._log(f"Edge shift for {symbol}: {shift_ev:+.1f} eV (measured: {measured_edge:.4f} keV)")

        label = f"{symbol} ({source}){edge_shift_text}"

        self.ax.plot(E, Y, "-", alpha=0.9, label=label, color='cyan', linewidth=1.5)
        if mark_edge is not None:
            self.ax.axvline(mark_edge, linestyle="--", alpha=0.6, color='orange', label=f"{symbol} edge (theoretical)")
        legend = self.ax.legend(loc="best", facecolor='#2b2b2b', edgecolor='white')
        for text in legend.get_texts():
            text.set_color('white')
        self.fig.canvas.draw_idle()
        self._log(f"Loaded {source} curve for {symbol}: {os.path.basename(path)}  (N={E.size})")

    def _apply_edge_to_fields(self):
        sel = self.edge_list.curselection()
        if not sel:
            messagebox.showinfo("Select", "Select an element from the list first.")
            return
        el = self.edge_list.get(sel[0]).split()[0]
        E = ELEMENT_TO_EDGE[el]
        try:
            win = float(self.win_var.get())
            npts = int(float(self.npts_var.get()))
        except Exception as ex:
            messagebox.showerror("Invalid window/points", str(ex))
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
            self._log(f"Note: Adjusted to 1 eV minimum step → {npts} points")

        self.e_start.delete(0, "end"); self.e_start.insert(0, f"{emin:.6f}")
        self.e_end.delete(0, "end");   self.e_end.insert(0, f"{emax:.6f}")
        self.e_step.delete(0, "end");  self.e_step.insert(0, f"{step:.3f}")
        self._update_manual_points()
        self._log(f"Applied {el} edge: start={emin:.3f} end={emax:.3f} step={step:.3f} eV ({npts} pts)")

    def _load_curve_dialog(self):
        path = filedialog.askopenfilename(
            title="Select curve file",
            filetypes=[("Curve files", "*.csv *.npy"), ("All files", "*.*")]
        )
        if not path:
            return
        try:
            E, Y = _load_curve_file(path)
            if not self.overlay_var.get():
                self._reset_plot_axes()
            self.ax.plot(E, Y, "-", alpha=0.9, label=os.path.basename(path), color='cyan', linewidth=1.5)
            legend = self.ax.legend(loc="best", facecolor='#2b2b2b', edgecolor='white')
            for text in legend.get_texts():
                text.set_color('white')
            self.fig.canvas.draw_idle()
            self._log(f"Loaded curve: {path}  (N={E.size})")
        except Exception as ex:
            messagebox.showerror("Load curve error", str(ex))

    # ---------- Energy method management ----------
    def _on_method_change(self):
        """Show/hide appropriate frames based on selected energy method."""
        method = self.energy_method.get()

        # Hide all frames first
        self.manual_frame.pack_forget()
        self.plot_select_frame.pack_forget()
        self.custom_frame.pack_forget()

        # Show the selected frame
        if method == "manual":
            self.manual_frame.pack(side=tk.TOP, fill=tk.X, before=self.progress)
            self._disable_span_selector()
        elif method == "plot_select":
            self.plot_select_frame.pack(side=tk.TOP, fill=tk.X, before=self.progress)
        elif method == "custom":
            self.custom_frame.pack(side=tk.TOP, fill=tk.X, before=self.progress)
            self._disable_span_selector()

    def _enable_plot_selection(self):
        """Enable interactive span selection on the plot."""
        if self._span_selector is not None:
            self._disable_span_selector()
            return

        self._span_selector = SpanSelector(
            self.ax,
            self._on_span_select,
            'horizontal',
            useblit=True,
            props=dict(alpha=0.3, facecolor='red'),
            interactive=True,
            drag_from_anywhere=True
        )
        self.btn_enable_select.config(text="Disable Selection")
        self._log("Span selector enabled. Drag on plot to select energy range.")

    def _disable_span_selector(self):
        """Disable span selector."""
        if self._span_selector is not None:
            self._span_selector.set_active(False)
            self._span_selector = None
            self.btn_enable_select.config(text="Enable Selection")
            self.fig.canvas.draw_idle()

    def _on_span_select(self, xmin, xmax):
        """Callback when user selects a span on the plot."""
        if xmin == xmax:
            return
        self._selected_range = (min(xmin, xmax), max(xmin, xmax))

        # Calculate appropriate number of points for 1 eV step
        range_ev = abs(xmax - xmin) * 1000  # Convert to eV
        suggested_points = int(range_ev / 1.0) + 1  # 1 eV minimum step

        # Update the points field with suggestion
        self.plot_npts.delete(0, "end")
        self.plot_npts.insert(0, str(suggested_points))

        self.plot_range_label.config(text=f"Range: {xmin:.4f} - {xmax:.4f} keV ({suggested_points} pts @ 1eV)")
        self._log(f"Selected energy range: {xmin:.4f} - {xmax:.4f} keV → {suggested_points} points (1 eV step)")

    def _load_custom_energies(self):
        """Load custom energy values from a file."""
        path = filedialog.askopenfilename(
            title="Select energy file (one value per line)",
            filetypes=[("Text files", "*.txt *.csv *.dat"), ("All files", "*.*")]
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
            self.custom_info_label.config(
                text=f"Loaded {len(energies)} points: {energies[0]:.4f} - {energies[-1]:.4f} keV"
            )
            self._log(f"Loaded {len(energies)} custom energy points from {os.path.basename(path)}")
        except Exception as ex:
            messagebox.showerror("Load error", f"Failed to load energy file:\n{ex}")
            self._log(f"Error loading custom energies: {ex}")

    def _edit_energy_table(self):
        """Open a dialog to manually edit energy values."""
        dialog = tk.Toplevel(self)
        dialog.title("Edit Energy Table")
        dialog.geometry("400x500")

        tk.Label(dialog, text="Enter energy values (one per line, in keV):").pack(padx=10, pady=5)

        text_frame = tk.Frame(dialog)
        text_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        scrollbar = tk.Scrollbar(text_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        text = tk.Text(text_frame, yscrollcommand=scrollbar.set, width=40, height=20)
        text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=text.yview)

        # Pre-fill with existing values if any
        if self._custom_energies is not None:
            for e in self._custom_energies:
                text.insert(tk.END, f"{e:.6f}\n")

        def save_and_close():
            try:
                content = text.get("1.0", tk.END).strip()
                if not content:
                    messagebox.showwarning("Empty", "No energy values entered")
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
                self.custom_info_label.config(
                    text=f"{len(energies)} points: {energies[0]:.4f} - {energies[-1]:.4f} keV"
                )
                self._log(f"Set {len(energies)} custom energy points")
                dialog.destroy()

            except Exception as ex:
                messagebox.showerror("Parse error", str(ex))

        btn_frame = tk.Frame(dialog)
        btn_frame.pack(fill=tk.X, padx=10, pady=10)
        ttk.Button(btn_frame, text="Save", command=save_and_close).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Cancel", command=dialog.destroy).pack(side=tk.LEFT, padx=5)

    def _get_energy_array(self):
        """Get energy array based on selected method. Returns np.array or raises exception."""
        method = self.energy_method.get()

        if method == "manual":
            # Manual method: start, end, step (in eV)
            try:
                emin = float(self.e_start.get())
                emax = float(self.e_end.get())
                step = float(self.e_step.get())
                if step <= 0:
                    raise ValueError("Step must be > 0")
                npts = int((emax*1000 - emin*1000)/step) + 1
                if npts <= 1:
                    raise ValueError("Number of points must be > 1")
                return np.linspace(emin, emax, npts)
            except Exception as ex:
                raise ValueError(f"Manual method error: {ex}")

        elif method == "plot_select":
            # Plot selection method
            if self._selected_range is None:
                raise ValueError("No energy range selected on plot. Enable selection and drag on plot.")
            try:
                npts = int(float(self.plot_npts.get()))
                if npts <= 1:
                    raise ValueError("Number of points must be > 1")
                emin, emax = self._selected_range
                return np.linspace(emin, emax, npts)
            except ValueError as ex:
                raise ValueError(f"Plot selection method error: {ex}")

        elif method == "custom":
            # Custom energy array
            if self._custom_energies is None:
                raise ValueError("No custom energies loaded. Load from file or edit table.")
            return self._custom_energies.copy()

        else:
            raise ValueError(f"Unknown energy method: {method}")

    # ---------- Calibrate ----------
    def on_calibrate(self):
        try:
            energies = self._get_energy_array()
        except Exception as ex:
            messagebox.showerror("Invalid input", str(ex))
            return

        npts = len(energies)
        self._stop_requested = False
        self.btn_cal.config(state=tk.DISABLED)
        self.btn_start.config(state=tk.DISABLED)
        self.btn_stop.config(state=tk.NORMAL)
        self.progress['value'] = 0
        self.progress['maximum'] = npts

        threading.Thread(target=self._calib_worker, args=(energies,), daemon=True).start()

    def _calib_worker(self, energies):
        sums = []
        npts = len(energies)
        det_pv = self.detector_var.get()
        acq_pv = self.cam_acq_var.get()
        acq_rbv_pv = self.cam_acq_rbv_var.get()
        e_set_pv = self.energy_set_var.get()
        e_rb_pv = self.energy_rb_var.get().strip()
        try:
            settle = float(self.settle_var.get())
        except Exception:
            settle = DEFAULTS["settle_s"]

        try:
            for i, E in enumerate(energies, start=1):
                if self._stop_requested:
                    self._log("Calibration aborted by user.")
                    break

                self._log(f"Set energy → {E:.4f} keV")
                epics_put(e_set_pv, E, wait=True)
                t0 = time.time()
                if e_rb_pv:
                    for _ in range(60):
                        try:
                            rb = float(epics_get(e_rb_pv))
                            if abs(rb - E) <= 0.001:  # ~1 eV
                                break
                        except Exception:
                            pass
                        time.sleep(0.05)
                dt = max(0.0, settle - (time.time() - t0))
                if dt > 0:
                    time.sleep(dt)

                self._log("Acquire one frame")
                try:
                    epics_put(acq_pv, 1, wait=False)
                except Exception:
                    pass
                for _ in range(80):
                    if self._stop_requested:
                        break
                    try:
                        if float(epics_get(acq_rbv_pv)) == 0.0:
                            break
                    except Exception:
                        pass
                    time.sleep(0.05)

                img = pva_get_ndarray(det_pv)
                s = float(np.sum(img)); sums.append(s)
                self._log(f"Sum @ {E:.4f} keV = {s:.6g}")

                self.progress['value'] = i

                # Plot live; respect overlay toggle
                if not self.overlay_var.get():
                    # replace plot content
                    self.ax.clear()
                    self.ax.set_title("Calibration spectrum (sum of pixels vs energy)")
                    self.ax.set_xlabel("Energy (keV)")
                    self.ax.set_ylabel("Sum of pixels")
                    self.ax.grid(True, alpha=0.3)
                # Draw/update current calibration segment
                self.ax.plot(energies[:i], sums, "o-", color='lime', linewidth=1.5, markersize=4,
                           label="Calibration" if i == 1 and self.overlay_var.get() else None)
                if self.overlay_var.get():
                    legend = self.ax.legend(loc="best", facecolor='#2b2b2b', edgecolor='white')
                    for text in legend.get_texts():
                        text.set_color('white')
                self.fig.canvas.draw_idle()

            # Keep last calibration for optional saving
            self._last_calib = (energies, np.array(sums, dtype=float))

        except Exception as ex:
            self._log(f"ERROR (calibrate): {ex}")
            messagebox.showerror("Calibration error", str(ex))
        finally:
            self.btn_cal.config(state=tk.NORMAL)
            self.btn_start.config(state=tk.NORMAL)
            self.btn_stop.config(state=tk.DISABLED)
            self.progress['value'] = 0

    # ---------- Start / Stop ----------
    def on_start(self):
        """Launch the .sh (set in PV Settings) that SSHes and runs xanes_energy.py."""
        script_path = self.start_script_var.get().strip()
        if not script_path or not os.path.exists(script_path):
            messagebox.showerror("Start error", f"Start script not found:\n{script_path or '(empty)'}")
            return

        # Get energy array and validate
        try:
            energies = self._get_energy_array()
        except Exception as ex:
            messagebox.showerror("Invalid energy configuration", str(ex))
            return

        method = self.energy_method.get()

        # Prime the PVs so the remote script reads current fields
        try:
            if method == "manual":
                # For manual mode, set the PVs directly
                epics_put(DEFAULTS["xanes_start_pv"],  float(self.e_start.get()))
                epics_put(DEFAULTS["xanes_end_pv"],    float(self.e_end.get()))
                epics_put(DEFAULTS["xanes_step_pv"],   float(self.e_step.get()))
                self._log(f"Manual mode: {len(energies)} points from {energies[0]:.4f} to {energies[-1]:.4f} keV")
            else:
                # For plot_select and custom methods, save energies to file
                # The remote script will need to be modified to use the energies file directly
                outfile = DEFAULTS["custom_energies_file"]
                np.save(outfile, energies)
                self._log(f"Saved {len(energies)} custom energies to {outfile}")

                # Still set the PVs for the range (for display/logging purposes)
                epics_put(DEFAULTS["xanes_start_pv"],  float(energies[0]))
                epics_put(DEFAULTS["xanes_end_pv"],    float(energies[-1]))
                # Calculate equivalent step size for info
                if len(energies) > 1:
                    avg_step = (energies[-1] - energies[0]) * 1000 / (len(energies) - 1)
                    epics_put(DEFAULTS["xanes_step_pv"], avg_step)

                self._log(f"Using {method} method: {len(energies)} points from {energies[0]:.4f} to {energies[-1]:.4f} keV")
                messagebox.showinfo("Custom Energies",
                    f"Custom energy array saved to:\n{outfile}\n\n"
                    f"IMPORTANT: Your xanes_energy.py script must be modified to use this file "
                    f"instead of calculating energies from start/end/step PVs.")
        except Exception as ex:
            self._log(f"WARNING: could not prime XANES PVs: {ex}")

        self._stop_requested = False
        self.btn_start.config(state=tk.DISABLED)
        self.btn_cal.config(state=tk.NORMAL)
        self.btn_stop.config(state=tk.NORMAL)
        self.progress['value'] = 0
        self.progress['maximum'] = 100

        def launch():
            try:
                self._log(f"Launching script: {script_path}")
                self._proc = subprocess.Popen(
                    ["bash", script_path],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                    preexec_fn=os.setsid  # new process group so we can kill everything on Stop
                )
                self._proc_pgid = os.getpgid(self._proc.pid)
                for line in self._proc.stdout:
                    self._log(line.rstrip())
                    if self._stop_requested:
                        break
                rc = self._proc.wait()
                self._log(f"Start script exited with code {rc}")
            except Exception as ex:
                self._log(f"ERROR (start launcher): {ex}")
                messagebox.showerror("Start error", str(ex))
            finally:
                self.after(0, self._reset_buttons)

        threading.Thread(target=launch, daemon=True).start()

    def on_stop(self):
        """Terminate the whole process group started by Start and (optionally) touch safety PVs."""
        self._stop_requested = True
        if self._proc and self._proc.poll() is None and self._proc_pgid:
            try:
                self._log(f"Stopping process group PGID={self._proc_pgid}")
                os.killpg(self._proc_pgid, signal.SIGTERM)
            except Exception as ex:
                self._log(f"Terminate failed: {ex}")

        # Optional safety PVs — set strings to "" in PV tab if you want to disable.
        try:
            epics_put(DEFAULTS["epid_h_on_pv"], "off")
            epics_put(DEFAULTS["epid_v_on_pv"], "off")
            epics_put(DEFAULTS["shaker_run_pv"], "Stop")
            self._log("Feedback/shaker: OFF/STOP sent.")
        except Exception as ex:
            self._log(f"NOTE: safety PVs not touched or unavailable: {ex}")

        self._reset_buttons()

    def _reset_buttons(self):
        self.btn_stop.config(state=tk.DISABLED)
        self.btn_start.config(state=tk.NORMAL)
        self.btn_cal.config(state=tk.NORMAL)
        self.progress['value'] = 0

    # ---------- Shutdown ----------
    def _on_close(self):
        """No safety caputs here. Just try to stop the process group if running."""
        try:
            if self._proc and self._proc.poll() is None and self._proc_pgid:
                os.killpg(self._proc_pgid, signal.SIGTERM)
        except Exception:
            pass
        self.destroy()

# -------------------------
# Main
# -------------------------
if __name__ == "__main__":
    app = XANESGui()
    app.mainloop()