"""Logging setup shared by every command."""

from __future__ import annotations

import logging
from os import environ
from pathlib import Path

from rich.logging import RichHandler

LOG_LEVELS = ("debug", "info", "warning", "error", "critical")
FILE_FORMAT = "%(asctime)s.%(msecs)03d %(levelname)-8s %(name)s: %(message)s"


def default_log_level() -> str:
    """``$LOG_LEVEL`` if it names a level, else ``info``."""
    level = environ.get("LOG_LEVEL", "info").strip().lower()
    return level if level in LOG_LEVELS else "info"


def setup_logging(
    level: str, *, log_file: Path | None = None, console: bool = True
) -> None:
    """Log at ``level`` to the console (rich) and/or ``log_file`` (appended).

    Interactive UIs pass ``console=False`` so log lines don't break the screen.
    """
    handlers: list[logging.Handler] = []
    if console:
        handlers.append(RichHandler(markup=False, rich_tracebacks=True))
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(logging.Formatter(FILE_FORMAT, "%H:%M:%S"))
        handlers.append(file_handler)
    if not handlers:
        handlers.append(logging.NullHandler())
    logging.basicConfig(
        level=level.upper(), format="%(message)s", datefmt="%H:%M:%S", handlers=handlers
    )


def set_log_level(level: str) -> str:
    """Change the root logger's level at runtime; returns the new level name."""
    name = level.strip().lower()
    if name not in LOG_LEVELS:
        raise ValueError(f"level must be one of {', '.join(LOG_LEVELS)}")
    logging.getLogger().setLevel(name.upper())
    return name


def current_log_level() -> str:
    """The root logger's level as a lowercase name."""
    return logging.getLevelName(logging.getLogger().getEffectiveLevel()).lower()
