"""Tests for the command-line entry point (:mod:`vidsnap.cli`).

Argument handling and error paths are tested without a binary; a full end-to-end
split runs as an integration test when ffmpeg is available.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import make_testsrc, requires_ffmpeg
from vidsnap import cli


@pytest.fixture(autouse=True)
def _isolate_logging(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Keep the CLI's log file out of the real app-data dir during tests.
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))


def test_missing_input_exits_2() -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main([])
    assert exc.value.code == 2


def test_exact_flag_is_not_yet_supported(capsys: pytest.CaptureFixture[str]) -> None:
    rc = cli.main(["clip.mp4", "--exact"])
    assert rc == 2
    assert "Phase 6" in capsys.readouterr().err


def test_zero_minutes_rejected() -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["clip.mp4", "--minutes", "0"])
    assert exc.value.code == 2


def test_missing_file_reports_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = cli.main([str(tmp_path / "nope.mp4")])
    assert rc == 1
    assert "Error" in capsys.readouterr().err


# --------------------------------------------------------------------------- #
# Integration — full split through the CLI
# --------------------------------------------------------------------------- #


@requires_ffmpeg
@pytest.mark.integration
def test_cli_splits_end_to_end(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = make_testsrc(tmp_path / "clip.mp4", seconds=5 * 60)
    rc = cli.main([str(source), "--minutes", "2"])
    assert rc == 0

    out = capsys.readouterr().out
    assert "Done" in out

    seg_dir = tmp_path / "clip_segments"
    segments = sorted(seg_dir.glob("clip_part_*.mp4"))
    assert len(segments) == 3  # 5 min / 2 min -> 3 segments
