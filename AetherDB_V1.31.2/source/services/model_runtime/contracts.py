"""Strict contracts shared by resource admission and model workers."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SchedulingPolicy(str, Enum):
    CONSERVATIVE = "CONSERVATIVE"
    AUTO = "AUTO"
    PARALLEL = "PARALLEL"


class LeaseMode(str, Enum):
    EXCLUSIVE = "EXCLUSIVE"
    SHARED = "SHARED"


class ResourceClass(str, Enum):
    CORE_RESIDENT = "CORE_RESIDENT"
    GPU_EXCLUSIVE_HEAVY = "GPU_EXCLUSIVE_HEAVY"
    GPU_EXCLUSIVE_MEDIUM = "GPU_EXCLUSIVE_MEDIUM"
    GPU_SHARED_LIGHT = "GPU_SHARED_LIGHT"
    CPU_PARALLEL = "CPU_PARALLEL"
    IO_BACKGROUND = "IO_BACKGROUND"
    REMOTE_RUNTIME = "REMOTE_RUNTIME"


class LeaseOwnerType(str, Enum):
    AETHERDB_WORKER = "aetherdb_worker"
    AETHERDB_MANAGED_RUNTIME = "aetherdb_managed_runtime"
    AETHERDB_TASK = "aetherdb_task"


class AdmissionStatus(str, Enum):
    ADMITTED = "admitted"
    QUEUED = "queued"
    REQUIRES_EVICTION = "requires_eviction"
    REQUIRES_CPU_OFFLOAD = "requires_cpu_offload"
    REQUIRES_INSTALL = "requires_install"
    INSUFFICIENT_RESOURCES = "insufficient_resources"
    BLOCKED_BY_POLICY = "blocked_by_policy"


class ComputeDeviceSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, protected_namespaces=())

    device_id: str = Field(min_length=1, max_length=160)
    visible_index: int = Field(ge=0)
    vendor: Literal["AMD", "NVIDIA"]
    name: str = Field(min_length=1, max_length=256)
    backend: Literal["rocm_migraphx", "cuda"]
    total_vram_mb: int = Field(ge=0)
    used_vram_mb: int = Field(ge=0)
    free_vram_mb: int = Field(ge=0)
    utilization_percent: float | None = Field(default=None, ge=0, le=100)
    driver_version: str | None = Field(default=None, max_length=128)
    device_uuid: str | None = Field(default=None, max_length=256)
    source: Literal["amd-smi", "rocm-smi", "nvidia-smi"]
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class ResourceSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, protected_namespaces=())

    snapshot_id: str = Field(min_length=1, max_length=64)
    captured_at: str
    platform: str = Field(min_length=1, max_length=64)
    architecture: str = Field(min_length=1, max_length=64)
    total_ram_mb: int = Field(ge=0)
    available_ram_mb: int = Field(ge=0)
    model_disk_total_mb: int = Field(ge=0)
    model_disk_free_mb: int = Field(ge=0)
    devices: tuple[ComputeDeviceSnapshot, ...] = ()
    probe_errors: tuple[str, ...] = ()


class ExternalResourceOccupancy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, protected_namespaces=())

    occupancy_id: str = Field(min_length=1, max_length=96)
    source: Literal["device_unattributed", "external_runtime"]
    ownership: Literal["external"] = "external"
    runtime_id: str | None = Field(default=None, max_length=160)
    model_id: str | None = Field(default=None, max_length=256)
    device_id: str = Field(min_length=1, max_length=160)
    observed_vram_mb: int = Field(ge=0)
    observed_ram_mb: int = Field(default=0, ge=0)
    confidence: Literal["unattributed", "reported", "measured"]
    observed_at: str


class ResourceDrift(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, protected_namespaces=())

    drift_id: str = Field(min_length=1, max_length=64)
    code: Literal[
        "LEASE_OWNER_MISSING",
        "LEASE_OWNER_MISMATCH",
        "LEASE_DEVICE_MISSING",
        "WORKER_LEASE_MISSING",
        "REMOTE_RUNTIME_UNAVAILABLE",
    ]
    subject_type: Literal["lease", "worker", "runtime"]
    subject_id: str = Field(min_length=1, max_length=160)
    lease_id: str | None = Field(default=None, max_length=64)
    device_id: str | None = Field(default=None, max_length=160)
    runtime_id: str | None = Field(default=None, max_length=160)
    owner_type: LeaseOwnerType | None = None
    detected_at: str
    details: dict = Field(default_factory=dict)


class AdmissionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    package_id: str | None = Field(
        default=None,
        pattern=r"^[a-z0-9][a-z0-9._-]{2,95}$",
    )
    task_id: str = Field(min_length=1, max_length=160)
    resource_class: ResourceClass | Literal["AUTO"] = "AUTO"
    requested_backend: Literal[
        "auto", "rocm_migraphx", "rocm_pytorch", "cuda", "cpu", "remote"
    ] = "auto"
    requested_lease_mode: LeaseMode | Literal["AUTO"] = "AUTO"
    priority: int = Field(default=50, ge=0, le=100)
    competition_mode: bool | None = None
    runtime_id: str | None = Field(default=None, min_length=1, max_length=160)
    model_id: str | None = Field(default=None, min_length=1, max_length=256)
    estimated_ram_mb: int = Field(default=0, ge=0, le=10_000_000)

    @field_validator("task_id")
    @classmethod
    def clean_task_id(cls, value: str):
        cleaned = value.strip()
        if not cleaned or any(ord(char) < 32 for char in cleaned):
            raise ValueError("task_id contains invalid characters")
        return cleaned

    @model_validator(mode="after")
    def validate_resource_target(self):
        if self.resource_class == ResourceClass.REMOTE_RUNTIME:
            if not self.runtime_id or not self.model_id:
                raise ValueError("remote runtime admission requires runtime_id and model_id")
            if self.requested_backend not in {"auto", "remote"}:
                raise ValueError("remote runtime admission requires the remote backend")
        elif not self.package_id:
            raise ValueError("package_id is required for native resource admission")
        return self


class AdmissionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    status: AdmissionStatus
    reason_code: str = Field(min_length=1, max_length=96)
    message: str = Field(min_length=1, max_length=512)
    package_id: str | None
    task_id: str
    resource_class: ResourceClass
    requested_backend: str
    effective_backend: str | None = None
    lease_mode: LeaseMode | None = None
    device_id: str | None = None
    reserved_vram_mb: int = Field(default=0, ge=0)
    estimated_peak_vram_mb: int = Field(default=0, ge=0)
    runtime_context_overhead_mb: int = Field(default=0, ge=0)
    safety_margin_mb: int = Field(default=0, ge=0)
    snapshot_id: str
    policy: SchedulingPolicy
    competition_mode: bool
    blocking_lease_ids: tuple[str, ...] = ()
    lease_id: str | None = None
    runtime_id: str | None = None
    model_id: str | None = None
    estimated_ram_mb: int = Field(default=0, ge=0)


class RuntimePolicyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    scheduling_policy: SchedulingPolicy
    competition_mode: bool
    lease_ttl_seconds: int = Field(default=30, ge=10, le=300)
    pressure_free_vram_percent: int = Field(default=10, ge=5, le=50)


class WorkerStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    package_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,95}$")
    replica_id: str = Field(default="default", pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    residency_mode: Literal["PINNED", "PREFERRED", "ON_DEMAND"] | None = None


class WorkerLoadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    task_id: str = Field(min_length=1, max_length=160)
    requested_backend: Literal[
        "auto", "rocm_migraphx", "rocm_pytorch", "cuda", "cpu"
    ] = "auto"
    requested_lease_mode: LeaseMode | Literal["AUTO"] = "AUTO"
    priority: int = Field(default=50, ge=0, le=100)
    competition_mode: bool | None = None


class WorkerProbeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    requested_backend: Literal["rocm_migraphx", "rocm_pytorch", "cuda", "cpu"]
    priority: int = Field(default=100, ge=0, le=100)
    keep_loaded: bool = False


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
