"""Phase 1 smoke tests — prove the skeleton imports and wires together.

These are deliberately lightweight; real behavioural tests for probing and
splitting arrive with Phases 2 and 3.
"""

from __future__ import annotations

import vidsnap
from vidsnap import cli, ffmpeg, log
from vidsnap.splitter import DEFAULT_SEGMENT_SECONDS


def test_version_is_exposed() -> None:
    assert vidsnap.__version__
    assert isinstance(vidsnap.__version__, str)


def test_cli_version_flag(capsys) -> None:
    # argparse's version action raises SystemExit(0) after printing.
    try:
        cli.main(["--version"])
    except SystemExit as exc:
        assert exc.code == 0
    out = capsys.readouterr().out
    assert vidsnap.__version__ in out


def test_cli_requires_input() -> None:
    # No input -> argparse error -> SystemExit(2).
    try:
        cli.main([])
    except SystemExit as exc:
        assert exc.code == 2
    else:  # pragma: no cover - defensive
        raise AssertionError("expected SystemExit for missing input")


def test_default_segment_length_is_two_minutes() -> None:
    assert DEFAULT_SEGMENT_SECONDS == 120


def test_ffmpeg_resolver_raises_cleanly_when_missing(monkeypatch) -> None:
    # Force both bundled and PATH lookups to miss.
    monkeypatch.setattr(ffmpeg.shutil, "which", lambda _name: None)
    monkeypatch.setattr(ffmpeg, "_BUNDLED_BIN_DIR", ffmpeg.Path("/nonexistent-vidsnap-bin"))
    try:
        ffmpeg.find_ffmpeg()
    except ffmpeg.BinaryNotFoundError as exc:
        assert "ffmpeg" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("expected BinaryNotFoundError")


def test_app_data_dir_is_creatable(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    d = log.app_data_dir()
    assert d.is_dir()
