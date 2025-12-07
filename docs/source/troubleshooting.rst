Troubleshooting
===============

This guide covers common issues and their solutions.

Installation Issues
-------------------

ImportError: No module named 'PyQt5'
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Symptom:**

.. code-block:: text

   ImportError: No module named 'PyQt5'

**Solution:**

Install PyQt5:

.. code-block:: bash

   pip install PyQt5

Or with conda:

.. code-block:: bash

   conda install pyqt

**Verification:**

.. code-block:: bash

   python -c "import PyQt5; print(PyQt5.__version__)"

ImportError: No module named 'epics'
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Symptom:**

.. code-block:: text

   ImportError: No module named 'epics'

**Solution:**

Install pyepics:

.. code-block:: bash

   pip install pyepics

**Verification:**

.. code-block:: bash

   python -c "import epics; print(epics.__version__)"
   caget IOC:test:PV

ImportError: No module named 'pvaccess'
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Symptom:**

.. code-block:: text

   ImportError: No module named 'pvaccess'

**Solution:**

Install pvaccess:

.. code-block:: bash

   pip install pvaccess

**Note**: Requires EPICS 7. If unavailable, install from conda-forge:

.. code-block:: bash

   conda install -c conda-forge pvaccess

**Verification:**

.. code-block:: bash

   python -c "import pvaccess; print(pvaccess.__version__)"
   pvget test:pv

EPICS Connection Issues
-----------------------

PV Connection Timeout
~~~~~~~~~~~~~~~~~~~~~

**Symptom:**

Log shows:

.. code-block:: text

   Failed to connect to PV: 32id:TXMOptics:EnergySet

**Causes and Solutions:**

1. **EPICS environment not configured**

   Check variables:

   .. code-block:: bash

      echo $EPICS_CA_ADDR_LIST
      echo $EPICS_PVA_ADDR_LIST

   Set if missing:

   .. code-block:: bash

      export EPICS_CA_ADDR_LIST="164.54.53.255"
      export EPICS_CA_AUTO_ADDR_LIST=NO
      export EPICS_PVA_ADDR_LIST="164.54.53.255"

2. **Network connectivity issue**

   Test IOC reachability:

   .. code-block:: bash

      ping <ioc_address>

   Check routing:

   .. code-block:: bash

      traceroute <ioc_address>

3. **Firewall blocking EPICS ports**

   Test ports:

   .. code-block:: bash

      telnet <ioc_address> 5064  # CA
      telnet <ioc_address> 5075  # PVA

   Open firewall if needed:

   .. code-block:: bash

      sudo iptables -A INPUT -p tcp --dport 5064:5065 -j ACCEPT
      sudo iptables -A INPUT -p udp --dport 5064:5065 -j ACCEPT

4. **IOC not running**

   Verify with standalone tools:

   .. code-block:: bash

      caget 32id:TXMOptics:EnergySet
      pvget 32idbSP1:Pva1:Image

   Contact beamline staff if IOC is down.

5. **Incorrect PV name**

   Verify PV exists:

   .. code-block:: bash

      caget -a 32id:TXMOptics:EnergySet

   Check for typos in PV Settings tab.

PVAccess Image Data Not Available
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Symptom:**

.. code-block:: text

   Error reading image data from PVA

**Solutions:**

1. **Check PVA plugin is enabled on areaDetector**

   Verify IOC configuration includes:

   .. code-block:: text

      NDPvaConfigure("PVA1", queueSize, 0, "DET1:cam1:ArrayData", 0, "DET1:Pva1")

2. **Verify image is being produced**

   Check with pvget:

   .. code-block:: bash

      pvget 32idbSP1:Pva1:Image

   Should show NTNDArray structure.

3. **Check data type**

   GUI expects ``ubyteValue`` field. If using different data type (e.g., ``ushortValue``), modify source code:

   .. code-block:: python

      # In CalibrationWorker.run()
      data = image['value'][0]['ushortValue']  # Change from ubyteValue

GUI Behavior Issues
-------------------

Calibration Not Starting
~~~~~~~~~~~~~~~~~~~~~~~~

**Symptom:**

Click **Calibrate** button, nothing happens.

**Checks:**

