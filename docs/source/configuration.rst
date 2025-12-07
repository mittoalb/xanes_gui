Configuration
=============

This guide covers all configuration options for the XANES GUI.

Settings File
-------------

Location
~~~~~~~~

The GUI stores settings in:

.. code-block:: text

   ~/.xanes_gui_settings.json

This file is automatically created on first run and updated whenever settings change.

Format
~~~~~~

JSON format with the following structure:

.. code-block:: json

   {
     "pva_name": "32idbSP1:Pva1:Image",
     "acquire_pv": "32idbSP1:cam1:Acquire",
     "acquire_rbv_pv": "32idbSP1:cam1:Acquire_RBV",
     "energy_set_pv": "32id:TXMOptics:EnergySet",
     "energy_rb_pv": "32id:TXMOptics:Energy_RBV",
     "settle_time": "0.15",
     "start_sh_path": "/home/user/scripts/xanes_start.sh",
     "calibrated_curves_folder": "/data/Calibrated/",
     "simulated_curves_folder": "/data/Curves/",
     "curve_extension": ".npy",
     "curve_source": "calibrated",
     "energy_method": 0,
     "overlay_mode": false,
     "start_energy": "6.912",
     "end_energy": "7.312",
     "step_energy": "1.0"
   }

Manual Editing
~~~~~~~~~~~~~~

You can manually edit this file while the GUI is closed. The GUI validates settings on load and uses defaults for missing or invalid values.

EPICS PV Configuration
----------------------

Detector Settings
~~~~~~~~~~~~~~~~~

**Detector PVA (NTNDArray)**

* **Purpose**: PVAccess channel for detector image acquisition
* **Format**: ``<prefix>:Pva1:Image``
* **Example**: ``32idbSP1:Pva1:Image``
* **Required**: Yes
* **Type**: NTNDArray structure with image data

The PVA channel must provide NTNDArray format with:

* ``value[0]['ubyteValue']`` - Image data array
* Supports any detector with areaDetector PVA plugin

**Camera Acquire PV**

* **Purpose**: Trigger detector acquisition
* **Format**: ``<prefix>:cam1:Acquire``
* **Example**: ``32idbSP1:cam1:Acquire``
* **Required**: Yes
* **Values**: 0 (stop), 1 (start)

**Camera Acquire Readback PV**

* **Purpose**: Monitor acquisition status
* **Format**: ``<prefix>:cam1:Acquire_RBV``
* **Example**: ``32idbSP1:cam1:Acquire_RBV``
* **Required**: Yes
* **Values**: 0 (idle), 1 (acquiring)

Energy Control Settings
~~~~~~~~~~~~~~~~~~~~~~~

**Energy Set PV**

* **Purpose**: Set monochromator energy
* **Format**: ``<prefix>:EnergySet``
* **Example**: ``32id:TXMOptics:EnergySet``
* **Required**: Yes
* **Units**: keV
* **Precision**: Typically 0.001 keV (1 eV)

**Energy Readback PV** (Optional)

* **Purpose**: Verify energy reached target
* **Format**: ``<prefix>:Energy_RBV``
* **Example**: ``32id:TXMOptics:Energy_RBV``
* **Required**: No (but recommended)
* **Units**: keV

If specified, calibration waits for readback to match setpoint within tolerance before triggering acquisition.

**Settle Time**

* **Purpose**: Time to wait after energy change before acquisition
* **Format**: Decimal seconds
* **Example**: ``0.15``
* **Required**: Yes
* **Range**: 0.0 - 10.0 seconds
* **Typical**: 0.1 - 0.5 seconds

Adjust based on monochromator stabilization time.

Scan Parameter PVs
~~~~~~~~~~~~~~~~~~

These PVs are set by the **Start XANES** button:

* ``32ida:XanesStart`` - Start energy (keV)
* ``32ida:XanesEnd`` - End energy (keV)
* ``32ida:XanesStep`` - Step size (eV)

**Note**: These PV names are currently hard-coded. For different PV names, modify the script or contact support.

For custom energy arrays (Method 3), the array is saved to ``~/energies.npy`` instead.

Safety PVs
~~~~~~~~~~

On scan abort, these PVs are triggered:

* ``32idcTXM:FrameType`` - Set to 2
* ``32idcTXM:EPID_OFF`` - Set to 1
* ``32idcTXM:ShakerON`` - Set to 0

**Note**: These are hard-coded for APS 32-ID. Modify source code for different beamline configurations.

File Path Configuration
-----------------------

Start Script Path
~~~~~~~~~~~~~~~~~

* **Purpose**: Bash script to execute for XANES acquisition
* **Format**: Absolute path
* **Example**: ``/home/beams/USER32ID/scan_scripts/xanes_start.sh``
* **Required**: For **Start XANES** functionality
* **Permissions**: Must be executable (``chmod +x``)

**Script Requirements:**

The script should:

