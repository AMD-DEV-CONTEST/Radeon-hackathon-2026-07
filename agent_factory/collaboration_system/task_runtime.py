"""Application-level registration for the single background-task service."""

from __future__ import annotations

from threading import RLock

from agent_factory.collaboration_system.task_service import BackgroundTaskService
from agent_factory.contracts import ServiceUnavailableError


_lock = RLock()
_service: BackgroundTaskService | None = None


def register_background_task_service(service: BackgroundTaskService) -> None:
    global _service
    with _lock:
        if _service is not None and _service is not service:
            raise RuntimeError("a background-task service is already registered")
        _service = service


def unregister_background_task_service(service: BackgroundTaskService) -> None:
    global _service
    with _lock:
        if _service is service:
            _service = None


def background_task_service() -> BackgroundTaskService:
    with _lock:
        service = _service
    if service is None:
        raise ServiceUnavailableError("后台任务服务尚未启动。")
    return service
