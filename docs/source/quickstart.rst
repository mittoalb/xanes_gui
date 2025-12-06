Quick Start Guide
=================

This guide will help you perform your first XANES scan in 5 minutes.

Launch the Application
-----------------------

Start the XANES GUI:

.. code-block:: bash

   python xanes_gui.py

Or if installed as a package:

.. code-block:: bash

   xanes-gui

First Time Setup
----------------

1. Configure PV Settings
~~~~~~~~~~~~~~~~~~~~~~~~~

Navigate to the **PV Settings** tab and verify:

* **Detector PVA**: ``32idbSP1:Pva1:Image``
* **Energy Set PV**: ``32id:TXMOptics:EnergySet``
* **Start Script Path**: ``/path/to/your/xanes_start.sh``

Click on the paths to browse and select files if needed.

2. Select Reference Curves
~~~~~~~~~~~~~~~~~~~~~~~~~~~

In the **Scan** tab, choose your curve source:

* **Calibrated (measured)**: For measured reference spectra
* **Simulated**: For theoretical spectra

Performing a Calibration Scan
------------------------------

Step 1: Select an Element
~~~~~~~~~~~~~~~~~~~~~~~~~~

1. In the right sidebar, click on an element from the edge list (e.g., **Fe** for iron)
2. The reference curve will load automatically
3. The edge position and energy will be displayed

Step 2: Configure Energy Range
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Choose one of three methods:

**Method A: Manual Entry** (Default)

1. Keep **Manual (Start/End/Step)** selected
2. Click **Apply to fields** to auto-fill based on the selected edge
3. Adjust if needed:

   * Start energy: ``6.912`` keV
   * End energy: ``7.312`` keV
   * Step: ``1.0`` eV

   The GUI will calculate: → 401 points

**Method B: Plot Selection**

1. Select **Select range on plot**
2. Click **Enable Selection**
3. Drag the red region on the plot to select your energy range
4. Adjust **# Points** if needed

**Method C: Custom Energy Array**

1. Select **Import custom energy array**
2. Click **Load from CSV/TXT** or **Edit Table**
3. Enter your custom energy points

Step 3: Run Calibration
~~~~~~~~~~~~~~~~~~~~~~~~

1. Click the orange **Calibrate** button
2. Monitor progress:

   * Progress bar shows scan completion
   * Log shows real-time messages
   * Plot updates with live data

3. Click **Stop** to abort if needed

Performing a XANES Scan
------------------------

After calibration (or directly):

1. Configure energy range (same as calibration)
2. Verify the **Start Script Path** in PV Settings
3. Click the green **Start XANES** button
4. The script will:

   * Set EPICS PVs with energy parameters
   * Launch the XANES acquisition script
   * Display progress in the log

5. Click **Stop** to abort and trigger safety PVs

Understanding the Interface
---------------------------

Main Components
~~~~~~~~~~~~~~~

**Left Panel: Plot Area**

* Displays reference curves and calibration data
* Interactive zoom (mouse wheel) and pan (drag)
* Legend shows loaded curves and edge positions

**Right Panel: Controls**

* Edge selection list (filterable)
* Curve source selection
* Auto-fill configuration
* Overlay toggle

**Bottom Section**

* Energy range method selection
* Progress bar
* Control buttons (Calibrate, Start, Stop)
* Log window

Tips and Best Practices
------------------------

Energy Range Selection
~~~~~~~~~~~~~~~~~~~~~~

* **Standard scan**: ±200 eV around the edge (default)
* **High resolution**: Use 1 eV step or smaller
* **Quick scan**: Use larger step (2-5 eV) for fewer points

Using Reference Curves
~~~~~~~~~~~~~~~~~~~~~~

1. **Calibrated curves**: Show measured edge shifts in eV
2. **Overlay mode**: Check to compare multiple curves
3. **Custom curves**: Load your own CSV/NPY files

Monitoring Calibration
~~~~~~~~~~~~~~~~~~~~~~

* Watch the log for energy changes and detector sums
* Live plot shows the absorption edge forming
* Progress bar indicates remaining points

Common Workflows
----------------

Quick Fe K-edge Scan
~~~~~~~~~~~~~~~~~~~~

1. Select **Fe** from edge list
2. Click **Apply to fields**
3. Click **Calibrate** to measure
4. Click **Start XANES** for full acquisition

Custom Energy Range
~~~~~~~~~~~~~~~~~~~

1. Click **Enable Selection** under plot method
2. Drag red region on a loaded curve
3. Fine-tune # Points field
4. Click **Calibrate** or **Start XANES**

Comparing Edge Positions
~~~~~~~~~~~~~~~~~~~~~~~~~

1. Check **Overlay on existing plot**
2. Select different elements to compare
3. Observe theoretical vs. measured edge shifts

Next Steps
----------

* Read the :doc:`user_guide` for detailed explanations
* Check :doc:`features` for advanced capabilities
* Consult :doc:`troubleshooting` if you encounter issues
