from __future__ import annotations

import gc
from typing import Literal

import torch
from pydantic import BaseModel, ConfigDict, Field

from colorgraph.devices.base import ComputeBackend, RuntimeKind
from colorgraph.vision.model_lifecycle import (
    inference_cache_stats,
    release_inference_models,
)


class AcceleratorMemorySnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runtime: RuntimeKind
    allocated_bytes: int = Field(ge=0)
    reserved_bytes: int = Field(ge=0)
    model_cache_entries: int = Field(ge=0)
    active_model_leases: int = Field(ge=0)


class StageReleaseEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["colorgraph.stage-release-evidence/v1"] = (
        "colorgraph.stage-release-evidence/v1"
    )
    transition: str = Field(min_length=1)
    released_model_count: int = Field(ge=0)
    maximum_residual_allocated_bytes: int = Field(ge=0)
    before: AcceleratorMemorySnapshot
    after: AcceleratorMemorySnapshot
    release_verified: bool


def _clear_accelerator_blas_workspaces(backend: ComputeBackend) -> bool:
    if backend.info.runtime not in {"cuda", "rocm"}:
        return False
    clear_workspaces = getattr(torch._C, "_cuda_clearCublasWorkspaces", None)
    if not callable(clear_workspaces):
        return False
    clear_workspaces()
    return True


def accelerator_memory_snapshot(
    backend: ComputeBackend,
) -> AcceleratorMemorySnapshot:
    stats = inference_cache_stats()["models"]
    allocated_bytes = 0
    reserved_bytes = 0
    if backend.info.runtime in {"cuda", "rocm"}:
        allocated_bytes = int(torch.cuda.memory_allocated(backend.torch_device))
        reserved_bytes = int(torch.cuda.memory_reserved(backend.torch_device))
    return AcceleratorMemorySnapshot(
        runtime=backend.info.runtime,
        allocated_bytes=allocated_bytes,
        reserved_bytes=reserved_bytes,
        model_cache_entries=stats["entries"],
        active_model_leases=stats["active_leases"],
    )


def release_pytorch_stage(
    backend: ComputeBackend,
    *,
    transition: str,
    maximum_residual_allocated_mb: int = 64,
) -> StageReleaseEvidence:
    """Release idle inference models before Ollama or formal rendering."""

    if maximum_residual_allocated_mb < 0:
        raise ValueError("maximum residual accelerator memory must be non-negative")
    before = accelerator_memory_snapshot(backend)
    released = release_inference_models()
    gc.collect()
    backend.synchronize()
    _clear_accelerator_blas_workspaces(backend)
    backend.empty_cache()
    backend.synchronize()
    after = accelerator_memory_snapshot(backend)
    maximum_residual_bytes = maximum_residual_allocated_mb * 1024**2
    verified = (
        after.model_cache_entries == 0
        and after.active_model_leases == 0
        and (
            after.runtime == "cpu"
            or after.allocated_bytes <= maximum_residual_bytes
        )
    )
    evidence = StageReleaseEvidence(
        transition=transition,
        released_model_count=released,
        maximum_residual_allocated_bytes=maximum_residual_bytes,
        before=before,
        after=after,
        release_verified=verified,
    )
    if not verified:
        raise RuntimeError(
            f"PyTorch stage release {transition!r} failed: "
            f"entries={after.model_cache_entries}; "
            f"active_leases={after.active_model_leases}; "
            f"allocated_bytes={after.allocated_bytes}; "
            f"limit={maximum_residual_bytes}"
        )
    return evidence
