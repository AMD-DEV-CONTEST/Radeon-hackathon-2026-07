from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

import structlog

from .config import AppPaths

LOG_FILE_NAME = "xenix.log"


def setup_logging(paths: AppPaths) -> Path:
    log_level_name = os.getenv("XENIX_LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_name, logging.INFO)
    log_path = paths.logs / LOG_FILE_NAME

    formatter = structlog.stdlib.ProcessorFormatter(
        processor=structlog.processors.JSONRenderer(sort_keys=True),
        foreign_pre_chain=_shared_processors(),
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.handlers.clear()
    _configure_structlog(log_level)

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    logging.captureWarnings(True)

    return log_path


def shutdown_logging() -> None:
    """Release process-wide handlers owned by the desktop runtime."""

    root_logger = logging.getLogger()
    handlers = tuple(root_logger.handlers)
    root_logger.handlers.clear()
    for handler in handlers:
        try:
            handler.flush()
        finally:
            handler.close()
    logging.captureWarnings(False)


def get_logger(name: str):
    return structlog.get_logger(name)


def _configure_structlog(log_level: int) -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.ExtraAdder(),
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    logging.getLogger().setLevel(log_level)


def _shared_processors():
    return [
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.ExtraAdder(),
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
