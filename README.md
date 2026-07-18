# VidSnap

Split any video into ~2-minute segments, saved as new files **with zero quality
loss**. VidSnap runs entirely on your machine — no web server, no cloud, no
accounts, **no telemetry**. Nothing you feed it ever leaves your computer.

> **Status:** feature-complete. All seven phases are done — the CLI and the GUI
> split videos losslessly, exact-cut mode is available, the awkward-input edge
> cases are covered, and there is a Windows installer.

## Install

Download `VidSnapSetup-<version>.exe` from the
[latest release](https://github.com/SATCORPDEVS/VIDSNAP/releases) and run it.
**Nothing else to install** — FFmpeg ships inside.

The installer works without administrator rights (it falls back to a per-user
install), adds a Start Menu entry for the GUI, and can optionally put the
`vidsnap` command on your `PATH`.

Windows SmartScreen will likely warn that the app is unrecognised, because the
build is not code-signed — a signing certificate costs a few hundred dollars a
year and is deliberately deferred. Choose **More info → Run anyway** if you trust
the download.

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

### Building the installer

```bash
uv sync --group dev --group packaging
uv run python scripts/fetch_ffmpeg.py          # bin/ must be populated first
uv run python scripts/build_installer.py       # --skip-installer to stop after PyInstaller
```

This produces `dist/VidSnap/` (a runnable one-dir build, ~490 MB — almost all of
it the bundled FFmpeg) and `dist/installer/VidSnapSetup-<version>.exe`. The
installer step needs [Inno Setup 6](https://jrsoftware.org/isdl.php); the build
script finds `ISCC.exe` on `PATH` or in the usual install locations.

PyInstaller is used in **one-dir** mode, never one-file: a one-file build
re-extracts itself to a temp folder on every launch, which is both what packers
do (AV heuristics flag it) and a needless 170 MB unpack each time you split a
video. UPX compression is off for the same reason. If Defender flags even the
one-dir build, the next thing to try is Nuitka — not one-file.

`scripts/smoke_test.py <install-dir>` checks an *installed* copy end to end:
`--version`, then generating a video with the bundled FFmpeg, splitting it, and
verifying the segments' codec matches the source. CI runs it on a bare
`windows-latest` runner after a silent install, which is the clean-machine test.

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

**Source offer.** The GPL requires that anyone given the binary can get the
corresponding source. For any released installer, that source is this repository
at the matching `v<version>` tag. The bundled FFmpeg is an unmodified upstream
build; its exact version, download URL, and verified SHA-256 are pinned in
[`scripts/fetch_ffmpeg.py`](scripts/fetch_ffmpeg.py) and recorded in
`_internal/bin/FFMPEG_BUILD.txt` inside the installation, and FFmpeg's own source
is available from the FFmpeg project.
