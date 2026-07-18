"""Small formatting helpers shared by the CLI and the GUI."""

from __future__ import annotations

__all__ = ["format_duration"]


def format_duration(seconds: float) -> str:
    """Format a duration as ``M:SS``, or ``H:MM:SS`` once it reaches an hour."""
    total = round(seconds)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"
