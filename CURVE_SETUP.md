# Your XANES Curve Setup

## Directory Structure

Your curves are now properly configured in:

```
Xanes_GUI/
├── Calibrated/          # Real experimental measurements
│   ├── Ni_calibrated.npy
│   └── Pt_calibrated.npy
└── Curves/              # Simulated XANES data (full periodic table)
    ├── Fe.npy
    ├── Co.npy
    ├── Ni.npy
    ├── ... (94 elements total)
```

## File Formats

### Simulated Curves (Curves/)
- **Format**: Binary numpy arrays (`.npy`)
- **Structure**: 10001 × 2 array (Energy, Intensity)
- **Energy range**: 6.0 - 16.0 keV (covers K-edges of elements 6-16 keV)
- **Naming**: `{Element}.npy` (e.g., `Fe.npy`, `Co.npy`)

**Example (Fe.npy)**:
```
Shape: (10001, 2)
Energy: 6.000 - 16.000 keV
Points: 10001
```

### Calibrated Curves (Calibrated/)
- **Format**: Text files with `.npy` extension (space-separated)
- **Structure**: N × 2 array (Energy, Intensity)
- **Energy range**: Focused around K-edge (~200 eV window)
- **Naming**: `{Element}_calibrated.npy` (e.g., `Ni_calibrated.npy`)

**Example (Ni_calibrated.npy)**:
```
Shape: (55, 2)
Energy: 8.300 - 8.500 keV (around Ni K-edge at 8.333 keV)
Points: 55
Format: Space-separated text (despite .npy extension)
```

## GUI Configuration

The GUI is now configured to use your local directories:

```python
"curve_dir_calibrated": "Xanes_GUI/Calibrated"
"curve_dir_simulated": "Xanes_GUI/Curves"
```

## Smart File Loading

The GUI loader (`_load_curve_file`) automatically handles:

1. **Binary numpy files** (`.npy`) - Your simulated curves
2. **Text files with `.npy` extension** - Your calibrated curves
3. **CSV/TXT files** - Any additional data format

### Loading Logic:
```
1. Try to load as binary numpy array
2. If that fails (OSError/ValueError), try as text file
3. Handle both Nx2 and 2xN array orientations
4. Extract first two columns (Energy, Intensity)
```

## Naming Convention Support

The GUI intelligently handles different naming conventions:

### When requesting **Calibrated** curves:
1. First tries: `Ni_calibrated.npy`
2. Then tries: `Ni.npy`
3. Falls back to simulated if not found

### When requesting **Simulated** curves:
1. Tries: `Ni.npy`
2. Falls back to calibrated `Ni_calibrated.npy` if not found

## Current Data Inventory

### Calibrated (2 elements):
- **Ni** (Nickel) - 8.300-8.500 keV, 55 points
- **Pt** (Platinum) - Unknown range (text file)

### Simulated (94 elements):
All elements from periodic table with K-edges in 6-16 keV range

## Usage in GUI

### Loading Calibrated Data:
1. Select **"Calibrated (measured)"** radio button
2. Click **Ni** or **Pt** from element list
3. GUI loads `{Element}_calibrated.npy`
4. Plot shows focused region around K-edge

### Loading Simulated Data:
1. Select **"Simulated"** radio button
2. Click any element (Fe, Co, Ni, etc.)
3. GUI loads `{Element}.npy`
4. Plot shows full 6-16 keV range

### Comparing Data:
1. Enable **"Overlay on existing plot"** checkbox
2. Select "Calibrated", click Ni → Shows experimental data
3. Select "Simulated", click Ni → Overlays theoretical prediction
4. Compare theory vs. experiment!

## Example Workflow: Ni K-edge Study

```
1. Goal: Study Ni K-edge at 8.333 keV

2. Initial Planning (Simulated):
   - Select "Simulated"
   - Click "Ni" → Loads full 6-16 keV theoretical curve
   - Select "Select range on plot"
   - Enable selection, drag around 8.0-8.6 keV
   - Click "Apply to fields" → Sets up scan parameters

3. After Experiment (Calibrated):
   - Select "Calibrated"
   - Click "Ni" → Loads your 8.3-8.5 keV measurement
   - Compare with theoretical prediction

4. Comparison:
   - Enable overlay
   - Load both curves
   - See how your data matches theory
```

## Adding New Calibrated Data

When you collect new calibrated curves:

### Option 1: Save as text with `_calibrated` suffix (recommended)
```
Calibrated/Fe_calibrated.npy
```
Format: Space-separated text, 2 columns (Energy, Intensity)

### Option 2: Save as standard numpy array
```python
import numpy as np
# Your energy and intensity arrays
data = np.column_stack([energy, intensity])
np.save('Calibrated/Fe_calibrated.npy', data)
```

## File Format Details

### Simulated Curves Header:
```python
>>> data = np.load('Curves/Fe.npy')
>>> data.shape
(10001, 2)
>>> data[:3]
array([[ 6.000,  84.842],
       [ 6.001,  84.803],
       [ 6.002,  84.764]])
```

### Calibrated Curves Header:
```
8.300000000000000711e+00 1.062791277000000000e+11
8.303703703703703809e+00 9.964642344400000000e+10
8.307407407407408684e+00 9.947627611600000000e+10
```
(Space-separated, scientific notation)

## Tips

1. **Quick check**: Use simulated curves for all planning
2. **After calibration**: Save as `{Element}_calibrated.npy` in Calibrated/
3. **Comparison**: Enable overlay to plot both on same axes
4. **Energy selection**: Use simulated curves to visualize and select ranges
5. **Validation**: Compare your calibrated data against simulations

## Troubleshooting

**"Curve file not found"**:
- Check filename matches: `Ni_calibrated.npy` or `Ni.npy`
- Verify file is in correct directory
- Check element symbol spelling

**Wrong curve loaded**:
- Check radio button selection (Calibrated vs Simulated)
- Look at log message to see which file was loaded
- Verify fallback didn't occur unintentionally

**Load error**:
- File format might be unsupported
- Try converting to text (space/comma separated)
- Ensure 2 columns: Energy, Intensity
