#!/usr/bin/env python3
"""DEPRECATED — superseded by branding/render-branding.py.

The boot splashes used to be rendered here from usr/share/pixmaps/sysible-logo-dark.svg,
which was a SEPARATE copy of the logo that drifted from the dock icon — so the boot
screen kept shipping the old mark. All branding is now rendered from ONE canonical
source (branding/logo/sysible-mark.svg) by branding/render-branding.py, which also
produces these splashes. This shim just forwards to it so no stale path survives.
"""
import os
import runpy
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
GEN = os.path.join(HERE, "..", "render-branding.py")

if __name__ == "__main__":
    sys.stderr.write("render-splash.py is deprecated; running branding/render-branding.py instead.\n")
    runpy.run_path(GEN, run_name="__main__")
