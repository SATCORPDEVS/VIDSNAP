# Changelog

All notable changes to VidSnap are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims to
adhere to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added — Phase 7 (tests & packaging)
- **Windows installer.** `packaging/vidsnap.spec` freezes the app with
  PyInstaller in **one-dir** mode — producing `vidsnap.exe` (console) and
  `vidsnap-gui.exe` (windowed) sharing one library tree — and
  `packaging/vidsnap.iss` wraps that in an Inno Setup installer with a Start Menu
  entry, an optional desktop icon, and an optional `PATH` entry. One-file mode
  and UPX are deliberately avoided: both are AV heuristics, and one-file would
  also re-extract ~170 MB of FFmpeg on every launch. The installer needs no
  administrator rights (per-user fallback via `PrivilegesRequired=lowest`).
- `vidsnap/ffmpeg.py` now resolves `bin/` in a frozen build as well as from a
  source checkout: when `sys.frozen` is set it anchors on `sys._MEIPASS` (the
  `_internal` folder the spec copies the binaries into), falling back to the
  folder holding the executable. The FFmpeg binaries are bundled as *data*, not
  as `binaries`, so PyInstaller does not scan a static exe for library imports.
- `scripts/build_installer.py`: runs PyInstaller then Inno Setup, taking the
  version from `vidsnap/__init__.py` so it cannot drift, clearing stale build
  caches first, and failing early with a readable message when `bin/` is empty or
  `ISCC.exe` is missing. `--skip-installer` stops after the frozen build.
- `scripts/smoke_test.py`: the clean-machine check, run against an *installed*
  copy. Stdlib-only and it never imports `vidsnap`, since importing the source
  would test the checkout rather than the installation. It runs `--version`,
  generates a 5-minute video with the bundled FFmpeg, splits it, and asserts
  three valid segments whose codec matches the source — proving the shipped
  binary stream-copies rather than re-encodes.
- **CI release job**, on `v*` tags and gated behind the existing quality job:
  builds the installer on `windows-latest`, installs it silently on the bare
  runner, runs the smoke test, and uploads the installer as the artifact plus a
  draft release whose notes carry the GPL source offer.
