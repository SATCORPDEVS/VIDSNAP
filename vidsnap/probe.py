"""ffprobe wrapper — inspect a source video before splitting.

Runs ``ffprobe -print_format json -show_format -show_streams`` and distils the
result into a :class:`MediaInfo`: duration, container, video codec/resolution,
and audio/subtitle stream counts. It also validates the input (exists, is a
readable media file, has a real video stream) and flags streams that would be
lost when the output container cannot carry them (e.g. non-``mov_text``
subtitles written into an ``.mp4``).

Everything runs locally. ffprobe is always invoked with an argument list — never
``shell=True`` — so hostile filenames cannot inject commands.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from vidsnap import ffmpeg
from vidsnap.log import get_logger

_logger = get_logger()

# Subtitle codecs an MP4/MOV container can carry via ``-c copy``. Anything else
# (subrip, ass, …) is dropped when the segment is written to such a container.
_MP4_SUBTITLE_CODECS = frozenset({"mov_text"})
_MP4_LIKE_SUFFIXES = frozenset({".mp4", ".m4v", ".mov"})


class ProbeError(RuntimeError):
    """Base error for probing failures."""


class InvalidInputError(ProbeError):
    """The input is missing, unreadable, or not a media file ffprobe understands."""


class NoVideoStreamError(ProbeError):
    """The input parsed as media but has no real video stream to split."""


@dataclass(frozen=True)
class MediaInfo:
    """Summary of a source media file, as reported by ffprobe."""

    path: Path
    duration_seconds: float
    container: str
    video_codec: str
    width: int
    height: int
    audio_stream_count: int
    subtitle_stream_count: int
    subtitle_codecs: tuple[str, ...] = field(default_factory=tuple)

    @property
    def resolution(self) -> str:
        """Human-readable ``"1920x1080"`` resolution string."""
        return f"{self.width}x{self.height}"

    @property
    def output_extension(self) -> str:
        """Container extension segments should use — the input's own suffix.

        VidSnap never transcodes the container, so the output extension mirrors
        the input. Falls back to ``.mkv`` (the most permissive container) when
        the input has no suffix.
        """
        return self.path.suffix.lower() or ".mkv"

    def is_shorter_than(self, segment_seconds: float) -> bool:
        """True when the whole file is shorter than one segment."""
        return self.duration_seconds <= segment_seconds

    def dropped_subtitle_warning(self) -> str | None:
        """Warn if subtitle streams would be dropped by the output container.

        MKV keeps everything; MP4/MOV only carry ``mov_text`` subtitles. Returns
        a user-facing message when streams would be lost, else ``None``.
        """
        if self.subtitle_stream_count == 0:
            return None
        if self.output_extension not in _MP4_LIKE_SUFFIXES:
            return None
        incompatible = sorted({c for c in self.subtitle_codecs if c not in _MP4_SUBTITLE_CODECS})
        if not incompatible:
            return None
        return (
            f"{len(incompatible)} subtitle format(s) ({', '.join(incompatible)}) cannot be "
            f"stored in a {self.output_extension} container and will be dropped during the "
            "split. Use an .mkv source to keep every stream."
        )


def probe(path: Path) -> MediaInfo:
    """Probe ``path`` with ffprobe and return a :class:`MediaInfo`.

    Raises:
        InvalidInputError: the file is missing/unreadable or ffprobe rejects it.
        NoVideoStreamError: the file has no real video stream to split.
        ProbeError: ffprobe output could not be parsed or lacked a duration.
    """
    path = Path(path)
    if not path.exists():
        raise InvalidInputError(f"Input file does not exist: {path}")
    if not path.is_file():
        raise InvalidInputError(f"Input path is not a file: {path}")

    ffprobe_bin = ffmpeg.find_ffprobe()
    cmd = [
        ffprobe_bin,
        # ``-v error`` (not ``quiet``) keeps genuine errors on stderr so a failed
        # probe is diagnosable, while still suppressing info/warning noise.
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    _logger.info("probing %s", path)
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True, encoding="utf-8")
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        _logger.error("ffprobe failed for %s: %s", path, stderr)
        raise InvalidInputError(
            f"ffprobe could not read {path.name}: {stderr or 'unknown error'}"
        ) from exc

    try:
        data: dict[str, Any] = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ProbeError(f"Could not parse ffprobe output for {path.name}") from exc

    return _parse(path, data)


def _to_float(value: object) -> float | None:
    if isinstance(value, (str, int, float)):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _extract_duration(fmt: dict[str, Any], streams: list[dict[str, Any]]) -> float:
    """Best-effort duration: prefer the container, fall back to the longest stream."""
    container_duration = _to_float(fmt.get("duration"))
    if container_duration is not None and container_duration > 0:
        return container_duration
    stream_durations = [
        d for s in streams if (d := _to_float(s.get("duration"))) is not None and d > 0
    ]
    if stream_durations:
        return max(stream_durations)
    raise ProbeError("Could not determine media duration from ffprobe output.")


def _is_attached_pic(stream: dict[str, Any]) -> bool:
    """True for cover-art / thumbnail 'video' streams, which aren't real tracks."""
    return stream.get("disposition", {}).get("attached_pic", 0) == 1


def _parse(path: Path, data: dict[str, Any]) -> MediaInfo:
    fmt: dict[str, Any] = data.get("format", {})
    streams: list[dict[str, Any]] = data.get("streams", [])

    video_streams = [
        s for s in streams if s.get("codec_type") == "video" and not _is_attached_pic(s)
    ]
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
    subtitle_streams = [s for s in streams if s.get("codec_type") == "subtitle"]

    if not video_streams:
        raise NoVideoStreamError(
            f"No video stream found in {path.name}; VidSnap only splits videos."
        )

    video = video_streams[0]
    return MediaInfo(
        path=path,
        duration_seconds=_extract_duration(fmt, streams),
        container=str(fmt.get("format_name", "unknown")),
        video_codec=str(video.get("codec_name", "unknown")),
        width=int(video.get("width", 0) or 0),
        height=int(video.get("height", 0) or 0),
        audio_stream_count=len(audio_streams),
        subtitle_stream_count=len(subtitle_streams),
        subtitle_codecs=tuple(str(s.get("codec_name", "unknown")) for s in subtitle_streams),
    )
