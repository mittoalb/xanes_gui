XANES GUI Documentation
========================

A PyQt5-based graphical user interface for X-ray Absorption Near Edge Structure (XANES) spectroscopy measurements at APS Beamline 32-ID.

.. image:: https://img.shields.io/badge/python-3.8+-blue.svg
   :target: https://www.python.org/downloads/

.. image:: https://img.shields.io/badge/PyQt-5-green.svg
   :target: https://www.riverbankcomputing.com/software/pyqt/

Contents
--------

.. toctree::
   :maxdepth: 2
   :caption: User Guide

   installation
   quickstart
   user_guide
   features

.. toctree::
   :maxdepth: 2
   :caption: Reference

   api
   configuration
   troubleshooting

.. toctree::
   :maxdepth: 1
   :caption: About

   changelog
   license

Overview
--------

XANES GUI provides a modern, user-friendly interface for:

* **Energy calibration scans** - Measure K-edge positions of reference materials
* **XANES data collection** - Automated energy scans with flexible configuration
* **Reference curve visualization** - Load and compare calibrated and simulated spectra
* **Multiple energy range methods** - Manual, plot-based selection, or custom arrays
* **Real-time monitoring** - Live plot updates during calibration scans

Key Features
------------

* **Dark theme interface** optimized for beamline environments
* **Dual curve support** - Calibrated (measured) and simulated reference spectra
* **Automatic edge detection** - Calculate energy shifts from measured data
* **Three energy definition modes**:

  * Manual: Start/End/Step
  * Plot selection: Interactive range selection
  * Custom: Import energy arrays from files

* **EPICS integration** - Full control via Channel Access and PVAccess
* **Thread-safe operations** - Non-blocking UI during scans
* **Comprehensive logging** - Timestamped event tracking

Quick Links
-----------

* :doc:`installation` - Get started with installation
* :doc:`quickstart` - Your first XANES scan in 5 minutes
* :doc:`user_guide` - Complete user guide
* :doc:`api` - API reference for developers

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
