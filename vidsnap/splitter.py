"""Splitting engine — builds and runs the ffmpeg segment command. The core.

By default the split is **lossless stream copy** (``-c copy``): FFmpeg copies the
encoded video/audio packets straight into new segment files without re-encoding,
so the output is bit-identical to the source. The only cost is that cuts snap to
the nearest keyframe, so a "2:00" segment may run 2:00-2:04.

The opt-in **exact-cut mode** (``exact=True``, ``--exact``) re-encodes the video
so a keyframe lands exactly on every boundary, giving frame-accurate segment
lengths at the cost of time and a generation of quality. It is never the default
and every entry point labels it.

FFmpeg is always invoked with an argument list — never ``shell=True``, never a
concatenated string — so hostile filenames cannot inject commands. Progress is
read from ``-progress pipe:1`` and reported as a fraction in ``[0.0, 1.0]``;
after the run each segment is re-probed to prove it is a non-empty, valid video.
Nothing is ever buffered: FFmpeg streams the file, so a 10 GB source costs no
more memory than a 10 MB one.
"""

from __future__ import annotations

import contextlib
import subprocess
import threading
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

from vidsnap import ffmpeg, probe
from vidsnap.humanize import format_duration
from vidsnap.log import get_logger

_logger = get_logger()

DEFAULT_SEGMENT_SECONDS = 120

# How far the summed segment durations may drift from the source before we log a
# warning (keyframe cutting should not change total duration meaningfully).
_DURATION_TOLERANCE_SECONDS = 2.0

# A segment is only worth calling out as "long" if it overshoots by more than
# this — below it the difference is rounding, not sparse keyframes.
_DRIFT_REPORT_THRESHOLD_SECONDS = 1.0

# Exact-cut re-encode settings. CRF 17 is visually transparent for most sources;
# ``slow`` trades encode time for size. Audio and subtitles are still copied —
# only the video has to be re-encoded to place keyframes.
_EXACT_VIDEO_CODEC = "libx264"
_EXACT_CRF = "17"
_EXACT_PRESET = "slow"

# Progress is reported in [0.0, 1.0].
ProgressCallback = Callable[[float], None]


class SplitError(RuntimeError):
    """Raised when FFmpeg fails or the produced segments do not verify."""


class SplitCancelled(RuntimeError):
    """Raised when the caller cancelled the split via its ``cancel_event``.

    Not a :class:`SplitError`: cancellation is a deliberate user action, not a
    failure, and callers generally want to report it differently. ``segments``
    holds the completed segments that were kept; the partial one FFmpeg was
    still writing is deleted before this is raised.
    """

    def __init__(self, segments: Sequence[Path]) -> None:
        super().__init__("Split cancelled.")
        self.segments = tuple(segments)


@dataclass(frozen=True)
class SplitResult:
    """The segments a split produced, plus how long each one actually ran.

    Stream copy cuts on keyframes, so the real segment lengths are a property of
    the *source*, not of the requested length: a screen recording with a 10-second
    GOP can only be cut every 10 seconds. Carrying the measured durations here
    lets the CLI and GUI show that drift instead of leaving the user to discover
    a 2:14 "2-minute" segment in a player.

    Iterating or taking ``len()`` of a result yields its segment paths, so the
    common ``for seg in result`` / ``len(result)`` reads naturally.
    """

    segments: tuple[Path, ...]
    durations: tuple[float, ...]
    requested_seconds: int
    exact: bool = False

    def __len__(self) -> int:
        return len(self.segments)

    def __iter__(self) -> Iterator[Path]:
        return iter(self.segments)

    @property
    def output_dir(self) -> Path | None:
        """Folder the segments were written to, or ``None`` if there are none."""
        return self.segments[0].parent if self.segments else None

    @property
    def total_seconds(self) -> float:
        return sum(self.durations)

    @property
    def longest_seconds(self) -> float:
        return max(self.durations, default=0.0)

    def length_report(self) -> str | None:
        """One line describing how far the real lengths ran over the request.

        Returns ``None`` when every segment landed on the requested length (as it
        always does in exact-cut mode), so callers can print this unconditionally.
        """
        # The final segment is a remainder — always short, never evidence of drift.
        full_segments = self.durations[:-1]
        overshoot = max(full_segments, default=0.0) - self.requested_seconds
        if overshoot <= _DRIFT_REPORT_THRESHOLD_SECONDS:
            return None
        return (
            f"Segments run up to {format_duration(max(full_segments))} rather than "
            f"{format_duration(self.requested_seconds)}: cuts can only land on the source's "
            "keyframes, which are up to "
            f"{format_duration(overshoot)} apart. Use exact-cut mode for exact lengths."
        )


