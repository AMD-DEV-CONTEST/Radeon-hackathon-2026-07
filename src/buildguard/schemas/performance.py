"""Performance record schemas."""

from typing import Any

from pydantic import Field

from buildguard.schemas.common import RecordSchema


class PerformanceRecord(RecordSchema):
    operation: str = Field(min_length=1, max_length=256)
    duration_ms: float = Field(ge=0)
    success: bool = True
    cpu_percent: float | None = Field(default=None, ge=0, le=100)
    process_memory_mb: float | None = Field(default=None, ge=0)
    gpu_metrics: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
