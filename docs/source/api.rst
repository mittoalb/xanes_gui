API Reference
=============

This page provides detailed API documentation for developers.

Main Application Class
-----------------------

XANESGui
~~~~~~~~

.. class:: XANESGui(QMainWindow)

   Main application window for XANES GUI.

   **Initialization:**

   .. code-block:: python

      app = QApplication(sys.argv)
      gui = XANESGui()
      gui.show()
      sys.exit(app.exec_())

   **Attributes:**

   * ``curve_data`` (dict): Stores loaded curve data as {label: (energies, intensities)}
   * ``current_edge_energy`` (float): Currently selected K-edge energy in keV
   * ``calibration_energies`` (list): Energy points from calibration scan
   * ``calibration_sums`` (list): Detector sums from calibration scan
   * ``custom_energies`` (numpy.ndarray): Custom energy array for Method 3
   * ``pv_settings`` (dict): EPICS PV configuration and paths

   **Methods:**

   .. method:: load_curve(file_path, label=None)

      Load a reference curve from NPY or CSV file.

      :param file_path: Path to curve file
      :type file_path: str
      :param label: Display label (optional, defaults to filename)
      :type label: str
      :return: True if loaded successfully
      :rtype: bool

   .. method:: plot_curve(energies, intensities, label, color=None)

      Plot a curve on the main plot widget.

      :param energies: Energy values in keV
      :type energies: numpy.ndarray
      :param intensities: Intensity values (arbitrary units)
      :type intensities: numpy.ndarray
      :param label: Curve label for legend
      :type label: str
      :param color: Plot color (optional, auto-assigned if None)
      :type color: str or tuple

   .. method:: calculate_edge_shift(energies, intensities, theoretical_edge)

      Calculate edge shift from calibrated curve.

      :param energies: Energy values in keV
      :type energies: numpy.ndarray
      :param intensities: Intensity values
      :type intensities: numpy.ndarray
      :param theoretical_edge: Theoretical edge energy in keV
      :type theoretical_edge: float
      :return: Edge shift in eV
      :rtype: float

      **Algorithm:**

      1. Normalize intensities to [0, 1]
      2. Calculate derivative
      3. Find maximum derivative position (measured edge)
      4. Return (measured - theoretical) * 1000

   .. method:: start_calibration()

      Launch calibration scan in background thread.

      Creates a ``CalibrationWorker`` thread and connects signals.

   .. method:: start_xanes_script()

      Launch XANES acquisition script.

      Creates a ``StartScriptWorker`` thread and executes configured bash script.

   .. method:: stop_scan()

      Abort current calibration or script operation.

      Sends stop signals to worker threads and triggers safety PVs.

   .. method:: load_settings()

      Load GUI settings from JSON file.

      :return: Settings dictionary
      :rtype: dict

      Settings file: ``~/.xanes_gui_settings.json``

   .. method:: save_settings()

      Save current GUI settings to JSON file.

      Persists PV configuration, paths, and UI state.

Worker Threads
--------------

CalibrationWorker
~~~~~~~~~~~~~~~~~

.. class:: CalibrationWorker(QThread)

   Background thread for calibration scans.

   **Signals:**

   * ``progress_update(int)`` - Emits progress percentage (0-100)
   * ``log_message(str)`` - Emits log messages for display
   * ``scan_complete()`` - Emitted when scan finishes successfully
   * ``data_point(float, float)`` - Emits (energy, detector_sum) for each point

   **Attributes:**

   * ``energies`` (list): Energy points to scan
   * ``pv_settings`` (dict): EPICS PV configuration
   * ``stop_requested`` (bool): Flag for abort request

   **Methods:**

   .. method:: run()

      Execute calibration scan.

      For each energy point:

      1. Set energy via EPICS PV
      2. Wait for readback confirmation (if configured)
      3. Apply settling time
      4. Trigger detector acquisition
      5. Wait for acquisition complete
      6. Read detector image via PVAccess
      7. Sum all pixels
      8. Emit data_point signal

   .. method:: request_stop()

      Request scan abort.

      Sets ``stop_requested`` flag; scan aborts after current point.

StartScriptWorker
~~~~~~~~~~~~~~~~~

