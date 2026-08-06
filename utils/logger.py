"""Logging configuration."""

import logging
import sys

from config.settings import LOG_LEVEL


def setup_logging(name: str | None = None) -> logging.Logger:
    """Configure and return a logger with consistent formatting."""
    logger = logging.getLogger(name or __name__)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%H:%M:%S",
            )
        )
        logger.addHandler(handler)
        logger.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))
    return logger
