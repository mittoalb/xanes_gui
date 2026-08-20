"""Pure-Python core for xanes_gui — no PyQt5, no Qt event loop.

This module duplicates the business-logic pieces of `xanes_gui.gui` and
`xanes_gui.gui_2d` so they can be called from a CLI, a script, or an
AI-agent tool without spinning up a Qt application.

The GUIs themselves are UNCHANGED. Duplication is intentional here —
we're building alongside so nothing that already works breaks. Once
the CLI is validated in the wild, a follow-up patch can migrate the
GUIs to import from here.

Public surface (stable — the CLI depends on these):

    # Energy generation
    generate_energies_manual(start_keV, end_keV, step_eV) -> np.ndarray
    generate_energies_around_edge(element, half_width_eV, step_eV) -> np.ndarray
    load_energies_from_file(path) -> np.ndarray
    save_energies(path, energies) -> None

    # Absorption edges
    K_EDGES_6_16_KEV: list[tuple[str, float]]
    ELEMENT_TO_EDGE: dict[str, float]
    edge_of(element, series="K") -> float

    # Settings
    DEFAULTS: dict
    SETTINGS_FILE_3D    = "~/.xanes_gui_settings.json"
    SETTINGS_FILE_2D    = "~/.xanes_gui_2d_settings.json"
    load_settings(path=None, is_2d=False) -> dict
    save_settings(cfg, path=None, is_2d=False) -> None

    # 3D XANES — SSH-launched scan
    build_3d_launch_command(remote_config) -> list[str]
    run_3d_scan(remote_config, repeat_count=1, repeat_interval_s=0.0,
                on_log=print) -> int   # exit code of last iteration

    # 2D XANES — in-process scan  (imports gui_2d.ScanWorker on demand)
    run_2d_scan(pvs, scan, params, on_log=print, on_progress=None) -> str

    # QGMax interlock (via ~/.pystream/qgmax_request.json)
    write_qgmax_request(action, run_every=None) -> bool
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
from typing import Callable, Iterable, Optional

import numpy as np


# ── constants ───────────────────────────────────────────────────────────

DEFAULTS: dict = {
    "detector_pv":         "32idbSP1:Pva1:Image",
    "cam_acquire_pv":      "32idbSP1:cam1:Acquire",
    "cam_acquire_rbv_pv":  "32idbSP1:cam1:Acquire_RBV",
    "energy_pv":           "32id:TXMOptics:Energy",
    "energy_set_pv":       "32id:TXMOptics:EnergySet",
    "energy_rb_pv":        "32id:TXMOptics:Energy_RBV",
    "settle_s":            0.15,
    "xanes_start_pv":      "32id:TXMOptics:XanesStart",
    "xanes_end_pv":        "32id:TXMOptics:XanesEnd",
    "xanes_step_pv":       "32id:TXMOptics:XanesStep",
    "custom_energies_file": os.path.expanduser("~/energies.npy"),
    "fast_shutter_pv":     "32idbTXM:uniblitz:control",
    "remote_user":         "usertxm",
    "remote_host":         "gauss",
    "conda_env":           "tomoscan",
    "work_dir":            "/home/beams/USERTXM/epics/synApps/support/tomoscan/iocBoot/iocTomoScan_32ID/",
    "conda_path":          "/home/beams/USERTXM/conda/anaconda",
    "script_name":         "/home/beams/USERTXM/Software/xanes_gui/xanes_energy.py",
}

# K-edges approx. 6-16 keV. Mirrors gui.K_EDGES_6_16_KEV verbatim so
# calibration files + labels stay 1:1 between the CLI and the GUI.
K_EDGES_6_16_KEV: list[tuple[str, float]] = [
    ("Mn",  6.539), ("Fe",  7.112), ("Co",  7.709), ("Ni",  8.333),
    ("Cu",  8.979), ("Zn",  9.659), ("Ga", 10.367), ("Ge", 11.103),
    ("Pt", 11.564), ("As", 11.867), ("Se", 12.658), ("Br", 13.474),
    ("Kr", 14.327), ("Rb", 15.200), ("Sr", 16.105),
]
ELEMENT_TO_EDGE: dict[str, float] = {el: e for el, e in K_EDGES_6_16_KEV}

SETTINGS_FILE_3D = os.path.expanduser("~/.xanes_gui_settings.json")
SETTINGS_FILE_2D = os.path.expanduser("~/.xanes_gui_2d_settings.json")

QGMAX_REQUEST_FILE  = os.path.expanduser("~/.pystream/qgmax_request.json")
QGMAX_RESPONSE_FILE = os.path.expanduser("~/.pystream/qgmax_response.json")


# ── energy generation (mirrors gui.get_energy_array) ────────────────────

def generate_energies_manual(start_keV: float, end_keV: float,
                              step_eV: float) -> np.ndarray:
    """Linear scan from start to end (inclusive), stepping in eV.
    Matches `gui.get_energy_array` manual branch."""
    if step_eV <= 0:
        raise ValueError("step_eV must be > 0")
    if end_keV <= start_keV:
        raise ValueError("end_keV must be greater than start_keV")
    npts = int((end_keV * 1000 - start_keV * 1000) / step_eV) + 1
    if npts <= 1:
        raise ValueError("Number of points must be > 1 "
                         "(check start/end/step)")
    return np.linspace(float(start_keV), float(end_keV), npts)


def generate_energies_around_edge(element: str, half_width_eV: float,
                                   step_eV: float) -> np.ndarray:
    """Scan symmetric around an element's K-edge.
    ± `half_width_eV` at `step_eV` spacing."""
    if element not in ELEMENT_TO_EDGE:
        raise ValueError(f"Unknown element {element!r}. "
                         f"Available: {sorted(ELEMENT_TO_EDGE)}")
    if step_eV <= 0:
        raise ValueError("step_eV must be > 0")
    if half_width_eV <= 0:
        raise ValueError("half_width_eV must be > 0")
    edge_keV = ELEMENT_TO_EDGE[element]
    start = edge_keV - half_width_eV / 1000.0
    end   = edge_keV + half_width_eV / 1000.0
    return generate_energies_manual(start, end, step_eV)


def load_energies_from_file(path: str) -> np.ndarray:
    """Load energies (one per line or npy/csv). Same tolerant loader
    as gui.load_custom_energies."""
    path = os.path.expanduser(path)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"energies file not found: {path}")
    if path.endswith(".npy"):
        arr = np.load(path)
    else:
        arr = np.loadtxt(path)
    if arr.ndim == 2 and arr.shape[1] >= 1:
        arr = arr[:, 0]
    arr = np.asarray(arr, dtype=float).flatten()
    if arr.size == 0:
        raise ValueError("No energy values found in file")
    return arr


def save_energies(path: str, energies: Iterable[float]) -> None:
    """Save energies as an npy (default) or newline-separated text
    file. `path`'s extension picks the format."""
    path = os.path.expanduser(path)
    arr = np.asarray(list(energies), dtype=float)
    if path.endswith(".npy"):
        np.save(path, arr)
    else:
        np.savetxt(path, arr, fmt="%.6f")


