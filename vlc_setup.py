"""
vlc_setup.py
Must be imported before any other module that imports vlc.
"""
import os
import sys

if getattr(sys, "frozen", False):
    _bundle = sys._MEIPASS
    os.environ["PYTHON_VLC_LIB_PATH"] = os.path.join(_bundle, "libvlc.so.5")
    os.environ["PYTHON_VLC_MODULE_PATH"] = os.path.join(_bundle, "vlc")