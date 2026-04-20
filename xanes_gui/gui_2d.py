#!/usr/bin/env python3
"""
2D XANES / ZP focus-calibration GUI for APS Beamline 32-ID TXM.

Same visual style as the 1-D xanes_gui, extended to drive a full scan loop:

  For each energy in [E_start, E_end, step]:
    1. Set mono energy (write E, press EnergySet, wait on RBV).
    2. Compute experimental ZP motor position (finite-conjugate formula,
       L = camera_distance + f(E)) and move the ZP.
    3. Move sample to DATA position (topx, topz[, rot]); acquire a frame.
    4. Move sample to REFERENCE position (topx_ref, topz_ref[, rot_ref]);
       acquire a frame.
    5. Append frames to a master HDF5 file:
         /exchange/data         (N, H, W)   — sample frames
         /exchange/data_flat    (N, H, W)   — reference / flat frames
         /exchange/energy       (N,)        — eV
         /exchange/zp_position  (N,)        — mm
         /exchange/theta_data   (N,)        — deg
         /exchange/theta_flat   (N,)        — deg

Usable for ZP focus-vs-energy calibration (track a resolution pattern
across the plane perpendicular to the beam) and for 2-D XANES imaging.
"""

import json
import os
import signal
import subprocess
import sys
import threading
import time

import h5py
import numpy as np
import epics
import pvaccess as pva
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QColor, QPalette
from PyQt5.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog,
                             QFileDialog, QFrame, QGroupBox, QHBoxLayout,
                             QLabel, QLineEdit, QMainWindow, QMessageBox,
                             QProgressBar, QPushButton, QRadioButton,
                             QScrollArea, QTabWidget, QTextEdit,
                             QVBoxLayout, QWidget)


HC_EV_NM = 1239.84198  # eV·nm

# Settings file shared with the 1D GUI — we read it for the calibration-curve
# directories so the two tools stay in sync.
SHARED_1D_SETTINGS = os.path.expanduser("~/.xanes_gui_settings.json")

# Optics Calculator config file — single source of truth for ZP parameters.
OPTICS_CONFIG_PATHS = [
    "/home/beams0/AMITTONE/Software/txm_calc/optics_config.json",
    "/home/beams/AMITTONE/Software/txm_calc/optics_config.json",
    "/home/beams/USERTXM/Software/txm_calc/optics_config.json",
    "/home/beams0/USERTXM/Software/txm_calc/optics_config.json",
    os.path.expanduser("~/Software/txm_calc/optics_config.json"),
]


def find_optics_config_path():
    for p in OPTICS_CONFIG_PATHS:
        if os.path.exists(p):
            return p
    return None


def load_optics_config():
    """Return the txm_calc optics_config.json contents, or None if unavailable."""
    path = find_optics_config_path()
    if not path:
        return None
    try:
        with open(path) as fh:
            return json.load(fh)
    except Exception:
        return None

# K-edges (6–16 keV) — kept in sync with gui.py's K_EDGES_6_16_KEV.
K_EDGES_6_16_KEV = [
    ("Mn",  6.539), ("Fe",  7.112), ("Co",  7.709), ("Ni",  8.333),
    ("Cu",  8.979), ("Zn",  9.659), ("Ga", 10.367), ("Ge", 11.103),
    ("Pt", 11.564), ("As", 11.867), ("Se", 12.658), ("Br", 13.474),
    ("Kr", 14.327), ("Rb", 15.200), ("Sr", 16.105),
]
ELEMENT_TO_EDGE = {el: E for el, E in K_EDGES_6_16_KEV}


def load_shared_curve_settings():
    """Return (curve_dir_calibrated, curve_dir_simulated, curve_ext) from the
    1D GUI settings file if present, else (None, None, None)."""
    try:
        with open(SHARED_1D_SETTINGS) as fh:
            d = json.load(fh)
        return (d.get("curve_dir_calibrated") or None,
                d.get("curve_dir_simulated") or None,
                d.get("curve_ext") or ".npy")
    except Exception:
        return None, None, ".npy"


