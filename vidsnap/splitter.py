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
) -> Sequence[Path]:
    """Split ``input_path`` into ~``segment_seconds`` segments; return their paths.

    The source is probed first (validating it and giving the total duration used
    for progress). Segments are written to ``output_dir`` (default
    ``<input name>_segments`` next to the input) using the source's own
    container, then verified.

    Raises:
        probe.ProbeError: the input is missing/unreadable or not a video.
        ffmpeg.BinaryNotFoundError: ffmpeg/ffprobe could not be located.
        SplitError: FFmpeg failed or the output segments did not verify.
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

    returncode, stderr = _run_with_progress(cmd, info.duration_seconds, on_progress)
    if returncode != 0:
        _logger.error("ffmpeg exited %d: %s", returncode, stderr)
        raise SplitError(f"FFmpeg failed to split {input_path.name}: {stderr or 'unknown error'}")

    segments = sorted(
        p
        for p in output_dir.iterdir()
        if p.is_file() and p.name.startswith(prefix) and p.suffix.lower() == ext
    )
    _verify_segments(segments, info.duration_seconds)
    _logger.info("split complete: %d segment(s) in %s", len(segments), output_dir)
    return segments


def _run_with_progress(
    cmd: list[str],
    total_seconds: float,
    on_progress: ProgressCallback | None,
) -> tuple[int, str]:
    """Run ``cmd``, parsing ``-progress`` output on stdout; return (rc, stderr).

    stderr is drained on a background thread so a chatty FFmpeg cannot deadlock
    by filling the pipe while we block reading stdout.
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

    if proc.stdout is not None:
        for raw in proc.stdout:
            _handle_progress_line(raw.strip(), total_seconds, on_progress)

    proc.wait()
    drainer.join(timeout=2)
    return proc.returncode, "".join(stderr_chunks).strip()


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
