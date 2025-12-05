#!/usr/bin/env python3
"""
Retrieve experimental XANES/XAFS spectra from MDR XAFS DB (NIMS), convert to CSV for GUI.

Features:
- Accepts element symbol(s) or atomic number(s) with -Z/--element, comma-separated.
- Searches MDR API (dice.nims.go.jp and mdr.nims.go.jp) for <Element> + "K edge" + XAFS.
- Downloads dataset ZIP, extracts first .xdi/.dat/.txt/.csv.
- Parses XDI/ASCII, optionally normalizes with a simple pre/post-edge line.
- Windows around E0 and writes Energy_eV,Mu to {outdir}/{Element}_{Edge}_{raw|norm}.csv.

Example:
  python retrieve.py -Z 26,27,28 --edge K --normalize
"""

import argparse
import io
import os
import re
import sys
import json
import math
import pathlib
import zipfile
from typing import Optional, Tuple, Iterable, Dict, Any, List

import numpy as np
import requests

# ---------- Element helpers ----------
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
def coerce_element_symbol(z_or_sym: str) -> str:
    """Accept 'Fe' or '26' and return a proper symbol like 'Fe'."""
    s = (z_or_sym or "").strip()
    if not s:
        raise ValueError("Empty element")
    if s.isdigit():
        z = int(s)
        if z in Z2SYM:
            return Z2SYM[z]
        raise ValueError(f"Unknown atomic number Z={z}")
    return s[:1].upper() + s[1:].lower()

def parse_element_list(arg: str) -> List[str]:
    out = []
    for token in (arg or "").split(","):
        token = token.strip()
        if token:
            out.append(coerce_element_symbol(token))
    if not out:
        raise ValueError("No elements provided")
    return out

# ---------- Edge energies (fallback) ----------
K_EDGES = {
    'C': 284.2, 'N': 409.9, 'O': 543.1, 'F': 696.7, 'Na': 1070.8, 'Mg': 1303.0, 'Al': 1559.6,
    'Si': 1839.0, 'P': 2145.5, 'S': 2472.0, 'Cl': 2822.0, 'K': 3608.4, 'Ca': 4038.5, 'Sc': 4492.0,
    'Ti': 4966.4, 'V': 5465.0, 'Cr': 5989.0, 'Mn': 6539.0, 'Fe': 7112.0, 'Co': 7709.0, 'Ni': 8333.0,
    'Cu': 8979.0, 'Zn': 9659.0, 'Ga': 10367.0, 'Ge': 11103.0, 'As': 11867.0, 'Se': 12658.0,
    'Br': 13474.0, 'Kr': 14326.0, 'Rb': 15200.0, 'Sr': 16105.0, 'Y': 17038.0, 'Zr': 17998.0,
    'Nb': 18986.0, 'Mo': 20000.0, 'Ag': 25514.0, 'Sn': 29200.0, 'I': 33169.0
}

# ---------- MDR endpoints (two hosts) ----------
BASES = [
    # Manual host
    {"list": "https://dice.nims.go.jp/services/MDR/api/v1/datasets",
     "one":  "https://dice.nims.go.jp/services/MDR/api/v1/datasets/{id}",
     "zip":  "https://dice.nims.go.jp/services/MDR/datasets/{id}.zip"},
    # Alternate/legacy host
    {"list": "https://mdr.nims.go.jp/api/v1/datasets",
     "one":  "https://mdr.nims.go.jp/api/v1/datasets/{id}",
     "zip":  "https://mdr.nims.go.jp/datasets/{id}.zip"},
]

# ---------- MDR helpers ----------
def _iter_api_records(js: Any) -> Iterable[Dict[str, Any]]:
    """Yield dataset dicts from various MDR response shapes."""
    if isinstance(js, list):
        for rec in js:
            if isinstance(rec, dict):
                yield rec
        return
    if isinstance(js, dict):
        for key in ("data", "items", "results"):
            val = js.get(key)
            if isinstance(val, list):
                for rec in val:
                    if isinstance(rec, dict):
                        yield rec
                return
        # Sometimes a dict of dicts
        if all(isinstance(v, dict) for v in js.values()):
            for rec in js.values():
                yield rec

def _try_get(url: str, **kwargs) -> Optional[requests.Response]:
    try:
        r = requests.get(url, timeout=30, **kwargs)
        if r.ok:
            return r
    except Exception:
        return None
    return None

def _search_page(base: dict, q: str, page: Optional[int]) -> Iterable[Dict[str, Any]]:
    params = {"q": q}
    if page is not None:
        params["page"] = page
    r = _try_get(base["list"], params=params)
    if not r:
        return []
    try:
        js = r.json()
    except Exception:
        return []
    return list(_iter_api_records(js))

def search_mdr(element: str, edge: str = "K", max_pages: int = 3) -> Iterable[Dict[str, Any]]:
    """Yield MDR dataset records for element/edge using simple keyword query."""
    q = f'XAFS {element} "{edge} edge"'
    for base in BASES:
        got_any = False
        for page in range(1, max_pages + 1):
            recs = list(_search_page(base, q, page))
            if not recs:
                break
            got_any = True
            for rec in recs:
                yield rec
        if got_any:
            return  # stop after first base that returns anything

