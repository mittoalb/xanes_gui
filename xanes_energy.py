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

# Check for custom energies file from GUI (must be fresh < 60 seconds)
custom_energies_file = os.path.expanduser("~/energies.npy")
use_custom = False

if os.path.exists(custom_energies_file):
    file_age = time.time() - os.path.getmtime(custom_energies_file)
    if file_age < 60:  # File modified within last 60 seconds
        try:
            energies = np.load(custom_energies_file)
            if energies.ndim == 1 and len(energies) > 1:
                use_custom = True
                emin = energies[0]
                emax = energies[-1]
                npts = len(energies)
                print(f"[INFO] Using custom energies from GUI ({npts} points)")
                print(f"[INFO] Custom energy range: {emin:.4f} - {emax:.4f} keV")
        except Exception as e:
            print(f"[WARNING] Could not load custom energies file: {e}")
            print("[INFO] Falling back to PV-based calculation")

# If no custom energies, calculate from PVs (original method)
if not use_custom:
    # Read energy scan parameters
    emin = float(caget("32id:TXMOptics:XanesStart"))
    emax = float(caget("32id:TXMOptics:XanesEnd"))
    steps = int(float(caget("32id:TXMOptics:XanesStep")))

    # Calculate energy array
    npts = int((emax*1000 - emin*1000)/steps) + 1
    energies = np.linspace(emin, emax, npts)

    # Save energy array
    np.save(custom_energies_file, energies)
    print(f"[INFO] Calculated {npts} points from PVs: {emin:.4f} - {emax:.4f} keV (step: {steps} eV)")

# Read calibration file paths
params1 = caget("32id:TXMOptics:EnergyCalibrationFileOne")
params2 = caget("32id:TXMOptics:EnergyCalibrationFileTwo")

params1 = "/home/beams/USERTXM/epics/synApps/support/txmoptics/iocBoot/iocTXMOptics/" + params1
params2 = "/home/beams/USERTXM/epics/synApps/support/txmoptics/iocBoot/iocTXMOptics/" + params2

print(f"[INFO] Final energies array:", energies)
print(f"[INFO] Saved to: {custom_energies_file}")
print(f"[INFO] Using calibration files:\n  - {params1}\n  - {params2}")

subprocess.run([
     "tomoscan", "energy",
     "--tomoscan-prefix", "32id:TomoScan:",
     "--file-params1", params1,
     "--file-params2", params2,
     "--file-energies", custom_energies_file
])