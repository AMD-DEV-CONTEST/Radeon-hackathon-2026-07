from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AcceleratorPortabilityError(ValueError):
    pass


class AcceleratorBackend(str, Enum):
    ROCM = "rocm"
    CUDA = "cuda"


@dataclass(frozen=True)
class AcceleratorObservation:
    requested_backend: str
    selected_backend: AcceleratorBackend
    hip_version: str | None
    cuda_version: str | None


def resolve_accelerator_backend(
    requested_backend: str,
    *,
    gpu_available: bool,
    hip_version: str | None,
    cuda_version: str | None,
) -> AcceleratorObservation:
    """Select ROCm or CUDA without weakening the observed-hardware receipt."""

    if requested_backend not in {"auto", "rocm", "cuda"}:
        raise AcceleratorPortabilityError("accelerator backend is unsupported")
    if not gpu_available:
        raise AcceleratorPortabilityError("no visible PyTorch GPU is available")
    observed = (
        AcceleratorBackend.ROCM
        if hip_version
        else AcceleratorBackend.CUDA
        if cuda_version
        else None
    )
    if observed is None:
        raise AcceleratorPortabilityError(
            "visible GPU is not backed by an observed ROCm/HIP or CUDA runtime"
        )
    if requested_backend != "auto" and requested_backend != observed.value:
        raise AcceleratorPortabilityError(
            f"requested {requested_backend} but observed {observed.value}"
        )
    return AcceleratorObservation(
        requested_backend=requested_backend,
        selected_backend=observed,
        hip_version=hip_version or None,
        cuda_version=cuda_version or None,
    )