def load_curve_file(path):
    """Load (E, Y) from .npy or .csv (matches gui.py)."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".npy":
        try:
            arr = np.load(path, allow_pickle=False)
            if arr.ndim != 2:
                raise ValueError("NPY must be 2D")
            if arr.shape[0] == 2:
                return arr[0], arr[1]
            if arr.shape[1] == 2:
                return arr[:, 0], arr[:, 1]
            raise ValueError("NPY shape must be 2xN or Nx2")
        except (ValueError, OSError):
            data = np.loadtxt(path)
            return data[:, 0], data[:, 1]
    try:
        data = np.loadtxt(path, delimiter=",")
    except Exception:
        data = np.loadtxt(path)
    return data[:, 0], data[:, 1]


# Default PVs / paths — edited at runtime via the "PVs" tab
DEFAULTS = {
    # Imaging chain
    "detector_pv":         "32idbSP1:Pva1:Image",
    "cam_acquire_pv":      "32idbSP1:cam1:Acquire",
    "cam_acquire_rbv_pv":  "32idbSP1:cam1:Acquire_RBV",
    "cam_acquire_time_pv": "32idbSP1:cam1:AcquireTime",
    "cam_image_mode_pv":   "32idbSP1:cam1:ImageMode",
    "cam_num_images_pv":   "32idbSP1:cam1:NumImages",

    # Mono energy
    "energy_pv":     "32id:TXMOptics:Energy",      # target value (keV)
    "energy_set_pv": "32id:TXMOptics:EnergySet",   # "press to move"
    "energy_rb_pv":  "32id:TXMOptics:Energy_RBV",  # readback (keV)
    "energy_units":  "keV",                        # "keV" or "eV" on this beamline
    "energy_tol":    0.001,                        # tolerance in the above units

    # Motors
    "zp_motor_pv": "32id:m1",
    "topx_pv":     "32id:m2",
    "topz_pv":     "32id:m3",
    "rot_pv":      "32id:m4",

    # ZP + geometry defaults
    "zp_diameter_um":     300.0,
    "zp_drn_nm":           30.0,
    "zp_eps_mm":            0.0,
    "mono_offset_eV":      30.0,
    "camera_distance_mm": 3500.0,

    # Timing
    "motor_settle_s":       0.5,
    "post_energy_settle_s": 2.0,

    # Output
    "save_dir":        os.path.expanduser("~/scans"),
    "master_h5_name":  "xanes2d_scan.h5",
    "hdf5_compression": None,    # uncompressed: fastest writes, fully portable
    "hdf5_gzip_level": 1,
}


# ── physics helpers ───────────────────────────────────────────────────────

def zp_focal_length_mm(energy_eV, diameter_um, drn_nm, mono_offset_eV=0.0):
    e = energy_eV - mono_offset_eV
    if e <= 0:
        return None
    wavelength_nm = HC_EV_NM / e
    return (diameter_um * 1000.0 * drn_nm / wavelength_nm) * 1e-6


def zp_motor_position_mm(energy_eV, L_mm, diameter_um, drn_nm,
                         mono_offset_eV=0.0, eps_mm=0.0):
    f = zp_focal_length_mm(energy_eV, diameter_um, drn_nm, mono_offset_eV)
    if f is None or L_mm <= 0:
        return None
    disc = L_mm * L_mm - 4.0 * L_mm * f
    if disc < 0:
        return None
    return (L_mm - disc ** 0.5) / 2.0 + eps_mm


def zp_motor_from_cal(energy_eV, cal_points):
    """Interpolate ZP motor position directly from calibration measurements.

    `cal_points` is a list of [E_eV, motor_mm] pairs captured by the TXM
    Optics Calculator's calibration dialog. Uses cubic interpolation when
    ≥4 points are available and scipy is present, else linear. Returns
    None if there are fewer than 2 points."""
    if not cal_points or len(cal_points) < 2:
        return None
    pts = sorted(((float(E), float(m)) for E, m in cal_points), key=lambda p: p[0])
    Es = np.array([p[0] for p in pts])
    Ms = np.array([p[1] for p in pts])
    if len(pts) >= 4:
        try:
            from scipy.interpolate import CubicSpline
            cs = CubicSpline(Es, Ms, extrapolate=True)
            return float(cs(energy_eV))
        except Exception:
            pass
    return float(np.interp(energy_eV, Es, Ms))


# ── EPICS helpers (pyepics) ───────────────────────────────────────────────

def epics_put(pv, value, wait=True, timeout=15.0):
    if not pv:
        return
    ok = epics.caput(pv, value, wait=wait, timeout=timeout)
    if ok is None or ok == 0:
        # caput returns 1 on success for pyepics >= 3.5; None on failure.
        # Some builds return 0; treat non-exception as OK but log via caller if needed.
        return


def epics_get_float(pv, timeout=3.0):
    v = epics.caget(pv, timeout=timeout)
    if v is None:
        raise RuntimeError(f"caget failed: {pv}")
    return float(v)


def epics_get(pv, as_string=True, timeout=3.0):
    v = epics.caget(pv, as_string=as_string, timeout=timeout)
    if v is None:
        raise RuntimeError(f"caget failed: {pv}")
    return v


# ── PVA image grab (copied from gui.py, trimmed) ──────────────────────────

_PVA_CH_CACHE = {}

def _pva_channel(det_pv):
    ch = _PVA_CH_CACHE.get(det_pv)
    if ch is None:
        ch = pva.Channel(det_pv)
        _PVA_CH_CACHE[det_pv] = ch
    return ch


def _pva_unique_id(st):
    try:
        uid = st.get('uniqueId') if hasattr(st, 'get') else st['uniqueId']
        return int(uid)
    except Exception:
        return None


def _ndarray_from_struct(st):
    """Decode an NTNDArray pvaccess struct into a 2-D ndarray (same logic as
    the previous pva_get_ndarray, factored out so callers can inspect uniqueId
    before extracting the pixels)."""
    val = st['value'][0]
    flat = None
    for key in ('ushortValue', 'shortValue', 'intValue', 'floatValue',
                'doubleValue', 'ubyteValue', 'byteValue'):
        if key in val:
            flat = np.asarray(val[key])
            break
    if flat is None:
        raise RuntimeError("Unsupported NTNDArray numeric type")

    dims = []
    try:
        dims = st['dimension']
    except Exception:
        pass
    if len(dims) >= 2:
        h = int(dims[0]['size'])
        w = int(dims[1]['size'])
        if h * w == flat.size:
            return flat.reshape(h, w)

    try:
        attrs = st['attribute']
        width, height = None, None
        for attr in attrs:
            name = attr['name']
            if name in ('ArraySize0_Y', 'ArraySizeY', 'dimY'):
                height = int(attr['value'])
            elif name in ('ArraySize1_X', 'ArraySizeX', 'dimX'):
                width = int(attr['value'])
        if width and height and width * height == flat.size:
            return flat.reshape(height, width)
    except Exception:
        pass

    n = flat.size
    for h in range(int(np.sqrt(n)), 0, -1):
        if n % h == 0:
            return flat.reshape(h, n // h)
    side = int(np.sqrt(flat.size))
    return flat.reshape(side, flat.size // side)


def pva_current_unique_id(det_pv):
    try:
        return _pva_unique_id(_pva_channel(det_pv).get())
    except Exception:
        return None


def pva_wait_for_new(det_pv, prev_uid, timeout):
    """Block until the PVA server publishes a frame with uniqueId != prev_uid.
    Returns (ndarray, new_uid) on success, (None, None) on timeout."""
    ch = _pva_channel(det_pv)
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            st = ch.get()
            uid = _pva_unique_id(st)
            if uid is not None and uid != prev_uid:
                return _ndarray_from_struct(st), uid
            # If the server doesn't expose uniqueId, fall back to returning
            # whatever we got — still better than the previous 30s hang.
            if uid is None:
                return _ndarray_from_struct(st), None
        except Exception:
            pass
        time.sleep(0.005)
    return None, None


def pva_get_ndarray(det_pv):
    return _ndarray_from_struct(_pva_channel(det_pv).get())


# ── master HDF5 writer ────────────────────────────────────────────────────

class MasterH5:
    """HDF5 master file with full scan + instrument metadata.

    Layout:
      /exchange/
        data              (N, H, W)  — sample frames
        data_flat         (N, H, W)  — reference frames
        energy            (N,)  [eV]
        zp_position       (N,)  [mm]
        theta_data        (N,)  [deg]
        theta_flat        (N,)  [deg]
      /measurement/instrument/...   — static attributes captured at scan start
      /measurement/per_step/...     — per-acquisition growable datasets
          timestamp_epoch
          energy_rbv
          zp_rbv, topx_data_rbv, topz_data_rbv, rot_data_rbv,
          topx_ref_rbv,  topz_ref_rbv,  rot_ref_rbv
          step_time_s
    """

    PER_STEP_FIELDS = [
        ("timestamp_epoch", "s (epoch)"),
        ("energy_rbv",      "eV"),
        ("zp_rbv",          "mm"),
        ("topx_data_rbv",   "mm"),
        ("topz_data_rbv",   "mm"),
        ("rot_data_rbv",    "deg"),
        ("topx_ref_rbv",    "mm"),
        ("topz_ref_rbv",    "mm"),
        ("rot_ref_rbv",     "deg"),
        ("step_time_s",     "s"),
    ]

    def __init__(self, path, scan_meta):
        self.path = path
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.f = h5py.File(path, "w")
        self.f.attrs["created"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        self.f.attrs["format"] = "xanes_gui.gui_2d v1"
        self.f.attrs["scan_config"] = json.dumps(scan_meta, indent=2, default=str)

        self._compress_kwargs = {}
        comp = scan_meta.get("hdf5_compression", "gzip")
        if comp:
            self._compress_kwargs["compression"] = comp
            if comp == "gzip":
                self._compress_kwargs["compression_opts"] = int(
                    scan_meta.get("hdf5_gzip_level", 3))

        # /exchange — images + primary axes
        self.exchange = self.f.create_group("exchange")
        self._data_ds = None
        self._flat_ds = None
        self._e_ds = self.exchange.create_dataset(
            "energy", shape=(0,), maxshape=(None,), dtype="f8")
        self._e_ds.attrs["units"] = "eV"
        self._zp_ds = self.exchange.create_dataset(
            "zp_position", shape=(0,), maxshape=(None,), dtype="f8")
        self._zp_ds.attrs["units"] = "mm"
        self._theta_d_ds = self.exchange.create_dataset(
            "theta_data", shape=(0,), maxshape=(None,), dtype="f8")
        self._theta_d_ds.attrs["units"] = "deg"
        self._theta_f_ds = self.exchange.create_dataset(
            "theta_flat", shape=(0,), maxshape=(None,), dtype="f8")
        self._theta_f_ds.attrs["units"] = "deg"

        # /measurement/instrument — static
        self.measurement = self.f.create_group("measurement")
        self.instrument = self.measurement.create_group("instrument")

        # /measurement/per_step — growable readbacks
        self.per_step = self.measurement.create_group("per_step")
        self._step_ds = {}
        for name, units in self.PER_STEP_FIELDS:
            ds = self.per_step.create_dataset(
                name, shape=(0,), maxshape=(None,), dtype="f8")
            ds.attrs["units"] = units
            self._step_ds[name] = ds

    # ── static instrument snapshot ─────────────────────────────────────
    def write_instrument_snapshot(self, snapshot: dict):
        """`snapshot` is a nested dict of (group_name -> {attr: value}).
        Written to /measurement/instrument/<group>.attrs[<attr>] = value.
        """
        for group_name, attrs in snapshot.items():
            grp = self.instrument.require_group(group_name)
            for k, v in attrs.items():
                if v is None:
                    continue
                try:
                    grp.attrs[k] = v
                except TypeError:
                    grp.attrs[k] = str(v)

    # ── image stacks ───────────────────────────────────────────────────
    def _ensure(self, name, sample):
        if name in self.exchange:
            return self.exchange[name]
        h, w = sample.shape[-2:]
        ds = self.exchange.create_dataset(
            name, shape=(0, h, w),
            maxshape=(None, h, w),
            chunks=(1, h, w),
            dtype=sample.dtype,
            **self._compress_kwargs,
        )
        return ds

    def append_data(self, arr):
        if self._data_ds is None:
            self._data_ds = self._ensure("data", arr)
        n = self._data_ds.shape[0]
        self._data_ds.resize(n + 1, axis=0)
        self._data_ds[n] = arr

    def append_flat(self, arr):
        if self._flat_ds is None:
            self._flat_ds = self._ensure("data_flat", arr)
        n = self._flat_ds.shape[0]
        self._flat_ds.resize(n + 1, axis=0)
        self._flat_ds[n] = arr

    # ── per-step bookkeeping ───────────────────────────────────────────
    def append_meta(self, energy_eV, zp_mm, theta_d, theta_f):
        for ds, val in [(self._e_ds, energy_eV),
                        (self._zp_ds, zp_mm),
                        (self._theta_d_ds, float("nan") if theta_d is None else theta_d),
                        (self._theta_f_ds, float("nan") if theta_f is None else theta_f)]:
            n = ds.shape[0]
            ds.resize(n + 1, axis=0)
            ds[n] = val

    def append_step_readbacks(self, readbacks: dict):
        """Append one row to each /measurement/per_step/<field> dataset.
        Missing fields are stored as NaN.
        """
        for name, _ in self.PER_STEP_FIELDS:
            ds = self._step_ds[name]
            n = ds.shape[0]
            ds.resize(n + 1, axis=0)
            val = readbacks.get(name)
            try:
                ds[n] = float(val) if val is not None else float("nan")
            except (TypeError, ValueError):
                ds[n] = float("nan")

    def set_end_time(self):
        self.f.attrs["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S")

    def flush(self):
        self.f.flush()

    def close(self):
        try:
            self.f.flush()
        finally:
            self.f.close()


# ── scan worker thread ────────────────────────────────────────────────────

class ScanWorker(QThread):
    progress = pyqtSignal(int, int)         # (step index 1-based, total)
    log = pyqtSignal(str)
    error = pyqtSignal(str)
    done = pyqtSignal(str)                  # master file path

    def __init__(self, pvs, scan, params):
        super().__init__()
        self.pvs = pvs                    # dict of PV names
        self.scan = scan                  # dict with positions, energies, etc.
        self.params = params              # dict with ZP, geometry, output
        self._stop = False
        self._pv_cache = {}               # cached epics.PV objects

    def stop(self):
        self._stop = True

    # EPICS helpers
    def _pv(self, pvname):
        """Return a connected, cached epics.PV. Fresh connects are slow;
        reusing PV objects makes subsequent .get/.put ~instant."""
        if not pvname:
            return None
        pv = self._pv_cache.get(pvname)
        if pv is None:
            pv = epics.PV(pvname, auto_monitor=True)
            pv.wait_for_connection(timeout=3.0)
            self._pv_cache[pvname] = pv
        return pv

    def _put(self, pv, val, wait=True, timeout=15.0):
        """Write via plain caput. Using cached PVs here can race with the
        auto_monitor subscription and let ca_put_callback (=motor DMOV) fire
        before motion actually completes — caput avoids that."""
        if not pv:
            return
        epics.caput(pv, val, wait=wait, timeout=timeout)

    def _get_float(self, pv, default=None):
        if not pv:
            return default
        try:
            p = self._pv(pv)
            v = p.get(timeout=1.0, use_monitor=True) if p else None
            return default if v is None else float(v)
        except Exception:
            return default

    def _get_str(self, pv, default=None):
        if not pv:
            return default
        try:
            p = self._pv(pv)
            v = p.get(as_string=True, timeout=1.0, use_monitor=True) if p else None
            return default if v is None else str(v)
        except Exception:
            return default

    def _wait_for(self, pvname, predicate, timeout):
        """Event-driven wait: return True once predicate(value) holds.
        Uses PV monitor callbacks instead of caget polling."""
        pv = self._pv(pvname)
        if pv is None:
            return False
        ev = threading.Event()
        hit = [False]

        def _cb(value=None, **_):
            try:
                if predicate(value):
                    hit[0] = True
                    ev.set()
            except Exception:
                pass

        cid = pv.add_callback(_cb)
        try:
            # Fresh CA read (use_monitor=False) — otherwise we may accept a
            # stale cached value from before the most recent put. For an
            # energy step of exactly `tol` this was the reason we'd return
            # immediately and proceed while the mono was still moving.
            v = pv.get(timeout=1.0, use_monitor=False)
            if v is not None and predicate(v):
                return True
            deadline = time.time() + timeout
            while time.time() < deadline:
                if self._stop:
                    return False
                if ev.wait(0.1):
                    return hit[0]
            return False
        finally:
            try:
                pv.remove_callback(cid)
            except Exception:
                pass

    def _rbv(self, motor_pv):
        """Read `.RBV` field of a motor PV, falling back to the plain PV."""
        if not motor_pv:
            return None
        v = self._get_float(f"{motor_pv}.RBV")
        if v is None:
            v = self._get_float(motor_pv)
        return v

    def _collect_instrument_snapshot(self, first_frame_shape):
        """Snapshot all static instrument/geometry info for the master file."""
        pvs = self.pvs
        p = self.params
        s = self.scan

        H, W = first_frame_shape[-2], first_frame_shape[-1]

        # Detector + file plugin + binning/crop (best effort — missing PVs OK)
        cam_prefix = pvs.get("cam_acquire_pv", "").split(":Acquire")[0] or ""

        det = {
            "exposure_time_s": float(s.get("exposure_s", float("nan"))),
            "num_images_per_point": 1,
            "trigger_mode": self._get_str(f"{cam_prefix}:TriggerMode"),
            "manufacturer": self._get_str(f"{cam_prefix}:Manufacturer_RBV"),
            "model": self._get_str(f"{cam_prefix}:Model_RBV"),
            "data_type": self._get_str(f"{cam_prefix}:DataType_RBV"),
            "image_height_px": int(H),
            "image_width_px": int(W),
            "size_x_rbv": self._get_float(f"{cam_prefix}:SizeX_RBV"),
            "size_y_rbv": self._get_float(f"{cam_prefix}:SizeY_RBV"),
            "binx": self._get_float(f"{cam_prefix}:BinX"),
            "biny": self._get_float(f"{cam_prefix}:BinY"),
            "min_x": self._get_float(f"{cam_prefix}:MinX"),
            "min_y": self._get_float(f"{cam_prefix}:MinY"),
            "temperature_c": self._get_float(f"{cam_prefix}:Temperature_RBV"),
            "detector_pv": pvs.get("detector_pv"),
            "cam_prefix": cam_prefix,
        }

        optics_prefix = "32id:TXMOptics"
        zp = {
            "zp_diameter_um": p.get("zp_diameter_um"),
            "zp_drn_nm": p.get("zp_drn_nm"),
            "zp_eps_mm": p.get("zp_eps_mm"),
            "mono_offset_eV": p.get("mono_offset_eV"),
            "camera_distance_mm": p.get("camera_distance_mm"),
            "zp_motor_pv": pvs.get("zp_motor_pv"),
            "image_pixel_size_nm": self._get_float(f"{optics_prefix}:ImagePixelSize"),
            "crop_left": self._get_float(f"{optics_prefix}:CropLeft"),
            "crop_right": self._get_float(f"{optics_prefix}:CropRight"),
            "crop_top": self._get_float(f"{optics_prefix}:CropTop"),
            "crop_bottom": self._get_float(f"{optics_prefix}:CropBottom"),
        }

        mono = {
            "energy_pv": pvs.get("energy_pv"),
            "energy_set_pv": pvs.get("energy_set_pv"),
            "energy_rb_pv": pvs.get("energy_rb_pv"),
            "energy_units": pvs.get("energy_units"),
            "energy_tol": float(pvs.get("energy_tol", 0.0)),
            "post_energy_settle_s": float(p.get("post_energy_settle_s", 0.0)),
        }

        sample = {
            "topx_pv": pvs.get("topx_pv"),
            "topz_pv": pvs.get("topz_pv"),
            "rot_pv": pvs.get("rot_pv"),
            "motor_settle_s": float(p.get("motor_settle_s", 0.0)),
            "topx_data_mm": s.get("topx_data_mm"),
            "topz_data_mm": s.get("topz_data_mm"),
            "rot_data_deg": s.get("rot_data_deg"),
            "topx_ref_mm": s.get("topx_ref_mm"),
            "topz_ref_mm": s.get("topz_ref_mm"),
            "rot_ref_deg": s.get("rot_ref_deg"),
            "topx_initial_rbv": self._rbv(pvs.get("topx_pv")),
            "topz_initial_rbv": self._rbv(pvs.get("topz_pv")),
            "rot_initial_rbv": self._rbv(pvs.get("rot_pv")),
        }

        scan_plan = {
            "energy_first_eV": self.scan["energies_eV"][0] if self.scan["energies_eV"] else None,
            "energy_last_eV":  self.scan["energies_eV"][-1] if self.scan["energies_eV"] else None,
            "energy_step_eV":  (self.scan["energies_eV"][1] - self.scan["energies_eV"][0])
                               if len(self.scan["energies_eV"]) > 1 else None,
            "n_energies": len(self.scan["energies_eV"]),
            "scan_start_epoch": time.time(),
        }

        return {
            "detector": det,
            "zone_plate_and_optics": zp,
            "monochromator": mono,
            "sample_stage": sample,
            "scan_plan": scan_plan,
        }

    def _move_motor(self, pv, target, settle):
        if not pv:
            return
        self._put(pv, float(target), wait=True, timeout=60.0)
        if settle > 0:
            time.sleep(settle)

    def _set_energy(self, e_value):
        units = self.pvs.get("energy_units", "keV")
        e_for_pv = e_value / 1000.0 if units == "keV" else e_value
        # wait=False: this IOC does not fire put-completion on energy_pv, so
        # wait=True would always time out (30 s per step). RBV is the real
        # completion signal.
        self._put(self.pvs["energy_pv"], e_for_pv, wait=False)
        if self.pvs.get("energy_set_pv"):
            # EnergySet is rising-edge triggered: if it's still 1 from the
            # previous step, writing 1 again is a no-op and the mono doesn't
            # move. Force 0 first to guarantee a clean 0→1 edge.
            self._put(self.pvs["energy_set_pv"], 0, wait=False)
            self._put(self.pvs["energy_set_pv"], 1, wait=False)
        rb_pv = self.pvs.get("energy_rb_pv")
        if rb_pv:
            tol = float(self.pvs.get("energy_tol", 0.001))
            t_wait = time.time()
            matched = self._wait_for(
                rb_pv,
                lambda v: v is not None and abs(float(v) - e_for_pv) <= tol,
                timeout=30.0,
            )
            if not matched and not self._stop:
                final = self._get_float(rb_pv)
                waited = time.time() - t_wait
                self.log.emit(
                    f"    energy wait timed out after {waited:.1f}s: "
                    f"target={e_for_pv:g} RBV={final!r} tol={tol:g} "
                    f"(Δ={abs(float(final) - e_for_pv):g} if readable). "
                    f"Raise 'energy_tol' in the PVs tab if the mono settles "
                    f"slightly off-target."
                )
        time.sleep(float(self.params.get("post_energy_settle_s", 2.0)))

    def _set_zp_for_energy(self, energy_eV):
        p = self.params
        cal = p.get("zp_cal_points")
        s = zp_motor_from_cal(energy_eV, cal) if cal else None
        if s is None:
            L = p["camera_distance_mm"] + zp_focal_length_mm(
                energy_eV, p["zp_diameter_um"], p["zp_drn_nm"],
                p["mono_offset_eV"])
            s = zp_motor_position_mm(
                energy_eV, L, p["zp_diameter_um"], p["zp_drn_nm"],
                p["mono_offset_eV"], p["zp_eps_mm"])
        if s is None:
            raise ValueError(f"No ZP solution at {energy_eV:.2f} eV")
        self._move_motor(self.pvs["zp_motor_pv"], s,
                         self.params.get("motor_settle_s", 0.5))
        return s

    def _configure_camera_once(self):
        """Set NumImages/ImageMode/AcquireTime a single time at scan start
        instead of on every frame."""
        self._put(self.pvs["cam_num_images_pv"], 1)
        self._put(self.pvs["cam_image_mode_pv"], 0)  # Single
        self._put(self.pvs["cam_acquire_time_pv"], float(self.scan["exposure_s"]))

    def _acquire_one(self):
        # Snapshot the current PVA uniqueId BEFORE triggering, then block until
        # the server publishes a frame with a different uniqueId. This is the
        # only reliable completion signal across IOC flavours — cam_acquire_rbv
        # can be a state-string, unpublished, or simply never transition in
        # the way our poll expects.
        det = self.pvs["detector_pv"]
        prev_uid = pva_current_unique_id(det)
        self._put(self.pvs["cam_acquire_pv"], 1, wait=False)
        exposure = float(self.scan["exposure_s"])
        img, _ = pva_wait_for_new(det, prev_uid,
                                  timeout=max(5.0, exposure * 3 + 5))
        if img is None and self._stop:
            return None
        if img is None:
            # Last-resort fallback: return current frame even if uid didn't
            # advance, so the scan doesn't hang on a misconfigured detector.
            return pva_get_ndarray(det)
        return img

    def run(self):
        try:
            energies_eV = list(self.scan["energies_eV"])
            total = len(energies_eV)
            master_path = self.params["master_path"]

            scan_meta = {**self.pvs, **self.scan, **self.params,
                         "energies_eV": energies_eV,
                         "hdf5_compression": DEFAULTS.get("hdf5_compression", "gzip"),
                         "hdf5_gzip_level": DEFAULTS.get("hdf5_gzip_level", 3)}
            master = MasterH5(master_path, scan_meta)

            self.log.emit(f"Master file: {master_path}")
            self.log.emit(f"Scanning {total} energies "
                          f"({energies_eV[0]:.2f} → {energies_eV[-1]:.2f} eV)")

            self._configure_camera_once()

            # Warmup: prime the mono so the first real move isn't timed
            # against the per-step stopwatch. If first_E == current_E the
            # move is a no-op; otherwise we pay the cold-start once, here.
            if energies_eV:
                t_warm = time.time()
                self.log.emit(f"Warming mono to {energies_eV[0]:.2f} eV…")
                self._set_energy(energies_eV[0])
                self.log.emit(f"Warmup done in {time.time() - t_warm:.1f}s")

            instrument_snapshot_written = False

            for i, e_eV in enumerate(energies_eV, start=1):
                if self._stop:
                    self.log.emit("Stopped by user.")
                    break

                t0 = time.time()
                self.log.emit(f"[{i}/{total}] E = {e_eV:.2f} eV")

                tE = time.time()
                self._set_energy(e_eV)
                if self._stop:
                    break
                energy_rbv = self._get_float(self.pvs.get("energy_rb_pv"))
                if energy_rbv is not None and self.pvs.get("energy_units") == "keV":
                    energy_rbv *= 1000.0  # store readback in eV
                t_energy = time.time() - tE

                tZ = time.time()
                zp = self._set_zp_for_energy(e_eV)
                zp_rbv = self._rbv(self.pvs.get("zp_motor_pv")) or zp
                t_zp = time.time() - tZ

                # DATA
                tM = time.time()
                if self.scan.get("rot_data_deg") is not None:
                    self._move_motor(self.pvs["rot_pv"],
                                     self.scan["rot_data_deg"],
                                     self.params["motor_settle_s"])
                self._move_motor(self.pvs["topx_pv"], self.scan["topx_data_mm"],
                                 self.params["motor_settle_s"])
                self._move_motor(self.pvs["topz_pv"], self.scan["topz_data_mm"],
                                 self.params["motor_settle_s"])
                if self._stop:
                    break

                data_topx_rbv = self._rbv(self.pvs.get("topx_pv"))
                data_topz_rbv = self._rbv(self.pvs.get("topz_pv"))
                data_rot_rbv = self._rbv(self.pvs.get("rot_pv"))
                t_move_data = time.time() - tM

                tA = time.time()
                data_img = self._acquire_one()
                if data_img is None:
                    break
                t_acq_data = time.time() - tA

                tS = time.time()
                master.append_data(data_img)
                t_save_data = time.time() - tS

                if not instrument_snapshot_written:
                    snap = self._collect_instrument_snapshot(data_img.shape)
                    master.write_instrument_snapshot(snap)
                    instrument_snapshot_written = True

                # REF / FLAT
                tM2 = time.time()
                self._move_motor(self.pvs["topx_pv"], self.scan["topx_ref_mm"],
                                 self.params["motor_settle_s"])
                self._move_motor(self.pvs["topz_pv"], self.scan["topz_ref_mm"],
                                 self.params["motor_settle_s"])
                if self.scan.get("rot_ref_deg") is not None:
                    self._move_motor(self.pvs["rot_pv"],
                                     self.scan["rot_ref_deg"],
                                     self.params["motor_settle_s"])
                if self._stop:
                    break

                ref_topx_rbv = self._rbv(self.pvs.get("topx_pv"))
                ref_topz_rbv = self._rbv(self.pvs.get("topz_pv"))
                ref_rot_rbv = self._rbv(self.pvs.get("rot_pv"))
                t_move_ref = time.time() - tM2

                tA2 = time.time()
                flat_img = self._acquire_one()
                if flat_img is None:
                    break
                t_acq_flat = time.time() - tA2

                tS2 = time.time()
                master.append_flat(flat_img)
                master.append_meta(
                    e_eV, zp,
                    self.scan.get("rot_data_deg"),
                    self.scan.get("rot_ref_deg"),
                )
                master.append_step_readbacks({
                    "timestamp_epoch": time.time(),
                    "energy_rbv": energy_rbv,
                    "zp_rbv": zp_rbv,
                    "topx_data_rbv": data_topx_rbv,
                    "topz_data_rbv": data_topz_rbv,
                    "rot_data_rbv": data_rot_rbv,
                    "topx_ref_rbv": ref_topx_rbv,
                    "topz_ref_rbv": ref_topz_rbv,
                    "rot_ref_rbv": ref_rot_rbv,
                    "step_time_s": time.time() - t0,
                })
                master.flush()
                t_save_flat = time.time() - tS2

                # Return to data rotation for next step if we rotated for ref
                if (self.scan.get("rot_ref_deg") is not None
                        and self.scan.get("rot_data_deg") is not None):
                    self._move_motor(self.pvs["rot_pv"],
                                     self.scan["rot_data_deg"],
                                     self.params["motor_settle_s"])

                self.progress.emit(i, total)
                step_total = time.time() - t0
                self.log.emit(
                    f"    step {step_total:.2f}s  "
                    f"[E {t_energy:.2f} | ZP {t_zp:.2f} | "
                    f"mv {t_move_data:.2f}/{t_move_ref:.2f} | "
                    f"acq {t_acq_data:.2f}/{t_acq_flat:.2f} | "
                    f"save {t_save_data:.2f}/{t_save_flat:.2f}]"
                )

            master.set_end_time()
            master.close()
            self.done.emit(master_path)

        except Exception as ex:
            self.error.emit(f"Scan error: {ex}")


# ── GUI ──────────────────────────────────────────────────────────────────

class Xanes2DGui(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("XANES 2D / ZP focus calibration")
        self.resize(1500, 1100)

        self.settings_file = os.path.expanduser("~/.xanes_gui_2d_settings.json")
        self._worker = None

        self._apply_dark_theme()

        main = QWidget()
        self.setCentralWidget(main)
        lay = QVBoxLayout(main)
        lay.setContentsMargins(0, 0, 0, 0)

        self.tabs = QTabWidget()
        lay.addWidget(self.tabs)

        self._build_scan_tab()
        self._build_pv_tab()

        self._load_settings()

        # Pull ZP params from the TXM Optics Calculator's config file.
        self._reload_optics_config()

        # Pick up shared calibration curve directory from the 1-D GUI.
        self._refresh_shared_curve_settings()

        self.log("XANES 2D GUI ready.")

    # ── visuals ────────────────────────────────────────────────────────
    def _apply_dark_theme(self):
        pal = QPalette()
        pal.setColor(QPalette.Window, QColor(43, 43, 43))
        pal.setColor(QPalette.WindowText, Qt.white)
        pal.setColor(QPalette.Base, QColor(30, 30, 30))
        pal.setColor(QPalette.AlternateBase, QColor(43, 43, 43))
        pal.setColor(QPalette.ToolTipBase, Qt.white)
        pal.setColor(QPalette.ToolTipText, Qt.white)
        pal.setColor(QPalette.Text, Qt.white)
        pal.setColor(QPalette.Button, QColor(43, 43, 43))
        pal.setColor(QPalette.ButtonText, Qt.white)
        pal.setColor(QPalette.BrightText, Qt.red)
        pal.setColor(QPalette.Highlight, QColor(42, 130, 218))
        pal.setColor(QPalette.HighlightedText, Qt.black)
        self.setPalette(pal)

    # ── scan tab ───────────────────────────────────────────────────────
    def _build_scan_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)

        # scan-config side panel
        side = QWidget()
        sl = QVBoxLayout(side)
        sl.setContentsMargins(10, 10, 10, 10)

        # Energy range
        energy_box = QGroupBox("Energy range (eV)")
        elay = QVBoxLayout()
        row = QHBoxLayout()
        row.addWidget(QLabel("Start:"))
        self.e_start = QLineEdit("8000")
        row.addWidget(self.e_start)
        row.addWidget(QLabel("End:"))
        self.e_end = QLineEdit("8100")
        row.addWidget(self.e_end)
        row.addWidget(QLabel("Step:"))
        self.e_step = QLineEdit("10")
        row.addWidget(self.e_step)
        elay.addLayout(row)
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Mono offset (eV):"))
        self.mono_offset = QLineEdit(str(DEFAULTS["mono_offset_eV"]))
        row2.addWidget(self.mono_offset)
        row2.addStretch()
        elay.addLayout(row2)
        self.energy_info = QLabel("")
        self.energy_info.setStyleSheet("color: cyan;")
        elay.addWidget(self.energy_info)
        for w_edit in (self.e_start, self.e_end, self.e_step):
            w_edit.textChanged.connect(self._update_energy_info)
        energy_box.setLayout(elay)
        sl.addWidget(energy_box)
        self._update_energy_info()

        # Edge / XANES element — reads the same calibration-curve dir as the
        # 1-D xanes GUI so both tools share the same catalogue.
        edge_box = QGroupBox("Edge (K-edges 6–16 keV)")
        edl = QVBoxLayout()
        hpicker = QHBoxLayout()
        hpicker.addWidget(QLabel("Element:"))
        self.edge_combo = QComboBox()
        for el, E in K_EDGES_6_16_KEV:
            self.edge_combo.addItem(f"{el}   {E:.3f} keV", userData=(el, E))
        hpicker.addWidget(self.edge_combo)
        hpicker.addWidget(QLabel("± window (eV):"))
        self.edge_window = QLineEdit("100")
        self.edge_window.setMaximumWidth(80)
        hpicker.addWidget(self.edge_window)
        hpicker.addWidget(QLabel("Step (eV):"))
        self.edge_step = QLineEdit("2")
        self.edge_step.setMaximumWidth(60)
        hpicker.addWidget(self.edge_step)
        edl.addLayout(hpicker)

        btnrow = QHBoxLayout()
        self.btn_apply_edge = QPushButton("Apply to scan range")
        self.btn_apply_edge.clicked.connect(self._apply_edge_to_range)
        btnrow.addWidget(self.btn_apply_edge)
        self.btn_load_curve = QPushButton("Load calibrated curve")
        self.btn_load_curve.clicked.connect(self._load_calibrated_curve_for_element)
        btnrow.addWidget(self.btn_load_curve)
        edl.addLayout(btnrow)

        self.curve_dir_label = QLabel("curve dir: (shared from 1-D GUI)")
        self.curve_dir_label.setStyleSheet("color: #9ecae1; font-size: 9pt;")
        self.curve_dir_label.setWordWrap(True)
        edl.addWidget(self.curve_dir_label)

        edge_box.setLayout(edl)
        sl.addWidget(edge_box)

        # Zone plate — sourced from the TXM Optics Calculator's optics_config.json
        zp_box = QGroupBox("Zone plate  (from TXM Optics Calculator)")
        zl = QVBoxLayout()
        top = QHBoxLayout()
        top.addWidget(QLabel("ZP:"))
        self.zp_combo = QComboBox()
        self.zp_combo.currentIndexChanged.connect(self._on_zp_selection_changed)
        top.addWidget(self.zp_combo)
        self.btn_reload_optics = QPushButton("Reload optics_config")
        self.btn_reload_optics.clicked.connect(self._reload_optics_config)
        top.addWidget(self.btn_reload_optics)
        zl.addLayout(top)

        self.zp_info_label = QLabel("—")
        self.zp_info_label.setStyleSheet("color: #9ecae1; font-size: 9pt;")
        self.zp_info_label.setWordWrap(True)
        zl.addWidget(self.zp_info_label)

        # Editable override fields for Δrₙ_eff and ε — useful when
        # optics_config.json has no calibrated values yet.
        rov = QHBoxLayout()
        rov.addWidget(QLabel("Δrₙ eff (nm):"))
        self.zp_drn_override = QLineEdit()
        self.zp_drn_override.setMaximumWidth(80)
        self.zp_drn_override.setToolTip(
            "Override effective Δrₙ. Pre-filled from optics_config.")
        self.zp_drn_override.editingFinished.connect(self._update_zp_info_label)
        rov.addWidget(self.zp_drn_override)
        rov.addWidget(QLabel("ε (mm):"))
        self.zp_eps_override = QLineEdit()
        self.zp_eps_override.setMaximumWidth(80)
        self.zp_eps_override.setToolTip(
            "Override residual motor offset ε. Pre-filled from optics_config.")
        self.zp_eps_override.editingFinished.connect(self._update_zp_info_label)
        rov.addWidget(self.zp_eps_override)
        rov.addStretch()
        zl.addLayout(rov)

        r2 = QHBoxLayout()
        r2.addWidget(QLabel("Camera distance (mm):"))
        self.cam_dist = QLineEdit(str(DEFAULTS["camera_distance_mm"]))
        self.cam_dist.setToolTip("Pre-filled from optics_config user_parameters")
        r2.addWidget(self.cam_dist)
        r2.addStretch()
        zl.addLayout(r2)

        self.optics_src_label = QLabel("optics_config: not loaded")
        self.optics_src_label.setStyleSheet("color: #888; font-size: 8pt;")
        zl.addWidget(self.optics_src_label)
        zp_box.setLayout(zl)
        sl.addWidget(zp_box)

        # Internal storage for selected ZP params
        self._optics_config = None
        self._zp_params = {
            "zp_diameter_um": DEFAULTS["zp_diameter_um"],
            "zp_drn_nm": DEFAULTS["zp_drn_nm"],
            "zp_eps_mm": DEFAULTS["zp_eps_mm"],
        }

        # Sample positions
        pos_box = QGroupBox("Sample positions (mm, deg)")
        pl = QVBoxLayout()
        h1 = QHBoxLayout()
        h1.addWidget(QLabel("DATA topx:"))
        self.topx_data = QLineEdit("0.0")
        h1.addWidget(self.topx_data)
        h1.addWidget(QLabel("topz:"))
        self.topz_data = QLineEdit("0.0")
        h1.addWidget(self.topz_data)
        h1.addWidget(QLabel("rot:"))
        self.rot_data = QLineEdit("")
        self.rot_data.setPlaceholderText("blank = leave rot")
        h1.addWidget(self.rot_data)
        pl.addLayout(h1)
        h2 = QHBoxLayout()
        h2.addWidget(QLabel("REF  topx:"))
        self.topx_ref = QLineEdit("2.0")
        h2.addWidget(self.topx_ref)
        h2.addWidget(QLabel("topz:"))
        self.topz_ref = QLineEdit("0.0")
        h2.addWidget(self.topz_ref)
        h2.addWidget(QLabel("rot:"))
        self.rot_ref = QLineEdit("")
        self.rot_ref.setPlaceholderText("blank = leave rot")
        h2.addWidget(self.rot_ref)
        pl.addLayout(h2)
        pos_box.setLayout(pl)
        sl.addWidget(pos_box)

        # Acquisition
        acq_box = QGroupBox("Acquisition")
        al = QVBoxLayout()
        h = QHBoxLayout()
        h.addWidget(QLabel("Exposure (s):"))
        self.exposure = QLineEdit("1.0")
        h.addWidget(self.exposure)
        h.addWidget(QLabel("Motor settle (s):"))
        self.motor_settle = QLineEdit(str(DEFAULTS["motor_settle_s"]))
        h.addWidget(self.motor_settle)
        h.addWidget(QLabel("Post-E settle (s):"))
        self.post_energy_settle = QLineEdit(str(DEFAULTS["post_energy_settle_s"]))
        h.addWidget(self.post_energy_settle)
        al.addLayout(h)
        acq_box.setLayout(al)
        sl.addWidget(acq_box)

        # Output
        out_box = QGroupBox("Output master HDF5")
        ol = QVBoxLayout()
        hrow = QHBoxLayout()
        self.save_dir = QLineEdit(DEFAULTS["save_dir"])
        hrow.addWidget(self.save_dir)
        btn_browse = QPushButton("Browse…")
        btn_browse.clicked.connect(self._browse_save_dir)
        hrow.addWidget(btn_browse)
        ol.addLayout(hrow)
        hrow2 = QHBoxLayout()
        hrow2.addWidget(QLabel("File name:"))
        self.master_name = QLineEdit(DEFAULTS["master_h5_name"])
        hrow2.addWidget(self.master_name)
        ol.addLayout(hrow2)
        out_box.setLayout(ol)
        sl.addWidget(out_box)

        sl.addStretch()
        lay.addWidget(side, stretch=1)

        # Progress + buttons
        self.progress = QProgressBar()
        lay.addWidget(self.progress)

        btnrow = QHBoxLayout()
        self.btn_dry = QPushButton("Dry Run (plan)")
        self.btn_dry.setStyleSheet(
            "background-color: #6a6a6a; color: white; font-weight: bold; min-height: 40px;")
        self.btn_dry.clicked.connect(self._on_dry_run)
        btnrow.addWidget(self.btn_dry)

        self.btn_start = QPushButton("Start 2D scan")
        self.btn_start.setStyleSheet(
            "background-color: #32CD32; color: black; font-weight: bold; min-height: 40px;")
        self.btn_start.clicked.connect(self._on_start)
        btnrow.addWidget(self.btn_start)

        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setStyleSheet(
            "background-color: #FF3B30; color: white; font-weight: bold; min-height: 40px;")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._on_stop)
        btnrow.addWidget(self.btn_stop)

        lay.addLayout(btnrow)

        # Terminal
        trow = QHBoxLayout()
        trow.addWidget(QLabel("Terminal:"))
        trow.addStretch()
        btn_clear = QPushButton("Clear")
        btn_clear.setMaximumWidth(80)
        btn_clear.clicked.connect(lambda: self.log_text.clear())
        trow.addWidget(btn_clear)
        lay.addLayout(trow)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(220)
        self.log_text.setStyleSheet("""
            QTextEdit {
                background-color: #000000; color: #00ff00;
                font-family: 'Courier New', monospace; font-size: 10pt; padding: 5px;
            }
        """)
        lay.addWidget(self.log_text)

        self.tabs.addTab(w, "2D scan")

    # ── PV tab ─────────────────────────────────────────────────────────
    def _build_pv_tab(self):
        w = QWidget()
        outer = QVBoxLayout(w)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)

        self.pv_edits = {}
        pv_group = QGroupBox("EPICS / PVA configuration")
        gl = QVBoxLayout()
        for key, default in [
            ("detector_pv",         "Detector PVA PV"),
            ("cam_acquire_pv",      "cam:Acquire"),
            ("cam_acquire_rbv_pv",  "cam:Acquire_RBV"),
            ("cam_acquire_time_pv", "cam:AcquireTime"),
            ("cam_image_mode_pv",   "cam:ImageMode"),
            ("cam_num_images_pv",   "cam:NumImages"),
            ("energy_pv",           "Energy setpoint"),
            ("energy_set_pv",       "EnergySet button"),
            ("energy_rb_pv",        "Energy readback"),
            ("energy_units",        "Energy units (keV/eV)"),
            ("energy_tol",          "Energy readback tolerance"),
            ("zp_motor_pv",         "ZP motor"),
            ("topx_pv",             "Sample topx motor"),
            ("topz_pv",             "Sample topz motor"),
            ("rot_pv",              "Sample rotation motor"),
        ]:
            row = QHBoxLayout()
            lbl = QLabel(default + ":")
            lbl.setMinimumWidth(220)
            row.addWidget(lbl)
            le = QLineEdit(str(DEFAULTS[key]))
            row.addWidget(le)
            gl.addLayout(row)
            self.pv_edits[key] = le
        pv_group.setLayout(gl)
        layout.addWidget(pv_group)

        # Save/Load buttons
        btnrow = QHBoxLayout()
        b_save = QPushButton("Save settings")
        b_save.clicked.connect(self._save_settings_clicked)
        btnrow.addWidget(b_save)
        b_reload = QPushButton("Reload defaults")
        b_reload.clicked.connect(self._reload_defaults)
        btnrow.addWidget(b_reload)
        btnrow.addStretch()
        layout.addLayout(btnrow)
        layout.addStretch()

        scroll.setWidget(content)
        outer.addWidget(scroll)
        self.tabs.addTab(w, "PVs")

    # ── helpers ────────────────────────────────────────────────────────
    def log(self, msg):
        t = time.strftime("%H:%M:%S")
        self.log_text.append(f"[{t}] {msg}")

    def _browse_save_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Select output folder",
                                             self.save_dir.text() or os.path.expanduser("~"))
        if d:
            self.save_dir.setText(d)

    def _energies_eV(self):
        try:
            s = float(self.e_start.text())
            e = float(self.e_end.text())
            d = float(self.e_step.text())
        except ValueError:
            return []
        if d <= 0:
            return []
        out = []
        x = s
        while x <= e + 1e-6:
            out.append(round(x, 4))
            x += d
        return out

    def _update_energy_info(self):
        energies = self._energies_eV()
        if not energies:
            self.energy_info.setText("—")
            return
        self.energy_info.setText(
            f"{len(energies)} points, {energies[0]:.2f} → {energies[-1]:.2f} eV")

    def _read_opt_float(self, edit, fallback=None):
        t = edit.text().strip()
        if t == "":
            return fallback
        try:
            return float(t)
        except ValueError:
            return fallback

    def _gather_config(self):
        pvs = {k: self.pv_edits[k].text().strip() for k in self.pv_edits}
        pvs["energy_tol"] = float(pvs.get("energy_tol") or DEFAULTS["energy_tol"])
        scan = {
            "energies_eV": self._energies_eV(),
            "exposure_s": float(self.exposure.text()),
            "topx_data_mm": float(self.topx_data.text()),
            "topz_data_mm": float(self.topz_data.text()),
            "rot_data_deg": self._read_opt_float(self.rot_data, None),
            "topx_ref_mm": float(self.topx_ref.text()),
            "topz_ref_mm": float(self.topz_ref.text()),
            "rot_ref_deg": self._read_opt_float(self.rot_ref, None),
        }
        diameter, _drn_nominal, drn_eff, eps_mm, cal_points = self._current_zp_values()
        params = {
            "zp_name": self.zp_combo.currentText(),
            "zp_diameter_um": float(diameter),
            "zp_drn_nm":      float(drn_eff),
            "zp_eps_mm":      float(eps_mm),
            "zp_cal_points":  cal_points,
            "mono_offset_eV": float(self.mono_offset.text()),
            "camera_distance_mm": float(self.cam_dist.text()),
            "motor_settle_s": float(self.motor_settle.text()),
            "post_energy_settle_s": float(self.post_energy_settle.text()),
            "master_path": os.path.join(self.save_dir.text().strip(),
                                        self.master_name.text().strip()),
        }
        return pvs, scan, params

    # ── dry run ────────────────────────────────────────────────────────
    def _on_dry_run(self):
        try:
            pvs, scan, params = self._gather_config()
        except ValueError as ex:
            QMessageBox.warning(self, "Input error", f"Invalid field: {ex}")
            return

        energies = scan["energies_eV"]
        if not energies:
            self.log("No energies to scan.")
            return
        self.log("---- DRY RUN ----")
        self.log(f"Master file: {params['master_path']}")
        self.log(f"{len(energies)} energies, "
                 f"{energies[0]:.2f} → {energies[-1]:.2f} eV "
                 f"(step {scan['energies_eV'][1] - scan['energies_eV'][0] if len(energies) > 1 else 0:.2f} eV)")
        self.log(f"DATA pos: topx={scan['topx_data_mm']}, topz={scan['topz_data_mm']}, "
                 f"rot={scan['rot_data_deg']}")
        self.log(f"REF  pos: topx={scan['topx_ref_mm']}, topz={scan['topz_ref_mm']}, "
                 f"rot={scan['rot_ref_deg']}")
        cal = params.get("zp_cal_points")
        if cal:
            self.log(f"ZP position source: measured calibration ({len(cal)} points)")
        else:
            self.log("ZP position source: analytical (drn_eff + eps_mm)")
        for i, e in enumerate(energies, 1):
            if cal:
                s = zp_motor_from_cal(e, cal)
                if s is None:
                    self.log(f"  [{i}] E={e:.2f} eV  (invalid)")
                    continue
                self.log(f"  [{i}] E={e:.2f} eV  ZP={s:.4f} mm  [cal]")
                continue
            f = zp_focal_length_mm(e, params["zp_diameter_um"], params["zp_drn_nm"],
                                   params["mono_offset_eV"])
            if f is None:
                self.log(f"  [{i}] E={e:.2f} eV  (invalid)")
                continue
            L = params["camera_distance_mm"] + f
            s = zp_motor_position_mm(e, L, params["zp_diameter_um"], params["zp_drn_nm"],
                                     params["mono_offset_eV"], params["zp_eps_mm"])
            self.log(f"  [{i}] E={e:.2f} eV  f={f:.3f} mm  L={L:.3f} mm  ZP={s:.4f} mm")

    # ── start / stop ───────────────────────────────────────────────────
    def _on_start(self):
        try:
            pvs, scan, params = self._gather_config()
        except ValueError as ex:
            QMessageBox.warning(self, "Input error", f"Invalid field: {ex}")
            return
        if not scan["energies_eV"]:
            QMessageBox.warning(self, "Empty scan", "No energy points.")
            return
        os.makedirs(self.save_dir.text().strip(), exist_ok=True)

        self.progress.setMaximum(len(scan["energies_eV"]))
        self.progress.setValue(0)
        self.btn_start.setEnabled(False)
        self.btn_dry.setEnabled(False)
        self.btn_stop.setEnabled(True)

        self._worker = ScanWorker(pvs, scan, params)
        self._worker.progress.connect(self._on_progress)
        self._worker.log.connect(self.log)
        self._worker.error.connect(self._on_error)
        self._worker.done.connect(self._on_done)
        self._worker.start()

    def _on_stop(self):
        if self._worker and self._worker.isRunning():
            self._worker.stop()
            self.log("Stop requested…")

    def _on_progress(self, i, total):
        self.progress.setValue(i)

    def _on_error(self, msg):
        self.log(msg)
        QMessageBox.critical(self, "Scan error", msg)
        self._reset_buttons()

    def _on_done(self, master_path):
        self.log(f"Scan complete: {master_path}")
        self._reset_buttons()

    def _reset_buttons(self):
        self.btn_start.setEnabled(True)
        self.btn_dry.setEnabled(True)
        self.btn_stop.setEnabled(False)

    # ── settings ───────────────────────────────────────────────────────
    def _save_settings_clicked(self):
        self._save_settings(popup=True)

    def _save_settings(self, popup=False):
        data = {
            "pvs": {k: self.pv_edits[k].text() for k in self.pv_edits},
            "zp": {
                "zp_name": self.zp_combo.currentText(),
                "zp_drn_override": self.zp_drn_override.text(),
                "zp_eps_override": self.zp_eps_override.text(),
                "mono_offset_eV": self.mono_offset.text(),
                "camera_distance_mm": self.cam_dist.text(),
            },
            "scan": {
                "e_start": self.e_start.text(),
                "e_end": self.e_end.text(),
                "e_step": self.e_step.text(),
                "exposure": self.exposure.text(),
                "motor_settle": self.motor_settle.text(),
                "post_energy_settle": self.post_energy_settle.text(),
                "topx_data": self.topx_data.text(),
                "topz_data": self.topz_data.text(),
                "rot_data": self.rot_data.text(),
                "topx_ref": self.topx_ref.text(),
                "topz_ref": self.topz_ref.text(),
                "rot_ref": self.rot_ref.text(),
                "save_dir": self.save_dir.text(),
                "master_name": self.master_name.text(),
            },
        }
        try:
            with open(self.settings_file, "w") as fh:
                json.dump(data, fh, indent=2)
            self.log(f"Settings saved to {self.settings_file}")
            if popup:
                QMessageBox.information(self, "Saved",
                                        f"Settings saved to:\n{self.settings_file}")
        except Exception as ex:
            self.log(f"Error saving settings: {ex}")

    def _load_settings(self):
        if not os.path.exists(self.settings_file):
            return
        try:
            with open(self.settings_file) as fh:
                d = json.load(fh)
        except Exception as ex:
            self.log(f"Settings load failed: {ex}")
            return

        for k, edit in self.pv_edits.items():
            edit.setText(str(d.get("pvs", {}).get(k, DEFAULTS[k])))
        zp = d.get("zp", {})
        self._saved_zp_name = zp.get("zp_name")
        self._saved_zp_drn_override = zp.get("zp_drn_override")
        self._saved_zp_eps_override = zp.get("zp_eps_override")
        self.mono_offset.setText(zp.get("mono_offset_eV", self.mono_offset.text()))
        self.cam_dist.setText(zp.get("camera_distance_mm", self.cam_dist.text()))
        sc = d.get("scan", {})
        self.e_start.setText(sc.get("e_start", self.e_start.text()))
        self.e_end.setText(sc.get("e_end", self.e_end.text()))
        self.e_step.setText(sc.get("e_step", self.e_step.text()))
        self.exposure.setText(sc.get("exposure", self.exposure.text()))
        self.motor_settle.setText(sc.get("motor_settle", self.motor_settle.text()))
        self.post_energy_settle.setText(sc.get("post_energy_settle", self.post_energy_settle.text()))
        self.topx_data.setText(sc.get("topx_data", self.topx_data.text()))
        self.topz_data.setText(sc.get("topz_data", self.topz_data.text()))
        self.rot_data.setText(sc.get("rot_data", self.rot_data.text()))
        self.topx_ref.setText(sc.get("topx_ref", self.topx_ref.text()))
        self.topz_ref.setText(sc.get("topz_ref", self.topz_ref.text()))
        self.rot_ref.setText(sc.get("rot_ref", self.rot_ref.text()))
        self.save_dir.setText(sc.get("save_dir", self.save_dir.text()))
        self.master_name.setText(sc.get("master_name", self.master_name.text()))
        self.log(f"Settings loaded from {self.settings_file}")

    # ── optics_config (ZP params) ──────────────────────────────────────
    def _reload_optics_config(self):
        cfg = load_optics_config()
        self._optics_config = cfg
        path = find_optics_config_path()
        if cfg is None:
            self.optics_src_label.setText("optics_config: NOT FOUND "
                                          f"(looked in {len(OPTICS_CONFIG_PATHS)} locations)")
            self.log("optics_config.json not found — using default ZP params.")
            self.zp_combo.clear()
            return
        self.optics_src_label.setText(f"optics_config: {path}")

        zps = cfg.get("zone_plates", {})
        # Preserve current selection if possible
        current = self.zp_combo.currentText()
        self.zp_combo.blockSignals(True)
        self.zp_combo.clear()
        for name in zps.keys():
            self.zp_combo.addItem(name)
        saved = getattr(self, "_saved_zp_name", None)
        if saved and saved in zps:
            self.zp_combo.setCurrentText(saved)
        elif current and current in zps:
            self.zp_combo.setCurrentText(current)
        elif "30nm ZP" in zps:
            self.zp_combo.setCurrentText("30nm ZP")
        self.zp_combo.blockSignals(False)

        # Populate camera distance + mono offset from user_parameters
        up = cfg.get("user_parameters", {})
        cam = up.get("camera_distance")
        if cam is not None:
            self.cam_dist.setText(str(cam))
        shift = up.get("detector_energy_shift")
        if shift is not None:
            self.mono_offset.setText(str(shift))

        self._on_zp_selection_changed()
        self.log(f"Loaded optics_config from {path}  "
                 f"({len(zps)} zone plates)")

    def _on_zp_selection_changed(self):
        if self._optics_config is None:
            return
        name = self.zp_combo.currentText()
        zp = self._optics_config.get("zone_plates", {}).get(name)
        if not zp:
            return
        diameter = float(zp.get("diameter", DEFAULTS["zp_diameter_um"]))
        drn_nominal = float(zp.get("drn", DEFAULTS["zp_drn_nm"]))
        drn_eff = float(zp.get("drn_eff", drn_nominal))
        eps_mm = float(zp.get("eps_mm", 0.0))
        cal = zp.get("cal_points")
        cal_points = cal.get("points") if isinstance(cal, dict) else None
        self._zp_cached_nominal = {
            "zp_diameter_um": diameter,
            "drn_nominal": drn_nominal,
            "drn_eff_file": drn_eff,
            "eps_mm_file": eps_mm,
            "cal_points": cal_points,
        }
        # Respect a saved-settings override if present; otherwise take from file.
        saved_drn = getattr(self, "_saved_zp_drn_override", None)
        saved_eps = getattr(self, "_saved_zp_eps_override", None)
        self.zp_drn_override.blockSignals(True)
        self.zp_eps_override.blockSignals(True)
        self.zp_drn_override.setText(saved_drn if saved_drn not in (None, "")
                                     else f"{drn_eff:g}")
        self.zp_eps_override.setText(saved_eps if saved_eps not in (None, "")
                                     else f"{eps_mm:g}")
        self.zp_drn_override.blockSignals(False)
        self.zp_eps_override.blockSignals(False)
        # Consume the saved-override hint once applied
        self._saved_zp_drn_override = None
        self._saved_zp_eps_override = None
        self._update_zp_info_label()

    def _current_zp_values(self):
        """Resolve the effective ZP parameters: dropdown + inline overrides."""
        diameter = (self._zp_cached_nominal["zp_diameter_um"]
                    if hasattr(self, "_zp_cached_nominal")
                    else DEFAULTS["zp_diameter_um"])
        try:
            drn_eff = float(self.zp_drn_override.text())
        except (ValueError, AttributeError):
            drn_eff = (self._zp_cached_nominal["drn_eff_file"]
                       if hasattr(self, "_zp_cached_nominal")
                       else DEFAULTS["zp_drn_nm"])
        try:
            eps_mm = float(self.zp_eps_override.text())
        except (ValueError, AttributeError):
            eps_mm = (self._zp_cached_nominal["eps_mm_file"]
                      if hasattr(self, "_zp_cached_nominal")
                      else DEFAULTS["zp_eps_mm"])
        drn_nominal = (self._zp_cached_nominal["drn_nominal"]
                       if hasattr(self, "_zp_cached_nominal") else drn_eff)
        cal_points = (self._zp_cached_nominal.get("cal_points")
                      if hasattr(self, "_zp_cached_nominal") else None)
        return diameter, drn_nominal, drn_eff, eps_mm, cal_points

    def _update_zp_info_label(self):
        diameter, drn_nominal, drn_eff, eps_mm, _cal = self._current_zp_values()
        src_drn = "file"
        src_eps = "file"
        if hasattr(self, "_zp_cached_nominal"):
            if abs(drn_eff - self._zp_cached_nominal["drn_eff_file"]) > 1e-9:
                src_drn = "override"
            if abs(eps_mm - self._zp_cached_nominal["eps_mm_file"]) > 1e-9:
                src_eps = "override"
        self.zp_info_label.setText(
            f"D = {diameter:g} μm   Δrₙ nominal = {drn_nominal:g} nm   "
            f"Δrₙ eff = {drn_eff:g} nm [{src_drn}]   "
            f"ε = {eps_mm:+g} mm [{src_eps}]"
        )

    # ── shared calibration curve ───────────────────────────────────────
    def _refresh_shared_curve_settings(self):
        cal_dir, sim_dir, ext = load_shared_curve_settings()
        self._curve_dir_calibrated = cal_dir
        self._curve_dir_simulated = sim_dir
        self._curve_ext = ext or ".npy"
        txt = []
        if cal_dir:
            txt.append(f"calibrated: {cal_dir}")
        if sim_dir:
            txt.append(f"simulated: {sim_dir}")
        if not txt:
            txt.append("no shared curve dir set in 1-D GUI")
        self.curve_dir_label.setText("  |  ".join(txt))

    def _current_element_edge_keV(self):
        data = self.edge_combo.currentData()
        if data is None:
            return None, None
        return data  # (element, edge_keV)

    def _apply_edge_to_range(self):
        el, e_keV = self._current_element_edge_keV()
        if e_keV is None:
            return
        try:
            window = float(self.edge_window.text())
            step = float(self.edge_step.text())
        except ValueError:
            QMessageBox.warning(self, "Input error", "Window / step must be numeric.")
            return
        edge_eV = e_keV * 1000.0
        self.e_start.setText(f"{edge_eV - window:.2f}")
        self.e_end.setText(f"{edge_eV + window:.2f}")
        self.e_step.setText(f"{step:g}")
        self.log(f"Applied {el} K-edge ({edge_eV:.2f} eV) ± {window:g} eV, step {step:g} eV")

    def _load_calibrated_curve_for_element(self):
        el, _ = self._current_element_edge_keV()
        if el is None:
            return
        self._refresh_shared_curve_settings()
        if not self._curve_dir_calibrated:
            QMessageBox.information(
                self, "No shared curve dir",
                "Calibrated-curve directory is not set in the 1-D XANES GUI.\n"
                "Open the 1-D GUI and set 'curve_dir_calibrated' in its PV tab, "
                "then come back."
            )
            return
        ext = self._curve_ext or ".npy"
        candidate = os.path.join(self._curve_dir_calibrated, f"{el}{ext}")
        if not os.path.exists(candidate):
            QMessageBox.warning(self, "Curve not found",
                                f"No calibrated curve for {el} at:\n{candidate}")
            return
        try:
            E, Y = load_curve_file(candidate)
        except Exception as ex:
            QMessageBox.warning(self, "Load failed", f"Could not load {candidate}:\n{ex}")
            return
        self.log(f"Loaded {el} calibrated curve: {candidate} ({len(E)} points, "
                 f"{E.min():.3f}–{E.max():.3f} keV)")

    def _reload_defaults(self):
        for k, edit in self.pv_edits.items():
            edit.setText(str(DEFAULTS[k]))
        self.log("PV fields reset to defaults.")

    # ── close ──────────────────────────────────────────────────────────
    def closeEvent(self, event):
        try:
            self._save_settings(popup=False)
        except Exception:
            pass
        if self._worker and self._worker.isRunning():
            self._worker.stop()
            self._worker.wait(2000)
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setApplicationName("XANES 2D GUI")
    window = Xanes2DGui()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