- `tests/test_packaging.py`: covers the frozen-resolution branches (the one code
  path that otherwise runs for the first time on a user's machine) and pins the
  packaging inputs — one-dir not one-file, FFmpeg bundled, installer version in
  step with the package, GPL licence conveyed.
- README: an Install section, installer-build instructions, a SmartScreen note,
  and an explicit GPL written source offer.

### Added — Phase 6 (hardening & edge cases)
- **Exact-cut mode**, the one opt-in path that re-encodes: `--exact` on the CLI,
  an unticked-by-default checkbox in the GUI. The video is re-encoded
  (`libx264 -crf 17 -preset slow`) with a keyframe forced on every boundary, so
  cuts are frame-accurate; audio and subtitles are still copied untouched. Both
  front ends state the cost — much slower, one generation of quality — before
  starting. `-segment_time_delta 0.05` accompanies it: without that tolerance a
  forced keyframe landing a rounding-hair before the boundary makes the segment
  muxer skip the cut, doubling the first segment's length.
- `splitter.split()` now returns a `SplitResult` (segment paths **plus each
  segment's measured duration**, already gathered during verification) instead of
  a bare path list. It behaves like a sequence — `len()` and iteration yield the
  segments — so callers read the same as before.
- `SplitResult.length_report()`: when stream copy has to overshoot because the
  source's keyframes are far apart, the CLI, GUI, and log say by how much rather
  than leaving the user to find a 2:14 "2-minute" segment in a player. The short
  final remainder is excluded — that is arithmetic, not drift.
- `vidsnap/paths.py`: pre-split advisories. Warns when the output folder is inside
  a cloud-synced tree (OneDrive/Dropbox/Google Drive/iCloud — the segments are
  about the size of the source, so syncing them is a real cost) or on a different
  drive from the source.
- A source shorter than one segment now says so explicitly in both front ends:
  the result is a single lossless copy of the whole file.
- `tests/test_paths.py`, plus splitter integration coverage for the sources that
  actually break things: spaces/unicode/bracket filenames, sparse-keyframe
  sources (drift reported losslessly, exact in `--exact`), multiple audio tracks,
  rotation metadata surviving a stream copy, and variable frame rate.
  `make_testsrc` grew `gop_seconds`, `audio_tracks`, `rotate`, and `vfr` to
  generate them.

### Added — Phase 5 (GUI)
- `vidsnap/gui.py`: Tkinter window with a video picker, segment-length spinner
  (minutes, default 2), output-folder picker, progress bar, status line, and an
  "Open folder" button on completion. Launch with `vidsnap-gui`.
- Windows DPI awareness is enabled *before* the Tk root is created, and Tk's
  font scaling is set from the real display DPI, so the UI is neither blurry nor
  undersized on high-DPI screens.
- The split runs on a worker thread so the window stays responsive. That thread
  never touches a widget: it posts typed messages to a `queue.Queue` which the UI
  thread drains from an `after()` timer.
- **Cancel** support, new in the engine: `splitter.split()` takes a
  `cancel_event`; setting it terminates FFmpeg, deletes the partial segment it
  was mid-write (an unfinalised container is unplayable), keeps the completed
  ones, and raises `SplitCancelled`. Closing the window mid-split cancels too,
  rather than orphaning the FFmpeg process.
- `vidsnap/humanize.py`: `format_duration` extracted so the CLI and GUI share one
  implementation.
- `tests/test_gui.py` and `tests/test_humanize.py`; cancellation tests added to
  `tests/test_splitter.py`. GUI tests share a single session Tk root and give
  each test its own `Toplevel`, and skip cleanly where no usable Tk is present.

### Added — Phase 4 (CLI)
- `vidsnap <input> [--minutes 2] [--out DIR]` runs the full pipeline: probe →
  summary → lossless split → progress bar → output-folder report. `--exact` is
  parsed but reports that re-encode mode lands in Phase 6.
- `tests/test_cli.py`: argument/error-path unit tests plus an end-to-end
  integration split.

### Added — Phase 3 (splitting engine)
- `vidsnap/splitter.py`: builds and runs the lossless stream-copy segment
  command (`-c copy -map 0 -f segment -segment_time N -reset_timestamps 1`),
  always as an argument list — never a shell string.
- Streams FFmpeg's `-progress pipe:1` output to emit progress callbacks in
  `[0.0, 1.0]`; stderr is drained on a background thread so a chatty FFmpeg
  cannot deadlock the pipe.
- Segments are written to `<input name>_segments/` (overridable) using the
  source's own container, named `<name>_part_001.<ext>` upward.
- Post-run verification: each segment is re-probed (non-empty, valid video) and
  the summed durations are checked against the source (±2 s, logged on drift).
- Fixed `scripts/fetch_ffmpeg.py`: the gyan `.7z` uses the BCJ2 filter, which
  `py7zr` cannot decode. Extraction now shells out to libarchive's `bsdtar`
  (bundled with Windows 10 1803+/11), and the `py7zr` dependency / `setup`
  dependency-group are dropped.
- `tests/test_splitter.py`: command-construction and progress-parsing unit
  tests; integration tests assert segment count, non-empty files, duration sums,
  and **codec equality proving no re-encode occurred**.

### Added — Phase 2 (probing module)
- `vidsnap/probe.py`: ffprobe wrapper. Runs `ffprobe -print_format json
  -show_format -show_streams` (invoked as an argument list, never a shell
  string) and returns a `MediaInfo` with duration, container, video
  codec/resolution, and audio/subtitle stream counts.
- Input validation: raises `InvalidInputError` for missing/unreadable files or
  ffprobe rejections, and `NoVideoStreamError` when there is no real video
  stream (cover-art / attached-pic "video" streams are ignored).
- Duration is read from the container, falling back to the longest stream.
- `MediaInfo.dropped_subtitle_warning()`: flags subtitle streams that an
  MP4/MOV container cannot carry (only `mov_text` survives; MKV keeps
  everything), so no stream is lost silently.
- `tests/test_probe.py`: unit tests drive `probe()` with canned ffprobe JSON
  (no ffmpeg required); an integration test probes a synthetic video when a
  real binary is present.

### Added — Phase 1 (environment, tooling & skeleton)
- Project scaffold: `pyproject.toml` as the single source of truth (uv, Ruff
  lint+format, ty, pytest); package skeleton under `vidsnap/`.
- `vidsnap/ffmpeg.py`: runtime resolver — bundled `bin/` binary first, then
  `ffmpeg`/`ffprobe` on PATH.
- `vidsnap/log.py`: local rotating-file logging in the per-user app-data dir
  (nothing leaves the machine).
- `vidsnap/cli.py`: argument parser with working `--version` (split pipeline
  lands in Phase 4).
- `scripts/fetch_ffmpeg.py`: downloads the **pinned** FFmpeg GPL static build
  (gyan.dev full build 8.1.2) and **verifies its published SHA-256 before
  unpacking**, failing hard on mismatch; records provenance in
  `bin/FFMPEG_BUILD.txt`.
- GitHub Actions CI: `ruff check`, `ruff format --check`, `ty check`, and
  `pytest` on every push (quality gates from the first commit).
- `LICENSE` (GPL-3.0), `CLAUDE.md`, this changelog.

[Unreleased]: https://github.com/vidsnap/vidsnap/commits/main
