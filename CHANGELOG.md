# Changelog

All notable changes to VidSnap are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims to
adhere to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
