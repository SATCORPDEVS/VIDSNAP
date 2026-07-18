# VidSnap

Split any video into ~2-minute segments, saved as new files **with zero quality
loss**. VidSnap runs entirely on your machine — no web server, no cloud, no
accounts, **no telemetry**. Nothing you feed it ever leaves your computer.

> **Status:** usable. Phases 1–6 are complete — the CLI and the GUI both split
> videos losslessly, exact-cut mode is available, and the awkward-input edge
> cases are covered. Remaining work (a packaged installer) is tracked in
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
may actually be, say, 2:03. That is expected and is the price of losslessness —
and VidSnap tells you when it happens, rather than leaving you to find a 2:14
segment in a player.

When frame-exact boundaries matter more than perfect fidelity, **exact-cut mode**
(`--exact`, or the checkbox in the GUI) re-encodes the video with a keyframe forced
on every boundary. It is much slower and costs one generation of quality, so it is
never the default and every entry point says so before it starts.

## Development setup

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12+.

```bash
uv sync --group dev                   # create the venv and install tooling
uv run python scripts/fetch_ffmpeg.py # download the pinned, checksum-verified FFmpeg into bin/
uv run ruff check .                   # lint
uv run ty check                       # type check
uv run pytest                         # tests
```

`scripts/fetch_ffmpeg.py` downloads a **pinned** FFmpeg build and **verifies its
published SHA-256 checksum before unpacking**, refusing to proceed on any
mismatch. The version, source, and checksum are recorded in the script and in
`bin/FFMPEG_BUILD.txt` after a successful fetch.

## Usage

### GUI

```
vidsnap-gui
```

Choose a video, set the segment length in minutes, optionally pick an output
folder or tick **Exact cuts**, and press **Split**. Progress is shown as it runs and the window stays
responsive; **Cancel** stops FFmpeg, keeps the segments already finished, and
deletes the partial one it was still writing.

### CLI

```
vidsnap <input> [--minutes 2] [--out DIR] [--exact]
```

Segments are written to `<input name>_segments/` next to the input unless
`--out` says otherwise. `--exact` re-encodes for frame-exact cuts.

VidSnap warns before it starts when the output folder is inside a cloud-synced
folder (OneDrive, Dropbox, …) or on a different drive from the source, and when
subtitle streams cannot survive the output container.

## FAQ

**Why is a segment 2:03 and not exactly 2:00?**
Lossless stream copy can only cut on keyframes, which don't fall exactly every
two minutes. VidSnap snaps to the nearest keyframe rather than re-encode, and
reports the real lengths when they run long. Sources with sparse keyframes (screen
recordings often have 10 s between them) drift the most. Use `--exact` if you need
frame-exact cuts and accept a re-encode.

**My video is shorter than one segment. What happens?**
You get a single output file that is a lossless copy of the whole video, and a
note saying so.

**Can it handle a 10 GB file?**
Yes. FFmpeg streams the file; VidSnap never loads video into memory, so a 10 GB
source costs no more RAM than a small one.

**Does VidSnap send my videos anywhere?**
No. It is fully offline. The only part of this project that touches the network is
the developer script that downloads FFmpeg (`scripts/fetch_ffmpeg.py`).

## License

VidSnap is licensed under **GPL-3.0-or-later**. It bundles the GPL build of
FFmpeg (which includes libx264 for exact-cut mode); see
[`LICENSE`](LICENSE) and [`CLAUDE.md`](CLAUDE.md) for the licensing rationale.
FFmpeg is a trademark of Fabrice Bellard and is a separate work under its own
license.
