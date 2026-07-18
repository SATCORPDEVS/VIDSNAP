"""Runtime resolver for the ffmpeg / ffprobe binaries.

Resolution order:

1. The binary bundled next to the package in ``bin/`` (populated by
   ``scripts/fetch_ffmpeg.py`` and shipped inside the installer).
2. The binary found on ``PATH`` (developer convenience / fallback).

Everything else in VidSnap invokes ffmpeg through these resolvers so there is a
single place that knows where the binaries live.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def _bundled_dir() -> Path:
    """Where ``bin/`` sits, in a source checkout and in a frozen build alike.

    Running from source, ``bin/`` is at the repository root, one level above the
    package. In a PyInstaller one-dir build the package lives inside an archive
    with no on-disk ``__file__``, so the anchor is ``sys._MEIPASS`` — the
    ``_internal`` folder the spec copies ``bin/`` into — instead.
    """
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass is not None:
            return Path(meipass) / "bin"
        return Path(sys.executable).resolve().parent / "bin"
    return Path(__file__).resolve().parent.parent / "bin"


_BUNDLED_BIN_DIR = _bundled_dir()

_EXE_SUFFIX = ".exe" if os.name == "nt" else ""


class BinaryNotFoundError(RuntimeError):
    """Raised when a required binary is neither bundled nor on PATH."""


def bundled_bin_dir() -> Path:
    """Directory where bundled binaries are expected."""
    return _BUNDLED_BIN_DIR


def _resolve(name: str) -> str | None:
    bundled = _BUNDLED_BIN_DIR / f"{name}{_EXE_SUFFIX}"
    if bundled.is_file():
        return str(bundled)
    on_path = shutil.which(name)
    if on_path:
        return on_path
    return None


def find_ffmpeg() -> str:
    """Absolute path to ffmpeg, preferring the bundled build.

    Raises:
        BinaryNotFoundError: if ffmpeg cannot be located.
    """
    resolved = _resolve("ffmpeg")
    if resolved is None:
        raise BinaryNotFoundError(
            "ffmpeg not found. Run `python scripts/fetch_ffmpeg.py` to download the "
            "bundled build, or install ffmpeg and put it on your PATH."
        )
    return resolved


def find_ffprobe() -> str:
    """Absolute path to ffprobe, preferring the bundled build.

    Raises:
        BinaryNotFoundError: if ffprobe cannot be located.
    """
    resolved = _resolve("ffprobe")
    if resolved is None:
        raise BinaryNotFoundError(
            "ffprobe not found. Run `python scripts/fetch_ffmpeg.py` to download the "
            "bundled build, or install ffmpeg and put it on your PATH."
        )
    return resolved