def get_dataset_id(rec: Dict[str, Any]) -> str:
    """Extract a dataset identifier from a record."""
    if "id" in rec and isinstance(rec["id"], (str, int)):
        return str(rec["id"])
    attrs = rec.get("attributes") or {}
    for k in ("uuid", "id", "identifier"):
        if k in attrs:
            return str(attrs[k])
    data = rec.get("data") or {}
    if "id" in data:
        return str(data["id"])
    raise KeyError("Could not find dataset id in record")

def download_zip(dataset_id: str) -> Tuple[str, bytes]:
    """Try ZIP download across bases; return (url, content)."""
    for base in BASES:
        url = base["zip"].format(id=dataset_id)
        r = _try_get(url)
        if r and r.content:
            return url, r.content
    raise RuntimeError(f"Could not download dataset ZIP for id={dataset_id}")

def extract_first_spectrum(zip_bytes: bytes) -> Tuple[str, bytes]:
    """
    Return (filename, bytes) of first plausible spectrum file in the zip.
    Preference: .xdi > .dat/.txt/.csv
    """
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        names = [n for n in z.namelist() if not n.endswith('/')]
        def rank(name: str):
            n = name.lower()
            # (lower is better)
            if n.endswith(".xdi"): return (0, len(n))
            if n.endswith(".dat"): return (1, len(n))
            if n.endswith(".txt"): return (2, len(n))
            if n.endswith(".csv"): return (3, len(n))
            return (9, len(n))
        names.sort(key=rank)
        for name in names:
            if rank(name)[0] >= 9:
                continue
            with z.open(name) as f:
                data = f.read()
            if data:
                return name, data
    raise RuntimeError("No spectrum-like file (.xdi/.dat/.txt/.csv) found in ZIP")

# ---------- Parsing / normalization ----------
def parse_xdi_or_ascii(raw: bytes) -> Tuple[dict, np.ndarray]:
    """Parse XDI header if present (# Key: Value), then numeric cols -> (header, Nx2 E,mu)."""
    header, text_lines = {}, []
    for ln in raw.decode('utf-8', errors='ignore').splitlines():
        if ln.startswith('#'):
            m = re.match(r"#\s*([\w\.\-]+)\s*:\s*(.*)", ln)
            if m:
                header[m.group(1).strip()] = m.group(2).strip()
            continue
        if ln.strip():
            text_lines.append(ln)
    if not text_lines:
        raise RuntimeError("No numeric data lines")

    arr = np.genfromtxt(text_lines)
    if arr.ndim == 1:
        arr = arr[None, :]
    if arr.shape[1] < 2:
        raise RuntimeError("Numeric data has fewer than 2 columns")

    E = arr[:, 0].astype(float)

    def find_idx(label_sub: str) -> Optional[int]:
        for k, v in header.items():
            if k.lower().startswith('column') and isinstance(v, str) and label_sub in v.lower():
                try:
                    return int(k.split('.')[-1]) - 1
                except Exception:
                    pass
        return None

    idx_mu = find_idx('mu')
    idx_i0 = find_idx('i0')
    idx_it = find_idx('itrans') or find_idx('itr') or find_idx('it')

    if idx_mu is not None and arr.shape[1] > idx_mu:
        Y = arr[:, idx_mu].astype(float)
    elif idx_i0 is not None and idx_it is not None and arr.shape[1] > max(idx_i0, idx_it):
        I0 = np.clip(arr[:, idx_i0].astype(float), 1e-12, np.inf)
        It = np.clip(arr[:, idx_it].astype(float),  1e-12, np.inf)
        Y = -np.log(It / I0)
    else:
        Y = arr[:, 1].astype(float)

    return header, np.column_stack([E, Y])

def guess_e0(header: dict, element: str, edge: str = "K", E: Optional[np.ndarray] = None) -> float:
    for k in ("Scan.edge_energy", "Edge.energy", "Edge.E0"):
        if k in header:
            try:
                return float(header[k])
            except Exception:
                pass
    if edge.upper().startswith('K') and element in K_EDGES:
        return K_EDGES[element]
    if E is not None:
        return float(np.median(E))
    raise RuntimeError("Could not determine edge energy E0")

def normalize_xanes(E: np.ndarray, mu: np.ndarray, e0: float,
                    pre=(-200.0, -50.0), post=(150.0, 800.0)) -> Tuple[np.ndarray, float]:
    pre_mask  = (E >= e0 + pre[0]) & (E <= e0 + pre[1])
    post_mask = (E >= e0 + post[0]) & (E <= e0 + post[1])
    if not (np.any(pre_mask) and np.any(post_mask)):
        # fallback: min-max
        step = max(mu.ptp(), 1e-12)
        return (mu - mu.min()) / step, step

    def linfit(x, y):
        A = np.vstack([x, np.ones_like(x)]).T
        a, b = np.linalg.lstsq(A, y, rcond=None)[0]
        return a, b

    ap, bp = linfit(E[pre_mask],  mu[pre_mask])
    as_, bs = linfit(E[post_mask], mu[post_mask])

    mu0 = ap*E + bp
    step = (as_*e0 + bs) - (ap*e0 + bp)
    if abs(step) < 1e-12:
        step = 1.0
    mu_norm = (mu - mu0) / step
    return mu_norm, step