def edge_of(element: str, series: str = "K") -> float:
    """Return the absorption-edge energy in keV. Series is currently
    only "K" — the module's built-in table is K-edges in 6-16 keV."""
    if series.upper() != "K":
        raise ValueError(f"series {series!r} not supported yet — only 'K'")
    if element not in ELEMENT_TO_EDGE:
        raise ValueError(f"Unknown element {element!r}. "
                         f"Available: {sorted(ELEMENT_TO_EDGE)}")
    return ELEMENT_TO_EDGE[element]


# ── settings JSON ───────────────────────────────────────────────────────

def _settings_path(is_2d: bool, override: Optional[str]) -> str:
    return override or (SETTINGS_FILE_2D if is_2d else SETTINGS_FILE_3D)


def load_settings(path: Optional[str] = None, is_2d: bool = False) -> dict:
    """Load a settings JSON (3D or 2D). Returns {} on missing / corrupt."""
    p = _settings_path(is_2d, path)
    try:
        with open(p) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_settings(cfg: dict, path: Optional[str] = None,
                   is_2d: bool = False) -> None:
    """Write a settings JSON atomically."""
    p = _settings_path(is_2d, path)
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    tmp = p + f".tmp.{os.getpid()}"
    with open(tmp, "w") as f:
        json.dump(cfg, f, indent=2, sort_keys=True)
    os.replace(tmp, p)