def build_segment_command(
    ffmpeg: str,
    input_path: Path,
    output_pattern: str,
    segment_seconds: int = DEFAULT_SEGMENT_SECONDS,
    exact: bool = False,
) -> list[str]:
    """Build the segment command as an argument list.

    ``output_pattern`` is a printf-style path (e.g. ``clip_part_%03d.mp4``).
    Always returns a list (never a shell string) so hostile filenames cannot
    inject commands.

    With ``exact=False`` (the default) the command is a lossless stream copy.
    With ``exact=True`` the video is re-encoded with a keyframe forced at every
    segment boundary, so the cuts are frame-accurate; audio and subtitles are
    still copied untouched.
    """
    codec_args = (
        # ``-c copy`` first, then override only the video: audio and subtitles are
        # still copied, and just the video stream is re-encoded to place keyframes.
        [
            "-c",
            "copy",
            "-c:v",
            _EXACT_VIDEO_CODEC,
            "-crf",
            _EXACT_CRF,
            "-preset",
            _EXACT_PRESET,
            # A keyframe exactly on every multiple of segment_seconds is what makes
            # the segment muxer's cuts frame-accurate.
            "-force_key_frames",
            f"expr:gte(t,n_forced*{segment_seconds})",
        ]
        if exact
        else ["-c", "copy"]  # lossless: copy packets, never re-encode
    )
    # The segment muxer only cuts on a keyframe at or after the boundary. A forced
    # keyframe can land a rounding-hair *before* it, in which case the cut would
    # be skipped and the segment would come out double length. This tolerance
    # accepts a keyframe that close to the boundary. Stream copy does not want it:
    # there the cut point is dictated by the source's own keyframes anyway.
    segment_tolerance_args = ["-segment_time_delta", "0.05"] if exact else []
    return [
        ffmpeg,
        "-hide_banner",
        "-nostdin",  # never block waiting on stdin
        "-loglevel",
        "error",
        "-y",  # overwrite existing segments in the output dir without prompting
        "-i",
        str(input_path),
        "-map",
        "0",  # keep every stream the container allows
        *codec_args,
        "-f",
        "segment",
        "-segment_time",
        str(segment_seconds),
        *segment_tolerance_args,
        "-segment_start_number",
        "1",  # first file is _part_001, not _part_000
        "-reset_timestamps",
        "1",  # each segment starts at 0:00 so it plays everywhere
        "-progress",
        "pipe:1",
        "-nostats",
        output_pattern,
    ]


def default_output_dir(input_path: Path) -> Path:
    """The default segments folder: ``<input name>_segments`` next to the input."""
    return input_path.parent / f"{input_path.stem}_segments"


