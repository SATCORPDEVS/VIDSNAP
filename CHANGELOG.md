# Changelog

All notable changes to VidSnap are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims to
adhere to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
