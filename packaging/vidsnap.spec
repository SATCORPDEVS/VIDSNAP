# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — VidSnap one-dir build.

Produces a single ``dist/VidSnap/`` folder holding two executables that share
one set of libraries:

* ``vidsnap.exe``     — console, the CLI
* ``vidsnap-gui.exe`` — windowed, the Tkinter app

**One-dir, never one-file.** A one-file build unpacks itself to a temp folder at
every launch, which is the same behaviour packers use and which AV heuristics
routinely flag; it also re-extracts the ~170 MB of FFmpeg on every run. If
Defender flags even this build, the documented next step is Nuitka — not code
signing, and never one-file.

The bundled FFmpeg binaries are copied in as *data*, not as ``binaries``:
PyInstaller scans entries in ``binaries`` for their own shared-library imports,
which is meaningless for a static ffmpeg.exe and only risks it being rewritten.
As data they land in ``_internal/bin/``, exactly where
``vidsnap.ffmpeg._bundled_dir()`` looks when frozen.

Build with ``python scripts/build_installer.py`` (which also runs Inno Setup),
or directly with ``pyinstaller packaging/vidsnap.spec``.
"""

from pathlib import Path

# SPECPATH is injected by PyInstaller; it is the folder holding this spec.
REPO_ROOT = Path(SPECPATH).parent  # noqa: F821
BIN_DIR = REPO_ROOT / "bin"

_missing = [n for n in ("ffmpeg.exe", "ffprobe.exe") if not (BIN_DIR / n).is_file()]
if _missing:
    raise SystemExit(
        f"packaging/vidsnap.spec: {', '.join(_missing)} not found in {BIN_DIR}. "
        "Run `uv run python scripts/fetch_ffmpeg.py` before building — an installer "
        "without the bundled FFmpeg would ship broken."
    )

# Files copied into _internal/ alongside the code.
DATAS = [
    (str(BIN_DIR / "ffmpeg.exe"), "bin"),
    (str(BIN_DIR / "ffprobe.exe"), "bin"),
    # Provenance of the bundled GPL build: version, source URL, verified SHA-256.
    (str(BIN_DIR / "FFMPEG_BUILD.txt"), "bin"),
    (str(REPO_ROOT / "LICENSE"), "."),
]

# Nothing here needs the scientific stack or the dev tooling; excluding it keeps
# the build honest if any of it happens to be in the build environment.
EXCLUDES = ["numpy", "pytest", "ruff", "setuptools", "pip", "unittest", "pydoc"]


def _analysis(script: str) -> Analysis:  # noqa: F821
    return Analysis(  # noqa: F821
        [str(REPO_ROOT / "packaging" / script)],
        pathex=[str(REPO_ROOT)],
        binaries=[],
        datas=DATAS,
        hiddenimports=[],
        hookspath=[],
        runtime_hooks=[],
        excludes=EXCLUDES,
        noarchive=False,
    )


cli_a = _analysis("entry_cli.py")
gui_a = _analysis("entry_gui.py")

cli_pyz = PYZ(cli_a.pure)  # noqa: F821
gui_pyz = PYZ(gui_a.pure)  # noqa: F821

cli_exe = EXE(  # noqa: F821
    cli_pyz,
    cli_a.scripts,
    [],
    exclude_binaries=True,  # one-dir: the libraries live in COLLECT, not in here
    name="vidsnap",
    console=True,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX compression is itself an AV heuristic trigger
)

gui_exe = EXE(  # noqa: F821
    gui_pyz,
    gui_a.scripts,
    [],
    exclude_binaries=True,
    name="vidsnap-gui",
    console=False,  # windowed: no console flash when launched from the shortcut
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
)

# One COLLECT for both executables. The two analyses overlap almost entirely
# (the GUI adds Tkinter), so collecting them together ships one copy of the
# shared libraries rather than two near-identical trees.
coll = COLLECT(  # noqa: F821
    cli_exe,
    gui_exe,
    cli_a.binaries,
    cli_a.datas,
    gui_a.binaries,
    gui_a.datas,
    strip=False,
    upx=False,
    name="VidSnap",
)
