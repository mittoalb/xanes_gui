#!/bin/bash
# Wrapper script to launch XANES GUI

cd "$(dirname "$0")"
exec python xanes_gui/gui.py
