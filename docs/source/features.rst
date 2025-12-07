Features
========

This page provides detailed descriptions of all XANES GUI features.

Dark Theme Interface
--------------------

The GUI uses a dark theme optimized for beamline environments:

* Reduces eye strain during long acquisition sessions
* High contrast for better visibility in dimly lit hutches
* Professional appearance with consistent styling
* Color-coded buttons (orange=calibrate, green=start, red=stop)

Dual Curve Support
------------------

Calibrated Curves
~~~~~~~~~~~~~~~~~

**Source**: Experimental measurements from calibration scans

**Features**:

* Stored in ``Calibrated/`` folder
* Automatic edge shift calculation
* Shows measured edge position vs. theoretical
* Format: ``Element_calibrated.npy`` or ``Element.npy``

**Edge Shift Calculation**:

1. Normalize curve (min-max scaling)
2. Calculate derivative
3. Find maximum derivative position (measured edge)
4. Compute shift: ``(measured - theoretical) * 1000 eV``

Example display: ``Fe (calibrated) [Δ=+2.3eV]``

Simulated Curves
~~~~~~~~~~~~~~~~

**Source**: Theoretical absorption spectra

**Features**:

* Stored in ``Curves/`` folder
* No edge shift calculation
* Useful for planning scans
* Format: ``Element.npy``

Energy Range Definition
-----------------------

Three Methods for Maximum Flexibility
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Method 1: Manual Entry**

Best for: Standard scans with known parameters

* Enter start, end, step directly
* Auto-calculation of total points
* Warning for steps < 1 eV
* **Apply to fields** button for quick setup

**Method 2: Plot Selection**

Best for: Visual selection based on reference curves

* Interactive red region on plot
* Drag to select energy range
* Specify integer step size (1, 2, 3... eV)
* Exact step size preserved using np.arange
* Both extremes always included
* Real-time range display

**Method 3: Custom Energy Array**

Best for: Non-uniform spacing or specialized scans

* Load from CSV/TXT file
* Manual entry via table editor
* Support for pre-edge, edge, post-edge with different steps
* Unlimited flexibility

File Format Support
-------------------

NPY Files
~~~~~~~~~

**Binary Format** (Preferred)

* Fast loading
* Compact storage
* 2xN or Nx2 numpy arrays

**Text Format**

* Space or comma-separated
* Two columns: energy (keV), intensity
* Auto-detection of format

CSV Files
~~~~~~~~~

* Comma or space-separated
* First column: energy (keV)
* Second column: intensity (arbitrary units)

Custom Energy Arrays
~~~~~~~~~~~~~~~~~~~~

* One energy value per line
* Energy in keV
* No header required

Example:

.. code-block:: text

   6.539
   6.540
   6.542
   6.545
   6.550

Real-Time Calibration
---------------------

Live Plot Updates
~~~~~~~~~~~~~~~~~

During calibration scans:

* Plot updates with each new energy point
* Green markers show measured data
* Progress bar indicates completion
* Log shows energy changes and detector sums

Thread-Safe Operation
~~~~~~~~~~~~~~~~~~~~~~

* Non-blocking UI during scans
* Cancel operation at any time
* Partial data retained on abort
* Safety PVs triggered on stop

Data Acquisition
~~~~~~~~~~~~~~~~

For each energy point:

1. Set energy via EPICS PV
2. Wait for readback confirmation (optional)
3. Apply settling time
4. Trigger detector acquisition
5. Wait for acquisition complete
6. Read detector image via PVAccess
7. Sum all pixels
8. Update plot and log

EPICS Integration
-----------------

Channel Access (CA)
~~~~~~~~~~~~~~~~~~~

Used for:

* Energy set/readback PVs
* Camera acquisition control
* Scan parameter PVs (XanesStart, XanesEnd, XanesStep)

PVAccess (PVA)
~~~~~~~~~~~~~~

Used for:

