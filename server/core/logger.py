"""Application logging configuration.

Use ``get_logger(__name__)`` in modules. The root logger is configured once at
import time for console + file handlers under ``settings.log_dir``.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from core.config import settings


def setup_logging() -> logging.Logger:
    """Configure application-wide logging and return the app logger."""
    log_dir = Path(settings.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)
    log_format = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Avoid duplicate handlers on reload
    if root_logger.handlers:
        root_logger.handlers.clear()

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(logging.Formatter(log_format, date_format))

    file_handler = logging.FileHandler(log_dir / "app.log", encoding="utf-8")
    file_handler.setLevel(log_level)
    file_handler.setFormatter(logging.Formatter(log_format, date_format))

    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)

    app_logger = logging.getLogger(settings.app_name)
    app_logger.setLevel(log_level)
    return app_logger


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a module logger inheriting the application logging config."""
    return logging.getLogger(name or settings.app_name)


logger = setup_logging()
