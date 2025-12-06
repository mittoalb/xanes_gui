Changelog
=========

All notable changes to the XANES GUI project are documented here.

The format is based on `Keep a Changelog <https://keepachangelog.com/en/1.0.0/>`_,
and this project adheres to `Semantic Versioning <https://semver.org/spec/v2.0.0.html>`_.

Version 1.0.0 (2024-12-06)
--------------------------

Initial release of PyQt5-based XANES GUI.

Added
~~~~~

**Core Functionality**

* Complete PyQt5-based GUI for XANES spectroscopy measurements
* Calibration scan mode with live plotting
* XANES acquisition mode with external script launching
* Thread-safe operation with non-blocking UI

**Energy Range Configuration**

* Method 1: Manual entry (Start/End/Step)
* Method 2: Interactive plot selection with draggable region
* Method 3: Custom energy array import from CSV/TXT files
* Auto-fill functionality for standard ±200 eV edge ranges
* Real-time validation and point calculation

**Reference Curve System**

* Dual curve support (Calibrated and Simulated)
* Automatic edge shift calculation for calibrated curves
* Edge position markers on plots
* Curve overlay mode
* Support for NPY (binary and text) and CSV formats
* Manual curve loading from files

**User Interface**

* Dark theme optimized for beamline environments
* Resizable splitter layout (plot area and controls)
* Comprehensive edge database with filterable list
* Real-time progress indicators
* Timestamped log window with auto-scroll
* Color-coded action buttons (orange/green/red)

**EPICS Integration**

* Channel Access (pyepics) for PV control
* PVAccess for detector image acquisition
* Configurable PV names and paths
* Energy readback verification (optional)
* Configurable settling time
* Safety PV triggering on abort

**Plotting Features**

* Real-time plot updates during calibration
* Interactive zoom and pan with mouse
* Auto-ranging with right-click reset
* Multiple curve overlay capability
* K-edge position markers
* Custom color assignment

**Data Handling**

* Calibration data retention and plotting
* Detector image summation via PVAccess
* Custom energy array export to ~/energies.npy
* Settings persistence in JSON format

**Script Integration**

* External bash script launching for XANES acquisition
* Process group management for clean termination
* Stream script output to log window
* EPICS PV parameter passing (XanesStart, XanesEnd, XanesStep)

**Configuration**

* PV Settings tab for all EPICS configuration
* File browser integration for paths
* Settings auto-save in ~/.xanes_gui_settings.json
* Session state persistence

Changed
~~~~~~~

* **Complete rewrite from Tkinter to PyQt5**

  Previous version used Tkinter for GUI framework. This release completely
  reimplements the interface using PyQt5 for:

  * Better threading support
  * Modern dark theme
  * More responsive plotting with pyqtgraph
  * Native integration with EPICS tools

* **Improved plot selection method**

  LinearRegionItem now defaults to K-edge ± 20 eV instead of 0-1 keV range,
  providing more intuitive initial selection.

* **Enhanced splitter usability**

  Splitter handle width increased from 1px to 10px for easier dragging.

Fixed
~~~~~

* Calibration scan now properly updates plot with live data
* Plot auto-ranging works correctly with overlay mode
* Energy readback verification handles timeout correctly
* Thread cleanup on application exit
* Proper signal/slot connections for cross-thread communication

Security
~~~~~~~~

* Script execution uses process groups to prevent orphaned processes
* Path validation for file operations
* PV name validation to prevent injection

Known Issues
~~~~~~~~~~~~

* Some PV names (safety PVs, scan parameter PVs) are hard-coded for APS 32-ID
* Settings file location not configurable (always ~/.xanes_gui_settings.json)
* No built-in curve generation or fitting tools
* Plot downsampling not implemented for very large datasets (>10,000 points)

Migration Notes
---------------

From Tkinter Version
~~~~~~~~~~~~~~~~~~~~~

**Configuration Migration**

The PyQt5 version uses a different settings file format:

**Old (Tkinter)**: INI-style configuration file

**New (PyQt5)**: JSON format in ~/.xanes_gui_settings.json

To migrate:

1. Run the new GUI once to generate settings file
2. Open ~/.xanes_gui_settings.json
3. Update PV names and paths from your old configuration

**PV Settings**

All PV settings now configured in the "PV Settings" tab instead of separate
configuration file. Update these on first run.

**Curve Files**

Curve files are compatible. No changes needed to NPY or CSV reference curves.

**Scripts**

XANES start scripts are compatible if they read from EPICS PVs or ~/energies.npy.
No changes needed.

Future Plans
------------

Version 1.1.0 (Planned)
~~~~~~~~~~~~~~~~~~~~~~~

* Configurable scan parameter PV names (remove 32ida hard-coding)
* Configurable safety PV names
* Export calibration data to file
* Import/export settings profiles
* Plot data cursors and measurements
* Curve fitting tools (edge position, normalization)

Version 1.2.0 (Planned)
~~~~~~~~~~~~~~~~~~~~~~~

* Multi-element XANES support
* Batch scan configuration
* Automated edge finding from spectra
* Integration with data analysis pipelines
* ROI-based imaging mode
* Remote monitoring via web interface

Version 2.0.0 (Planned)
~~~~~~~~~~~~~~~~~~~~~~~

* Plugin architecture for custom energy methods
* Database backend for scan history
* Advanced plotting (2D maps, time series)
* Machine learning edge classification
* Automated quality control
* Cloud data storage integration

Contributing
------------

See CONTRIBUTING.md for development guidelines.

To report bugs or request features, please open an issue at:
https://github.com/yourusername/xanes-gui/issues

Versioning Policy
-----------------

* **Major version** (X.0.0): Breaking changes, major rewrites
* **Minor version** (0.X.0): New features, non-breaking changes
* **Patch version** (0.0.X): Bug fixes, documentation updates

Deprecation Policy
------------------

Features marked as deprecated will be maintained for at least one minor version
before removal. Deprecation warnings will appear in the log.

License
-------

See :doc:`license` for license information.
