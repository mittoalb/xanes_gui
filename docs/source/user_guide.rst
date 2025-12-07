User Guide
==========

This comprehensive guide covers all features and functionality of the XANES GUI.

Interface Overview
------------------

The XANES GUI consists of two main tabs:

1. **Scan Tab**: Main interface for calibration and data collection
2. **PV Settings Tab**: EPICS PV configuration

Scan Tab Layout
~~~~~~~~~~~~~~~

**Plot Area (Left)**

The main plotting region displays:

* Reference curves (calibrated and simulated)
* Calibration scan data (live updates)
* K-edge markers
* Interactive zoom and pan controls

**Control Panel (Right)**

* Edge selection list with filter
* Curve source selector (Calibrated/Simulated)
* Auto-fill scan configuration
* Manual curve loading

**Energy Configuration (Center)**

Three energy range definition methods with mode-specific controls

**Action Buttons (Bottom)**

* Orange **Calibrate**: Perform calibration scan
* Green **Start XANES**: Launch full acquisition
* Red **Stop**: Abort current operation

Energy Range Methods
--------------------

The GUI offers three methods to define energy ranges:

Method 1: Manual (Start/End/Step)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**When to use**: Standard scans with uniform energy spacing

**Configuration**:

* **Start energy (keV)**: Lower bound of energy range
* **End energy (keV)**: Upper bound of energy range
* **Step (eV)**: Energy increment (minimum 1 eV recommended)

**Auto-calculation**: The GUI displays total number of points

Example: Fe K-edge scan

.. code-block:: text

   Start: 6.912 keV
   End: 7.312 keV
   Step: 1.0 eV
   → 401 points

**Tips**:

* Use **Apply to fields** button to auto-fill from selected edge
* Step < 1 eV shows warning but is allowed
* Points calculated as: ``(end - start) * 1000 / step + 1``

Method 2: Select Range on Plot
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**When to use**: Visual selection based on reference curves

**Usage**:

1. Load a reference curve for the element
2. Select **Select range on plot** method
3. Click **Enable Selection**
4. Drag the red region to desired energy range
5. The range and suggested points update automatically

**Features**:

* Visual feedback on the plot
* Auto-suggests points for 1 eV step
* Manually adjust # Points if needed
* Click **Disable Selection** to remove region

Method 3: Import Custom Energy Array
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**When to use**: Non-uniform energy spacing or pre-defined arrays

**Loading from file**:

1. Select **Import custom energy array**
2. Click **Load from CSV/TXT**
3. Choose file with energy values (one per line, in keV)

**Manual entry**:

1. Click **Edit Table**
2. Enter energy values (one per line)
3. Click **Save**

**File format**:

.. code-block:: text

   6.539
   6.540
   6.542
   6.545
   6.550

Reference Curves
----------------

Curve Types
~~~~~~~~~~~

**Calibrated (Measured)**

* Experimental data from calibration scans
* Shows measured edge shifts in eV
* Stored in ``Calibrated/`` folder
* Naming: ``Element_calibrated.npy`` or ``Element.npy``

**Simulated**

* Theoretical absorption spectra
* No edge shift calculation
* Stored in ``Curves/`` folder
* Naming: ``Element.npy``

Loading Curves
~~~~~~~~~~~~~~

**Automatic loading**:

1. Select curve source (Calibrated/Simulated)
2. Click element in edge list
3. Curve loads and plots automatically
4. Edge marker (orange dashed line) appears

**Manual loading**:

1. Click **Load curve (CSV/NPY)**
2. Select file
3. Curve plots with filename as label

Edge Shift Calculation
~~~~~~~~~~~~~~~~~~~~~~~

For calibrated curves:

1. Curve is normalized (min-max scaling)
2. Derivative is calculated
3. Maximum derivative position = measured edge
4. Shift = (measured - theoretical) * 1000 eV

Displayed as: ``Fe (calibrated) [Δ=+2.3eV]``

Overlay Mode
~~~~~~~~~~~~

Check **Overlay on existing plot** to:

* Compare multiple elements
* Keep calibration data while loading references
* Build composite plots

Uncheck to clear plot before loading new curves.

Calibration Scans
-----------------

Purpose
~~~~~~~

Calibration scans measure:

* Detector response vs. energy
* Actual K-edge positions
* System calibration validation

Procedure
~~~~~~~~~

1. **Configure energy range** using any method
2. **Click Calibrate button**
3. **Monitor progress**:

   * Progress bar fills as scan proceeds
   * Log shows energy set confirmations and detector sums
   * Plot updates in real-time with green markers