# ---------- Orchestration ----------
def fetch_convert_one(element: str, edge: str, outdir: pathlib.Path,
                      window: Tuple[float, float], normalize: bool) -> Optional[pathlib.Path]:
    # 1) Find a dataset
    chosen_id = None
    chosen_title = ""
    for rec in search_mdr(element, edge=edge, max_pages=5):
        # prefer records that mention element and xafs in title/desc
        attrs = rec.get("attributes") or {}
        title = (attrs.get("title") or rec.get("title") or "").lower()
        desc  = (attrs.get("description") or rec.get("description") or "").lower()
        if element.lower() in (title + desc) and ("xafs" in title or "xafs" in desc):
            try:
                chosen_id = get_dataset_id(rec)
                chosen_title = attrs.get("title") or rec.get("title") or ""
                break
            except Exception:
                continue
        # fallback: first record that yields an id
        if chosen_id is None:
            try:
                chosen_id = get_dataset_id(rec)
                chosen_title = attrs.get("title") or rec.get("title") or ""
            except Exception:
                pass
    if not chosen_id:
        print(f"[WARN] No MDR dataset found for {element} {edge}", file=sys.stderr)
        return None

    # 2) Download ZIP
    try:
        zip_url, zip_bytes = download_zip(chosen_id)
    except Exception as e:
        print(f"[WARN] Failed ZIP download for {element} {edge}: {e}", file=sys.stderr)
        return None

    # 3) Extract spectrum
    try:
        spec_name, spec_bytes = extract_first_spectrum(zip_bytes)
    except Exception as e:
        print(f"[WARN] No spectrum file in dataset {chosen_id}: {e}", file=sys.stderr)
        return None

    # 4) Parse
    try:
        header, data = parse_xdi_or_ascii(spec_bytes)
    except Exception as e:
        print(f"[WARN] Failed to parse spectrum {spec_name}: {e}", file=sys.stderr)
        return None

    E, mu = data[:, 0], data[:, 1]

    # 5) Determine E0 and window
    try:
        e0 = guess_e0(header, element, edge=edge, E=E)
    except Exception:
        # last resort: median energy
        e0 = float(np.median(E))
    wmin, wmax = window
    mask = (E >= e0 + wmin) & (E <= e0 + wmax)
    if not np.any(mask):
        mask = slice(None)

    # 6) Normalize (optional)
    if normalize:
        muN, step = normalize_xanes(E, mu, e0=e0)
        Ew, muw = E[mask], muN[mask]
        tag = "norm"
    else:
        Ew, muw = E[mask], mu[mask]
        tag = "raw"

    # 7) Save
    outdir.mkdir(parents=True, exist_ok=True)
    outpath = outdir / f"{element}_{edge}_{tag}.csv"
    np.savetxt(outpath, np.column_stack([Ew, muw]), delimiter=",",
               header="Energy_eV,Mu", comments="")
    print(f"Saved: {outpath}  (dataset {chosen_id}, file {spec_name})")
    if chosen_title:
        print(f"  Title: {chosen_title}")
    print(f"  ZIP:   {zip_url}")
    return outpath

def main():
    p = argparse.ArgumentParser(description="Download XANES from MDR and convert to CSV for GUI.")
    p.add_argument("-Z","--element", required=True,
                   help="Element symbol or atomic number (comma-separated allowed), e.g. 'Fe' or '26,27,28'")
    p.add_argument("--edge", default="K", help="Edge (K, L3, ...). Default: K")
    p.add_argument("--window", type=float, nargs=2, default=(-200.0, 800.0),
                   help="Energy window around E0 [emin emax] in eV (default -200 800)")
    p.add_argument("--normalize", action="store_true", help="Pre/post-edge normalization")
    p.add_argument("--outdir", default="xanes_curves", help="Output folder (default: xanes_curves)")
    args = p.parse_args()

    try:
        elements = parse_element_list(args.element)
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(2)

    outdir = pathlib.Path(args.outdir)
    window = (float(args.window[0]), float(args.window[1]))
    ok = 0
    for elem in elements:
        try:
            path = fetch_convert_one(elem, args.edge, outdir, window, args.normalize)
            if path is not None:
                ok += 1
        except KeyboardInterrupt:
            raise
        except Exception as e:
            print(f"[WARN] Failed for {elem} {args.edge}: {e}", file=sys.stderr)

    if ok == 0:
        sys.exit(1)

if __name__ == "__main__":
    main()

