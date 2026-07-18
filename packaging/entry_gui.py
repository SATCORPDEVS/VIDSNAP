"""Frozen-build entry point for the windowed app (``vidsnap-gui.exe``).

See :mod:`entry_cli` — same rationale, windowed target.
"""

from __future__ import annotations

import multiprocessing
import sys

from vidsnap.gui import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
