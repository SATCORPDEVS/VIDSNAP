# Changelog

All notable changes to VidSnap are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims to
adhere to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
