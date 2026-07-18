"""Splitting engine — builds and runs the ffmpeg segment command.

Implemented in Phase 3 (the core). This module constructs the stream-copy
segment command, streams ffmpeg progress, and verifies the output segments.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

DEFAULT_SEGMENT_SECONDS = 120

# Progress is reported in [0.0, 1.0].
ProgressCallback = Callable[[float], None]


def build_segment_command(
    ffmpeg: str,
    input_path: Path,
    output_pattern: str,
    segment_seconds: int = DEFAULT_SEGMENT_SECONDS,
) -> list[str]:
    """Build the lossless stream-copy segment command as an argument list.

    Always returns a list (never a shell string) so hostile filenames cannot
    inject commands. Phase 3 wires this into execution + progress parsing.
    """
    raise NotImplementedError("build_segment_command() lands in Phase 3")


def split(
    input_path: Path,
    output_dir: Path | None = None,
    segment_seconds: int = DEFAULT_SEGMENT_SECONDS,
    on_progress: ProgressCallback | None = None,
) -> Sequence[Path]:
    """Split ``input_path`` into segments; return the created file paths.

    Phase 3 will implement this.
    """
    raise NotImplementedError("split() lands in Phase 3")
