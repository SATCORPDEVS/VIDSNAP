"""Tkinter GUI entry point.

Implemented in Phase 5. Note the Windows DPI-awareness fix must run *before*
the Tk root window is created, or the UI renders blurry on high-DPI displays.
"""

from __future__ import annotations

import contextlib
import ctypes
import os


def _enable_dpi_awareness() -> None:
    """Opt into per-monitor DPI awareness on Windows (no-op elsewhere)."""
    if os.name != "nt":
        return
    try:
        # PROCESS_PER_MONITOR_DPI_AWARE = 2
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        # Older Windows without shcore — fall back to the system-DPI-aware API.
        with contextlib.suppress(AttributeError, OSError):
            ctypes.windll.user32.SetProcessDPIAware()  # type: ignore[attr-defined]


def main() -> int:
    """Launch the GUI. Phase 5 will implement the window."""
    _enable_dpi_awareness()
    raise NotImplementedError("GUI lands in Phase 5")


if __name__ == "__main__":
    raise SystemExit(main())
