"""LangSmith tracing stub for future LangGraph observability."""

from __future__ import annotations

from typing import Any

from core.config import settings
from core.logger import get_logger

logger = get_logger(__name__)


class LangSmithTracer:
    """No-op tracer. Replace with langsmith client when enabled."""

    def __init__(self, api_key: str | None = None, project: str | None = None) -> None:
        self.api_key = api_key or getattr(settings, "langsmith_api_key", None)
        self.project = project or getattr(settings, "langsmith_project", "agentvox")
        self.enabled = bool(getattr(settings, "langsmith_enabled", False) and self.api_key)

    def traceable(self, name: str | None = None):
        def decorator(fn):
            return fn

        _ = name
        return decorator

    def log_event(self, event: str, payload: dict[str, Any] | None = None) -> None:
        _ = (event, payload)
        return None


_tracer: LangSmithTracer | None = None


def get_langsmith_tracer() -> LangSmithTracer:
    global _tracer
    if _tracer is None:
        _tracer = LangSmithTracer()
        if not _tracer.enabled:
            logger.debug("LangSmith tracing disabled (stub tracer active)")
    return _tracer
