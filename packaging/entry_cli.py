"""Frozen-build entry point for the console app (``vidsnap.exe``).

PyInstaller freezes a *script*, not a ``module:function`` reference, so the
console_scripts entry point in ``pyproject.toml`` needs this two-line stand-in.
Keep it free of logic: everything real belongs in :mod:`vidsnap.cli`.
"""

from __future__ import annotations

import multiprocessing
import sys

from vidsnap.cli import main

if __name__ == "__main__":
    # Harmless here (VidSnap does not spawn processes), but required boilerplate
    # in any frozen app: without it a child process would re-run this script.
    multiprocessing.freeze_support()
    sys.exit(main())