.. class:: StartScriptWorker(QThread)

   Background thread for XANES script execution.

   **Signals:**

   * ``log_message(str)`` - Emits script output lines
   * ``script_complete(int)`` - Emits script return code

   **Attributes:**

   * ``script_path`` (str): Path to bash script
   * ``process`` (subprocess.Popen): Script process

   **Methods:**

   .. method:: run()

      Execute bash script and stream output.

      Uses ``subprocess.Popen`` with process group for clean termination.

   .. method:: stop()

      Terminate script process.

      Sends SIGTERM to process group.

EPICS Interface
---------------

PV Operations
~~~~~~~~~~~~~

**Channel Access (pyepics):**

.. code-block:: python

   import epics

   # Set energy
   epics.caput('32id:TXMOptics:EnergySet', 7.112)

   # Read energy
   energy = epics.caget('32id:TXMOptics:Energy_RBV')

   # Trigger acquisition
   epics.caput('32idbSP1:cam1:Acquire', 1)

   # Monitor acquisition status
   status = epics.caget('32idbSP1:cam1:Acquire_RBV')

**PVAccess (pvaccess):**

.. code-block:: python

   from pvaccess import Channel

   # Create channel
   chan = Channel('32idbSP1:Pva1:Image')

   # Get NTNDArray
   image = chan.get()

   # Extract data
   data = image['value'][0]['ubyteValue']

File Format Specifications
---------------------------

NPY Files
~~~~~~~~~

**Binary Format:**

.. code-block:: python

   import numpy as np

   # Save curve
   data = np.column_stack([energies, intensities])
   np.save('Fe_calibrated.npy', data)

   # Load curve
   data = np.load('Fe_calibrated.npy')
   energies = data[:, 0]
   intensities = data[:, 1]

**Text Format:**

.. code-block:: text

   # Two columns: energy (keV), intensity
   6.912 0.123
   6.913 0.125
   6.914 0.128

CSV Files
~~~~~~~~~

**Format:**

.. code-block:: text

   # Comma or space-separated
   6.912,0.123
   6.913,0.125
   6.914,0.128

Custom Energy Arrays
~~~~~~~~~~~~~~~~~~~~

**Format:**

.. code-block:: text

   # One energy per line (keV)
   6.912
   6.913
   6.914

Settings File Format
--------------------

JSON Structure
~~~~~~~~~~~~~~

**File:** ``~/.xanes_gui_settings.json``

.. code-block:: json

   {
     "pva_name": "32idbSP1:Pva1:Image",
     "acquire_pv": "32idbSP1:cam1:Acquire",
     "acquire_rbv_pv": "32idbSP1:cam1:Acquire_RBV",
     "energy_set_pv": "32id:TXMOptics:EnergySet",
     "energy_rb_pv": "32id:TXMOptics:Energy_RBV",
     "settle_time": "0.15",
     "start_sh_path": "/home/user/xanes_start.sh",
     "calibrated_curves_folder": "/path/to/Calibrated/",
     "simulated_curves_folder": "/path/to/Curves/",
     "curve_extension": ".npy",
     "curve_source": "calibrated",
     "energy_method": 0,
     "overlay_mode": false,
     "start_energy": "6.912",
     "end_energy": "7.312",
     "step_energy": "1.0"
   }

Extending the GUI
-----------------

Adding New Energy Methods
~~~~~~~~~~~~~~~~~~~~~~~~~~

1. Add radio button to energy method group:

.. code-block:: python

   self.method4_radio = QRadioButton("Method 4: Description")
   self.energy_method_group.addButton(self.method4_radio, 3)

2. Create method-specific widget:

.. code-block:: python

   self.method4_widget = QWidget()
   # Add controls to widget

3. Add to stacked widget:

.. code-block:: python

   self.energy_stack.addWidget(self.method4_widget)

4. Connect to method selection:

.. code-block:: python

   self.method4_radio.toggled.connect(
       lambda: self.energy_stack.setCurrentWidget(self.method4_widget)
   )

5. Implement energy array generation:

.. code-block:: python

   def get_method4_energies(self):
       # Generate energy array
       return energies

Adding Custom Curve Processing
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Extend ``calculate_edge_shift`` method:

