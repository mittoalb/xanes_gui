Installation
============

Requirements
------------

* Python 3.8 or higher
* PyQt5 5.15+
* numpy 1.20+
* pyqtgraph 0.12+
* pyepics 3.5+
* pvaccess (EPICS 7)

System Requirements
-------------------

**Operating System:**

* Linux (tested on RHEL 8/9, Ubuntu 20.04+)
* macOS 10.14+
* Windows 10+ (EPICS support may be limited)

**Hardware:**

* Minimum 4 GB RAM
* 100 MB disk space
* Network connection to EPICS IOCs

Installation Methods
--------------------

Using pip (Recommended)
~~~~~~~~~~~~~~~~~~~~~~~

Install directly from the repository:

.. code-block:: bash

   pip install git+https://github.com/yourusername/xanes-gui.git

Or install from PyPI (if published):

.. code-block:: bash

   pip install xanes-gui

From Source
~~~~~~~~~~~

1. Clone the repository:

.. code-block:: bash

   git clone https://github.com/yourusername/xanes-gui.git
   cd xanes-gui

2. Install in development mode:

.. code-block:: bash

   pip install -e .

Using Conda
~~~~~~~~~~~

Create a conda environment with all dependencies:

.. code-block:: bash

   conda create -n xanes python=3.10
   conda activate xanes
   pip install xanes-gui

Dependencies Installation
-------------------------

Manual Installation
~~~~~~~~~~~~~~~~~~~

If you prefer to install dependencies manually:

.. code-block:: bash

   # Core dependencies
   pip install PyQt5 pyqtgraph numpy

   # EPICS dependencies
   pip install pyepics pvaccess

Configuration
-------------

After installation, configure the EPICS environment:

.. code-block:: bash

   export EPICS_CA_ADDR_LIST="your_ioc_address"
   export EPICS_CA_AUTO_ADDR_LIST=NO
   export EPICS_PVA_ADDR_LIST="your_ioc_address"

Add these to your ``.bashrc`` or ``.bash_profile`` for persistence.

Verify Installation
-------------------

Check that the installation was successful:

.. code-block:: bash

   python -c "import xanes_gui; print('XANES GUI installed successfully')"

Run the GUI:

.. code-block:: bash

   xanes-gui

Or:

.. code-block:: bash

   python -m xanes_gui

Troubleshooting
---------------

ImportError: No module named 'PyQt5'
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Install PyQt5:

.. code-block:: bash

   pip install PyQt5

EPICS Connection Issues
~~~~~~~~~~~~~~~~~~~~~~~

1. Verify EPICS environment variables are set
2. Check network connectivity to IOCs:

.. code-block:: bash

   caget your_pv_name

3. Ensure firewall allows EPICS ports (5064, 5065 for CA; 5075, 5076 for PVA)

Permission Errors
~~~~~~~~~~~~~~~~~

If you encounter permission errors during installation:

.. code-block:: bash

   pip install --user xanes-gui

Or use a virtual environment:

.. code-block:: bash

   python -m venv xanes_env
   source xanes_env/bin/activate
   pip install xanes-gui

Updating
--------

To update to the latest version:

.. code-block:: bash

   pip install --upgrade xanes-gui

Or from source:

.. code-block:: bash

   cd xanes-gui
   git pull
   pip install -e . --upgrade
