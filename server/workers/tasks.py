"""Celery task stubs. No background work is executed yet."""

from __future__ import annotations

from typing import Any

from integrations.celery_app import get_celery_app

celery_app = get_celery_app()


@celery_app.task(name="workers.tasks.example_task")
def example_task(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Placeholder task for future async jobs (resume parse, report export, etc.)."""
    return {"status": "stub", "payload": payload or {}}