# ── QGMax interlock ─────────────────────────────────────────────────────

def write_qgmax_request(action: str, run_every: Optional[int] = None) -> bool:
    """Write a request to `~/.pystream/qgmax_request.json` that
    pystream's QGMax plugin will pick up on its background watcher.

    `action` ∈ {"auto_enable", "auto_disable", "run_once"}.
    `run_every` (int ≥ 1) for auto_enable: run QGMax on every N-th
    tomoscan HDF5-location event. Ignored for other actions.

    Returns True on write success. Best-effort — no-op if pystream
    isn't installed / the directory can't be created."""
    try:
        os.makedirs(os.path.dirname(QGMAX_REQUEST_FILE), exist_ok=True)
        payload = {"action": action, "ts": time.time()}
        if action == "auto_enable" and run_every is not None:
            payload["run_every"] = int(run_every)
        with open(QGMAX_REQUEST_FILE, "w") as f:
            json.dump(payload, f)
        return True
    except OSError:
        return False


# ── 3D XANES — SSH-launched scan (mirrors StartScriptWorker) ────────────

def build_3d_launch_command(remote_config: dict) -> list[str]:
    """Build the shell command list that launches `xanes_energy.py`
    on the target host. Auto-detects local-vs-SSH by comparing the
    current host name with `remote_host` (and checking that
    `script_name` exists on the local FS as a further hint).

    Returns something like:
      Local:  ["bash","-l","-c", "cd WORK && source conda.sh && conda activate ENV && python SCRIPT"]
      SSH:    ["ssh","-t","USER@HOST", "bash -l -c \"cd WORK && ...\""]

    Kept 1:1 with gui.StartScriptWorker._build_cmd so the GUI + CLI
    reach `xanes_energy.py` the same way."""
    r = dict(DEFAULTS)  # fill missing keys with sensible defaults
    r.update(remote_config or {})

    remote_user  = r["remote_user"]
    remote_host  = r["remote_host"]
    conda_env    = r["conda_env"]
    work_dir     = r["work_dir"]
    conda_path   = r["conda_path"]
    script_name  = r["script_name"]

    current_host = socket.gethostname()
    current_short = current_host.split(".")[0]
    is_local = (
        current_host == remote_host or
        current_short == remote_host or
        remote_host in ("localhost", "127.0.0.1", "") or
        os.path.exists(script_name)
    )

    inner = (f"cd {work_dir} && "
             f"source {conda_path}/etc/profile.d/conda.sh && "
             f"conda activate {conda_env} && "
             f"python {script_name}")

    if is_local:
        return ["bash", "-l", "-c", inner]
    return ["ssh", "-t", f"{remote_user}@{remote_host}",
            f"bash -l -c \"cd {work_dir} && hostname && "
            f"source {conda_path}/etc/profile.d/conda.sh && "
            f"conda activate {conda_env} && python {script_name}\""]