* Detector image acquisition (NTNDArray)
* High-speed data transfer
* Structured data types

Configuration
~~~~~~~~~~~~~

All EPICS PVs configurable in PV Settings tab:

* Detector PVA name
* Energy control PVs
* Acquisition PVs
* Safety PVs (EPID, shaker)

Script Integration
------------------

Embedded Terminal Execution
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The **Start XANES** button:

* Sets EPICS PVs with scan parameters
* Saves custom energy array to ``~/energies.npy``
* Executes Python script in embedded terminal
* Real-time color-coded output display
* No external terminal windows

Smart Execution Detection
~~~~~~~~~~~~~~~~~~~~~~~~~~

Automatically chooses local or remote execution:

* Checks if script file exists locally
* Compares hostname with configured remote host
* Runs locally if on same machine
* Uses SSH if remote execution needed

**Detection logic**:

1. Exact hostname match (e.g., "gauss" == "gauss")
2. Short hostname match (e.g., "volta" from "volta.xray.aps.anl.gov")
3. Localhost variants ("localhost", "127.0.0.1")
4. Script file exists at configured path

SSH Configuration
~~~~~~~~~~~~~~~~~

Configurable in PV Settings tab:

* Remote user (e.g., "usertxm")
* Remote host (e.g., "gauss")
* Conda environment (e.g., "tomoscan")
* Working directory
* Conda installation path
* Python script path

Local Execution
~~~~~~~~~~~~~~~

When running locally:

.. code-block:: bash

   cd <work_dir>
   source <conda_path>/etc/profile.d/conda.sh
   conda activate <conda_env>
   python <script_name>

Remote Execution (SSH)
~~~~~~~~~~~~~~~~~~~~~~

When running remotely:

.. code-block:: bash

   ssh -t <user>@<host> "
     cd <work_dir> &&
     source <conda_path>/etc/profile.d/conda.sh &&
     conda activate <conda_env> &&
     python <script_name>
   "

Process Management
~~~~~~~~~~~~~~~~~~

* Process group creation for clean termination
* SIGTERM sent to entire process group on stop
* Line-buffered output streaming
* Return code checking
* Graceful error handling

Terminal Output Features
~~~~~~~~~~~~~~~~~~~~~~~~

**Color-coded messages**:

* Red: Errors and failures
* Orange: Warnings
* Blue: Operations (energy changes, acquisitions)
* Yellow: Data outputs (sum values, points)
* Green: Success messages and general info
* Gray: Timestamps

**Controls**:

* Auto-scroll to latest output
* Clear button to reset terminal
* Terminal persists between runs
* Copy-pasteable output

Interactive Plotting
--------------------

Zoom and Pan
~~~~~~~~~~~~

* **Mouse wheel**: Zoom in/out
* **Left click + drag**: Pan plot
* **Right click**: Reset zoom to auto-range
* **Double click**: Auto-range both axes

Legend
~~~~~~

* Shows all loaded curves
* Displays edge positions
* Shows edge shifts for calibrated curves
* Interactive (click to hide/show curves)

Overlay Mode
~~~~~~~~~~~~

* Check **Overlay on existing plot** to keep curves
* Uncheck to clear plot before loading new data
* Useful for comparing multiple elements
* Maintains calibration data while loading references

Edge Detection
--------------

Automatic K-Edge Finding
~~~~~~~~~~~~~~~~~~~~~~~~~

For calibrated curves:

* Derivative-based edge detection
* Sub-eV precision
* Comparison to theoretical values
* Edge shift calculation and display

Visual Indicators
~~~~~~~~~~~~~~~~~

* Orange dashed vertical line at K-edge
* Edge energy shown in legend
* Edge shift (Δ) displayed for calibrated curves

Edge List and Filtering
------------------------

Complete Element Database
~~~~~~~~~~~~~~~~~~~~~~~~~~

* All K-edges from low to high Z
* Edge energies in keV
* Quick visual identification