.. code-block:: python

   def custom_edge_detection(self, energies, intensities):
       # Custom algorithm
       # Return edge position
       pass

Adding New EPICS PVs
~~~~~~~~~~~~~~~~~~~~

1. Add to PV Settings tab:

.. code-block:: python

   self.new_pv_entry = QLineEdit()
   pv_layout.addRow("New PV:", self.new_pv_entry)

2. Save/load in settings:

.. code-block:: python

   def save_settings(self):
       settings['new_pv'] = self.new_pv_entry.text()

   def load_settings(self):
       self.new_pv_entry.setText(settings.get('new_pv', ''))

3. Use in worker thread:

.. code-block:: python

   new_pv = epics.PV(self.pv_settings['new_pv'])
   new_pv.put(value)

Constants and Defaults
----------------------

Default Values
~~~~~~~~~~~~~~

.. code-block:: python

   # Energy defaults
   DEFAULT_START_ENERGY = 7.0  # keV
   DEFAULT_END_ENERGY = 7.4    # keV
   DEFAULT_STEP_ENERGY = 1.0   # eV

   # Timing defaults
   DEFAULT_SETTLE_TIME = 0.15  # seconds

   # File extensions
   SUPPORTED_EXTENSIONS = ['.npy', '.csv', '.txt']

   # Plot colors
   PLOT_COLORS = ['#FF6B6B', '#4ECDC4', '#45B7D1',
                  '#FFA07A', '#98D8C8', '#F7DC6F']

K-Edge Database
~~~~~~~~~~~~~~~

.. code-block:: python

   EDGES = [
       ("H", 0.0136),
       ("He", 0.0246),
       # ... (full periodic table)
       ("Fe", 7.112),
       ("Co", 7.709),
       ("Ni", 8.333),
       # ...
   ]

Error Handling
--------------

Exception Classes
~~~~~~~~~~~~~~~~~

Custom exceptions for specific errors:

.. code-block:: python

   class EPICSConnectionError(Exception):
       """Raised when EPICS PV connection fails"""
       pass

   class InvalidEnergyRangeError(Exception):
       """Raised when energy range is invalid"""
       pass

   class CurveLoadError(Exception):
       """Raised when curve file cannot be loaded"""
       pass

Error Handling Pattern
~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   try:
       # EPICS operation
       epics.caput(pv_name, value, timeout=5)
   except epics.ca.CASeverityException as e:
       self.log_message.emit(f"EPICS Error: {e}")
   except Exception as e:
       self.log_message.emit(f"Unexpected error: {e}")

Testing
-------

Unit Test Example
~~~~~~~~~~~~~~~~~

.. code-block:: python

   import unittest
   from xanes_gui import XANESGui

   class TestXANESGui(unittest.TestCase):

       def setUp(self):
           self.app = QApplication([])
           self.gui = XANESGui()

       def test_edge_shift_calculation(self):
           energies = np.linspace(7.0, 7.2, 100)
           intensities = 1 / (1 + np.exp(-(energies - 7.112) * 20))
           shift = self.gui.calculate_edge_shift(
               energies, intensities, 7.112
           )
           self.assertLess(abs(shift), 5.0)  # Within 5 eV

       def tearDown(self):
           self.app.quit()

Integration Test Example
~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   def test_calibration_scan():
       # Requires EPICS IOC running
       gui = XANESGui()
       gui.start_energy_entry.setText("7.0")
       gui.end_energy_entry.setText("7.2")
       gui.step_energy_entry.setText("10.0")
       gui.start_calibration()
       # Wait for completion
       # Verify data

Development Guidelines
----------------------

Code Style
~~~~~~~~~~

* Follow PEP 8
* Use type hints where appropriate
* Document all public methods
* Use descriptive variable names

Thread Safety
~~~~~~~~~~~~~

* All EPICS operations in worker threads
* Use signals/slots for UI updates
* No direct UI manipulation from threads

Performance
~~~~~~~~~~~

* Use numpy for array operations
* Minimize plot redraws
* Cache computed values where possible

See Also
--------

* :doc:`user_guide` - User guide for GUI features
* :doc:`configuration` - Configuration details
* :doc:`troubleshooting` - Common issues and solutions
