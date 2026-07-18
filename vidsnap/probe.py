"""ffprobe wrapper — inspect a source video before splitting.

Implemented in Phase 2. This module extracts duration, container format,
codecs, resolution, and audio/subtitle stream counts, and validates the input.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MediaInfo:
    """Summary of a source media file (populated in Phase 2)."""

    path: Path
    duration_seconds: float
    container: str
    video_codec: str
    width: int
    height: int
    audio_stream_count: int
    subtitle_stream_count: int


def probe(path: Path) -> MediaInfo:
    """Probe ``path`` with ffprobe and return a :class:`MediaInfo`.

    Phase 2 will implement this.
    """
    raise NotImplementedError("probe() lands in Phase 2")
