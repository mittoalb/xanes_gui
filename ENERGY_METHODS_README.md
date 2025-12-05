# XANES GUI - Energy Range Methods

## Overview

The XANES GUI now supports three different methods for defining energy ranges:

### 1. **Manual (Start/End/Step)** - Traditional Linear Scan
- Define start energy (keV), end energy (keV), and step size (eV)
- The GUI automatically calculates and displays the number of points
- Uses the original EPICS PV workflow: `XanesStart`, `XanesEnd`, `XanesStep`
- Works with your existing `xanes_energy.py` script without modifications

### 2. **Select Range on Plot** - Interactive Visual Selection
- Load a reference curve or calibration plot
- Click "Enable Selection" button
- Drag on the plot to visually select the energy range of interest
- Specify the number of points to sample within the selected range
- Creates a linear energy array within the selected bounds

### 3. **Import Custom Energy Array** - Non-uniform Energy Grids
- Load energy values from a text file (CSV/TXT) - one value per line
- Or manually edit energies in a built-in table editor
- Supports non-uniform spacing (ideal for focused scans around features)
- Perfect for pre-calculated energy sequences or specialized scan patterns

## How It Works

### For Manual Method (Linear Scans)
1. GUI writes to EPICS PVs: `XanesStart`, `XanesEnd`, `XanesStep`
2. Your original `xanes_energy.py` script reads these PVs
3. Script calculates energy array: `npts = int((emax*1000 - emin*1000)/step) + 1`
4. Energy array is saved to `~/energies.npy`
5. Tomoscan uses the energy file

### For Plot Selection & Custom Methods (Non-linear Scans)
1. GUI generates/loads custom energy array
2. GUI saves energy array directly to `~/energies.npy`
3. GUI still sets PVs (for logging/display purposes)
4. **Your script needs updating** to detect and use the pre-saved energy file

## Updated Script

Replace your `xanes_energy.py` with the provided `xanes_energy_updated.py`, which:

- Checks if `~/energies.npy` exists and was modified in the last 60 seconds
- If YES: Uses the custom energy array from file (GUI pre-saved it)
- If NO: Calculates energies from PVs (traditional method)
- Works seamlessly with all three GUI methods

### Key Changes in Updated Script:

```python
# Check for custom energies file
custom_energies_file = os.path.expanduser("~/energies.npy")
use_custom = False

if os.path.exists(custom_energies_file):
    file_age = time.time() - os.path.getmtime(custom_energies_file)
    if file_age < 60:  # Fresh file from GUI
        use_custom = True
        energies = np.load(custom_energies_file)
```

## GUI Changes Summary

### Updated EPICS PVs:
- Changed from `XanesPoints` to `XanesStep` (step size in eV)
- Added calibration file PVs (already in your system)
- Added custom energies file path configuration

### UI Updates:
- Radio buttons to select energy method
- Dynamic UI showing relevant controls for each method
- Real-time point calculation display for manual mode
- Interactive span selector for plot selection
- Energy table editor dialog for custom arrays

### Files Modified:
- `xanes_gui.py` - Main GUI with all three energy methods

### Files Created:
- `xanes_energy_updated.py` - Updated scan script
- `ENERGY_METHODS_README.md` - This documentation

## Usage Examples

### Example 1: Quick Fe K-edge scan
1. Select "Manual" method
2. Click "Fe" in the element list
3. Click "Apply to fields" (auto-fills ±200 eV around edge)
4. Adjust step size if needed (default maintains 121 points)
5. Click "Start XANES"

### Example 2: Select interesting region from reference
1. Load a reference curve: "Load curve (CSV/NPY)"
2. Select "Select range on plot" method
3. Click "Enable Selection"
4. Drag on the plot to select the region of interest
5. Set number of points (default 121)
6. Click "Start XANES"

### Example 3: Custom non-uniform scan
1. Select "Import custom energy array" method
2. Option A: Click "Load from CSV/TXT" and select a file
3. Option B: Click "Edit Table" and manually enter energies
4. The GUI saves to `~/energies.npy` when you start the scan
5. Click "Start XANES"

## Calibration

The "Calibrate" button works with all three methods:
- Scans through the defined energy range
- Collects detector images at each energy
- Plots the sum of pixels vs energy in real-time
- Results can be overlaid with reference curves

## Important Notes

1. **For non-linear scans**: Make sure to use `xanes_energy_updated.py` instead of the original script
2. **File location**: Custom energies are always saved to `~/energies.npy`
3. **Time window**: The script checks for files newer than 60 seconds to avoid using stale data
4. **Backwards compatible**: Manual method works exactly like before with original script
5. **Step size convention**: Step is in eV (not keV) matching your original script

## Migration Path

1. **Immediate**: Use manual method with existing `xanes_energy.py` - no changes needed
2. **When ready**: Replace with `xanes_energy_updated.py` to enable all three methods
3. **Test**: Try plot selection and custom methods with the new script

## Configuration

Edit settings in the "PV Settings" tab:
- EPICS PV names
- Calibration file base directory
- Custom energies file path
- Reference curves directory

All settings are pre-configured for your beamline setup.
