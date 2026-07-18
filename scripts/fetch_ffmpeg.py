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
import os
import shutil
import subprocess
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


def _find_bsdtar() -> str:
    """Locate a libarchive-backed tar that can read .7z archives.

    The gyan build is compressed with the **BCJ2 filter**, which the pure-Python
    ``py7zr`` cannot decode. libarchive's ``bsdtar`` can, and modern Windows
    (10 1803+/11) ships it as ``System32\\tar.exe``. We prefer that explicit
    path because a bare ``tar`` on ``PATH`` may resolve to GNU tar (which cannot
    read 7z at all).
    """
    if os.name == "nt":
        system_root = os.environ.get("SYSTEMROOT", r"C:\Windows")
        candidate = Path(system_root) / "System32" / "tar.exe"
        if candidate.is_file():
            return str(candidate)
    found = shutil.which("bsdtar") or shutil.which("tar")
    if found:
        return found
    sys.exit(
        "Could not find a tar capable of reading .7z archives.\n"
        "On Windows this is System32\\tar.exe (bsdtar); elsewhere install "
        "libarchive's bsdtar."
    )


def _extract_wanted(archive: Path, out_dir: Path) -> list[Path]:
    """Extract the wanted binaries from the .7z into ``out_dir`` via bsdtar.

    Extraction goes to a staging dir (bsdtar preserves the archive's versioned
    ``ffmpeg-<ver>-full_build/bin/`` layout); only the wanted binaries are then
    copied out, flattened into ``out_dir``. tar is always invoked with an
    argument list — never a shell string.
    """
    tar = _find_bsdtar()
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    with tempfile.TemporaryDirectory(
        prefix="vidsnap-extract-", ignore_cleanup_errors=True
    ) as staging:
        staging_dir = Path(staging)
        result = subprocess.run(
            [tar, "-xf", str(archive), "-C", str(staging_dir)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            sys.exit(f"tar failed to extract the archive:\n{result.stderr.strip()}")

        for wanted in WANTED:
            matches = list(staging_dir.rglob(wanted))
            if not matches:
                sys.exit(f"Archive did not contain expected binary: {wanted}")
            dest = out_dir / wanted
            shutil.copyfile(matches[0], dest)
            written.append(dest)
            size_mib = dest.stat().st_size // (1024 * 1024)
            try:
                shown: Path = dest.relative_to(_REPO_ROOT)
            except ValueError:  # out_dir given outside the repo
                shown = dest
            print(f"  wrote {shown} ({size_mib} MiB)")
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

    with tempfile.TemporaryDirectory(prefix="vidsnap-ffmpeg-", ignore_cleanup_errors=True) as tmp:
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
