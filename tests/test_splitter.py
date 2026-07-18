"""Tests for the splitting engine (:mod:`vidsnap.splitter`).

Command construction is tested without any binary. The real split — segment
count, non-empty files, durations, and **codec equality proving no re-encode
happened** — runs as an integration test against a synthetic video when ffmpeg
is available.
"""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path

import pytest

from conftest import make_testsrc, requires_ffmpeg
from vidsnap import probe, splitter
from vidsnap.probe import InvalidInputError
from vidsnap.splitter import build_segment_command


def _ffprobe_codec(video: Path) -> str:
    from vidsnap import ffmpeg

    out = subprocess.run(
        [
            ffmpeg.find_ffprobe(),
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name",
            "-of",
            "default=nk=1:nw=1",
            str(video),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout.strip()


# --------------------------------------------------------------------------- #
# Command construction (no binary needed)
# --------------------------------------------------------------------------- #


def test_command_is_a_list_not_a_shell_string() -> None:
    cmd = build_segment_command("ffmpeg", Path("in.mp4"), "out_%03d.mp4", 120)
    assert isinstance(cmd, list)
    assert all(isinstance(part, str) for part in cmd)


def test_command_is_lossless_stream_copy() -> None:
    cmd = build_segment_command("ffmpeg", Path("in.mp4"), "out_%03d.mp4", 120)
    # -c copy, as adjacent tokens, means no re-encode.
    assert "-c" in cmd
    assert cmd[cmd.index("-c") + 1] == "copy"
    # Never a libx264 encode on the default path.
    assert "libx264" not in cmd


def test_command_has_expected_segment_flags() -> None:
    cmd = build_segment_command("ffmpeg", Path("in.mp4"), "out_%03d.mp4", 90)
    assert cmd[cmd.index("-f") + 1] == "segment"
    assert cmd[cmd.index("-segment_time") + 1] == "90"
    assert cmd[cmd.index("-map") + 1] == "0"
    assert cmd[cmd.index("-reset_timestamps") + 1] == "1"
    assert cmd[cmd.index("-progress") + 1] == "pipe:1"
    assert cmd[-1] == "out_%03d.mp4"


def test_hostile_filename_stays_a_single_argument() -> None:
    nasty = Path('weird; rm -rf ~ "$(whoami)".mp4')
    cmd = build_segment_command("ffmpeg", nasty, "out_%03d.mp4", 120)
    # The whole hostile name is exactly one argv element — nothing to inject.
    assert str(nasty) in cmd


def test_default_output_dir_is_next_to_input() -> None:
    d = splitter.default_output_dir(Path("/videos/holiday.mp4"))
    assert d.name == "holiday_segments"
    assert d.parent == Path("/videos")


# --------------------------------------------------------------------------- #
# Input validation (no binary needed — existence is checked before ffprobe)
# --------------------------------------------------------------------------- #


def test_split_missing_input_raises(tmp_path: Path) -> None:
    with pytest.raises(InvalidInputError):
        splitter.split(tmp_path / "nope.mp4")


# --------------------------------------------------------------------------- #
# Progress-line parsing (no binary needed)
# --------------------------------------------------------------------------- #


def test_progress_line_reports_fraction() -> None:
    seen: list[float] = []
    splitter._handle_progress_line("out_time_us=60000000", 120.0, seen.append)
    assert seen == [pytest.approx(0.5)]


def test_progress_line_end_reports_complete() -> None:
    seen: list[float] = []
    splitter._handle_progress_line("progress=end", 120.0, seen.append)
    assert seen == [1.0]


def test_progress_line_ignores_na() -> None:
    seen: list[float] = []
    splitter._handle_progress_line("out_time_us=N/A", 120.0, seen.append)
    assert seen == []


# --------------------------------------------------------------------------- #
# Integration — real split of a synthetic video
# --------------------------------------------------------------------------- #


@requires_ffmpeg
@pytest.mark.integration
def test_split_seven_minutes_into_four_segments(tmp_path: Path) -> None:
    source = make_testsrc(tmp_path / "clip.mp4", seconds=7 * 60)
    progress: list[float] = []
    segments = splitter.split(source, segment_seconds=120, on_progress=progress.append)

    # 7 min / 2 min -> 4 segments (last is a ~1-minute remainder).
    assert len(segments) == 4
    assert [s.name for s in segments] == [
        "clip_part_001.mp4",
        "clip_part_002.mp4",
        "clip_part_003.mp4",
        "clip_part_004.mp4",
    ]
    assert all(s.stat().st_size > 0 for s in segments)

    # Durations sum back to the source (within keyframe tolerance).
    total = sum(probe.probe(s).duration_seconds for s in segments)
    assert total == pytest.approx(7 * 60, abs=2.0)

    # Progress advanced and reached completion.
    assert progress
    assert progress[-1] == pytest.approx(1.0)
    assert progress == sorted(progress)


@requires_ffmpeg
@pytest.mark.integration
def test_split_preserves_codec_no_reencode(tmp_path: Path) -> None:
    source = make_testsrc(tmp_path / "clip.mp4", seconds=90)
    segments = splitter.split(source, segment_seconds=30)
    source_codec = _ffprobe_codec(source)
    for seg in segments:
        assert _ffprobe_codec(seg) == source_codec


@requires_ffmpeg
@pytest.mark.integration
def test_split_shorter_than_segment_makes_one_file(tmp_path: Path) -> None:
    source = make_testsrc(tmp_path / "short.mp4", seconds=10)
    segments = splitter.split(source, segment_seconds=120)
    assert len(segments) == 1
    assert segments[0].stat().st_size > 0


@requires_ffmpeg
@pytest.mark.integration
def test_split_custom_output_dir(tmp_path: Path) -> None:
    source = make_testsrc(tmp_path / "clip.mp4", seconds=30)
    out = tmp_path / "chunks"
    segments = splitter.split(source, output_dir=out, segment_seconds=15)
    assert all(s.parent == out for s in segments)
    assert len(segments) == 2


# --------------------------------------------------------------------------- #
# Cancellation
# --------------------------------------------------------------------------- #


def test_discard_partial_segment_removes_only_the_tail(tmp_path: Path) -> None:
    files = []
    for n in (1, 2, 3):
        f = tmp_path / f"clip_part_{n:03d}.mp4"
        f.write_bytes(b"data")
        files.append(f)

    kept = splitter._discard_partial_segment(files)

    assert kept == files[:2]
    assert all(f.exists() for f in files[:2])
    assert not files[2].exists()  # the partial tail is gone


def test_discard_partial_segment_handles_empty_list() -> None:
    assert splitter._discard_partial_segment([]) == []


@requires_ffmpeg
@pytest.mark.integration
def test_cancelled_split_raises_and_removes_partial(tmp_path: Path) -> None:
    source = make_testsrc(tmp_path / "clip.mp4", seconds=7 * 60)
    out = tmp_path / "chunks"
    # Pre-setting the event makes this deterministic: the very first progress
    # line FFmpeg emits trips the cancel check, before any real work finishes.
    cancel = threading.Event()
    cancel.set()

    with pytest.raises(splitter.SplitCancelled) as excinfo:
        splitter.split(source, output_dir=out, segment_seconds=30, cancel_event=cancel)

    # Whatever survived is complete and non-empty; the partial tail was deleted.
    kept = excinfo.value.segments
    on_disk = sorted(out.glob("clip_part_*.mp4"))
    assert list(kept) == on_disk
    assert all(s.stat().st_size > 0 for s in kept)


@requires_ffmpeg
@pytest.mark.integration
def test_uncancelled_event_does_not_affect_split(tmp_path: Path) -> None:
    source = make_testsrc(tmp_path / "clip.mp4", seconds=60)
    # An event that is never set must behave exactly like passing None.
    segments = splitter.split(source, segment_seconds=30, cancel_event=threading.Event())
    assert len(segments) == 2
