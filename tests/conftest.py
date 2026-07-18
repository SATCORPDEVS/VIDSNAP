"""Shared test fixtures.

Test videos are generated on demand with ``ffmpeg -f lavfi -i testsrc`` — never
committed as binaries. Integration tests that need a real ffmpeg are skipped
automatically when no binary is available (bundled or on PATH).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from vidsnap import ffmpeg


def _ffmpeg_available() -> bool:
    try:
        ffmpeg.find_ffmpeg()
    except ffmpeg.BinaryNotFoundError:
        return False
    return True


requires_ffmpeg = pytest.mark.skipif(
    not _ffmpeg_available(),
    reason="no ffmpeg binary available (run scripts/fetch_ffmpeg.py)",
)


def make_testsrc(dest: Path, *, seconds: int, fps: int = 30) -> Path:
    """Generate a synthetic test video at ``dest`` using ffmpeg's testsrc.

    A short GOP (keyframe every second) keeps keyframe-aligned splits predictable
    for tests. Returns ``dest``.
    """
    ffmpeg_bin = ffmpeg.find_ffmpeg()
    cmd = [
        ffmpeg_bin,
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=duration={seconds}:size=320x240:rate={fps}",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=440:duration={seconds}",
        "-c:v",
        "libx264",
        "-g",
        str(fps),  # keyframe every second
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        str(dest),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return dest


@pytest.fixture
def testsrc_7min(tmp_path: Path) -> Path:
    """A 7-minute synthetic video — expected to split into 4 two-minute segments."""
    return make_testsrc(tmp_path / "testsrc_7min.mp4", seconds=7 * 60)
