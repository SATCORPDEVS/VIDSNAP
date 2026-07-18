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


def _run_ffmpeg(args: list[str]) -> None:
    """Run ffmpeg for fixture generation, surfacing stderr if it fails."""
    result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8")
    if result.returncode != 0:
        raise RuntimeError(f"fixture ffmpeg failed:\n{result.stderr}")


def make_testsrc(
    dest: Path,
    *,
    seconds: int,
    fps: int = 30,
    gop_seconds: int = 1,
    audio_tracks: int = 1,
    rotate: int | None = None,
    vfr: bool = False,
) -> Path:
    """Generate a synthetic test video at ``dest`` using ffmpeg's testsrc.

    Defaults give a short GOP (keyframe every second), which keeps keyframe-aligned
    splits predictable. The keyword arguments exist to reproduce the awkward
    sources Phase 6 hardens against:

    ``gop_seconds``
        Seconds between keyframes. A large value imitates a screen recording,
        where a stream copy can only cut every GOP.
    ``audio_tracks``
        Number of audio streams, for checking every track survives the split.
    ``rotate``
        Degrees of display rotation, as phone videos carry in metadata.
    ``vfr``
        Emit variable frame timing rather than a constant rate.

    Returns ``dest``.
    """
    ffmpeg_bin = ffmpeg.find_ffmpeg()
    cmd = [
        ffmpeg_bin,
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=duration={seconds}:size=320x240:rate={fps}",
    ]
    for _ in range(audio_tracks):
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]

    cmd += ["-map", "0:v"]
    for index in range(audio_tracks):
        cmd += ["-map", f"{index + 1}:a"]

    if vfr:
        # Drop frames in alternating one-second windows, then let the muxer keep
        # the resulting uneven timestamps instead of padding back to a fixed rate.
        cmd += ["-vf", "select='lte(mod(t,2),1)'", "-fps_mode", "vfr"]

    cmd += [
        "-c:v",
        "libx264",
        "-g",
        str(fps * gop_seconds),
        "-keyint_min",
        str(fps * gop_seconds),
        # Without this x264 inserts extra keyframes at scene changes, which would
        # undo a deliberately long GOP.
        "-sc_threshold",
        "0",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        str(dest),
    ]
    _run_ffmpeg(cmd)

    if rotate is not None:
        _apply_rotation(dest, rotate)
    return dest


def _apply_rotation(video: Path, degrees: int) -> None:
    """Stamp display-rotation metadata onto ``video``, in place.

    ``-display_rotation`` is an *input* option, so this remuxes the file through a
    stream copy — the same lossless path VidSnap uses — rather than re-encoding.
    """
    ffmpeg_bin = ffmpeg.find_ffmpeg()
    rotated = video.with_name(f"{video.stem}_rot{video.suffix}")
    _run_ffmpeg(
        [
            ffmpeg_bin,
            "-y",
            "-display_rotation",
            str(degrees),
            "-i",
            str(video),
            "-map",
            "0",
            "-c",
            "copy",
            str(rotated),
        ]
    )
    rotated.replace(video)


@pytest.fixture
def testsrc_7min(tmp_path: Path) -> Path:
    """A 7-minute synthetic video — expected to split into 4 two-minute segments."""
    return make_testsrc(tmp_path / "testsrc_7min.mp4", seconds=7 * 60)