4. **Completion**: Buttons re-enable, data available for review

What Happens During Calibration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

For each energy point:

1. Set energy via ``EnergySet`` PV
2. Wait for readback confirmation (if configured)
3. Apply settling time
4. Trigger detector acquisition
5. Wait for acquisition complete
6. Read detector image via PVAccess
7. Sum all pixels
8. Log result and update plot

Abort Calibration
~~~~~~~~~~~~~~~~~

Click **Stop** button:

* Aborts scan after current point
* Partial data retained and plotted
* Safety PVs triggered (EPID, shaker)

XANES Data Collection
---------------------

Start Script Workflow
~~~~~~~~~~~~~~~~~~~~~

The **Start XANES** button:

1. Validates energy configuration
2. Sets EPICS PVs:

   * ``XanesStart``: Start energy
   * ``XanesEnd``: End energy
   * ``XanesStep``: Step size
   * Or saves custom energy array to ``~/energies.npy``

3. Launches bash script (configured in PV Settings)
4. Script typically:

   * SSHes to acquisition computer
   * Runs tomoscan energy command
   * Performs full XANES acquisition

Monitoring
~~~~~~~~~~

* Script output streams to log window
* Progress shown as script executes
* No live plot updates (data saved externally)

Stop Operation
~~~~~~~~~~~~~~

Click **Stop**:

* Terminates script process group
* Sends safety PV commands
* Resets button states

PV Settings Configuration
-------------------------

Required PVs
~~~~~~~~~~~~

**Detector & Acquisition**:

* **Detector PVA (NTNDArray)**: ``32idbSP1:Pva1:Image``
* **cam:Acquire PV**: ``32idbSP1:cam1:Acquire``
* **cam:Acquire_RBV PV**: ``32idbSP1:cam1:Acquire_RBV``

**Energy Control**:

* **Energy set PV**: ``32id:TXMOptics:EnergySet``
* **Energy RB PV (opt)**: ``32id:TXMOptics:Energy_RBV``
* **Settle (s)**: ``0.15`` (settle time after energy change)

**Scan Parameters**:

* **Start .sh path**: ``/path/to/xanes_start.sh``

Curve Directories
~~~~~~~~~~~~~~~~~

* **Calibrated curves folder**: ``/path/to/Calibrated/``
* **Simulated curves folder**: ``/path/to/Curves/``
* **Ref curve extension**: ``.npy`` or ``.csv``

Browse buttons available for easy selection.

File Formats
~~~~~~~~~~~~

**NPY files (preferred)**:

Binary numpy arrays, 2xN or Nx2 shape, or text format with 2 columns

**CSV files**:

Comma or space-separated, first column = energy (keV), second = intensity

Advanced Features
-----------------

Custom Energy Arrays
~~~~~~~~~~~~~~~~~~~~

For specialized scans:

1. Pre-edge region: Fine step (0.5 eV)
2. Edge region: Very fine step (0.2 eV)
3. Post-edge: Coarse step (2 eV)

Create file:

.. code-block:: text

   6.500
   6.505
   6.510
   ...
   6.535
   6.537
   6.539
   ...
   6.600
   6.602
   6.604

Edge List Filtering
~~~~~~~~~~~~~~~~~~~

Type in **Filter** box to search:

* Element symbol: ``fe`` matches Fe
* Edge energy: ``7.1`` matches Fe, Co
* Partial match supported

Keyboard Shortcuts
~~~~~~~~~~~~~~~~~~

* **Mouse wheel**: Zoom in/out on plot
* **Left click + drag**: Pan plot
* **Right click**: Reset zoom

Log Window
~~~~~~~~~~

* Timestamped entries
* Auto-scrolls to latest
* Copy-pasteable for records
* Shows all EPICS operations

Troubleshooting Tips
--------------------

Calibration Not Starting
~~~~~~~~~~~~~~~~~~~~~~~~

* Check energy range is valid (start < end, step > 0)
* Verify PV connections in log
* Test manual ``caput`` to energy PV

Plot Not Updating
~~~~~~~~~~~~~~~~~

* Check overlay mode setting
* Ensure file paths are correct
* Verify file format (2 columns)

Energy Not Changing
~~~~~~~~~~~~~~~~~~~

* Check EPICS connection
* Verify energy set PV is correct
* Look for error messages in log

Best Practices
--------------

1. **Test with calibration** before full XANES scan
2. **Use reference curves** to verify edge positions
3. **Monitor log** for EPICS errors
4. **Save calibration data** for future reference
5. **Check settling time** is appropriate for your system
