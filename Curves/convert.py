#!/usr/bin/env python3
import numpy as np
from pathlib import Path
import sys

# Folder containing the current .npy/.npz files
curves_dir = Path(sys.argv[1] if len(sys.argv) > 1 else str(Path.home() / "xanes_curves"))

def is_numeric_2d(arr):
    return isinstance(arr, np.ndarray) and arr.ndim == 2 and arr.dtype != object and (arr.shape[1] == 2 or arr.shape[0] == 2)

def to_numeric_2d_from_dict(d):
    # Try common keys from earlier generators
    if "energy_keV" in d:
        E_keV = np.asarray(d["energy_keV"], dtype=float)
    elif "energy_eV" in d:
        E_keV = np.asarray(d["energy_eV"], dtype=float) / 1000.0
    else:
        raise KeyError("No energy_keV or energy_eV in dict")

    # Prefer mass attenuation \u03bc/\u03c1; fall back to \u03bc if present
    if "mu_over_rho_cm2_per_g" in d:
        Y = np.asarray(d["mu_over_rho_cm2_per_g"], dtype=float)
    elif "mu_cm_inv" in d:
        Y = np.asarray(d["mu_cm_inv"], dtype=float)
    else:
        # Try generic second column name(s)
        for k in d:
            if k.lower() in ("mu", "mu_norm", "y"):
                Y = np.asarray(d[k], dtype=float)
                break
        else:
            raise KeyError("No curve series found (mu_over_rho_cm2_per_g / mu_cm_inv / mu / mu_norm / y)")

    # Ensure matching length
    n = min(E_keV.size, Y.size)
    return np.column_stack([E_keV[:n], Y[:n]])

def load_any(path):
    ext = path.suffix.lower()
    if ext == ".npy":
        # Try numeric; if object, allow_pickle then convert
        arr = np.load(path, allow_pickle=False)
        if is_numeric_2d(arr):
            return arr
        obj = np.load(path, allow_pickle=True)
        if hasattr(obj, "item"):
            d = obj.item()
            return to_numeric_2d_from_dict(d)
        raise ValueError(f"{path.name}: unsupported NPY shape/dtype")
    elif ext == ".npz":
        with np.load(path) as z:
            d = {k: z[k] for k in z.files}
        return to_numeric_2d_from_dict(d)
    else:
        raise ValueError("Unsupported file type")

def main():
    if not curves_dir.exists():
        print(f"Directory not found: {curves_dir}")
        sys.exit(1)

    for fn in sorted(curves_dir.glob("*.*")):
        if fn.suffix.lower() not in (".npy", ".npz"):
            continue
        try:
            arr = load_any(fn)
        except Exception as e:
            print(f"[skip] {fn.name}: {e}")
            continue

        # Ensure Nx2 (convert 2xN -> Nx2)
        if arr.shape[0] == 2 and arr.shape[1] != 2:
            arr = arr.T
        if not (arr.ndim == 2 and arr.shape[1] == 2):
            print(f"[skip] {fn.name}: not 2-column after conversion")
            continue

        # Determine target name: "Se.npy", "Fe.npy", etc.
        # Prefer embedded element name if present in filename; else keep base.
        base = fn.stem
        # If filename like "Se_K_norm", take the first token as element
        elem = base.split("_")[0]
        out = fn.with_name(f"{elem}.npy")

        np.save(out, arr.astype(np.float64))
        print(f"[ok] {fn.name} -> {out.name}  shape={arr.shape}, dtype={arr.dtype}")

if __name__ == "__main__":
    main()
