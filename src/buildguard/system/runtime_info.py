"""Environment probe result models."""

from pydantic import BaseModel, Field


class Availability(BaseModel):
    """Structured capability status."""

    available: bool
    detail: str | None = None
    path: str | None = None


class GPUInfo(BaseModel):
    """Detected GPU properties."""

    name: str
    memory_total_mb: float | None = None


class RuntimeInfo(BaseModel):
    """Complete environment gate report."""

    operating_system: str
    python_version: str
    cpu_count: int
    memory_total_mb: float
    commands: dict[str, Availability]
    llm_endpoint: Availability
    amd_gpu_detected: bool
    rocm_version: str | None = None
    gpus: list[GPUInfo] = Field(default_factory=list)

