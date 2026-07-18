"""Tests for the ffprobe wrapper (:mod:`vidsnap.probe`).

Unit tests drive ``probe()`` with canned ffprobe JSON (monkeypatching the binary
lookup and ``subprocess.run``), so they need no real ffmpeg. Integration tests,
marked with ``requires_ffmpeg``, probe a synthetic video generated on the fly.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from conftest import make_testsrc, requires_ffmpeg
from vidsnap import probe
from vidsnap.probe import (
    InvalidInputError,
    MediaInfo,
    NoVideoStreamError,
    ProbeError,
)


def _fake_ffprobe_json(
    *,
    duration: str | None = "420.000000",
    format_name: str = "mov,mp4,m4a,3gp,3g2,mj2",
    video: dict[str, Any] | None = None,
    audio_count: int = 1,
    subtitle_codecs: tuple[str, ...] = (),
    extra_streams: list[dict[str, Any]] | None = None,
) -> str:
    """Build an ffprobe-shaped JSON string for the fake subprocess."""
    streams: list[dict[str, Any]] = []
    if video is not None:
        streams.append(video)
    for _ in range(audio_count):
        streams.append({"codec_type": "audio", "codec_name": "aac"})
    for codec in subtitle_codecs:
        streams.append({"codec_type": "subtitle", "codec_name": codec})
    streams.extend(extra_streams or [])

    fmt: dict[str, Any] = {"format_name": format_name}
    if duration is not None:
        fmt["duration"] = duration
    return json.dumps({"format": fmt, "streams": streams})


def _install_fake_probe(monkeypatch: pytest.MonkeyPatch, stdout: str) -> None:
    """Make ``probe.probe`` run against canned JSON instead of a real binary."""
    monkeypatch.setattr(probe.ffmpeg, "find_ffprobe", lambda: "ffprobe")

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(probe.subprocess, "run", fake_run)


@pytest.fixture
def sample_video(tmp_path: Path) -> Path:
    """A real (empty) file on disk so existence checks pass; contents unused by fakes."""
    p = tmp_path / "clip.mp4"
    p.write_bytes(b"not really a video")
    return p


# --------------------------------------------------------------------------- #
# Input validation
# --------------------------------------------------------------------------- #


def test_missing_file_raises_invalid_input(tmp_path: Path) -> None:
    with pytest.raises(InvalidInputError, match="does not exist"):
        probe.probe(tmp_path / "nope.mp4")


def test_directory_raises_invalid_input(tmp_path: Path) -> None:
    with pytest.raises(InvalidInputError, match="not a file"):
        probe.probe(tmp_path)


def test_ffprobe_failure_is_wrapped(monkeypatch: pytest.MonkeyPatch, sample_video: Path) -> None:
    monkeypatch.setattr(probe.ffmpeg, "find_ffprobe", lambda: "ffprobe")

    def fake_run(cmd, **kwargs):
        raise subprocess.CalledProcessError(1, cmd, output="", stderr="Invalid data found")

    monkeypatch.setattr(probe.subprocess, "run", fake_run)
    with pytest.raises(InvalidInputError, match="Invalid data found"):
        probe.probe(sample_video)


def test_unparseable_output_raises_probe_error(
    monkeypatch: pytest.MonkeyPatch, sample_video: Path
) -> None:
    _install_fake_probe(monkeypatch, stdout="{not json")
    with pytest.raises(ProbeError, match="parse"):
        probe.probe(sample_video)


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #


def test_parses_core_fields(monkeypatch: pytest.MonkeyPatch, sample_video: Path) -> None:
    stdout = _fake_ffprobe_json(
        video={
            "codec_type": "video",
            "codec_name": "h264",
            "width": 1920,
            "height": 1080,
        },
        audio_count=2,
    )
    _install_fake_probe(monkeypatch, stdout)
    info = probe.probe(sample_video)

    assert isinstance(info, MediaInfo)
    assert info.duration_seconds == pytest.approx(420.0)
    assert info.video_codec == "h264"
    assert info.width == 1920
    assert info.height == 1080
    assert info.resolution == "1920x1080"
    assert info.audio_stream_count == 2
    assert info.subtitle_stream_count == 0
    assert info.output_extension == ".mp4"


def test_no_video_stream_raises(monkeypatch: pytest.MonkeyPatch, sample_video: Path) -> None:
    stdout = _fake_ffprobe_json(video=None, audio_count=1)
    _install_fake_probe(monkeypatch, stdout)
    with pytest.raises(NoVideoStreamError):
        probe.probe(sample_video)


def test_attached_pic_is_not_treated_as_video(
    monkeypatch: pytest.MonkeyPatch, sample_video: Path
) -> None:
    # An MP3-style cover-art "video" stream must not count as a real track.
    cover = {
        "codec_type": "video",
        "codec_name": "mjpeg",
        "width": 600,
        "height": 600,
        "disposition": {"attached_pic": 1},
    }
    stdout = _fake_ffprobe_json(video=None, audio_count=1, extra_streams=[cover])
    _install_fake_probe(monkeypatch, stdout)
    with pytest.raises(NoVideoStreamError):
        probe.probe(sample_video)


def test_duration_falls_back_to_stream(monkeypatch: pytest.MonkeyPatch, sample_video: Path) -> None:
    stdout = _fake_ffprobe_json(
        duration=None,
        video={
            "codec_type": "video",
            "codec_name": "h264",
            "width": 640,
            "height": 480,
            "duration": "128.5",
        },
    )
    _install_fake_probe(monkeypatch, stdout)
    info = probe.probe(sample_video)
    assert info.duration_seconds == pytest.approx(128.5)


def test_missing_duration_everywhere_raises(
    monkeypatch: pytest.MonkeyPatch, sample_video: Path
) -> None:
    stdout = _fake_ffprobe_json(
        duration=None,
        video={"codec_type": "video", "codec_name": "h264", "width": 640, "height": 480},
    )
    _install_fake_probe(monkeypatch, stdout)
    with pytest.raises(ProbeError, match="duration"):
        probe.probe(sample_video)


# --------------------------------------------------------------------------- #
# Derived helpers
# --------------------------------------------------------------------------- #


def _mkinfo(path: Path, **overrides: Any) -> MediaInfo:
    base: dict[str, Any] = {
        "path": path,
        "duration_seconds": 300.0,
        "container": "matroska,webm",
        "video_codec": "h264",
        "width": 1280,
        "height": 720,
        "audio_stream_count": 1,
        "subtitle_stream_count": 0,
        "subtitle_codecs": (),
    }
    base.update(overrides)
    return MediaInfo(**base)


def test_is_shorter_than() -> None:
    info = _mkinfo(Path("x.mp4"), duration_seconds=90.0)
    assert info.is_shorter_than(120)
    assert not _mkinfo(Path("x.mp4"), duration_seconds=200.0).is_shorter_than(120)


def test_mp4_drops_srt_subtitles_warning() -> None:
    info = _mkinfo(
        Path("movie.mp4"),
        subtitle_stream_count=1,
        subtitle_codecs=("subrip",),
    )
    warning = info.dropped_subtitle_warning()
    assert warning is not None
    assert "subrip" in warning
    assert ".mp4" in warning


def test_mp4_keeps_mov_text_no_warning() -> None:
    info = _mkinfo(
        Path("movie.mp4"),
        subtitle_stream_count=1,
        subtitle_codecs=("mov_text",),
    )
    assert info.dropped_subtitle_warning() is None


def test_mkv_never_warns_about_subtitles() -> None:
    info = _mkinfo(
        Path("movie.mkv"),
        subtitle_stream_count=2,
        subtitle_codecs=("subrip", "ass"),
    )
    assert info.dropped_subtitle_warning() is None


# --------------------------------------------------------------------------- #
# Integration — real ffprobe against a synthetic video
# --------------------------------------------------------------------------- #


@requires_ffmpeg
@pytest.mark.integration
def test_probe_real_testsrc(tmp_path: Path) -> None:
    video = make_testsrc(tmp_path / "clip.mp4", seconds=5)
    info = probe.probe(video)
    assert info.duration_seconds == pytest.approx(5.0, abs=0.5)
    assert info.width == 320
    assert info.height == 240
    assert info.video_codec == "h264"
    assert info.audio_stream_count == 1
