"""Command-line entry point.

Phase 1 provides ``--version`` and argument parsing; the actual split is wired
up in Phase 4 once the probing (Phase 2) and splitting (Phase 3) engines exist.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from vidsnap import __version__
from vidsnap.splitter import DEFAULT_SEGMENT_SECONDS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vidsnap",
        description="Split a video into ~N-minute segments locally, with zero quality loss.",
    )
    parser.add_argument("input", nargs="?", help="path to the source video")
    parser.add_argument(
        "--minutes",
        type=float,
        default=DEFAULT_SEGMENT_SECONDS / 60,
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
        help="frame-exact cuts via re-encode (slower, minor quality trade-off)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.input:
        parser.error("the following argument is required: input")

    # Phases 2-4 wire probe -> split -> progress reporting here.
    raise NotImplementedError("the split pipeline lands in Phase 4")


if __name__ == "__main__":
    raise SystemExit(main())
