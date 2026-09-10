"""ROCM-001 environment probe — honest fail when GPU/HIP missing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from specstyle.errors import DomainError
from specstyle.observability.hashing import hash_bytes


@dataclass(frozen=True, slots=True)
class RocmProbeResult:
    available: bool
    device_name: str | None
    hip_version: str | None
    reason: str | None
    snapshot_hash: str


def probe_rocm(torch_module: Any | None = None) -> RocmProbeResult:
    """Probe Radeon/ROCm. Pass None to auto-import torch; fails closed if absent."""
    if torch_module is None:
        try:
            import torch as torch_module  # type: ignore
        except Exception:
            material = b"rocm:unavailable:no_torch"
            return RocmProbeResult(
                False,
                None,
                None,
                "torch_not_importable",
                hash_bytes(material).value,
            )
    try:
        hip = getattr(getattr(torch_module, "version", None), "hip", None)
        cuda = getattr(torch_module, "cuda", None)
        available = bool(hip) and bool(cuda and cuda.is_available())
        name = None
        if available:
            name = cuda.get_device_name(0)
        reason = None if available else "hip_or_cuda_unavailable"
        material = f"rocm:{available}:{hip}:{name}:{reason}".encode()
        return RocmProbeResult(
            available,
            name,
            str(hip) if hip is not None else None,
            reason,
            hash_bytes(material).value,
        )
    except Exception as exc:
        material = f"rocm:error:{type(exc).__name__}".encode()
        return RocmProbeResult(
            False, None, None, "probe_exception", hash_bytes(material).value
        )


def require_rocm(result: RocmProbeResult) -> None:
    if type(result) is not RocmProbeResult:
        raise DomainError("invalid rocm probe")
    if not result.available:
        raise DomainError("rocm not available")
