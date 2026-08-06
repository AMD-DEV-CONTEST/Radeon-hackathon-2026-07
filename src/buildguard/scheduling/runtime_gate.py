"""Thread-safe admission gate connecting GPU work to the priority scheduler."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from buildguard.monitoring.base import BaseHardwareMonitor
from buildguard.scheduling.gpu_scheduler import GpuScheduler
from buildguard.scheduling.schemas import (
    GpuResourceState,
    GpuTask,
    SchedulingDecision,
)

LOGGER = logging.getLogger(__name__)
ResourceProvider = Callable[[], GpuResourceState | None]


class GpuAdmissionError(RuntimeError):
    """A bounded GPU request was rejected or timed out before execution."""


class ModelResidencyRegistry:
    """Observed/configured in-process model residency without fake unload hooks."""

    def __init__(self) -> None:
        self._models: dict[str, float] = {}
        self._pinned: set[str] = set()
        self._lock = threading.RLock()

    def register(self, name: str, memory_mb: float, *, pinned: bool = True) -> None:
        if not name.strip() or memory_mb < 0:
            raise ValueError("resident model name and memory must be valid")
        with self._lock:
            self._models[name] = float(memory_mb)
            if pinned:
                self._pinned.add(name)
            else:
                self._pinned.discard(name)

    def unregister(self, name: str) -> None:
        with self._lock:
            self._models.pop(name, None)
            self._pinned.discard(name)

    def snapshot(self) -> tuple[dict[str, float], set[str]]:
        with self._lock:
            return dict(self._models), set(self._pinned)


class MonitoredGpuResourceProvider:
    """Convert cached hardware telemetry into scheduler resource state."""

    def __init__(
        self,
        monitor: BaseHardwareMonitor,
        *,
        cache_seconds: float = 1.0,
        residency: ModelResidencyRegistry | None = None,
    ) -> None:
        if cache_seconds <= 0:
            raise ValueError("GPU telemetry cache_seconds must be positive")
        self.monitor = monitor
        self.cache_seconds = cache_seconds
        self.residency = residency
        self._lock = threading.RLock()
        self._sampled_at = 0.0
        self._cached: GpuResourceState | None = None

    def __call__(self) -> GpuResourceState | None:
        with self._lock:
            resident, pinned = (
                self.residency.snapshot() if self.residency is not None else ({}, set())
            )
            current = time.monotonic()
            if current - self._sampled_at < self.cache_seconds:
                return (
                    self._cached.model_copy(
                        update={"resident_models": resident, "pinned_models": pinned},
                        deep=True,
                    )
                    if self._cached
                    else None
                )
            snapshot = self.monitor.snapshot()
            self._sampled_at = current
            if not snapshot.gpus:
                self._cached = None
                return None
            gpu = snapshot.gpus[0]
            if gpu.memory_used_mb is None or gpu.memory_total_mb is None:
                self._cached = None
                return None
            self._cached = GpuResourceState(
                utilization_percent=gpu.utilization_percent or 0,
                memory_used_mb=gpu.memory_used_mb,
                memory_total_mb=gpu.memory_total_mb,
                resident_models=resident,
                pinned_models=pinned,
            )
            return self._cached.model_copy(deep=True)


class GpuInferenceGate:
    """Coordinate synchronous callers through one priority/resource queue."""

    def __init__(
        self,
        scheduler: GpuScheduler,
        resource_provider: ResourceProvider,
        *,
        wait_timeout_seconds: float = 30.0,
        poll_seconds: float = 0.05,
    ) -> None:
        if wait_timeout_seconds <= 0 or poll_seconds <= 0:
            raise ValueError("GPU gate timeouts must be positive")
        self.scheduler = scheduler
        self.resource_provider = resource_provider
        self.wait_timeout_seconds = wait_timeout_seconds
        self.poll_seconds = poll_seconds
        self._condition = threading.Condition(threading.RLock())
        self._decisions: dict[str, SchedulingDecision] = {}
        self._reserved: set[str] = set()

    def _resource(self) -> GpuResourceState | None:
        try:
            resource = self.resource_provider()
        except Exception as exc:  # noqa: BLE001 - telemetry failure must not stop inference
            LOGGER.warning("GPU telemetry unavailable; admission gate bypassed: %s", exc)
            return None
        if resource is None:
            return None
        return resource.model_copy(update={"active_inference": len(self._reserved)})

    def _dispatch_one(self, resource: GpuResourceState) -> None:
        decision = self.scheduler.next(resource)
        if decision is None or decision.action == "defer":
            return
        self._decisions[decision.task_id] = decision
        if decision.action in {"execute_gpu", "execute_cpu"}:
            self._reserved.add(decision.task_id)
        self._condition.notify_all()

    @contextmanager
    def admit(self, task: GpuTask) -> Iterator[SchedulingDecision | None]:
        """Wait for a decision, reserve a slot, and release it after the caller exits."""
        resource = self._resource()
        if resource is None:
            yield None
            return
        deadline = time.monotonic() + self.wait_timeout_seconds
        decision: SchedulingDecision | None = None
        with self._condition:
            self.scheduler.submit(task)
            while decision is None:
                decision = self._decisions.pop(task.task_id, None)
                if decision is not None:
                    break
                current = self._resource()
                if current is not None:
                    self._dispatch_one(current)
                    decision = self._decisions.pop(task.task_id, None)
                    if decision is not None:
                        break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self.scheduler.cancel(task.task_id)
                    raise GpuAdmissionError(
                        f"GPU admission timed out for task {task.task_id}"
                    )
                self._condition.wait(min(self.poll_seconds, remaining))
        if decision.action == "reject":
            raise GpuAdmissionError(decision.reason)
        try:
            yield decision
        finally:
            with self._condition:
                self._reserved.discard(task.task_id)
                self._condition.notify_all()

    @property
    def active_inference(self) -> int:
        with self._condition:
            return len(self._reserved)
