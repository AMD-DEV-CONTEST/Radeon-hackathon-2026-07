"""
LaunchKart AI 2.0 — Structured Logging

Configures structlog for JSON logging with correlation IDs and performance metrics.
"""

from __future__ import annotations

import logging
import sys
import uuid
from typing import Any
from contextvars import ContextVar

import structlog

# Context variable for request correlation ID
_correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")


def get_correlation_id() -> str:
    """Retrieve the current correlation ID."""
    return _correlation_id.get()


def set_correlation_id(corr_id: str | None = None) -> str:
    """Set the correlation ID for the current context."""
    new_id = corr_id or str(uuid.uuid4())
    _correlation_id.set(new_id)
    return new_id


def add_correlation_id(
    logger: logging.Logger, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Structlog processor to inject correlation ID into logs."""
    corr_id = _correlation_id.get()
    if corr_id:
        event_dict["request_id"] = corr_id
    return event_dict


def setup_logging(env: str = "development", debug: bool = True) -> None:
    """Configure structured logging application-wide."""
    
    # Base processors
    shared_processors: list[Any] = [
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        add_correlation_id,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    # Renderer depends on environment
    if env == "production" or not debug:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=shared_processors + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.DEBUG if debug else logging.INFO)
    
    # Disable duplicate uvicorn logging
    for _log in ["uvicorn", "uvicorn.error", "uvicorn.access"]:
        l = logging.getLogger(_log)
        l.handlers.clear()
        l.propagate = True
