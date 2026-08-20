"""Headless CLI for xanes_gui.

Usage::

    xanes-cli status --json
    xanes-cli config show [--is-2d] [--json]
    xanes-cli config set KEY VALUE [--is-2d]

    xanes-cli energies manual --start-keV 8.9 --end-keV 9.1 --step-eV 2 [--json]
    xanes-cli energies edge   --element Cu --half-width-eV 100 --step-eV 2 [--json]
    xanes-cli energies from-file PATH [--json]
    xanes-cli energies save PATH   ...       (same energy flags; writes .npy or .txt)

    xanes-cli edge get ELEMENT [--json]

    xanes-cli 3d dry-run [--config PATH] [--json]
    xanes-cli 3d start   [--config PATH] [--repeat N] [--interval-min M]
                          [--qgmax-every N] [--json]

    xanes-cli 2d dry-run [--config PATH] [--json]
    xanes-cli 2d start   [--config PATH] [--json]

Every read-style subcommand accepts `--json` for machine-parseable
output. Every action subcommand exits non-zero on failure with the
error on stderr. Design + shape mirrors tomogui's `tomogui-cli`.

Never opens a GUI. Every operation uses the pure-python core in
`xanes_gui.headless`; a Qt event loop is only spun up transiently
by `2d start` (needed so pyqtSignals from ScanWorker fire).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Optional

from . import headless as H


# ── output helpers ─────────────────────────────────────────────────────

def _emit(obj, as_json: bool) -> None:
    if as_json:
        print(json.dumps(obj, indent=2, default=str))
    else:
        if isinstance(obj, (dict, list)):
            print(json.dumps(obj, indent=2, default=str))
        else:
            print(obj)


def _die(msg: str, code: int = 2) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


# ── subcommand: status ─────────────────────────────────────────────────

def cmd_status(args) -> int:
    settings_3d = H.load_settings(is_2d=False)
    settings_2d = H.load_settings(is_2d=True)
    info = {
        "settings_3d_file":     H.SETTINGS_FILE_3D,
        "settings_3d_present":  bool(settings_3d),
        "settings_3d_keys":     sorted(settings_3d.keys()),
        "settings_2d_file":     H.SETTINGS_FILE_2D,
        "settings_2d_present":  bool(settings_2d),
        "settings_2d_keys":     sorted(settings_2d.keys()),
        "custom_energies_file": H.DEFAULTS["custom_energies_file"],
        "custom_energies_present": os.path.isfile(H.DEFAULTS["custom_energies_file"]),
        "qgmax_request_file":   H.QGMAX_REQUEST_FILE,
        "qgmax_request_present": os.path.isfile(H.QGMAX_REQUEST_FILE),
        "known_elements":       [el for el, _ in H.K_EDGES_6_16_KEV],
    }
    _emit(info, args.json)
    return 0


# ── subcommand: config ─────────────────────────────────────────────────

def cmd_config_show(args) -> int:
    cfg = H.load_settings(is_2d=args.is_2d)
    _emit(cfg, args.json)
    return 0


def cmd_config_set(args) -> int:
    cfg = H.load_settings(is_2d=args.is_2d)
    # Try to parse VALUE as JSON (number, bool, list); fall back to raw string.
    try:
        v = json.loads(args.value)
    except json.JSONDecodeError:
        v = args.value
    cfg[args.key] = v
    H.save_settings(cfg, is_2d=args.is_2d)
    _emit({"ok": True, "key": args.key, "value": v,
           "file": H.SETTINGS_FILE_2D if args.is_2d else H.SETTINGS_FILE_3D},
          args.json)
    return 0


# ── subcommand: energies ───────────────────────────────────────────────

def _energies_from_args(args) -> "np.ndarray":
    if args.energies_cmd == "manual":
        return H.generate_energies_manual(args.start_keV, args.end_keV, args.step_eV)
    if args.energies_cmd == "edge":
        return H.generate_energies_around_edge(args.element, args.half_width_eV, args.step_eV)
    if args.energies_cmd == "from-file":
        return H.load_energies_from_file(args.path)
    raise ValueError(f"unknown energies subcommand: {args.energies_cmd!r}")


def cmd_energies(args) -> int:
    try:
        energies = _energies_from_args(args)
    except (ValueError, FileNotFoundError) as ex:
        _die(str(ex), code=1)
    payload = {
        "n_points": int(len(energies)),
        "start_keV": float(energies[0]),
        "end_keV":   float(energies[-1]),
        "energies_keV": [float(e) for e in energies],
    }
    _emit(payload, args.json)
    return 0


def cmd_energies_save(args) -> int:
    try:
        energies = _energies_from_args(args)
    except (ValueError, FileNotFoundError) as ex:
        _die(str(ex), code=1)
    H.save_energies(args.out, energies)
    _emit({"ok": True, "path": os.path.abspath(args.out),
           "n_points": len(energies),
           "range_keV": [float(energies[0]), float(energies[-1])]},
          args.json)
    return 0


# ── subcommand: edge ───────────────────────────────────────────────────

def cmd_edge_get(args) -> int:
    try:
        e = H.edge_of(args.element)
    except ValueError as ex:
        _die(str(ex), code=1)
    _emit({"element": args.element, "edge_keV": e, "edge_eV": e * 1000.0},
          args.json)
    return 0


# ── subcommand: 3d ─────────────────────────────────────────────────────

def _load_3d_config(config_path: Optional[str]) -> dict:
    """Fold user settings on top of DEFAULTS. Explicit `--config` path
    wins; else use `~/.xanes_gui_settings.json`."""
    r = dict(H.DEFAULTS)
    r.update(H.load_settings(config_path, is_2d=False))
    return r


def cmd_3d_dry_run(args) -> int:
    r = _load_3d_config(args.config)
    cmd = H.build_3d_launch_command(r)
    _emit({"command":       cmd,
           "would_run_via": "ssh" if cmd[0] == "ssh" else "local",
           "remote_host":   r.get("remote_host"),
           "conda_env":     r.get("conda_env"),
           "script_name":   r.get("script_name"),
           "repeat_count":  int(args.repeat),
           "interval_s":    args.interval_min * 60.0},
          args.json)
    return 0


def cmd_3d_start(args) -> int:
    r = _load_3d_config(args.config)
    # Optional QGMax enable
    if args.qgmax_every and args.qgmax_every > 0:
        H.write_qgmax_request("auto_enable", run_every=args.qgmax_every)
        print(f"[qgmax] auto_enable run_every={args.qgmax_every} → "
              f"{H.QGMAX_REQUEST_FILE}", file=sys.stderr)
    try:
        rc = H.run_3d_scan(
            r,
            repeat_count=args.repeat,
            repeat_interval_s=args.interval_min * 60.0,
        )
    finally:
        if args.qgmax_every and args.qgmax_every > 0:
            H.write_qgmax_request("auto_disable")
            print("[qgmax] auto_disable", file=sys.stderr)
    _emit({"ok": rc == 0, "exit_code": rc,
           "iterations": int(args.repeat)}, args.json)
    return 0 if rc == 0 else rc


# ── subcommand: 2d ─────────────────────────────────────────────────────

def _load_2d_config(config_path: Optional[str]) -> dict:
    """The 2D config format is nested: {pvs: {...}, scan: {...}, params: {...}}.
    Returns the loaded dict (empty if the file's missing)."""
    return H.load_settings(config_path, is_2d=True)


def cmd_2d_dry_run(args) -> int:
    cfg = _load_2d_config(args.config)
    pvs    = cfg.get("pvs", {})
    scan   = cfg.get("scan", {})
    params = cfg.get("params", {})
    # 2D expects `scan.energies_eV` as a list of eV floats. Some GUI
    # versions store per-field pieces; the CLI just echoes what's in
    # the file so the user can see what a `start` would run.
    _emit({"pvs":     pvs,
           "scan":    scan,
           "params":  params,
           "n_energies": len(scan.get("energies_eV", []))
                          if "energies_eV" in scan else None,
           "would_write_to": params.get("save_dir")},
          args.json)
    return 0


def cmd_2d_start(args) -> int:
    cfg = _load_2d_config(args.config)
    pvs    = cfg.get("pvs")
    scan   = cfg.get("scan")
    params = cfg.get("params")
    if not (pvs and scan and params):
        _die("2D config is incomplete (need pvs/scan/params). "
             f"Load / edit {H.SETTINGS_FILE_2D} in the 2D GUI first.",
             code=1)
    try:
        master_path = H.run_2d_scan(pvs, scan, params)
    except RuntimeError as ex:
        _die(str(ex), code=1)
    _emit({"ok": True, "master_path": master_path}, args.json)
    return 0


# ── parser ─────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="xanes-cli",
        description="Headless driver for the xanes_gui 3D + 2D scans.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    # status
    s = sub.add_parser("status", help="Show current config file locations + presence")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_status)

    # config
    cfg = sub.add_parser("config", help="Read / write settings JSON")
    cfg_sub = cfg.add_subparsers(dest="config_cmd", required=True)

    cs = cfg_sub.add_parser("show", help="Print settings")
    cs.add_argument("--is-2d", action="store_true", help="Use 2D settings file")
    cs.add_argument("--json", action="store_true")
    cs.set_defaults(func=cmd_config_show)

    cst = cfg_sub.add_parser("set", help="Set one settings field")
    cst.add_argument("key")
    cst.add_argument("value", help="JSON literal (e.g. 4, true, \"gauss\") or plain string")
    cst.add_argument("--is-2d", action="store_true")
    cst.add_argument("--json", action="store_true")
    cst.set_defaults(func=cmd_config_set)

    # energies
    e = sub.add_parser("energies", help="Generate an energy array")
    e_sub = e.add_subparsers(dest="energies_cmd", required=True)

    em = e_sub.add_parser("manual", help="linspace between start/end at step (eV)")
    em.add_argument("--start-keV", type=float, required=True)
    em.add_argument("--end-keV", type=float, required=True)
    em.add_argument("--step-eV", type=float, required=True)
    em.add_argument("--json", action="store_true")
    em.set_defaults(func=cmd_energies)

    eg = e_sub.add_parser("edge", help="±half-width around an element's K-edge")
    eg.add_argument("--element", required=True,
                    help="Element symbol (e.g. Cu, Fe, Zn) — see `xanes-cli status --json`")
    eg.add_argument("--half-width-eV", type=float, required=True)
    eg.add_argument("--step-eV", type=float, required=True)
    eg.add_argument("--json", action="store_true")
    eg.set_defaults(func=cmd_energies)

    ef = e_sub.add_parser("from-file", help="Load from .npy / .csv / text file")
    ef.add_argument("path")
    ef.add_argument("--json", action="store_true")
    ef.set_defaults(func=cmd_energies)

    es = e_sub.add_parser("save", help="Same generation options + write to disk")
    es.add_argument("out")
    es_method = es.add_subparsers(dest="save_method", required=True)
    for sub_p in (
        es_method.add_parser("manual"), es_method.add_parser("edge"),
        es_method.add_parser("from-file"),
    ):
        pass  # arguments added per-branch below
    # Reuse identical arg definitions for each save subbranch — argparse
    # requires this awkward re-add because each subparser has its own
    # arg namespace. Keeps the CLI predictable.
    for sp in es_method.choices.values():
        pass
    # Simpler in practice: skip nesting under `save`; instead, the user
    # calls `xanes-cli energies save FILE manual --start-keV ...` style
    # via three add_arguments per branch. For MVP, only manual+edge:
    es_method.choices["manual"].add_argument("--start-keV", type=float, required=True)
    es_method.choices["manual"].add_argument("--end-keV", type=float, required=True)
    es_method.choices["manual"].add_argument("--step-eV", type=float, required=True)
    es_method.choices["manual"].add_argument("--json", action="store_true")
    es_method.choices["manual"].set_defaults(func=cmd_energies_save,
                                             energies_cmd="manual")
    es_method.choices["edge"].add_argument("--element", required=True)
    es_method.choices["edge"].add_argument("--half-width-eV", type=float, required=True)
    es_method.choices["edge"].add_argument("--step-eV", type=float, required=True)
    es_method.choices["edge"].add_argument("--json", action="store_true")
    es_method.choices["edge"].set_defaults(func=cmd_energies_save,
                                           energies_cmd="edge")
    es_method.choices["from-file"].add_argument("path")
    es_method.choices["from-file"].add_argument("--json", action="store_true")
    es_method.choices["from-file"].set_defaults(func=cmd_energies_save,
                                                 energies_cmd="from-file")

    # edge
    ed = sub.add_parser("edge", help="Absorption-edge lookup")
    ed_sub = ed.add_subparsers(dest="edge_cmd", required=True)
    edg = ed_sub.add_parser("get", help="Get the K-edge for one element")
    edg.add_argument("element")
    edg.add_argument("--json", action="store_true")
    edg.set_defaults(func=cmd_edge_get)

    # 3d
    d3 = sub.add_parser("3d", help="3D XANES (SSH-launched tomoscan-driver)")
    d3_sub = d3.add_subparsers(dest="d3_cmd", required=True)

    d3dry = d3_sub.add_parser("dry-run", help="Print the SSH command that would run")
    d3dry.add_argument("--config", default=None,
                       help="Path to a settings JSON (default: ~/.xanes_gui_settings.json)")
    d3dry.add_argument("--repeat", type=int, default=1)
    d3dry.add_argument("--interval-min", type=float, default=0.0)
    d3dry.add_argument("--json", action="store_true")
    d3dry.set_defaults(func=cmd_3d_dry_run)

    d3run = d3_sub.add_parser("start", help="Actually launch the 3D scan")
    d3run.add_argument("--config", default=None)
    d3run.add_argument("--repeat", type=int, default=1)
    d3run.add_argument("--interval-min", type=float, default=0.0)
    d3run.add_argument("--qgmax-every", type=int, default=0,
                       help="Enable QGMax auto-mode every N tomoscans (0 = off)")
    d3run.add_argument("--json", action="store_true")
    d3run.set_defaults(func=cmd_3d_start)

    # 2d
    d2 = sub.add_parser("2d", help="2D XANES (in-process scan)")
    d2_sub = d2.add_subparsers(dest="d2_cmd", required=True)

    d2dry = d2_sub.add_parser("dry-run", help="Echo the loaded 2D config")
    d2dry.add_argument("--config", default=None)
    d2dry.add_argument("--json", action="store_true")
    d2dry.set_defaults(func=cmd_2d_dry_run)

    d2run = d2_sub.add_parser("start", help="Run the 2D XANES scan headlessly")
    d2run.add_argument("--config", default=None)
    d2run.add_argument("--json", action="store_true")
    d2run.set_defaults(func=cmd_2d_start)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