def split(
    input_path: Path,
    output_dir: Path | None = None,
    segment_seconds: int = DEFAULT_SEGMENT_SECONDS,
    on_progress: ProgressCallback | None = None,
    cancel_event: threading.Event | None = None,
    exact: bool = False,
) -> SplitResult:
    """Split ``input_path`` into ~``segment_seconds`` segments.

    The source is probed first (validating it and giving the total duration used
    for progress). Segments are written to ``output_dir`` (default
    ``<input name>_segments`` next to the input) using the source's own
    container, then verified. The returned :class:`SplitResult` carries the
    segment paths and their measured durations.

    ``exact=True`` opts into frame-accurate cuts by re-encoding the video — far
    slower, and one generation of quality. The default stream copy is lossless.

    A source shorter than one segment is not a special case: FFmpeg writes a
    single segment, which is a lossless copy of the whole file.

    Setting ``cancel_event`` from another thread stops the run: FFmpeg is
    terminated, the partial segment it was mid-write is deleted, and
    :class:`SplitCancelled` is raised carrying the completed segments.

    Raises:
        probe.ProbeError: the input is missing/unreadable or not a video.
        ffmpeg.BinaryNotFoundError: ffmpeg/ffprobe could not be located.
        SplitError: FFmpeg failed or the output segments did not verify.
        SplitCancelled: ``cancel_event`` was set while the split was running.
    """
    input_path = Path(input_path)
    info = probe.probe(input_path)

    subtitle_warning = info.dropped_subtitle_warning()
    if subtitle_warning:
        _logger.warning("%s", subtitle_warning)

    if output_dir is None:
        output_dir = default_output_dir(input_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    ext = info.output_extension
    prefix = f"{input_path.stem}_part_"
    pattern = str(output_dir / f"{prefix}%03d{ext}")

    ffmpeg_bin = ffmpeg.find_ffmpeg()
    cmd = build_segment_command(ffmpeg_bin, input_path, pattern, segment_seconds, exact=exact)
    _logger.info(
        "splitting %s -> %s (segment_seconds=%d, exact=%s)",
        input_path,
        output_dir,
        segment_seconds,
        exact,
    )
    _logger.info("command: %s", " ".join(cmd))

    returncode, stderr, cancelled = _run_with_progress(
        cmd, info.duration_seconds, on_progress, cancel_event
    )

    if cancelled:
        kept = _discard_partial_segment(_collect_segments(output_dir, prefix, ext))
        _logger.info("split cancelled: kept %d complete segment(s) in %s", len(kept), output_dir)
        raise SplitCancelled(kept)

    if returncode != 0:
        _logger.error("ffmpeg exited %d: %s", returncode, stderr)
        raise SplitError(f"FFmpeg failed to split {input_path.name}: {stderr or 'unknown error'}")

    segments = _collect_segments(output_dir, prefix, ext)
    durations = _verify_segments(segments, info.duration_seconds)
    result = SplitResult(
        segments=tuple(segments),
        durations=durations,
        requested_seconds=segment_seconds,
        exact=exact,
    )
    _logger.info("split complete: %d segment(s) in %s", len(segments), output_dir)
    report = result.length_report()
    if report:
        _logger.info("%s", report)
    return result


def _collect_segments(output_dir: Path, prefix: str, ext: str) -> list[Path]:
    """Segment files this run wrote, in numeric (filename) order."""
    return sorted(
        p
        for p in output_dir.iterdir()
        if p.is_file() and p.name.startswith(prefix) and p.suffix.lower() == ext
    )


def _discard_partial_segment(segments: list[Path]) -> list[Path]:
    """Delete the last segment — the one FFmpeg was still writing when killed.

    Terminating FFmpeg mid-write leaves that file without a finalised container
    header (no moov atom for MP4), so it is unplayable. The earlier segments were
    already closed and remain valid, so only the tail is removed.
    """
    if not segments:
        return []
    partial = segments[-1]
    _logger.info("removing partial segment %s", partial.name)
    partial.unlink(missing_ok=True)
    return segments[:-1]


def _run_with_progress(
    cmd: list[str],
    total_seconds: float,
    on_progress: ProgressCallback | None,
    cancel_event: threading.Event | None = None,
) -> tuple[int, str, bool]:
    """Run ``cmd``, parsing ``-progress`` output; return (rc, stderr, cancelled).

    stderr is drained on a background thread so a chatty FFmpeg cannot deadlock
    by filling the pipe while we block reading stdout.

    ``cancel_event`` is checked once per progress line. FFmpeg emits those every
    few hundred milliseconds, so cancellation is responsive without needing a
    separate watchdog thread or a non-blocking read.
    """
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    stderr_chunks: list[str] = []

    def _drain_stderr() -> None:
        if proc.stderr is None:
            return
        for line in proc.stderr:
            stderr_chunks.append(line)

    drainer = threading.Thread(target=_drain_stderr, daemon=True)
    drainer.start()

    cancelled = False
    if proc.stdout is not None:
        for raw in proc.stdout:
            if cancel_event is not None and cancel_event.is_set():
                cancelled = True
                _terminate(proc)
                break
            _handle_progress_line(raw.strip(), total_seconds, on_progress)

    proc.wait()
    drainer.join(timeout=2)
    return proc.returncode, "".join(stderr_chunks).strip(), cancelled


def _terminate(proc: subprocess.Popen[str]) -> None:
    """Stop FFmpeg, escalating to a hard kill if it does not exit promptly."""
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        _logger.warning("ffmpeg did not exit after terminate(); killing it")
        proc.kill()
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=5)


def _handle_progress_line(
    line: str, total_seconds: float, on_progress: ProgressCallback | None
) -> None:
    if on_progress is None or "=" not in line:
        return
    key, _, value = line.partition("=")
    if key == "progress" and value == "end":
        on_progress(1.0)
        return
    if key == "out_time_us" and total_seconds > 0:
        try:
            elapsed = float(value) / 1_000_000
        except ValueError:  # "N/A" before the first packet
            return
        on_progress(max(0.0, min(elapsed / total_seconds, 1.0)))


def _verify_segments(segments: Sequence[Path], source_duration: float) -> tuple[float, ...]:
    """Post-run checks; returns each segment's measured duration.

    Checks that every segment is non-empty and that the durations sum back to the
    source. The per-segment durations are returned rather than discarded so the
    caller can report actual segment lengths without re-probing.
    """
    if not segments:
        raise SplitError("FFmpeg produced no output segments.")

    durations: list[float] = []
    for seg in segments:
        if seg.stat().st_size == 0:
            raise SplitError(f"Output segment {seg.name} is empty.")
        # Re-probing each segment also proves it is a valid, playable video.
        durations.append(probe.probe(seg).duration_seconds)

    total = sum(durations)
    drift = abs(total - source_duration)
    if drift > _DURATION_TOLERANCE_SECONDS:
        _logger.warning(
            "segment durations sum to %.2fs vs source %.2fs (drift %.2fs > %.1fs tolerance)",
            total,
            source_duration,
            drift,
            _DURATION_TOLERANCE_SECONDS,
        )
    return tuple(durations)
