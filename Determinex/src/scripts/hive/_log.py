"""
scripts/hive/_log.py — Structured logger for the Hive package
=============================================================
Drop-in structlog wrapper that replaces `logging.getLogger("hive")` throughout
the hive package. Every log call automatically carries bound context:
  session_id, step_id, attempt, oracle, model — set via bind_session().

Usage:
    from hive._log import get_logger, bind_session

    log = get_logger(__name__)
    log.info("step_start", step_id=step.id)

    # Bind session context for all subsequent log calls in this thread:
    bind_session(session_id="abc123", model="ollama/qwen2.5-coder")

    # Or use the context manager:
    with bound_context(session_id="abc123"):
        log.info("oracle_pass", oracle="rust", attempt=1)

Structured output:
    - Development: human-readable colored output via structlog.dev.ConsoleRenderer
    - CI / production: JSON via structlog.processors.JSONRenderer
      Set DETERMINEX_LOG_FORMAT=json to force JSON. Default: auto-detect (TTY → console).

Stdlib logging compatibility:
    stdlib `logging.getLogger("hive")` still works — structlog wraps the stdlib
    handler so existing callsites that haven't been updated keep emitting events.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

try:
    import structlog

    _STRUCTLOG_AVAILABLE = True
except ImportError:
    _STRUCTLOG_AVAILABLE = False

# ── Thread-local context store ────────────────────────────────────────────────
_local = threading.local()


def _get_ctx() -> dict[str, Any]:
    if not hasattr(_local, "ctx"):
        _local.ctx = {}
    return _local.ctx


def bind_session(
    session_id: str = "",
    step_id: int | None = None,
    attempt: int | None = None,
    model: str = "",
    oracle: str = "",
    **extra: Any,
) -> None:
    """Bind session context to the current thread. All subsequent log calls
    on this thread will include these fields automatically."""
    ctx = _get_ctx()
    if session_id:
        ctx["session_id"] = session_id
    if step_id is not None:
        ctx["step_id"] = step_id
    if attempt is not None:
        ctx["attempt"] = attempt
    if model:
        ctx["model"] = model
    if oracle:
        ctx["oracle"] = oracle
    ctx.update(extra)


def clear_session() -> None:
    """Clear thread-local context (call at session end)."""
    _local.ctx = {}


@contextmanager
def bound_context(**kwargs: Any) -> Generator[None, None, None]:
    """Context manager: bind kwargs for the duration, then restore previous state."""
    ctx = _get_ctx()
    old = dict(ctx)
    bind_session(**kwargs)
    try:
        yield
    finally:
        _local.ctx = old


# ── Structlog configuration ───────────────────────────────────────────────────


def _configure_structlog() -> None:
    """Configure structlog once at import time."""
    if not _STRUCTLOG_AVAILABLE:
        return

    log_format = os.environ.get("DETERMINEX_LOG_FORMAT", "").lower()
    use_json = log_format == "json" or not sys.stderr.isatty()

    shared_processors = [
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        # Inject thread-local session context into every event
        _inject_context,
    ]

    if use_json:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=shared_processors + [renderer],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Bridge stdlib logging through structlog so existing `logging.getLogger`
    # calls in code we haven't migrated yet still appear in the structured stream.
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stderr,
        level=logging.DEBUG if os.environ.get("DETERMINEX_DEBUG") else logging.INFO,
    )


def _inject_context(logger: Any, method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Structlog processor: merge thread-local session context into every event."""
    ctx = _get_ctx()
    for k, v in ctx.items():
        event_dict.setdefault(k, v)
    return event_dict


_configure_structlog()


# ── Public API ────────────────────────────────────────────────────────────────


def get_logger(name: str = "hive") -> Any:
    """Return a structured logger bound to `name`.

    Falls back to stdlib `logging.getLogger` if structlog is not installed,
    so this is safe to import even without structlog in the dependency set.
    """
    if _STRUCTLOG_AVAILABLE:
        return structlog.get_logger(name)
    return logging.getLogger(name)


# Module-level default logger for hive package consumers
log = get_logger("hive")
