# Configuration file for the Sphinx documentation builder.

# -- Project information -----------------------------------------------------
project = 'XANES GUI'
copyright = '2024, APS Beamline 32-ID'
author = 'APS Beamline 32-ID'
release = '1.0.0'

# -- General configuration ---------------------------------------------------
extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.napoleon',
    'sphinx.ext.viewcode',
    'sphinx.ext.intersphinx',
]

templates_path = ['_templates']
exclude_patterns = []

# -- Options for HTML output -------------------------------------------------
html_theme = 'sphinx_rtd_theme'
html_static_path = ['_static']

# -- Intersphinx mapping -----------------------------------------------------
intersphinx_mapping = {
    'python': ('https://docs.python.org/3', None),
    'numpy': ('https://numpy.org/doc/stable/', None),
    'pyqt5': ('https://www.riverbankcomputing.com/static/Docs/PyQt5/', None),
}
