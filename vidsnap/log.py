"""Local file logging setup.

VidSnap logs to a rotating file in the per-user app-data directory. Nothing ever
leaves the machine — this is purely so that user-reported failures are diagnosable.
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

_APP_NAME = "VidSnap"
_LOGGER_NAME = "vidsnap"
_MAX_BYTES = 1 * 1024 * 1024  # 1 MiB per file
_BACKUP_COUNT = 3

_configured = False


def app_data_dir() -> Path:
    """Return the per-user directory VidSnap uses for logs and state.

    Windows: ``%LOCALAPPDATA%\\VidSnap``. Other platforms fall back to
    ``$XDG_STATE_HOME`` / ``~/.local/state`` so the module stays importable
    (and testable) off-Windows.
    """
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
    else:
        base = os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state")
    path = Path(base) / _APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_file() -> Path:
    """Absolute path to the current log file."""
    return app_data_dir() / "vidsnap.log"


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """Configure and return the shared ``vidsnap`` logger.

    Idempotent: safe to call from both the CLI and GUI entry points.
    """
    global _configured
    logger = logging.getLogger(_LOGGER_NAME)
    if _configured:
        return logger

    logger.setLevel(level)
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        log_file(), maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    _configured = True
    return logger


def get_logger() -> logging.Logger:
    """Return the shared logger, configuring it on first use."""
    return setup_logging()