1. Read energy parameters from EPICS PVs or ``~/energies.npy``
2. SSH to acquisition computer (if needed)
3. Execute tomoscan or similar acquisition software
4. Save data to configured location

**Example Script:**

.. code-block:: bash

   #!/bin/bash

   # Read EPICS PVs
   START=$(caget -t 32ida:XanesStart)
   END=$(caget -t 32ida:XanesEnd)
   STEP=$(caget -t 32ida:XanesStep)

   # SSH to acquisition computer and run scan
   ssh -t user@acq_computer "cd /data && \
       tomoscan energy --start $START --end $END --step $STEP"

Curve Directories
~~~~~~~~~~~~~~~~~

**Calibrated Curves Folder**

* **Purpose**: Directory containing measured reference curves
* **Format**: Absolute path
* **Example**: ``/data/xanes/Calibrated/``
* **Required**: For calibrated curve loading
* **Permissions**: Read access required

**Expected Files:**

* ``<Element>_calibrated.npy`` or ``<Element>.npy``
* Example: ``Fe_calibrated.npy``, ``Co_calibrated.npy``

**Simulated Curves Folder**

* **Purpose**: Directory containing theoretical reference curves
* **Format**: Absolute path
* **Example**: ``/data/xanes/Curves/``
* **Required**: For simulated curve loading
* **Permissions**: Read access required

**Expected Files:**

* ``<Element>.npy``
* Example: ``Fe.npy``, ``Co.npy``

**Curve File Extension**

* **Purpose**: File extension for reference curves
* **Format**: Extension with or without dot
* **Example**: ``.npy`` or ``npy``
* **Supported**: ``.npy``, ``.csv``, ``.txt``
* **Recommended**: ``.npy`` (fastest loading)

EPICS Environment Variables
----------------------------

Channel Access
~~~~~~~~~~~~~~

Required environment variables for EPICS CA:

.. code-block:: bash

   # Required: IOC address list
   export EPICS_CA_ADDR_LIST="164.54.53.255"

   # Disable auto address list when using explicit list
   export EPICS_CA_AUTO_ADDR_LIST=NO

   # Optional: Timeout settings
   export EPICS_CA_CONN_TMO=5.0
   export EPICS_CA_BEACON_PERIOD=15.0

   # Optional: Network settings
   export EPICS_CA_MAX_ARRAY_BYTES=16384

Add to ``~/.bashrc`` for persistence.

PVAccess
~~~~~~~~

Required environment variables for EPICS PVA:

.. code-block:: bash

   # Required: IOC address list
   export EPICS_PVA_ADDR_LIST="164.54.53.255"

   # Optional: Timeout settings
   export EPICS_PVA_CONN_TMO=5.0

   # Optional: Broadcast port
   export EPICS_PVA_BROADCAST_PORT=5076

Testing Configuration
~~~~~~~~~~~~~~~~~~~~~

Verify EPICS connectivity:

.. code-block:: bash

   # Test Channel Access
   caget 32id:TXMOptics:EnergySet

   # Test PVAccess
   pvget 32idbSP1:Pva1:Image

If these fail, check:

1. Environment variables are set
2. Network connectivity to IOC
3. Firewall allows EPICS ports (5064, 5065, 5075, 5076)

Energy Configuration
--------------------

Default Energy Range
~~~~~~~~~~~~~~~~~~~~

**Start Energy**

* **Default**: 6.912 keV (Fe K-edge - 200 eV)
* **Range**: 0.1 - 100 keV
* **Precision**: 0.001 keV

**End Energy**

* **Default**: 7.312 keV (Fe K-edge + 200 eV)
* **Range**: 0.1 - 100 keV
* **Precision**: 0.001 keV
* **Constraint**: Must be > Start Energy

**Step Size**

* **Default**: 1.0 eV
* **Range**: > 0 eV
* **Recommended**: ≥ 1.0 eV
* **Warning**: Steps < 1 eV show warning but are allowed

Auto-Fill Configuration
~~~~~~~~~~~~~~~~~~~~~~~

The **Apply to fields** button uses these rules:

* Start = Edge - 200 eV
* End = Edge + 200 eV
* Step = 1.0 eV

This provides ±200 eV coverage around the edge, suitable for most XANES measurements.

UI Configuration
----------------

Curve Source
~~~~~~~~~~~~

* **Options**: Calibrated, Simulated
* **Default**: Calibrated
* **Persistence**: Saved in settings file

Determines which directory to load curves from.

Energy Method
~~~~~~~~~~~~~

* **Options**:
  0. Manual (Start/End/Step)
  1. Select range on plot
  2. Import custom energy array
* **Default**: 0 (Manual)
* **Persistence**: Saved in settings file

Overlay Mode
~~~~~~~~~~~~

* **Options**: On, Off
* **Default**: Off
* **Persistence**: Saved in settings file

When enabled, new curves are added to existing plot. When disabled, plot is cleared before loading.

Window Size and Position
~~~~~~~~~~~~~~~~~~~~~~~~

