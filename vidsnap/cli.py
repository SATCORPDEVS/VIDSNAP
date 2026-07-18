"""Command-line entry point.

``vidsnap <input> [--minutes 2] [--out DIR]`` probes the source, prints a short
summary, splits it losslessly (stream copy) into ~N-minute segments, and shows a
progress bar. Exact-cut (re-encode) mode is scaffolded via ``--exact`` but lands
in Phase 6.
"""

from __future__ import annotations

import argparse
import math
import sys
from collections.abc import Sequence
from pathlib import Path

from vidsnap import __version__, ffmpeg, probe, splitter
from vidsnap.humanize import format_duration
from vidsnap.log import setup_logging


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vidsnap",
        description="Split a video into ~N-minute segments locally, with zero quality loss.",
    )
    parser.add_argument("input", nargs="?", help="path to the source video")
    parser.add_argument(
        "--minutes",
        type=float,
        default=DEFAULT_MINUTES,
        help="segment length in minutes (default: 2)",
    )
    parser.add_argument(
        "--out",
        metavar="DIR",
        help="output directory (default: <input name>_segments next to the input)",
    )
    parser.add_argument(
        "--exact",
        action="store_true",
        help="frame-exact cuts via re-encode (slower, minor quality trade-off; Phase 6)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


DEFAULT_MINUTES = splitter.DEFAULT_SEGMENT_SECONDS / 60


def _make_progress_printer() -> splitter.ProgressCallback:
    """Return a callback that renders a single-line percentage bar on stderr."""
    state = {"last_pct": -1}
    width = 30

    def render(fraction: float) -> None:
        pct = int(fraction * 100)
        if pct == state["last_pct"]:
            return
        state["last_pct"] = pct
        filled = int(width * fraction)
        bar = "#" * filled + "-" * (width - filled)
        print(f"\r  [{bar}] {pct:3d}%", end="", file=sys.stderr, flush=True)

    return render


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.input:
        parser.error("the following argument is required: input")

    setup_logging()

    if args.exact:
        print(
            "Exact-cut (re-encode) mode is not available yet — it lands in Phase 6.\n"
            "Re-run without --exact for the lossless stream-copy split.",
            file=sys.stderr,
        )
        return 2

    segment_seconds = round(args.minutes * 60)
    if segment_seconds < 1:
        parser.error("--minutes must be greater than 0")

    input_path = Path(args.input)

    try:
        info = probe.probe(input_path)
    except (probe.ProbeError, ffmpeg.BinaryNotFoundError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    n_segments = math.ceil(info.duration_seconds / segment_seconds)
    print(
        f"{input_path.name}: {format_duration(info.duration_seconds)}, "
        f"{info.resolution} {info.video_codec} "
        f"-> ~{n_segments} segment(s) of {args.minutes:g} min"
    )

    subtitle_warning = info.dropped_subtitle_warning()
    if subtitle_warning:
        print(f"Warning: {subtitle_warning}", file=sys.stderr)

    output_dir = Path(args.out) if args.out else None
    try:
        segments = splitter.split(
            input_path,
            output_dir,
            segment_seconds,
            on_progress=_make_progress_printer(),
        )
    except (splitter.SplitError, probe.ProbeError, ffmpeg.BinaryNotFoundError) as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        return 1

    dest = segments[0].parent if segments else (output_dir or input_path.parent)
    print(f"\nDone. {len(segments)} file(s) created in {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
