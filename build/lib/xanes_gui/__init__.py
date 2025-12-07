"""
XANES GUI - A PyQt5-based interface for X-ray Absorption Spectroscopy

A modern graphical interface for XANES spectroscopy measurements at
APS Beamline 32-ID.
"""

__version__ = "1.0.0"
__author__ = "APS Beamline 32-ID"
__email__ = "32id@aps.anl.gov"

import sys
from PyQt5.QtWidgets import QApplication
from .gui import XANESGui


def main():
    """Main entry point for the XANES GUI application."""
    app = QApplication(sys.argv)
    app.setApplicationName("XANES GUI")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("APS Beamline 32-ID")
    app.setOrganizationDomain("aps.anl.gov")

    window = XANESGui()
    window.show()

    sys.exit(app.exec_())


__all__ = ["XANESGui", "main", "__version__"]