1. **Verify energy range is valid**

   * Start < End
   * Step > 0
   * Start and End > 0

   Log shows:

   .. code-block:: text

      Invalid energy range

2. **Check for EPICS connection errors**

   Look in log for:

   .. code-block:: text

      Failed to connect to PV: ...

   See `PV Connection Timeout`_ section.

3. **Ensure no scan already running**

   Only one scan can run at a time. Stop existing scan first.

4. **Check button state**

   If button is disabled, a scan may be running. Check progress bar.

Calibration Hangs
~~~~~~~~~~~~~~~~~

**Symptom:**

Calibration starts but stops progressing.

**Checks:**

1. **Energy readback not updating**

   If Energy RB PV is configured, calibration waits for readback. Check:

   .. code-block:: bash

      camonitor 32id:TXMOptics:Energy_RBV

   If not updating, either:

   * Fix monochromator control
   * Clear Energy RB PV field in PV Settings

2. **Detector not acquiring**

   Check acquisition status:

   .. code-block:: bash

      camonitor 32idbSP1:cam1:Acquire_RBV

   Should toggle 0 → 1 → 0 for each point.

   If stuck at 1:

   .. code-block:: bash

      caput 32idbSP1:cam1:Acquire 0

3. **Settle time too long**

   Check Settle field in PV Settings. Reduce if excessive (e.g., 10 seconds).

4. **PVAccess image timeout**

   Increase timeout in source code:

   .. code-block:: python

      image = chan.get(timeout=10.0)  # Increase from default

Plot Issues
-----------

Plot Not Updating During Calibration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Symptom:**

Progress bar moves but plot stays empty.

**Solutions:**

1. **Check plot visibility**

   Ensure plot widget is not hidden by splitter. Drag splitter to resize.

2. **Check overlay mode**

   If many curves loaded, new data might be off-scale. Uncheck **Overlay** and try again.

3. **Check for exceptions in log**

   Look for errors like:

   .. code-block:: text

      Error plotting data: ...

4. **Reset plot zoom**

   Right-click on plot to reset auto-range.

Curves Not Loading
~~~~~~~~~~~~~~~~~~

**Symptom:**

Click element in list, no curve appears.

**Checks:**

1. **Verify file exists**

   Check directory:

   .. code-block:: bash

      ls /path/to/Calibrated/Fe_calibrated.npy
      ls /path/to/Calibrated/Fe.npy

   File should exist with one of these names.

2. **Check file permissions**

   .. code-block:: bash

      ls -l /path/to/Calibrated/Fe_calibrated.npy

   Should be readable (r-- permission).

3. **Verify directory path is correct**

   In PV Settings tab, check:

   * Calibrated curves folder path
   * Simulated curves folder path

   Path should be absolute, not relative.

4. **Check file format**

   Load in Python to verify:

   .. code-block:: python

      import numpy as np
      data = np.load('Fe_calibrated.npy')
      print(data.shape)  # Should be (N, 2) or (2, N)

   If text format:

   .. code-block:: bash

      head Fe_calibrated.npy

   Should show two columns of numbers.

5. **Check curve extension setting**

   In PV Settings tab, ensure extension matches files (e.g., ``.npy``).

Plot Scale Issues
~~~~~~~~~~~~~~~~~

**Symptom:**

Curves appear as flat lines or are invisible.

**Solutions:**

1. **Reset auto-range**

   Right-click on plot → **Auto-range**

2. **Check data range**

   Verify curve data is reasonable:

   .. code-block:: python

      import numpy as np
      data = np.load('Fe_calibrated.npy')
      print(f"Energy range: {data[:, 0].min()} - {data[:, 0].max()}")
      print(f"Intensity range: {data[:, 1].min()} - {data[:, 1].max()}")

   Energy should be in keV (e.g., 7.0-8.0), not eV.

3. **Disable overlay mode**

   If multiple curves with different scales, uncheck **Overlay** and reload.

Energy Range Selection Issues
------------------------------

Plot Selection Not Working
~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Symptom:**

Can't enable plot selection or region doesn't appear.

**Solutions:**

1. **Load a curve first**

   Plot selection requires a curve to be loaded. Select an element from the list.

2. **Check if already enabled**

   Look for red region on plot. If present, selection is active.