* **Default**: 1400x900 pixels
* **Persistence**: Not currently saved
* **Splitter Position**: 70% plot, 30% controls

Performance Settings
--------------------

Plot Update Rate
~~~~~~~~~~~~~~~~

During calibration:

* **Update frequency**: Every data point
* **Max points**: No limit
* **Downsampling**: None (all points plotted)

For very long scans (>10,000 points), consider using custom energy arrays with coarser post-edge spacing.

Thread Pool Size
~~~~~~~~~~~~~~~~

* **Calibration thread**: 1 worker
* **Script thread**: 1 worker
* **Total**: 2 concurrent workers maximum

Additional workers can be added by modifying the source code.

Log Window
~~~~~~~~~~

* **Max lines**: Unlimited
* **Auto-scroll**: Always enabled
* **Timestamp format**: ``YYYY-MM-DD HH:MM:SS``

Advanced Configuration
----------------------

Custom PV Names
~~~~~~~~~~~~~~~

To use different PV names, edit ``~/.xanes_gui_settings.json`` directly:

.. code-block:: json

   {
     "pva_name": "MY_BEAMLINE:Det:Pva",
     "acquire_pv": "MY_BEAMLINE:Det:Acquire",
     "energy_set_pv": "MY_BEAMLINE:Mono:Energy"
   }

Multiple Configurations
~~~~~~~~~~~~~~~~~~~~~~~

For multiple beamline computers or configurations:

1. Create separate settings files:

.. code-block:: bash

   ~/.xanes_gui_settings_computer1.json
   ~/.xanes_gui_settings_computer2.json

2. Use symlink to switch:

.. code-block:: bash

   ln -sf ~/.xanes_gui_settings_computer1.json ~/.xanes_gui_settings.json

Custom K-Edge List
~~~~~~~~~~~~~~~~~~

The K-edge list is hard-coded in the source. To add custom edges:

1. Edit ``xanes_gui.py``
2. Modify the ``EDGES`` list:

.. code-block:: python

   EDGES = [
       ("Fe", 7.112),
       ("Co", 7.709),
       ("Custom1", 8.500),  # Add custom edge
   ]

Network Configuration
---------------------

Firewall Rules
~~~~~~~~~~~~~~

EPICS requires these ports:

**Channel Access:**

* TCP/UDP 5064 - CA server
* TCP/UDP 5065 - CA repeater
* TCP/UDP 49152-65535 - CA data connections

**PVAccess:**

* TCP/UDP 5075 - PVA server
* TCP/UDP 5076 - PVA broadcast

**Example iptables rules:**

.. code-block:: bash

   iptables -A INPUT -p tcp --dport 5064:5065 -j ACCEPT
   iptables -A INPUT -p udp --dport 5064:5065 -j ACCEPT
   iptables -A INPUT -p tcp --dport 5075:5076 -j ACCEPT
   iptables -A INPUT -p udp --dport 5075:5076 -j ACCEPT

SSH Configuration
~~~~~~~~~~~~~~~~~

If start script uses SSH:

1. Set up key-based authentication:

.. code-block:: bash

   ssh-keygen -t rsa
   ssh-copy-id user@acq_computer

2. Test passwordless SSH:

.. code-block:: bash

   ssh user@acq_computer "echo SSH works"

3. Add to ``~/.ssh/config``:

.. code-block:: text

   Host acq_computer
       Hostname 164.54.53.100
       User beams
       IdentityFile ~/.ssh/id_rsa
       StrictHostKeyChecking no

Troubleshooting Configuration
------------------------------

Settings Not Persisting
~~~~~~~~~~~~~~~~~~~~~~~~

Check:

1. Settings file permissions:

.. code-block:: bash

   ls -l ~/.xanes_gui_settings.json
   chmod 644 ~/.xanes_gui_settings.json

2. Home directory writable
3. No file system errors in system logs

EPICS PVs Not Found
~~~~~~~~~~~~~~~~~~~~

Check:

1. Environment variables set (``echo $EPICS_CA_ADDR_LIST``)
2. Network connectivity (``ping <ioc_address>``)
3. IOC running (``caget <pv_name>``)
4. PV names correct (no typos)
5. Firewall rules (``iptables -L``)

Curves Not Loading
~~~~~~~~~~~~~~~~~~

Check:

1. Directory paths correct and absolute
2. Read permissions on directories
3. Files exist with correct naming
4. File extension matches configuration
5. File format valid (2 columns, numeric data)

Script Not Executing
~~~~~~~~~~~~~~~~~~~~

Check:

1. Script path correct and absolute
2. Script executable (``chmod +x <script>``)
3. Script shebang present (``#!/bin/bash``)
4. No syntax errors (``bash -n <script>``)
5. Dependencies available (tomoscan, ssh, etc.)

See Also
--------

* :doc:`installation` - Installation and setup
* :doc:`user_guide` - Using the configured GUI
* :doc:`troubleshooting` - Detailed troubleshooting
