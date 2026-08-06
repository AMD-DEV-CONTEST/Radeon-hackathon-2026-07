from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


WorkerLifecycleAction = Literal["start", "shutdown"]
WorkerLifecycleStatus = Literal["completed", "failed", "skipped"]


@dataclass(frozen=True, slots=True)
class WorkerLifecycleEvent:
    worker_id: str
    worker_type: str
    action: WorkerLifecycleAction
    status: WorkerLifecycleStatus
    message: str = ""


class RuntimeBackgroundWorkerManager:
    def __init__(self, workers: list[Any] | tuple[Any, ...] | None = None) -> None:
        self._workers: list[Any] = []
        self._started: list[Any] = []
        self._started_ids: set[int] = set()
        if workers:
            self.add_many(workers)

    @property
    def workers(self) -> tuple[Any, ...]:
        return tuple(self._workers)

    @property
    def started_workers(self) -> tuple[Any, ...]:
        return tuple(self._started)

    def add(self, worker: Any) -> None:
        if any(item is worker for item in self._workers):
            return
        self._workers.append(worker)

    def add_many(self, workers: list[Any] | tuple[Any, ...]) -> None:
        for worker in workers:
            self.add(worker)

    def start_all(self) -> list[WorkerLifecycleEvent]:
        events: list[WorkerLifecycleEvent] = []
        for worker in self._workers:
            worker_key = id(worker)
            if worker_key in self._started_ids:
                events.append(_event(worker, action="start", status="skipped", message="already started"))
                continue
            start = getattr(worker, "start", None)
            if not callable(start):
                events.append(_event(worker, action="start", status="skipped", message="worker has no start method"))
                continue
            try:
                start()
            except Exception as exc:
                events.append(_event(worker, action="start", status="failed", message=f"{type(exc).__name__}: {exc}"))
                continue
            self._started_ids.add(worker_key)
            self._started.append(worker)
            events.append(_event(worker, action="start", status="completed"))
        return events

    def shutdown_all(self) -> list[WorkerLifecycleEvent]:
        events: list[WorkerLifecycleEvent] = []
        for worker in reversed(self._started):
            shutdown = getattr(worker, "shutdown", None)
            if not callable(shutdown):
                shutdown = getattr(worker, "stop", None)
            if not callable(shutdown):
                events.append(_event(worker, action="shutdown", status="skipped", message="worker has no shutdown or stop method"))
                continue
            try:
                shutdown()
            except Exception as exc:
                events.append(_event(worker, action="shutdown", status="failed", message=f"{type(exc).__name__}: {exc}"))
                continue
            events.append(_event(worker, action="shutdown", status="completed"))
        self._started.clear()
        self._started_ids.clear()
        return events


def _event(
    worker: Any,
    *,
    action: WorkerLifecycleAction,
    status: WorkerLifecycleStatus,
    message: str = "",
) -> WorkerLifecycleEvent:
    return WorkerLifecycleEvent(
        worker_id=_worker_id(worker),
        worker_type=type(worker).__name__,
        action=action,
        status=status,
        message=message,
    )


def _worker_id(worker: Any) -> str:
    runtime = getattr(worker, "runtime", None)
    owner_type = getattr(runtime, "owner_type", None)
    owner_id = getattr(runtime, "owner_id", None)
    if owner_type and owner_id:
        return f"{type(worker).__name__}:{owner_type}:{owner_id}"
    return f"{type(worker).__name__}:{id(worker)}"
