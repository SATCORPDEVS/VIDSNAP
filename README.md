# VidSnap

Split any video into ~2-minute segments, saved as new files **with zero quality
loss**. VidSnap runs entirely on your machine — no web server, no cloud, no
accounts, **no telemetry**. Nothing you feed it ever leaves your computer.

> **Status:** early development. Phase 1 (environment, tooling & skeleton) is
> complete; the CLI/GUI split pipeline is being built out per
> [`DEVELOPMENT_PLAN.md`](DEVELOPMENT_PLAN.md).

## How it works

VidSnap wraps FFmpeg's **stream-copy** segmenter, so segments are bit-identical
copies of the source — no re-encoding, no generational quality loss, and a
multi-gigabyte file splits in seconds:

```
ffmpeg -i input.mp4 -c copy -map 0 \
       -f segment -segment_time 120 -reset_timestamps 1 \
       output_part_%03d.mp4
```

Because stream copy can only cut on keyframes, a segment asked to be 2:00 long
may actually be, say, 2:03. That is expected and is the price of losslessness. An
optional, clearly-labeled "exact cut" mode (re-encode) will be available later for
when frame-exact boundaries matter more than perfect fidelity.

## Development setup

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12+.

```bash
uv sync --group dev --group setup     # create the venv and install tooling
uv run python scripts/fetch_ffmpeg.py # download the pinned, checksum-verified FFmpeg into bin/
uv run ruff check .                   # lint
uv run ty check                       # type check
uv run pytest                         # tests
```

`scripts/fetch_ffmpeg.py` downloads a **pinned** FFmpeg build and **verifies its
published SHA-256 checksum before unpacking**, refusing to proceed on any
mismatch. The version, source, and checksum are recorded in the script and in
`bin/FFMPEG_BUILD.txt` after a successful fetch.

## Usage (target CLI)

```
vidsnap <input> [--minutes 2] [--out DIR] [--exact]
```

## FAQ

**Why is a segment 2:03 and not exactly 2:00?**
Lossless stream copy can only cut on keyframes, which don't fall exactly every
two minutes. VidSnap snaps to the nearest keyframe rather than re-encode. Use the
(future) `--exact` mode if you need frame-exact cuts and accept a re-encode.

**Does VidSnap send my videos anywhere?**
No. It is fully offline. The only part of this project that touches the network is
the developer script that downloads FFmpeg (`scripts/fetch_ffmpeg.py`).

## License

VidSnap is licensed under **GPL-3.0-or-later**. It bundles the GPL build of
FFmpeg (which includes libx264 for exact-cut mode); see
[`LICENSE`](LICENSE) and [`CLAUDE.md`](CLAUDE.md) for the licensing rationale.
FFmpeg is a trademark of Fabrice Bellard and is a separate work under its own
license.
