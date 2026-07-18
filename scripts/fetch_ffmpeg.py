"""Download the pinned FFmpeg GPL static build, verify it, and unpack to ``bin/``.

Security model
--------------
The archive is downloaded over HTTPS and its **SHA-256 is verified against the
value published by the build host before anything is unpacked**. A mismatch is a
hard failure — the partial download is deleted and no files are extracted. This
is what makes bundling a third-party binary safe: we pin an exact version and
refuse to run anything whose bytes we did not expect.

Updating FFmpeg
---------------
FFmpeg demuxer CVEs are regular, so updating is expected to be routine. To bump:
change ``FFMPEG_VERSION``, ``ARCHIVE_URL`` and ``ARCHIVE_SHA256`` below to the
new pinned build and its published checksum, then open a one-line PR.

Provenance (version, source URL, checksum) is recorded both here and, after a
successful fetch, in ``bin/FFMPEG_BUILD.txt``.

License note
------------
This is the **GPL** static build (gyan.dev full build): it includes libx264,
which the optional Phase 6 "exact cut" re-encode mode needs. Bundling it is why
VidSnap itself is licensed GPL-3.0-or-later.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import tempfile
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# Pinned build — the single place that defines which FFmpeg we ship.
# ---------------------------------------------------------------------------
FFMPEG_VERSION = "8.1.2"
BUILD_SOURCE = "gyan.dev full build (GPL)"
ARCHIVE_URL = "https://www.gyan.dev/ffmpeg/builds/packages/ffmpeg-8.1.2-full_build.7z"
# Published at ARCHIVE_URL + ".sha256"
ARCHIVE_SHA256 = "0fff188997a499b5382e0f66e845d4556c48c54f0113ebed4853d556dbdd7059"

# Binaries we actually keep out of the archive.
WANTED = ("ffmpeg.exe", "ffprobe.exe")

_REPO_ROOT = Path(__file__).resolve().parent.parent
_BIN_DIR = _REPO_ROOT / "bin"

_CHUNK = 1024 * 1024  # 1 MiB


class ChecksumError(RuntimeError):
    """Raised when the downloaded archive does not match the pinned checksum."""


def _download(url: str, dest: Path) -> None:
    print(f"Downloading {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "vidsnap-fetch-ffmpeg"})
    # URL is a pinned HTTPS constant defined above, not user input.
    with urllib.request.urlopen(req) as resp, dest.open("wb") as fh:
        total = int(resp.headers.get("Content-Length", 0))
        read = 0
        while True:
            chunk = resp.read(_CHUNK)
            if not chunk:
                break
            fh.write(chunk)
            read += len(chunk)
            if total:
                pct = read * 100 // total
                mib = read // (1024 * 1024)
                total_mib = total // (1024 * 1024)
                print(f"\r  {mib} / {total_mib} MiB ({pct}%)", end="")
        print()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify(path: Path, expected: str) -> None:
    actual = _sha256(path)
    if actual.lower() != expected.lower():
        path.unlink(missing_ok=True)
        raise ChecksumError(
            "SHA-256 mismatch — refusing to unpack.\n"
            f"  expected: {expected}\n"
            f"  actual:   {actual}\n"
            "The download was deleted. Do not use this file."
        )
    print(f"Checksum OK: {actual}")


def _extract_wanted(archive: Path, out_dir: Path) -> list[Path]:
    try:
        import py7zr
    except ImportError:
        sys.exit(
            "This script needs py7zr to unpack the .7z build.\n"
            "  Install it with:  uv sync --group setup   (or: pip install py7zr)"
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    with py7zr.SevenZipFile(archive, mode="r") as zf:
        # Map each wanted basename to its full path inside the archive.
        names = zf.getnames()
        targets = {
            wanted: name
            for wanted in WANTED
            for name in names
            if name.replace("\\", "/").endswith("/" + wanted) or name == wanted
        }
        missing = [w for w in WANTED if w not in targets]
        if missing:
            sys.exit(f"Archive did not contain expected binaries: {', '.join(missing)}")

        extracted = zf.read(targets.values())  # {archive_name: BytesIO}
        for wanted, archive_name in targets.items():
            data = extracted[archive_name].read()
            dest = out_dir / wanted
            dest.write_bytes(data)
            written.append(dest)
            print(f"  wrote {dest.relative_to(_REPO_ROOT)} ({len(data) // (1024 * 1024)} MiB)")
    return written


def _write_provenance(out_dir: Path) -> None:
    (out_dir / "FFMPEG_BUILD.txt").write_text(
        "\n".join(
            [
                "VidSnap bundled FFmpeg build",
                "============================",
                f"version : {FFMPEG_VERSION}",
                f"source  : {BUILD_SOURCE}",
                f"url     : {ARCHIVE_URL}",
                f"sha256  : {ARCHIVE_SHA256}",
                "license : GPL-3.0 (see LICENSE and README)",
                "",
                "Fetched by scripts/fetch_ffmpeg.py — do not edit by hand.",
                "",
            ]
        ),
        encoding="utf-8",
    )


def fetch(out_dir: Path = _BIN_DIR, *, force: bool = False) -> None:
    existing = [out_dir / w for w in WANTED]
    if not force and all(p.is_file() for p in existing):
        print(f"Binaries already present in {out_dir} — use --force to re-download.")
        return

    with tempfile.TemporaryDirectory(prefix="vidsnap-ffmpeg-") as tmp:
        archive = Path(tmp) / "ffmpeg.7z"
        _download(ARCHIVE_URL, archive)
        _verify(archive, ARCHIVE_SHA256)
        _extract_wanted(archive, out_dir)

    _write_provenance(out_dir)
    print(f"\nDone. FFmpeg {FFMPEG_VERSION} ready in {out_dir}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", type=Path, default=_BIN_DIR, help="output directory (default: bin/)"
    )
    parser.add_argument("--force", action="store_true", help="re-download even if binaries exist")
    args = parser.parse_args(argv)

    try:
        fetch(args.out, force=args.force)
    except ChecksumError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