def run_3d_scan(remote_config: dict,
                 repeat_count: int = 1,
                 repeat_interval_s: float = 0.0,
                 on_log: Callable[[str], None] = print,
                 stop_flag: Optional[Callable[[], bool]] = None) -> int:
    """Run one or more iterations of the 3D XANES scan. Blocks until
    the last iteration exits or `stop_flag()` returns True.

    `on_log` receives every stdout line from the remote script (or
    a status line from this function). `stop_flag` is a zero-arg
    callable returning True to abort — polled between iterations
    and between stdout reads.

    Returns the exit code of the LAST iteration (0 = success).
    Same semantics as `StartScriptWorker.run` in the GUI."""
    repeat_count = max(1, int(repeat_count or 1))
    repeat_interval_s = max(0.0, float(repeat_interval_s or 0.0))
    last_rc = -1

    def _stop() -> bool:
        return bool(stop_flag()) if stop_flag else False

    for i in range(1, repeat_count + 1):
        if _stop():
            on_log(f"Stop requested — aborting before iteration {i}")
            return last_rc
        if repeat_count > 1:
            on_log(f"--- iteration {i} / {repeat_count} ---")

        iter_start = time.time()
        cmd = build_3d_launch_command(remote_config)
        on_log(f"Executing: {' '.join(cmd)}")

        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, preexec_fn=os.setsid,
        )
        pgid = os.getpgid(proc.pid)
        try:
            for line in proc.stdout:
                if _stop():
                    on_log("Stop requested — sending SIGTERM to script")
                    try:
                        os.killpg(pgid, signal.SIGTERM)
                    except OSError:
                        pass
                    break
                on_log(line.rstrip())
            last_rc = proc.wait()
        except KeyboardInterrupt:
            try:
                os.killpg(pgid, signal.SIGTERM)
            except OSError:
                pass
            proc.wait()
            on_log("Interrupted by user (SIGINT)")
            return 130
        if last_rc == 0:
            on_log(f"iteration {i} complete (rc={last_rc})")
        else:
            on_log(f"iteration {i} exited with rc={last_rc}")

        # Wait until next scan starts (start-to-start interval)
        if i < repeat_count:
            deadline = iter_start + repeat_interval_s
            now = time.time()
            if now < deadline:
                remaining = deadline - now
                on_log(f"Waiting {remaining:.1f}s until next iteration…")
                while not _stop() and time.time() < deadline:
                    time.sleep(min(0.5, max(0.0, deadline - time.time())))
    return last_rc


# ── 2D XANES — in-process scan (leverages ScanWorker without QApplication) ──

def run_2d_scan(pvs: dict,
                 scan: dict,
                 params: dict,
                 on_log: Callable[[str], None] = print,
                 on_progress: Optional[Callable[[int, int], None]] = None,
                 stop_flag: Optional[Callable[[], bool]] = None) -> str:
    """Run a 2D XANES scan headlessly by calling `gui_2d.ScanWorker.run`
    directly (NOT `.start()` — no QThread, no event loop). Signals are
    connected with DirectConnection so callbacks fire in-thread.

    Returns the final master HDF5 path on success, raises RuntimeError
    on failure. Same semantics as the GUI's Start button.

    Note: needs a `QCoreApplication` instance so pyqtSignals work — one
    is created if absent. No widgets are shown."""
    from PyQt5.QtCore import QCoreApplication, Qt
    if QCoreApplication.instance() is None:
        # Bare argv so QCoreApplication doesn't grab argv[1:]
        _app = QCoreApplication(sys.argv[:1])
    from .gui_2d import ScanWorker  # local import — pulls in Qt only if used

    worker = ScanWorker(pvs, scan, params)
    result: dict = {"path": None, "error": None}

    def _on_log(msg: str):    on_log(msg)
    def _on_prog(i, t):
        if on_progress: on_progress(i, t)
    def _on_error(msg: str):  result["error"] = msg
    def _on_done(path: str):  result["path"] = path

    worker.log.connect(_on_log, Qt.DirectConnection)
    worker.progress.connect(_on_prog, Qt.DirectConnection)
    worker.error.connect(_on_error, Qt.DirectConnection)
    worker.done.connect(_on_done, Qt.DirectConnection)

    # Stop-flag polling: patch worker's _stop_requested attribute if
    # present, else no-op (worker won't be interruptible from here).
    if stop_flag is not None and hasattr(worker, "_stop_requested"):
        import threading
        def _poll():
            while not result["path"] and not result["error"]:
                if stop_flag():
                    worker._stop_requested = True
                    return
                time.sleep(0.5)
        threading.Thread(target=_poll, daemon=True).start()

    # Run inline. `run()` is a plain method — QThread's .start() would
    # move it to a new OS thread; we don't need that.
    worker.run()

    if result["error"]:
        raise RuntimeError(result["error"])
    if result["path"] is None:
        raise RuntimeError("Scan finished without emitting done — check log")
    return result["path"]
