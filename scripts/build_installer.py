"""Build the Windows installer: PyInstaller one-dir, then Inno Setup.

Run from a checkout that has already fetched FFmpeg::

    uv run python scripts/fetch_ffmpeg.py
    uv run --group packaging python scripts/build_installer.py

Output:

* ``dist/VidSnap/``                        — the one-dir build (runnable as-is)
* ``dist/installer/VidSnapSetup-<ver>.exe`` — the installer

``--skip-installer`` stops after PyInstaller, which is what you want when Inno
Setup is not installed or you only need to test the frozen app.

The version is read from :mod:`vidsnap` and passed to ISCC, so
``vidsnap/__init__.py`` stays the single source of truth for it.

Like every other subprocess call in this project, PyInstaller and ISCC are
invoked with argument lists — never ``shell=True``.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PACKAGING = _REPO_ROOT / "packaging"
_SPEC = _PACKAGING / "vidsnap.spec"
_ISS = _PACKAGING / "vidsnap.iss"
_DIST = _REPO_ROOT / "dist"
_ONEDIR = _DIST / "VidSnap"
_INSTALLER_DIR = _DIST / "installer"

# Inno Setup does not put itself on PATH, so check the usual install locations
# before giving up. The names are upper-case because Python upper-cases every
# key in os.environ on Windows — "ProgramFiles" would simply never match.
_ISCC_CANDIDATES = (
    Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
    / "Inno Setup 6"
    / "ISCC.exe",
    Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Inno Setup 6" / "ISCC.exe",
)


class BuildError(RuntimeError):
    """A build step failed or a prerequisite is missing."""


def _version() -> str:
    sys.path.insert(0, str(_REPO_ROOT))
    import vidsnap

    return vidsnap.__version__


def _run(cmd: list[str], step: str) -> None:
    print(f"\n=== {step} ===\n$ {' '.join(cmd)}\n", flush=True)
    result = subprocess.run(cmd, cwd=_REPO_ROOT)
    if result.returncode != 0:
        raise BuildError(f"{step} failed with exit code {result.returncode}")


def _find_iscc() -> Path:
    on_path = shutil.which("iscc")
    if on_path:
        return Path(on_path)
    for candidate in _ISCC_CANDIDATES:
        if candidate.is_file():
            return candidate
    raise BuildError(
        "Inno Setup's ISCC.exe not found. Install Inno Setup 6 "
        "(https://jrsoftware.org/isdl.php), or pass --skip-installer to stop "
        "after the PyInstaller build."
    )


def build_onedir() -> None:
    """Run PyInstaller against the spec, from a clean slate.

    The previous build is removed first: PyInstaller reuses ``build/`` caches,
    and a stale one has been known to keep shipping a file the spec no longer
    lists — not something to discover in a release artifact.
    """
    for stale in (_ONEDIR, _REPO_ROOT / "build"):
        if stale.exists():
            print(f"Removing stale {stale.relative_to(_REPO_ROOT)}")
            shutil.rmtree(stale)

    _run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", str(_SPEC)],
        "PyInstaller (one-dir)",
    )

    exe = _ONEDIR / "vidsnap.exe"
    gui = _ONEDIR / "vidsnap-gui.exe"
    bundled_ffmpeg = _ONEDIR / "_internal" / "bin" / "ffmpeg.exe"
    for expected in (exe, gui, bundled_ffmpeg):
        if not expected.is_file():
            raise BuildError(f"PyInstaller did not produce {expected}")
    print(f"\nOne-dir build ready: {_ONEDIR}")


def build_installer(version: str) -> Path:
    """Compile the Inno Setup installer around the one-dir build."""
    if not _ONEDIR.is_dir():
        raise BuildError(f"{_ONEDIR} does not exist — build the one-dir app first.")
    iscc = _find_iscc()
    _INSTALLER_DIR.mkdir(parents=True, exist_ok=True)
    _run(
        [str(iscc), f"/DMyAppVersion={version}", str(_ISS)],
        "Inno Setup (installer)",
    )
    installer = _INSTALLER_DIR / f"VidSnapSetup-{version}.exe"
    if not installer.is_file():
        raise BuildError(f"Inno Setup did not produce {installer}")
    size_mb = installer.stat().st_size / (1024 * 1024)
    print(f"\nInstaller ready: {installer} ({size_mb:.1f} MB)")
    return installer


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="build_installer",
        description="Build the VidSnap one-dir app and Windows installer.",
    )
    parser.add_argument(
        "--skip-installer",
        action="store_true",
        help="stop after PyInstaller (no Inno Setup required)",
    )
    args = parser.parse_args(argv)

    if os.name != "nt":
        print(
            "Error: the installer targets Windows and must be built on Windows.",
            file=sys.stderr,
        )
        return 1

    version = _version()
    print(f"Building VidSnap {version}")

    try:
        build_onedir()
        if not args.skip_installer:
            build_installer(version)
    except BuildError as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
