#!/usr/bin/env python3
"""
Generate X-ray attenuation curves with xraylib for 6–16 keV and save to .npy.

Usage examples:
  python make_xraylib_curves.py -Z Fe,Co,Ni,Cu,Zn
  python make_xraylib_curves.py -Z 26,27,28 --outdir curves_xraylib
"""

import argparse, os, pathlib
import numpy as np

try:
    import xraylib
except ImportError as e:
    raise SystemExit(
        "xraylib is required. Install with:\n  pip install xraylib"
    )

Z2SYM = {
    1:"H",2:"He",3:"Li",4:"Be",5:"B",6:"C",7:"N",8:"O",9:"F",10:"Ne",
    11:"Na",12:"Mg",13:"Al",14:"Si",15:"P",16:"S",17:"Cl",18:"Ar",19:"K",20:"Ca",
    21:"Sc",22:"Ti",23:"V",24:"Cr",25:"Mn",26:"Fe",27:"Co",28:"Ni",29:"Cu",30:"Zn",
    31:"Ga",32:"Ge",33:"As",34:"Se",35:"Br",36:"Kr",37:"Rb",38:"Sr",39:"Y",40:"Zr",
    41:"Nb",42:"Mo",43:"Tc",44:"Ru",45:"Rh",46:"Pd",47:"Ag",48:"Cd",49:"In",50:"Sn",
    51:"Sb",52:"Te",53:"I",54:"Xe",55:"Cs",56:"Ba",57:"La",58:"Ce",59:"Pr",60:"Nd",
    61:"Pm",62:"Sm",63:"Eu",64:"Gd",65:"Tb",66:"Dy",67:"Ho",68:"Er",69:"Tm",70:"Yb",
    71:"Lu",72:"Hf",73:"Ta",74:"W",75:"Re",76:"Os",77:"Ir",78:"Pt",79:"Au",80:"Hg",
    81:"Tl",82:"Pb",83:"Bi",84:"Po",85:"At",86:"Rn",87:"Fr",88:"Ra",89:"Ac",90:"Th",
    91:"Pa",92:"U"
}

def coerce_symbols(arg: str):
    items = []
    for tok in (arg or "").split(","):
        s = tok.strip()
        if not s: 
            continue
        if s.isdigit():
            z = int(s)
            if z not in Z2SYM:
                raise ValueError(f"Unknown Z={z}")
            items.append(Z2SYM[z])
        else:
            items.append(s[:1].upper() + s[1:].lower())
    if not items:
        raise ValueError("No elements provided")
    return items

def main():
    ap = argparse.ArgumentParser(description="Generate μ/ρ and μ curves from xraylib (6–16 keV).")
    ap.add_argument("-Z","--elements", required=True,
                    help="Comma-separated element symbols or Z (e.g. 'Fe,Co,Ni' or '26,27,28').")
    ap.add_argument("--emin-keV", type=float, default=6.0, help="Min energy (keV). Default 6.0")
    ap.add_argument("--emax-keV", type=float, default=16.0, help="Max energy (keV). Default 16.0")
    ap.add_argument("--step-eV", type=float, default=0.5, help="Energy step (eV). Default 0.5")
    ap.add_argument("--outdir", default="curves_xraylib", help="Output directory for .npy files")
    args = ap.parse_args()

    symbols = coerce_symbols(args.elements)
    outdir = pathlib.Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    # Build energy axis in eV (dense), convert to keV for xraylib
    E_eV = np.arange(args.emin_keV * 1000.0, args.emax_keV * 1000.0 + 1e-9, args.step_eV)
    E_keV = E_eV / 1000.0

    all_payload = {}

    for sym in symbols:
        Z = xraylib.SymbolToAtomicNumber(sym)
        # mass attenuation coefficient μ/ρ (cm^2/g): total cross-section per mass
        mu_rho = np.array([xraylib.CS_Total(Z, float(ek)) for ek in E_keV], dtype=np.float64)
        # elemental density (g/cm^3) for linear μ
        try:
            rho = xraylib.ElementDensity(Z)
        except Exception:
            rho = np.nan  # some elements may not have a tabulated density
        mu = mu_rho * rho if np.isfinite(rho) else np.full_like(mu_rho, np.nan)

        # K-edge energy (eV) from xraylib if available
        try:
            e0_eV = xraylib.EdgeEnergy(Z, xraylib.K_SHELL) * 1000.0
        except Exception:
            e0_eV = np.nan

        payload = {
            "element": sym,
            "Z": Z,
            "energy_eV": E_eV,
            "energy_keV": E_keV,
            "mu_over_rho_cm2_per_g": mu_rho,
            "mu_cm_inv": mu,
            "density_g_cm3": rho,
            "E0_K_eV": e0_eV,
            "notes": "Computed with xraylib.CS_Total (no fine structure/XANES)."
        }

        # Save per-element .npy
        out_path = outdir / f"{sym}.npy"
        np.save(out_path, payload)
        print(f"Saved: {out_path}")

        # Also stash into combined dict
        all_payload[sym] = payload

    # Save combined bundle
    bundle_path = outdir / f"all_elements_{int(args.emin_keV)}_{int(args.emax_keV)}keV.npy"
    np.save(bundle_path, all_payload)
    print(f"Saved bundle: {bundle_path}")

if __name__ == "__main__":
    # argparse stores to args.emin_keV / args.emax_keV internally—fix attribute names:
    # quick shim because I used different names in ap.add_argument
    # (Some shells don't like hyphens in attribute names.)
    # We'll map them just after parsing. To keep it simple, re-parse and set.
    import sys
    if "--emin-keV" in sys.argv or "--emax-keV" in sys.argv:
        # Let argparse do its thing, then run main (which reads args.*_keV).
        pass
    main()

