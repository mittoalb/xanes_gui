# XANES GUI

A PyQt5-based graphical user interface for X-ray Absorption Near Edge Structure (XANES) spectroscopy measurements at APS Beamline 32-ID.

[![Python Version](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![PyQt](https://img.shields.io/badge/PyQt-5-green.svg)](https://www.riverbankcomputing.com/software/pyqt/)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

## Features

- **Modern PyQt5 Interface** - Dark theme optimized for beamline environments
- **Embedded Terminal** - Real-time script output in GUI (no external terminals)
- **Smart Execution** - Auto-detects local vs remote execution
- **Real-time Calibration** - Live plot updates during energy scans
- **Flexible Energy Configuration** - Three methods for defining scan ranges with integer step sizes
- **Reference Curve Support** - Calibrated and simulated spectra visualization with edge shift detection
- **EPICS Integration** - Full Channel Access and PVAccess support
- **Thread-Safe Operations** - Non-blocking UI during acquisitions
- **Interactive Plotting** - Zoom, pan, and overlay multiple curves

## Quick Start

### Installation

```bash
pip install git+https://github.com/yourusername/xanes-gui.git
```

Or install from source:

```bash
git clone https://github.com/yourusername/xanes-gui.git
cd xanes-gui
pip install -e .
```

### Running the GUI

```bash
xanes-gui
```

Or as a Python module:

```bash
python -m xanes_gui
```

### First Time Setup

1. Configure EPICS environment variables:

```bash
export EPICS_CA_ADDR_LIST="your_ioc_address"
export EPICS_CA_AUTO_ADDR_LIST=NO
export EPICS_PVA_ADDR_LIST="your_ioc_address"
```

2. Open the **PV Settings** tab and configure:
   - **EPICS/PVA Configuration**: Detector PVA channel, Energy control PVs
   - **Remote Execution (SSH)**: Remote host, conda environment, script path
   - **Reference Curves**: Calibrated and simulated curve directories

3. Select an element and click **Calibrate** to test!

## Energy Range Methods

### Method 1: Manual Entry
Standard scans with uniform spacing:
- Enter start energy, end energy, and step size (in eV)
- Auto-calculates total points
- Integer step sizes guaranteed (1, 2, 3... eV)
- Quick setup with **Apply to fields** button

### Method 2: Plot Selection
Visual selection based on reference curves:
- Drag a region on the plot to select energy range
- Specify integer step size (1, 2, 3... eV)
- Exact step size preserved using np.arange
- Perfect for edge-specific ranges

### Method 3: Custom Energy Array
Non-uniform spacing for specialized scans:
- Load from CSV/TXT file
- Manual entry via table editor
- Fine control over pre-edge, edge, and post-edge regions

## Documentation

Full documentation available at: https://xanes-gui.readthedocs.io

- [Installation Guide](https://xanes-gui.readthedocs.io/en/latest/installation.html)
- [Quick Start Tutorial](https://xanes-gui.readthedocs.io/en/latest/quickstart.html)
- [User Guide](https://xanes-gui.readthedocs.io/en/latest/user_guide.html)
- [API Reference](https://xanes-gui.readthedocs.io/en/latest/api.html)
- [Troubleshooting](https://xanes-gui.readthedocs.io/en/latest/troubleshooting.html)

## Requirements

- Python 3.8 or higher
- PyQt5 5.15+
- numpy 1.20+
- pyqtgraph 0.12+
- pyepics 3.5+
- pvaccess 1.0+

## System Requirements

- **OS**: Linux (RHEL 8/9, Ubuntu 20.04+), macOS 10.14+, Windows 10+
- **RAM**: Minimum 4 GB
- **Disk**: 100 MB
- **Network**: Connection to EPICS IOCs

## Screenshots

### Main Interface
![Main Interface](docs/images/main_interface.png)

### Calibration Scan
![Calibration](docs/images/calibration.png)

### Reference Curves
![Curves](docs/images/curves.png)

## Configuration

Settings are stored in `~/.xanes_gui_settings.json`:

```json
{
  "detector_pv": "32idbSP1:Pva1:Image",
  "energy_set_pv": "32id:TXMOptics:EnergySet",
  "remote_user": "usertxm",
  "remote_host": "gauss",
  "conda_env": "tomoscan",
  "script_name": "/home/beams/USERTXM/Software/xanes_gui/xanes_energy.py",
  "curve_dir_calibrated": "/data/Calibrated/",
  "curve_dir_simulated": "/data/Curves/"
}
```

## Usage Example

### Perform a Quick Fe K-edge Calibration

1. Launch the GUI: `xanes-gui`
2. Select **Fe** from the edge list
3. Click **Apply to fields** (sets 6.912-7.312 keV, 1 eV step)
4. Click **Calibrate**
5. Monitor real-time plot and progress

### Start a XANES Scan

1. Configure energy range (any method)
2. Verify remote execution settings in **PV Settings** tab
3. Click **Start XANES**
4. Monitor real-time output in embedded terminal
   - Auto-detects if running locally or needs SSH
   - Color-coded output (errors in red, operations in blue, success in green)
   - No external terminal windows opened

## Development

### Install Development Dependencies

```bash
pip install -e ".[dev,docs]"
```

### Run Tests

```bash
pytest
```

### Build Documentation

```bash
cd docs
make html
```

Documentation will be in `docs/build/html/`.

### Code Style

This project uses:
- Black for code formatting
- flake8 for linting
- mypy for type checking

```bash
black xanes_gui/
flake8 xanes_gui/
mypy xanes_gui/
```

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

See [CONTRIBUTING.md](CONTRIBUTING.md) for detailed guidelines.

## Citing

If you use XANES GUI in your research, please cite:

```bibtex
@software{xanes_gui_2024,
  title = {XANES GUI: A PyQt5-based Interface for X-ray Absorption Spectroscopy},
  author = {APS Beamline 32-ID},
  year = {2024},
  url = {https://github.com/yourusername/xanes-gui},
  version = {1.0.0}
}
```

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- Advanced Photon Source, Argonne National Laboratory
- U.S. Department of Energy, Office of Science
- APS Beamline 32-ID staff and users
- PyQt5 and pyqtgraph development teams
- EPICS collaboration

## Support

- **Documentation**: https://xanes-gui.readthedocs.io
- **Issues**: https://github.com/yourusername/xanes-gui/issues
- **Email**: 32id@aps.anl.gov

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for version history.

## Related Projects

- [EPICS](https://epics-controls.org/) - Experimental Physics and Industrial Control System
- [PyEpics](https://pyepics.github.io/pyepics/) - Python interface to EPICS Channel Access
- [areaDetector](https://areadetector.github.io/) - EPICS areaDetector framework
- [pyqtgraph](http://www.pyqtgraph.org/) - Scientific graphics and GUI library

---

**Developed at APS Beamline 32-ID** | [Advanced Photon Source](https://www.aps.anl.gov/)
