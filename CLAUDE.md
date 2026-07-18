# CLAUDE.md — VidSnap project context

Context for AI-assisted development sessions. Read this and `DEVELOPMENT_PLAN.md`
before making changes.

## What VidSnap is

A local Windows desktop tool that splits a video of any size into ~2-minute
segments saved as new video files **with zero quality loss**. Fully offline: no
web server, no cloud, no accounts, **no telemetry**. Nothing ever leaves the
machine.

## The one decision that governs everything

Splitting is done with **FFmpeg stream copy** (`-c copy`), never re-encoding by
default. Stream copy is bit-identical (lossless) and fast, at the cost of cutting
on keyframes (a "2:00" segment may be 2:00–2:04). Re-encoding is offered only as
an explicit, clearly-warned optional "exact cut" mode (Phase 6).

Canonical command:

```
ffmpeg -i input.mp4 -c copy -map 0 \
       -f segment -segment_time 120 -reset_timestamps 1 \
       output_part_%03d.mp4
```

## Tech stack

- **Python 3.12+**, fully type-hinted.
- **uv** for envs/deps/lockfile (`uv.lock` committed). **Ruff** for lint + format.
  **ty** for type checking. **pytest** for tests. All config lives in
  `pyproject.toml` — no `requirements.txt`, no `setup.py`.
- **FFmpeg + FFprobe**: bundled static binaries, **pinned to an exact version and
  SHA-256-verified at download time** by `scripts/fetch_ffmpeg.py`. Users install
  nothing.
- **GUI**: Tkinter (stdlib), with a Windows DPI-awareness shim called *before* the
  Tk root is created.
- **CLI**: `vidsnap input.mp4 --minutes 2`.
- **Packaging** (Phase 7): PyInstaller one-dir + Inno Setup installer (never
  one-file — AV heuristics flag it). Nuitka is the fallback.

## Licensing

VidSnap is **GPL-3.0-or-later** because it bundles the **GPL** FFmpeg build
(gyan.dev full build), which includes libx264 for exact-cut mode. The bundled
build's version, source URL, and verified checksum are pinned in
`scripts/fetch_ffmpeg.py` and recorded in `bin/FFMPEG_BUILD.txt` after fetch.

## Non-negotiable engineering rules

- **Subprocess safety:** always invoke ffmpeg/ffprobe with an **argument list** —
  never `shell=True`, never string-concatenated commands. Hostile filenames must
  not be able to inject.
- **Binary resolution:** go through `vidsnap/ffmpeg.py` (bundled `bin/` first,
  then `ffmpeg` on PATH). Don't hardcode paths elsewhere.
- **Lossless by default:** any code path that re-encodes must be behind the
  explicit `--exact` opt-in and clearly labeled.
- **Streaming, never buffering:** never load video into memory; a 10 GB file must
  split under ~100 MB RAM.
- **Privacy:** logging is local-only (rotating file in app-data via `vidsnap/log.py`).
  Never add network calls to the app itself. The only network access in the repo
  is `scripts/fetch_ffmpeg.py`.

## Layout

- `vidsnap/probe.py` — ffprobe wrapper (Phase 2)
- `vidsnap/splitter.py` — segment command build + run + verify (Phase 3, the core)
- `vidsnap/cli.py` — argparse entry point (Phase 4)
- `vidsnap/gui.py` — Tkinter window (Phase 5)
- `vidsnap/ffmpeg.py` — binary resolver
- `vidsnap/log.py` — local rotating-file logging
- `scripts/fetch_ffmpeg.py` — pinned, checksum-verified FFmpeg downloader
- `tests/` — unit + integration (integration tests skip when no ffmpeg present)

## Common commands

```
uv sync --group dev                 # set up the environment
uv run python scripts/fetch_ffmpeg.py   # download the pinned FFmpeg into bin/
uv run ruff check .                 # lint
uv run ruff format .                # format
uv run ty check                     # type check
uv run pytest                       # tests
```

## Development phases

See `DEVELOPMENT_PLAN.md`. The phase **order** is the commitment. A usable
CLI-only tool exists after Phase 4. Current status: **Phase 4 complete** — the
tool is usable: `vidsnap input.mp4 --minutes 2` probes, splits losslessly, and
reports the output folder. Phases 2–3 delivered `probe.py` and the `splitter.py`
engine; Phase 1 delivered the environment, tooling, skeleton, CI, and pinned
FFmpeg fetcher. Next: Phase 5 (Tkinter GUI).
