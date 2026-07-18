"""Tests for the pre-split path advisories (:mod:`vidsnap.paths`).

These are pure string/path logic — no ffmpeg, no filesystem.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from vidsnap import paths

_ON_WINDOWS = os.name == "nt"


@pytest.mark.parametrize(
    "path",
    [
        r"C:\Users\sam\OneDrive\Videos" if _ON_WINDOWS else "/home/sam/OneDrive/Videos",
        # A work account's folder is named "OneDrive - Contoso", not "OneDrive".
        r"C:\Users\sam\OneDrive - Contoso\clips" if _ON_WINDOWS else "/home/sam/OneDrive - Co/x",
        r"C:\Users\sam\Dropbox\clips" if _ON_WINDOWS else "/home/sam/Dropbox/clips",
        r"C:\Users\sam\Google Drive\clips" if _ON_WINDOWS else "/home/sam/Google Drive/clips",
    ],
)
def test_detects_synced_folders(path: str) -> None:
    assert paths.is_cloud_synced(Path(path))


def test_case_insensitive() -> None:
    base = r"C:\Users\sam\onedrive\v" if _ON_WINDOWS else "/home/sam/onedrive/v"
    assert paths.is_cloud_synced(Path(base))


def test_ordinary_folder_is_not_synced(tmp_path: Path) -> None:
    assert not paths.is_cloud_synced(tmp_path / "Videos")


def test_sync_warning_names_the_folder_and_the_cost() -> None:
    out = Path(r"C:\Users\sam\OneDrive\clips" if _ON_WINDOWS else "/home/sam/OneDrive/clips")
    warning = paths.cloud_sync_warning(out)
    assert warning is not None
    assert "OneDrive" in warning
    assert "sync" in warning


def test_no_sync_warning_for_local_folder(tmp_path: Path) -> None:
    assert paths.cloud_sync_warning(tmp_path) is None


# --------------------------------------------------------------------------- #
# Cross-drive output
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(not _ON_WINDOWS, reason="drive letters are a Windows concept")
def test_warns_when_output_is_on_another_drive() -> None:
    warning = paths.different_drive_warning(Path(r"C:\videos\in.mp4"), Path(r"D:\out"))
    assert warning is not None
    assert "d:" in warning.casefold()


@pytest.mark.skipif(not _ON_WINDOWS, reason="drive letters are a Windows concept")
def test_no_warning_when_output_is_on_the_same_drive() -> None:
    assert paths.different_drive_warning(Path(r"C:\videos\in.mp4"), Path(r"C:\out")) is None


def test_no_drive_warning_for_relative_paths() -> None:
    """Relative paths resolve against the same cwd, so they share a drive."""
    assert paths.different_drive_warning(Path("in.mp4"), Path("out")) is None