3. **Disable and re-enable**

   Click **Disable Selection**, then **Enable Selection** again.

4. **Check for errors in log**

   Look for exceptions when clicking **Enable Selection**.

Region Doesn't Move
~~~~~~~~~~~~~~~~~~~

**Symptom:**

Red region appears but can't be dragged.

**Solutions:**

1. **Click inside the region**

   Must click on the red shaded area, not the edges.

2. **Check zoom level**

   Zoom out if region is larger than visible area.

3. **Reset region**

   Disable and enable selection to reset.

Custom Energy Array Not Loading
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Symptom:**

Click **Load from CSV/TXT**, file loads, but energies not used.

**Checks:**

1. **Verify file format**

   .. code-block:: bash

      head energies.txt

   Should show one energy value per line (in keV):

   .. code-block:: text

      7.000
      7.001
      7.002

2. **Check for parsing errors in log**

   Look for:

   .. code-block:: text

      Error loading custom energies: ...

3. **Verify energy units**

   Energies should be in keV, not eV. If in eV, divide by 1000.

4. **Check for blank lines or headers**

   Remove any header lines or blank lines from file.

XANES Script Issues
-------------------

Start Script Not Executing
~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Symptom:**

Click **Start XANES**, no output in log.

**Checks:**

1. **Verify script path is set**

   In PV Settings tab, check **Start .sh path** is filled.

2. **Check script exists**

   .. code-block:: bash

      ls -l /path/to/xanes_start.sh

3. **Check script is executable**

   .. code-block:: bash

      chmod +x /path/to/xanes_start.sh

4. **Test script manually**

   .. code-block:: bash

      /path/to/xanes_start.sh

   Should execute without errors.

5. **Check for shebang**

   Script should start with:

   .. code-block:: bash

      #!/bin/bash

Script Fails Immediately
~~~~~~~~~~~~~~~~~~~~~~~~~

**Symptom:**

Script starts but exits with error.

**Debugging:**

1. **Check log for error message**

   Script output appears in log window.

2. **Run script manually with same parameters**

   .. code-block:: bash

      export XANES_START=$(caget -t 32ida:XanesStart)
      export XANES_END=$(caget -t 32ida:XanesEnd)
      export XANES_STEP=$(caget -t 32ida:XanesStep)
      /path/to/xanes_start.sh

3. **Check script dependencies**

   Ensure required commands available:

   .. code-block:: bash

      which ssh
      which tomoscan
      which caget

4. **Verify SSH configuration**

   If script uses SSH, test:

   .. code-block:: bash

      ssh user@acq_computer "echo SSH works"

   Should not prompt for password (use key-based auth).

5. **Check for syntax errors**

   .. code-block:: bash

      bash -n /path/to/xanes_start.sh

Script Can't Be Stopped
~~~~~~~~~~~~~~~~~~~~~~~

**Symptom:**

Click **Stop**, script continues running.

**Solutions:**

1. **Wait for current operation**

   Stop signal is sent, but script may finish current step first.

2. **Kill process manually**

   Find process:

   .. code-block:: bash

      ps aux | grep xanes_start.sh

   Kill it:

   .. code-block:: bash

      kill -9 <PID>

3. **Check script handles signals**

   Add to script:

   .. code-block:: bash

      trap "echo Caught signal; exit 1" SIGTERM SIGINT

Performance Issues
------------------

GUI Slow or Unresponsive
~~~~~~~~~~~~~~~~~~~~~~~~~

**Causes and Solutions:**

1. **Too many points in calibration**

   Reduce number of points:

   * Increase step size
   * Decrease energy range

2. **Large curve files**

   Use NPY format instead of CSV for faster loading.

3. **Many curves overlaid**

   Disable overlay mode and load fewer curves.

4. **Insufficient system resources**

   Check CPU and memory:

   .. code-block:: bash

      top

   Close other applications.

Plot Rendering Slow
~~~~~~~~~~~~~~~~~~~

**Solutions:**

1. **Reduce plot complexity**

   * Fewer curves
   * Fewer points per curve
   * Disable anti-aliasing (modify source)

2. **Use downsampling**

   Modify source to downsample before plotting:

   .. code-block:: python

      # Plot every 10th point
      plot_widget.plot(energies[::10], intensities[::10])