Search and Filter
~~~~~~~~~~~~~~~~~

Type in filter box to search by:

* Element symbol (e.g., ``Fe``)
* Edge energy (e.g., ``7.1``)
* Partial matches supported
* Real-time filtering

Comprehensive Terminal Logging
-------------------------------

Timestamped Events
~~~~~~~~~~~~~~~~~~

All operations logged with timestamps:

* EPICS PV changes
* Energy set commands
* Detector acquisitions
* Script output (stdout/stderr)
* SSH connection status
* Errors and warnings

Terminal Features
~~~~~~~~~~~~~~~~~

* Black background with green monospace text
* Color-coded message types
* Automatically scrolls to latest entry
* Maintains readability during long scans
* Copy-pasteable for records
* Clear button to reset display

Terminal Content
~~~~~~~~~~~~~~~~

* Energy set confirmations
* Detector sum values
* Script stdout/stderr streaming
* EPICS connection status
* SSH connection messages
* Local/remote execution indicator
* Return codes and completion status
* Error messages with context

User Interface Features
-----------------------

Responsive Layout
~~~~~~~~~~~~~~~~~

* Resizable plot and control panels
* Adjustable splitter (10px wide handle)
* Maintains proportions on window resize
* Compact design for beamline workstations

Keyboard Shortcuts
~~~~~~~~~~~~~~~~~~

* **Enter**: Apply filter in edge list
* **Tab**: Navigate between fields
* **Escape**: Cancel region selection

Tooltips
~~~~~~~~

* Hover over controls for descriptions
* Helpful hints for complex features
* Context-sensitive help

Validation
~~~~~~~~~~

* Real-time input validation
* Warning messages for invalid ranges
* Prevention of common errors
* Suggested corrections

Safety Features
---------------

Stop Button
~~~~~~~~~~~

* Immediately aborts current operation
* Sends SIGTERM to script processes
* Triggers safety EPICS PVs
* Resets UI state

Confirmation Dialogs
~~~~~~~~~~~~~~~~~~~~

* Prevents accidental operations
* Clear descriptions of actions
* Safe default choices

Error Handling
~~~~~~~~~~~~~~

* Graceful degradation on EPICS errors
* Informative error messages
* Recovery suggestions
* No silent failures

Session Persistence
-------------------

Settings Saved Automatically
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Configuration persisted across sessions:

* PV names and paths
* Curve source selection
* Energy range method
* Window size and position
* Overlay mode state
* Last used energy values

File Location
~~~~~~~~~~~~~

Settings stored in user home directory:

* ``~/.xanes_gui_settings.json``
* Human-readable JSON format
* Manual editing supported

Export and Sharing
------------------

Data Export
~~~~~~~~~~~

Calibration data can be saved as:

* NPY files for future reference
* CSV files for external analysis
* Compatible with standard tools

Configuration Export
~~~~~~~~~~~~~~~~~~~~

* Settings file can be copied/shared
* Useful for multiple beamline computers
* Maintains consistency across systems

Integration Features
--------------------

Compatible with Existing Workflows
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Works with standard tomoscan scripts
* EPICS PV naming conventions supported
* File formats match beamline standards

Extensibility
~~~~~~~~~~~~~

* Modular code structure
* Easy to add new features
* Well-documented API
* Open source (see :doc:`license`)

Performance
-----------

Optimized for Beamline Use
~~~~~~~~~~~~~~~~~~~~~~~~~~

* Fast plot rendering with pyqtgraph
* Non-blocking operations
* Minimal CPU usage during idle
* Quick startup time

Memory Efficient
~~~~~~~~~~~~~~~~

* Streaming data acquisition
* No unnecessary data retention
* Efficient numpy operations
* Garbage collection

Reliability
~~~~~~~~~~~

* Robust EPICS error handling
* Automatic reconnection attempts
* Thread-safe operations
* Tested on beamline systems
