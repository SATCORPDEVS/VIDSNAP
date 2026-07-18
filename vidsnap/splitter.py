"""Splitting engine — builds and runs the ffmpeg segment command. The core.

The split is **lossless stream copy** (``-c copy``): FFmpeg copies the encoded
video/audio packets straight into new segment files without re-encoding, so the
output is bit-identical to the source. The only cost is that cuts snap to the
nearest keyframe, so a "2:00" segment may run 2:00-2:04.

FFmpeg is always invoked with an argument list — never ``shell=True``, never a
concatenated string — so hostile filenames cannot inject commands. Progress is
read from ``-progress pipe:1`` and reported as a fraction in ``[0.0, 1.0]``;
after the run each segment is re-probed to prove it is a non-empty, valid video.
"""

from __future__ import annotations

import contextlib
import subprocess
import threading
from collections.abc import Callable, Sequence
from pathlib import Path

from vidsnap import ffmpeg, probe
from vidsnap.log import get_logger

_logger = get_logger()

DEFAULT_SEGMENT_SECONDS = 120

# How far the summed segment durations may drift from the source before we log a
# warning (keyframe cutting should not change total duration meaningfully).
_DURATION_TOLERANCE_SECONDS = 2.0

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


def build_segment_command(
    ffmpeg: str,
    input_path: Path,
    output_pattern: str,
    segment_seconds: int = DEFAULT_SEGMENT_SECONDS,
) -> list[str]:
    """Build the lossless stream-copy segment command as an argument list.

    ``output_pattern`` is a printf-style path (e.g. ``clip_part_%03d.mp4``).
    Always returns a list (never a shell string) so hostile filenames cannot
    inject commands.
    """
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
        "-c",
        "copy",  # lossless: copy packets, never re-encode
        "-f",
        "segment",
        "-segment_time",
        str(segment_seconds),
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
) -> Sequence[Path]:
    """Split ``input_path`` into ~``segment_seconds`` segments; return their paths.

    The source is probed first (validating it and giving the total duration used
    for progress). Segments are written to ``output_dir`` (default
    ``<input name>_segments`` next to the input) using the source's own
    container, then verified.

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
    cmd = build_segment_command(ffmpeg_bin, input_path, pattern, segment_seconds)
    _logger.info("splitting %s -> %s (segment_seconds=%d)", input_path, output_dir, segment_seconds)
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
    _verify_segments(segments, info.duration_seconds)
    _logger.info("split complete: %d segment(s) in %s", len(segments), output_dir)
    return segments


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


def _verify_segments(segments: Sequence[Path], source_duration: float) -> None:
    """Post-run checks: non-empty files, and durations that sum back to the source."""
    if not segments:
        raise SplitError("FFmpeg produced no output segments.")

    total = 0.0
    for seg in segments:
        if seg.stat().st_size == 0:
            raise SplitError(f"Output segment {seg.name} is empty.")
        # Re-probing each segment also proves it is a valid, playable video.
        total += probe.probe(seg).duration_seconds

    drift = abs(total - source_duration)
    if drift > _DURATION_TOLERANCE_SECONDS:
        _logger.warning(
            "segment durations sum to %.2fs vs source %.2fs (drift %.2fs > %.1fs tolerance)",
            total,
            source_duration,
            drift,
            _DURATION_TOLERANCE_SECONDS,
        )
