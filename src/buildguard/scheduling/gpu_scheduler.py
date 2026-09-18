"""Deterministic priority/deadline GPU scheduler with OOM degradation."""

from __future__ import annotations

import heapq
import threading
from datetime import datetime

from buildguard.config import GpuSchedulerConfig
from buildguard.scheduling.schemas import (
    GpuResourceState,
    GpuTask,
    SchedulingDecision,
)
from buildguard.utils.time import utc_now


class GpuScheduler:
    def __init__(self, config: GpuSchedulerConfig) -> None:
        self.config = config
        self._queue: list[tuple[int, float, int, GpuTask]] = []
        self._sequence = 0
        self._lock = threading.RLock()
        self._last_resource: GpuResourceState | None = None

    def submit(self, task: GpuTask) -> None:
        deadline = task.deadline.timestamp() if task.deadline is not None else float("inf")
        with self._lock:
            heapq.heappush(
                self._queue,
                (
                    self.config.task_priorities[task.task_type],
                    deadline,
                    self._sequence,
                    task,
                ),
            )
            self._sequence += 1

    def _unload_for(
        self,
        task: GpuTask,
        resource: GpuResourceState,
    ) -> list[str]:
        required = (
            task.estimated_memory_mb
            + self.config.reserved_vram_mb
            - resource.free_memory_mb
        )
        if required <= 0:
            return []
        released = 0.0
        selected: list[str] = []
        for name, memory in sorted(
            resource.resident_models.items(),
            key=lambda item: (-item[1], item[0]),
        ):
            if name == task.model_name or name in resource.pinned_models:
                continue
            selected.append(name)
            released += memory
            if released >= required:
                return selected
        return []

    def next(
        self,
        resource: GpuResourceState,
        *,
        now: datetime | None = None,
    ) -> SchedulingDecision | None:
        with self._lock:
            self._last_resource = resource.model_copy(deep=True)
            if not self._queue:
                return None
            _, _, _, task = heapq.heappop(self._queue)
            current = now or utc_now()
            if (
                task.deadline is not None
                and current > task.deadline
                and task.task_type == "background_indexing"
            ):
                return SchedulingDecision(
                    task_id=task.task_id,
                    action="reject",
                    reason="Background task missed its deadline",
                    effective_batch_size=task.batch_size,
                    queue_length=len(self._queue),
                )
            if resource.active_inference >= self.config.max_concurrent_inference:
                self.submit(task)
                return SchedulingDecision(
                    task_id=task.task_id,
                    action="defer",
                    reason="Maximum concurrent GPU inference reached",
                    effective_batch_size=task.batch_size,
                    queue_length=len(self._queue),
                )
            if (
                resource.utilization_percent
                >= self.config.max_gpu_utilization_percent
                and task.task_type not in {"emergency_vision", "risk_confirmation"}
            ):
                self.submit(task)
                return SchedulingDecision(
                    task_id=task.task_id,
                    action="defer",
                    reason="GPU utilization threshold reached",
                    effective_batch_size=task.batch_size,
                    queue_length=len(self._queue),
                )
            unload = self._unload_for(task, resource)
            available = resource.free_memory_mb + sum(
                resource.resident_models[name] for name in unload
            )
            required = task.estimated_memory_mb + self.config.reserved_vram_mb
            if available < required:
                if self.config.allow_cpu_fallback and task.can_cpu_fallback:
                    return SchedulingDecision(
                        task_id=task.task_id,
                        action="execute_cpu",
                        reason="Insufficient VRAM; using configured CPU fallback",
                        effective_batch_size=max(
                            1,
                            round(
                                task.batch_size
                                * self.config.oom_batch_reduction_factor
                            ),
                        ),
                        queue_length=len(self._queue),
                    )
                return SchedulingDecision(
                    task_id=task.task_id,
                    action="reject",
                    reason="Insufficient VRAM and CPU fallback is unavailable",
                    effective_batch_size=task.batch_size,
                    queue_length=len(self._queue),
                )
            return SchedulingDecision(
                task_id=task.task_id,
                action="execute_gpu",
                reason="GPU resources and priority policy allow execution",
                load_model=task.model_name not in resource.resident_models,
                unload_models=unload,
                effective_batch_size=task.batch_size,
                queue_length=len(self._queue),
            )

    def degrade_after_oom(self, task: GpuTask) -> SchedulingDecision:
        reduced = max(
            1,
            round(task.batch_size * self.config.oom_batch_reduction_factor),
        )
        if reduced < task.batch_size:
            return SchedulingDecision(
                task_id=task.task_id,
                action="defer",
                reason="OOM caught; retry with reduced batch size",
                effective_batch_size=reduced,
                queue_length=self.queue_length,
            )
        if self.config.allow_cpu_fallback and task.can_cpu_fallback:
            return SchedulingDecision(
                task_id=task.task_id,
                action="execute_cpu",
                reason="OOM at batch size 1; falling back to CPU",
                effective_batch_size=1,
                queue_length=self.queue_length,
            )
        return SchedulingDecision(
            task_id=task.task_id,
            action="reject",
            reason="OOM at minimum batch and CPU fallback is unavailable",
            effective_batch_size=1,
            queue_length=self.queue_length,
        )

    @property
    def queue_length(self) -> int:
        with self._lock:
            return len(self._queue)

    def queued_task_ids(self) -> list[str]:
        with self._lock:
            return [
                item[3].task_id
                for item in sorted(self._queue)
            ]

    def cancel(self, task_id: str) -> bool:
        """Remove one queued task, normally after its caller times out."""
        with self._lock:
            retained = [item for item in self._queue if item[3].task_id != task_id]
            if len(retained) == len(self._queue):
                return False
            self._queue = retained
            heapq.heapify(self._queue)
            return True

    @property
    def last_resource(self) -> GpuResourceState | None:
        with self._lock:
            return (
                self._last_resource.model_copy(deep=True)
                if self._last_resource is not None
                else None
            )
