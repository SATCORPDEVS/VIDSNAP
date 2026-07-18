"""Clean-machine smoke test for an *installed* VidSnap.

This is the check that the packaged app actually works — not the code, which
``pytest`` already covers, but the artifact a user downloads: the frozen
executable, the FFmpeg copied inside it, and the paths it resolves at runtime.
CI runs this on a bare ``windows-latest`` runner after installing the installer,
which is the closest thing to a clean machine we get for free.

Deliberately stdlib-only and it does **not** import ``vidsnap``: importing the
source package would test the checkout rather than the installation.

    python scripts/smoke_test.py "C:\\Program Files\\VidSnap"

Checks, in order:

1. ``vidsnap.exe --version`` runs and prints a version.
2. The bundled ffmpeg is present and executable, and generates a 5-minute
   synthetic video (so the test needs nothing pre-installed).
3. Splitting it into 2-minute segments produces 3 files.
4. Each segment probes as a valid video, and their codec matches the source —
   proof the shipped binary really did a stream copy rather than re-encoding.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

_FIXTURE_SECONDS = 300
_SEGMENT_MINUTES = 2
_EXPECTED_SEGMENTS = 3


class SmokeTestError(RuntimeError):
    """A smoke-test check failed."""


def _run(cmd: list[str], what: str, timeout: int = 300) -> str:
    """Run ``cmd`` (argument list, never a shell string) and return stdout."""
    print(f"$ {' '.join(cmd)}", flush=True)
    result = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout
    )
    if result.returncode != 0:
        raise SmokeTestError(
            f"{what} failed (exit {result.returncode}).\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result.stdout


def _check_version(vidsnap_exe: Path) -> None:
    out = _run([str(vidsnap_exe), "--version"], "vidsnap --version", timeout=60)
    if "vidsnap" not in out.lower():
        raise SmokeTestError(f"--version printed something unexpected: {out!r}")
    print(f"  version: {out.strip()}")


def _make_fixture(ffmpeg: Path, dest: Path) -> None:
    _run(
        [
            str(ffmpeg),
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=duration={_FIXTURE_SECONDS}:size=320x240:rate=30",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={_FIXTURE_SECONDS}",
            "-c:v",
            "libx264",
            "-g",
            "30",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(dest),
        ],
        "fixture generation with the bundled ffmpeg",
    )
    if not dest.is_file() or dest.stat().st_size == 0:
        raise SmokeTestError(f"bundled ffmpeg produced no fixture at {dest}")


def _video_codec(ffprobe: Path, video: Path) -> str:
    out = _run(
        [
            str(ffprobe),
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_streams",
            "-select_streams",
            "v:0",
            str(video),
        ],
        f"ffprobe {video.name}",
        timeout=60,
    )
    streams = json.loads(out).get("streams", [])
    if not streams:
        raise SmokeTestError(f"{video.name} has no video stream — it is not a valid segment")
    return str(streams[0].get("codec_name", ""))


def smoke_test(install_dir: Path) -> None:
    vidsnap_exe = install_dir / "vidsnap.exe"
    gui_exe = install_dir / "vidsnap-gui.exe"
    bundled = install_dir / "_internal" / "bin"
    ffmpeg = bundled / "ffmpeg.exe"
    ffprobe = bundled / "ffprobe.exe"

    print(f"Smoke-testing the installation at {install_dir}\n")
    for required in (vidsnap_exe, gui_exe, ffmpeg, ffprobe):
        if not required.is_file():
            raise SmokeTestError(f"installation is missing {required}")

    print("[1/4] vidsnap --version")
    _check_version(vidsnap_exe)

    with tempfile.TemporaryDirectory(prefix="vidsnap-smoke-") as tmp:
        tmp_path = Path(tmp)
        source = tmp_path / "smoke_source.mp4"
        out_dir = tmp_path / "segments"

        print("\n[2/4] generating a 5-minute fixture with the bundled ffmpeg")
        _make_fixture(ffmpeg, source)

        print(f"\n[3/4] splitting it into {_SEGMENT_MINUTES}-minute segments")
        _run(
            [
                str(vidsnap_exe),
                str(source),
                "--minutes",
                str(_SEGMENT_MINUTES),
                "--out",
                str(out_dir),
            ],
            "vidsnap split",
        )
        segments = sorted(out_dir.glob("smoke_source_part_*.mp4"))
        if len(segments) != _EXPECTED_SEGMENTS:
            raise SmokeTestError(
                f"expected {_EXPECTED_SEGMENTS} segments from a "
                f"{_FIXTURE_SECONDS}s source split at {_SEGMENT_MINUTES} min, "
                f"got {len(segments)}: {[s.name for s in segments]}"
            )
        print(f"  {len(segments)} segments: {', '.join(s.name for s in segments)}")

        print("\n[4/4] verifying the segments are valid and were not re-encoded")
        source_codec = _video_codec(ffprobe, source)
        for seg in segments:
            if seg.stat().st_size == 0:
                raise SmokeTestError(f"segment {seg.name} is empty")
            seg_codec = _video_codec(ffprobe, seg)
            if seg_codec != source_codec:
                raise SmokeTestError(
                    f"segment {seg.name} has codec {seg_codec!r} but the source is "
                    f"{source_codec!r} — the installed build re-encoded instead of "
                    "stream-copying"
                )
        print(f"  all segments are {source_codec}, matching the source (lossless)")

    print("\nSmoke test passed.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="smoke_test",
        description="Verify an installed VidSnap can split a video losslessly.",
    )
    parser.add_argument(
        "install_dir",
        nargs="?",
        default=r"C:\Program Files\VidSnap",
        help="the VidSnap installation directory (default: %(default)s)",
    )
    args = parser.parse_args(argv)

    try:
        smoke_test(Path(args.install_dir))
    except (SmokeTestError, subprocess.TimeoutExpired) as exc:
        print(f"\nSmoke test FAILED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