3. **Update pyqtgraph**

   .. code-block:: bash

      pip install --upgrade pyqtgraph

Data Issues
-----------

Edge Shift Calculation Wrong
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Symptom:**

Displayed edge shift doesn't match expectations.

**Checks:**

1. **Verify theoretical edge energy**

   Check EDGES list in source code:

   .. code-block:: python

      ("Fe", 7.112),  # Fe K-edge at 7.112 keV

2. **Check curve energy units**

   Curve energies must be in keV. If in eV, shift will be 1000x wrong.

3. **Inspect derivative**

   Edge shift uses max derivative position. For noisy data, derivative may be incorrect.

   Smooth curve before loading:

   .. code-block:: python

      from scipy.ndimage import gaussian_filter1d
      intensities_smooth = gaussian_filter1d(intensities, sigma=2)

4. **Check for multiple edges**

   If curve contains multiple edges, derivative may find wrong one.

Calibration Data Looks Wrong
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Symptom:**

Calibration scan produces unexpected values.

**Checks:**

1. **Verify detector is acquiring**

   Check camera:

   .. code-block:: bash

      caget 32idbSP1:cam1:Acquire_RBV

   View image:

   .. code-block:: bash

      pvget 32idbSP1:Pva1:Image

2. **Check for saturation**

   If detector sum is constant (e.g., always 255 * N_pixels), detector may be saturated.

   Reduce exposure time or attenuate beam.

3. **Check energy is changing**

   Monitor energy:

   .. code-block:: bash

      camonitor 32id:TXMOptics:Energy_RBV

   Should change with each calibration point.

4. **Verify sample is in beam**

   Ensure calibration foil or sample is properly positioned.

5. **Check for beam dump**

   If beam is dumped during scan, detector sums will drop to zero.

Advanced Troubleshooting
------------------------

Enable Debug Logging
~~~~~~~~~~~~~~~~~~~~

Add to beginning of ``xanes_gui.py``:

.. code-block:: python

   import logging
   logging.basicConfig(level=logging.DEBUG)

Run from terminal to see debug output:

.. code-block:: bash

   python xanes_gui.py 2>&1 | tee debug.log

Check for Thread Deadlocks
~~~~~~~~~~~~~~~~~~~~~~~~~~~

If GUI freezes:

1. **Send SIGQUIT to get thread dump**

   .. code-block:: bash

      kill -QUIT <PID>

2. **Check for exceptions in worker threads**

   Add exception logging:

   .. code-block:: python

      try:
          # worker code
      except Exception as e:
          logging.exception("Worker thread error:")

Inspect EPICS Traffic
~~~~~~~~~~~~~~~~~~~~~~

Use ``camonitor`` to watch PV changes:

.. code-block:: bash

   camonitor 32id:TXMOptics:EnergySet 32id:TXMOptics:Energy_RBV \
            32idbSP1:cam1:Acquire 32idbSP1:cam1:Acquire_RBV

Should show PV updates during calibration.

Profile Performance
~~~~~~~~~~~~~~~~~~~

Add profiling:

.. code-block:: python

   import cProfile
   import pstats

   profiler = cProfile.Profile()
   profiler.enable()

   # Run calibration

   profiler.disable()
   stats = pstats.Stats(profiler)
   stats.sort_stats('cumulative')
   stats.print_stats(20)

Getting Help
------------

If problems persist:

1. **Check documentation**

   * :doc:`user_guide` - Usage instructions
   * :doc:`configuration` - Configuration details
   * :doc:`api` - API reference

2. **Check log file**

   Save log output and review for error messages.

3. **Test with minimal configuration**

   * Test single edge
   * Use manual energy method
   * Disable overlay mode
   * Use small energy range

4. **Contact support**

   Provide:

   * XANES GUI version
   * Operating system and Python version
   * Full error messages from log
   * Steps to reproduce
   * Settings file content
   * Output of ``caget`` commands for relevant PVs

5. **Report bugs**

   Submit issues at: https://github.com/yourusername/xanes-gui/issues

   Include:

   * Detailed description
   * Expected vs. actual behavior
   * Minimal reproducible example
   * Log output
   * System information
