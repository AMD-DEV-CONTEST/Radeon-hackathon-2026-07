"""Validated GPU scheduling inputs and decisions."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from buildguard.schemas.common import StrictSchema, new_id
from buildguard.utils.time import utc_now

GpuTaskType = Literal[
    "emergency_vision",
    "risk_confirmation",
    "normal_monitoring",
    "agent_response",
    "report_generation",
    "background_indexing",
]


class GpuTask(StrictSchema):
    task_id: str = Field(default_factory=new_id)
    task_type: GpuTaskType
    model_name: str = Field(min_length=1, max_length=256)
    estimated_latency_ms: float = Field(ge=0)
    estimated_memory_mb: float = Field(ge=0)
    deadline: datetime | None = None
    batch_size: int = Field(default=1, ge=1, le=4096)
    can_cpu_fallback: bool = True
    submitted_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def aware_times(self) -> GpuTask:
        for value in (self.deadline, self.submitted_at):
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError("GPU scheduling times must be timezone-aware")
        return self


class GpuResourceState(StrictSchema):
    utilization_percent: float = Field(ge=0, le=100)
    memory_used_mb: float = Field(ge=0)
    memory_total_mb: float = Field(ge=0)
    resident_models: dict[str, float] = Field(default_factory=dict)
    pinned_models: set[str] = Field(default_factory=set)
    active_inference: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def memory_consistent(self) -> GpuResourceState:
        if self.memory_used_mb > self.memory_total_mb:
            raise ValueError("GPU memory used cannot exceed total")
        if any(value < 0 for value in self.resident_models.values()):
            raise ValueError("resident model memory must be non-negative")
        if not self.pinned_models.issubset(self.resident_models):
            raise ValueError("pinned models must also be resident models")
        return self

    @property
    def free_memory_mb(self) -> float:
        return self.memory_total_mb - self.memory_used_mb


class SchedulingDecision(StrictSchema):
    task_id: str
    action: Literal["execute_gpu", "execute_cpu", "defer", "reject"]
    reason: str = Field(min_length=1, max_length=2000)
    load_model: bool = False
    unload_models: list[str] = Field(default_factory=list)
    effective_batch_size: int = Field(ge=1)
    queue_length: int = Field(ge=0)
