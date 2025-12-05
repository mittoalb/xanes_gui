#!/usr/bin/env python3
"""
Updated XANES energy scan script that supports both:
1. Linear scans (start/end/step from PVs)
2. Custom energy arrays (from ~/energies.npy file)

The script checks if ~/energies.npy exists and is recent (modified within last 60 seconds).
If so, it uses the custom energy array. Otherwise, it calculates energies from PVs.
"""

import numpy as np
import subprocess
import os
import time

def caget(pv):
    try:
        result = subprocess.run(['caget', '-t', pv], stdout=subprocess.PIPE, check=True, text=True)
        return result.stdout.strip()
    except Exception as e:
        print(f"[ERROR] Reading {pv}: {e}")
        exit(1)

# Check for custom energies file
custom_energies_file = os.path.expanduser("~/energies.npy")
use_custom = False

if os.path.exists(custom_energies_file):
    # Check if file was modified in the last 60 seconds (indicating it's fresh from GUI)
    file_age = time.time() - os.path.getmtime(custom_energies_file)
    if file_age < 60:
        use_custom = True
        print(f"[INFO] Using custom energy array from {custom_energies_file} (age: {file_age:.1f}s)")

if use_custom:
    # Load custom energies
    energies = np.load(custom_energies_file)
    emin = energies[0]
    emax = energies[-1]
    npts = len(energies)
    print(f"[INFO] Loaded {npts} custom energy points: {emin:.4f} to {emax:.4f} keV")
else:
    # Read energy scan parameters from PVs (traditional method)
    emin = float(caget("32id:TXMOptics:XanesStart"))
    emax = float(caget("32id:TXMOptics:XanesEnd"))
    steps = float(caget("32id:TXMOptics:XanesStep"))  # step size in eV

    # Calculate energy array
    npts = int((emax*1000 - emin*1000)/steps) + 1
    energies = np.linspace(emin, emax, npts)

    # Save for tomoscan
    np.save(custom_energies_file, energies)
    print(f"[INFO] Calculated {npts} energies from PVs: {emin:.4f} to {emax:.4f} keV (step={steps} eV)")

print(f"[INFO] Energy array:", energies)

# Read calibration file paths
params1 = caget("32id:TXMOptics:EnergyCalibrationFileOne")
params2 = caget("32id:TXMOptics:EnergyCalibrationFileTwo")

params1 = "/home/beams/USERTXM/epics/synApps/support/txmoptics/iocBoot/iocTXMOptics/" + params1
params2 = "/home/beams/USERTXM/epics/synApps/support/txmoptics/iocBoot/iocTXMOptics/" + params2

print(f"[INFO] Using calibration files:\n  - {params1}\n  - {params2}")

# Launch tomoscan with energy file
subprocess.run([
    "tomoscan", "energy",
    "--tomoscan-prefix", "32id:TomoScan:",
    "--file-params1", params1,
    "--file-params2", params2,
    "--file-energies", custom_energies_file
])

# Stop shaker and switch off the feedback
print("[INFO] Stopping shaker and feedback...")
subprocess.run(["caput", "32idbSoft:epidH:on", "off"])
subprocess.run(["caput", "32idbSoft:epidV:on", "off"])
subprocess.run(["caput", "32idbShaker:shaker:run", "Stop"])
print("[INFO] XANES scan completed.")
