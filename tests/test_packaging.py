"""Phase 7 packaging tests.

Two things are checked here, neither of which needs PyInstaller or Inno Setup
installed:

* the binary resolver anchors ``bin/`` correctly in a *frozen* build, which is
  the one code path that only ever runs inside the installed app and so would
  otherwise be tested for the first time by a user;
* the packaging inputs (spec, installer script, entry points) exist and stay
  consistent with the project — a one-file PyInstaller build in particular is a
  regression, since AV heuristics flag the self-extracting pattern.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import vidsnap
from vidsnap import ffmpeg

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PACKAGING = _REPO_ROOT / "packaging"
_SPEC = _PACKAGING / "vidsnap.spec"
_ISS = _PACKAGING / "vidsnap.iss"


# --------------------------------------------------------------------------
# Frozen binary resolution
# --------------------------------------------------------------------------


def test_bundled_dir_from_source_is_the_repo_bin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delattr(ffmpeg.sys, "frozen", raising=False)
    assert ffmpeg._bundled_dir() == _REPO_ROOT / "bin"


def test_bundled_dir_when_frozen_follows_meipass(monkeypatch: pytest.MonkeyPatch) -> None:
    # PyInstaller sets both attributes; _MEIPASS is the _internal folder the
    # spec copies bin/ into.
    monkeypatch.setattr(ffmpeg.sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        ffmpeg.sys, "_MEIPASS", r"C:\Program Files\VidSnap\_internal", raising=False
    )
    assert ffmpeg._bundled_dir() == Path(r"C:\Program Files\VidSnap\_internal") / "bin"


def test_bundled_dir_when_frozen_without_meipass_falls_back_to_the_exe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Belt and braces for a freezer that sets sys.frozen but no _MEIPASS
    # (Nuitka, the documented fallback if Defender flags the PyInstaller build).
    monkeypatch.setattr(ffmpeg.sys, "frozen", True, raising=False)
    monkeypatch.delattr(ffmpeg.sys, "_MEIPASS", raising=False)
    monkeypatch.setattr(ffmpeg.sys, "executable", str(_REPO_ROOT / "vidsnap.exe"))
    assert ffmpeg._bundled_dir() == _REPO_ROOT / "bin"


# --------------------------------------------------------------------------
# Packaging inputs
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        _SPEC,
        _ISS,
        _PACKAGING / "entry_cli.py",
        _PACKAGING / "entry_gui.py",
        _REPO_ROOT / "scripts" / "build_installer.py",
        _REPO_ROOT / "scripts" / "smoke_test.py",
    ],
    ids=lambda p: p.name,
)
def test_packaging_input_exists(path: Path) -> None:
    assert path.is_file(), f"missing packaging input: {path}"


def test_spec_builds_one_dir_not_one_file() -> None:
    """A one-file build is the AV-flagged pattern the plan rules out.

    In PyInstaller's spec API that distinction is structural: a one-dir build
    passes ``a.binaries``/``a.datas`` to ``COLLECT``, a one-file build folds
    them into ``EXE`` and omits ``COLLECT`` entirely.
    """
    spec = _SPEC.read_text(encoding="utf-8")
    assert "COLLECT(" in spec
    assert "onefile" not in spec.lower().replace("one-file", "")


def test_spec_bundles_the_ffmpeg_binaries() -> None:
    spec = _SPEC.read_text(encoding="utf-8")
    assert "ffmpeg" in spec and "ffprobe" in spec


def test_installer_version_matches_the_package() -> None:
    """The .iss carries the version; keep it from drifting from __init__.py.

    ``build_installer.py`` passes the real version on the ISCC command line, so
    the literal in the script is only the standalone-compile default — but a
    stale default is exactly the kind of thing that ships in a manual build.
    """
    iss = _ISS.read_text(encoding="utf-8")
    assert f'#define MyAppVersion "{vidsnap.__version__}"' in iss


def test_installer_ships_the_gpl_licence() -> None:
    """GPL-3.0 obliges us to convey the licence with the binary."""
    iss = _ISS.read_text(encoding="utf-8")
    assert "LicenseFile" in iss
    assert "LICENSE" in iss
