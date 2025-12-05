# XANES GUI - Dual Curve Directory Support

## Overview

The XANES GUI now supports two separate directories for reference curves:

1. **Calibrated** - Real measured data from experiments
2. **Simulated** - Theoretical/simulated XANES curves

## Directory Structure

Default setup expects:
```
~/xanes_curves/
├── calibrated/     # Real measured XANES data
│   ├── Fe.npy
│   ├── Co.npy
│   ├── Ni.npy
│   └── ...
└── curves/         # Simulated XANES data
    ├── Fe.npy
    ├── Co.npy
    ├── Ni.npy
    └── ...
```

## Usage

### Selecting Curve Source

In the Scan tab, right panel:
- **"Reference Curves"** section has two radio buttons:
  - **Calibrated (measured)** - Loads from `~/xanes_curves/calibrated/`
  - **Simulated** - Loads from `~/xanes_curves/curves/`

### How It Works

1. **Click an element** (e.g., Fe) from the edge list
2. GUI looks for the curve file in the **selected source** directory
3. If not found, it **automatically checks the other directory** as fallback
4. The curve is loaded and plotted with a label indicating the source
5. Log message shows which source was used

### Example

**Scenario**: You select "Calibrated" but Fe.npy doesn't exist in `calibrated/`

Result:
- GUI finds Fe.npy in `curves/` directory
- Loads the simulated curve
- Shows: `Fe (calibrated)` in plot legend (but logs note about using simulated)
- Log: `"Note: Fe not found in calibrated directory, using simulated version"`

## Configuration

### Default Paths (in code)
```python
"curve_dir_calibrated": "~/xanes_curves/calibrated"
"curve_dir_simulated": "~/xanes_curves/curves"
```

### Customizing Paths

Go to **PV Settings** tab:
- **"Calibrated curves folder:"** - Browse/edit path to real data
- **"Simulated curves folder:"** - Browse/edit path to simulated data
- **"Ref curve extension:"** - Select `.npy` or `.csv`

Both directories can be configured independently.

## File Format

Curves should be saved as:
- **Filename**: `{Element_Symbol}.npy` or `{Element_Symbol}.csv`
  - Examples: `Fe.npy`, `Co.npy`, `Ni.csv`

- **Format**:
  - `.npy`: 2D numpy array, either 2xN or Nx2 (Energy, Intensity)
  - `.csv`: Two columns (Energy in keV, Normalized absorption)

## Features

### Smart Fallback
If a curve doesn't exist in the selected source, the GUI automatically tries the other directory. This prevents errors when:
- You only have simulated data for some elements
- You're still collecting calibrated data for certain elements

### Clear Labels
- Plot legend shows: `Element (source)`
  - Example: `Fe (calibrated)` or `Co (simulated)`
- K-edge line labeled: `Fe K-edge`

### Log Messages
All curve loading is logged with:
- Which source was requested
- Which file was actually loaded
- Number of data points in the curve
- Any fallback actions taken

## Workflow Example

### Starting a New Measurement Campaign

1. **Initial Setup**:
   - Select **"Simulated"** to use theoretical curves
   - Click element to load reference
   - Use reference to plan energy range

2. **After Calibration**:
   - Save measured XANES to `~/xanes_curves/calibrated/Fe.npy`
   - Switch to **"Calibrated"** in GUI
   - Click Fe again - now loads your real data

3. **Comparing Data**:
   - Enable "Overlay on existing plot"
   - Select "Simulated", click Fe
   - Select "Calibrated", click Fe again
   - Both curves plotted for comparison

## Tips

- **Organize by source**: Keep real and simulated data separate for clarity
- **Consistent naming**: Use element symbols (Fe, Co, Ni) for automatic loading
- **Backup calibrated data**: Real measurements are valuable, keep backups
- **Version control**: Consider dating calibrated curves (e.g., `calibrated/2024/`)

## Troubleshooting

**"Curve file not found" error**:
- Check that file exists in either directory
- Verify filename matches element symbol exactly
- Check file extension matches setting (.npy or .csv)
- Check paths in PV Settings tab

**Wrong curve loaded**:
- GUI shows in log which source was used
- If fallback occurred, you'll see a note in the log
- Verify the correct file exists in the selected directory

**Can't switch between sources**:
- Radio button selection in "Reference Curves" frame
- Click element again after changing source to reload

## Integration with Other Features

The curve source selection works seamlessly with:
- **Auto-fill scan parameters** - Apply edge energy to fields
- **Plot selection** - Draw energy range on loaded curves
- **Calibration overlay** - Overlay calibration on reference curves
- **Manual loading** - "Load curve (CSV/NPY)" button still available for one-off files
