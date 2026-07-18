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


def _display_rotation(video: Path) -> str | None:
    """The video stream's display rotation, or None if it carries none.

    Rotation lives in the display-matrix side data (modern FFmpeg) or, on older
    files, a ``rotate`` stream tag — so both are checked.
    """
    from vidsnap import ffmpeg

    out = subprocess.run(
        [
            ffmpeg.find_ffprobe(),
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream_side_data=rotation:stream_tags=rotate",
            "-of",
            "default=nk=1:nw=1",
            str(video),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout.strip() or None


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


def test_exact_mode_reencodes_video_only_and_forces_boundary_keyframes() -> None:
    cmd = build_segment_command("ffmpeg", Path("in.mp4"), "out_%03d.mp4", 90, exact=True)
    # Everything is copied, then the video alone is overridden to re-encode.
    assert cmd[cmd.index("-c") + 1] == "copy"
    assert cmd[cmd.index("-c:v") + 1] == "libx264"
    assert cmd[cmd.index("-crf") + 1] == "17"
    # A keyframe on every boundary is what makes the cuts frame-accurate.
    assert cmd[cmd.index("-force_key_frames") + 1] == "expr:gte(t,n_forced*90)"


def test_exact_mode_is_opt_in() -> None:
    """Re-encoding must never happen unless it was explicitly asked for."""
    assert "-c:v" not in build_segment_command("ffmpeg", Path("in.mp4"), "out_%03d.mp4", 120)


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
    result = splitter.split(source, segment_seconds=120, on_progress=progress.append)
    segments = result.segments

    # 7 min / 2 min -> 4 segments (last is a ~1-minute remainder).
    assert len(result) == 4
    assert [s.name for s in segments] == [
        "clip_part_001.mp4",
        "clip_part_002.mp4",
        "clip_part_003.mp4",
        "clip_part_004.mp4",
    ]
    assert all(s.stat().st_size > 0 for s in segments)

    # Durations sum back to the source (within keyframe tolerance), and the
    # result reports them without anyone having to re-probe.
    assert result.total_seconds == pytest.approx(7 * 60, abs=2.0)
    assert result.durations == pytest.approx(
        tuple(probe.probe(s).duration_seconds for s in segments)
    )

    # Progress advanced and reached completion.
    assert progress
    assert progress[-1] == pytest.approx(1.0)
    assert progress == sorted(progress)


@requires_ffmpeg
@pytest.mark.integration
def test_split_preserves_codec_no_reencode(tmp_path: Path) -> None:
    source = make_testsrc(tmp_path / "clip.mp4", seconds=90)
    result = splitter.split(source, segment_seconds=30)
    source_codec = _ffprobe_codec(source)
    for seg in result:
        assert _ffprobe_codec(seg) == source_codec


@requires_ffmpeg
@pytest.mark.integration
def test_split_shorter_than_segment_makes_one_lossless_copy(tmp_path: Path) -> None:
    source = make_testsrc(tmp_path / "short.mp4", seconds=10)
    result = splitter.split(source, segment_seconds=120)

    assert len(result) == 1
    assert result.segments[0].stat().st_size > 0
    # The whole source, untouched: same duration, same codec.
    assert result.durations[0] == pytest.approx(10, abs=1.0)
    assert _ffprobe_codec(result.segments[0]) == _ffprobe_codec(source)
    # A single short file is not "drift" — nothing to warn about.
    assert result.length_report() is None


@requires_ffmpeg
@pytest.mark.integration
def test_split_custom_output_dir(tmp_path: Path) -> None:
    source = make_testsrc(tmp_path / "clip.mp4", seconds=30)
    out = tmp_path / "chunks"
    result = splitter.split(source, output_dir=out, segment_seconds=15)
    assert all(s.parent == out for s in result)
    assert len(result) == 2
    assert result.output_dir == out


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
    assert len(splitter.split(source, segment_seconds=30, cancel_event=threading.Event())) == 2


# --------------------------------------------------------------------------- #
# Reporting actual segment lengths (no binary needed)
# --------------------------------------------------------------------------- #


def _result(durations: tuple[float, ...], requested: int = 120) -> splitter.SplitResult:
    segments = tuple(Path(f"part_{n:03d}.mp4") for n in range(1, len(durations) + 1))
    return splitter.SplitResult(segments, durations, requested_seconds=requested)


def test_length_report_silent_when_segments_match_request() -> None:
    assert _result((120.0, 120.0, 45.0)).length_report() is None


def test_length_report_ignores_the_short_final_remainder() -> None:
    """The last segment is always short; that is arithmetic, not keyframe drift."""
    assert _result((120.0, 120.0, 3.0)).length_report() is None


def test_length_report_names_the_overshoot_on_sparse_keyframes() -> None:
    # A screen recording with a 14 s GOP can only be cut every 14 s.
    report = _result((134.0, 128.0, 60.0)).length_report()
    assert report is not None
    assert "2:14" in report  # the longest segment, not the requested 2:00
    assert "keyframes" in report


def test_length_report_tolerates_sub_second_rounding() -> None:
    assert _result((120.4, 120.2, 30.0)).length_report() is None


def test_result_is_iterable_and_sized_like_a_segment_list() -> None:
    result = _result((120.0, 30.0))
    assert len(result) == 2
    assert list(result) == list(result.segments)
    assert result.longest_seconds == 120.0


# --------------------------------------------------------------------------- #
# Edge cases — awkward filenames, exact cuts, preserved streams and metadata
# --------------------------------------------------------------------------- #


@requires_ffmpeg
@pytest.mark.integration
@pytest.mark.parametrize(
    "name",
    [
        "my holiday clip.mp4",
        "café — bien sûr (2024).mp4",
        "видео_日本語.mp4",
        "brackets [1] & things #2.mp4",
    ],
)
def test_split_handles_awkward_filenames(tmp_path: Path, name: str) -> None:
    source = make_testsrc(tmp_path / name, seconds=30)
    result = splitter.split(source, segment_seconds=15)
    assert len(result) == 2
    # Segment names are derived from the source stem, spaces and all.
    assert all(s.name.startswith(f"{source.stem}_part_") for s in result)
    assert all(s.stat().st_size > 0 for s in result)


@requires_ffmpeg
@pytest.mark.integration
def test_exact_mode_cuts_on_the_requested_length(tmp_path: Path) -> None:
    # A 10-second GOP means a stream copy could only cut every 10 s; exact mode
    # forces a keyframe on the boundary instead.
    source = make_testsrc(tmp_path / "sparse.mp4", seconds=30, fps=30, gop_seconds=10)
    result = splitter.split(source, segment_seconds=4, exact=True)

    assert len(result) > 1
    for duration in result.durations[:-1]:
        assert duration == pytest.approx(4.0, abs=0.5)
    assert result.length_report() is None


@requires_ffmpeg
@pytest.mark.integration
def test_stream_copy_drift_is_reported_not_hidden(tmp_path: Path) -> None:
    """The same sparse source, split losslessly, must admit its segments run long."""
    source = make_testsrc(tmp_path / "sparse.mp4", seconds=30, fps=30, gop_seconds=10)
    result = splitter.split(source, segment_seconds=4)

    assert result.longest_seconds > 4.0  # cut snapped forward to the next keyframe
    report = result.length_report()
    assert report is not None
    assert "keyframes" in report


@requires_ffmpeg
@pytest.mark.integration
def test_split_keeps_every_audio_track(tmp_path: Path) -> None:
    source = make_testsrc(tmp_path / "multi.mp4", seconds=30, audio_tracks=2)
    result = splitter.split(source, segment_seconds=15)
    for seg in result:
        assert probe.probe(seg).audio_stream_count == 2


@requires_ffmpeg
@pytest.mark.integration
def test_split_preserves_rotation_metadata(tmp_path: Path) -> None:
    """Phone videos carry rotation in metadata; a stream copy must not lose it."""
    source = make_testsrc(tmp_path / "rotated.mp4", seconds=20, rotate=90)
    assert _display_rotation(source) is not None, "fixture did not get rotation metadata"

    result = splitter.split(source, segment_seconds=10)
    for seg in result:
        assert _display_rotation(seg) == _display_rotation(source)


@requires_ffmpeg
@pytest.mark.integration
def test_split_handles_variable_frame_rate_source(tmp_path: Path) -> None:
    source = make_testsrc(tmp_path / "vfr.mp4", seconds=30, vfr=True)
    result = splitter.split(source, segment_seconds=10)
    assert len(result) >= 3
    assert result.total_seconds == pytest.approx(30, abs=2.0)
