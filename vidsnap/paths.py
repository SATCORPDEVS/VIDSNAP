"""Path-level advisories shown before a split starts.

Nothing here changes what VidSnap does — these helpers only produce warnings the
CLI and GUI can show, so a slow or surprising outcome is predicted rather than
discovered afterwards.
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = ["cloud_sync_warning", "different_drive_warning", "is_cloud_synced"]

# Folder-name markers for the desktop sync clients that watch a directory tree.
# Matching on the name (rather than an env var) also catches a second account's
# folder, e.g. "OneDrive - Contoso".
_SYNC_MARKERS = ("onedrive", "dropbox", "google drive", "googledrive", "icloud")


def is_cloud_synced(path: Path) -> bool:
    """True when ``path`` sits inside a folder a sync client is watching.

    Purely name-based: a sync client's own state is not something we inspect, and
    a false positive only costs the user an extra sentence of warning.
    """
    parts = [part.casefold() for part in Path(path).absolute().parts]
    return any(part.startswith(marker) for part in parts for marker in _SYNC_MARKERS)


def cloud_sync_warning(output_dir: Path) -> str | None:
    """Warn that segments written here will be uploaded by a sync client.

    Splitting is lossless, so the segments together are roughly the size of the
    source — writing them into a synced folder silently doubles what the client
    has to upload. Returns a user-facing message, or ``None`` if the destination
    is not synced.
    """
    if not is_cloud_synced(output_dir):
        return None
    return (
        f"{output_dir} is inside a cloud-synced folder. The segments together are about "
        "the size of the source video, so syncing them may take a while and use quota. "
        "Choose a local folder if you only want the files on this machine."
    )


def different_drive_warning(input_path: Path, output_dir: Path) -> str | None:
    """Warn when segments land on a different drive from the source.

    Same-drive output is a fast local write; a different drive (or a network
    share) means every byte crosses that link, which dominates the runtime of an
    otherwise seconds-long stream copy.
    """
    source_drive = os.path.splitdrive(Path(input_path).absolute())[0].casefold()
    dest_drive = os.path.splitdrive(Path(output_dir).absolute())[0].casefold()
    if not source_drive or not dest_drive or source_drive == dest_drive:
        return None
    return (
        f"The output folder is on {dest_drive or 'another drive'} but the source is on "
        f"{source_drive}. Every byte has to be copied across, which is much slower than "
        "splitting to the same drive."
    )
