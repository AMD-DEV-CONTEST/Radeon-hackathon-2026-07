"""Celery application stub for future background workers."""

from __future__ import annotations

from typing import Any

from core.config import settings
from core.logger import get_logger

logger = get_logger(__name__)


class CeleryAppStub:
    """Placeholder Celery app. Swap for real Celery when workers are enabled."""

    def __init__(self, name: str = "agentvox") -> None:
        self.name = name
        self.enabled = bool(getattr(settings, "celery_enabled", False))
        self.broker_url = getattr(settings, "celery_broker_url", None)
        self.result_backend = getattr(settings, "celery_result_backend", None)

    def task(self, *args: Any, **kwargs: Any):
        def decorator(fn):
            fn.delay = lambda *a, **k: None  # type: ignore[attr-defined]
            fn.apply_async = lambda *a, **k: None  # type: ignore[attr-defined]
            return fn

        if args and callable(args[0]):
            return decorator(args[0])
        return decorator


_celery_app: CeleryAppStub | None = None


def get_celery_app() -> CeleryAppStub:
    global _celery_app
    if _celery_app is None:
        _celery_app = CeleryAppStub()
        if not _celery_app.enabled:
            logger.debug("Celery integration disabled (stub app active)")
    return _celery_app
