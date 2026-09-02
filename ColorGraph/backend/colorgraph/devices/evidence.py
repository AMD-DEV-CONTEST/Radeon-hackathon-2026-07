from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

import torch
from pydantic import BaseModel, ConfigDict, Field

from colorgraph.devices.base import ComputeBackend, RuntimeKind

TORCH_STAGE_EVIDENCE_VERSION = "colorgraph.torch-stage-evidence/v1"
_ACCELERATOR_RUNTIMES = {"cuda", "rocm"}


class TorchStageEvidence(BaseModel):
    """Machine-verifiable device evidence for one PyTorch inference call."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["colorgraph.torch-stage-evidence/v1"] = (
        TORCH_STAGE_EVIDENCE_VERSION
    )
    stage: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    runtime: RuntimeKind
    vendor: str
    device_name: str
    torch_device: str
    torch_version: str
    hip_version: str | None = None
    model_devices_required: bool = True
    model_devices: list[str]
    input_devices: list[str]
    output_devices: list[str]
    allocated_bytes_at_start: int | None = Field(default=None, ge=0)
    peak_allocated_bytes: int | None = Field(default=None, ge=0)
    peak_reserved_bytes: int | None = Field(default=None, ge=0)
    measurement_error: str | None = None
    accelerator_tensors_verified: bool
    amd_rocm_verified: bool


def _device_strings(value: object, *, _visited: set[int] | None = None) -> set[str]:
    if isinstance(value, torch.Tensor):
        return {str(value.device)}
    if value is None or isinstance(value, (str, bytes, int, float, bool)):
        return set()

    visited = _visited if _visited is not None else set()
    identity = id(value)
    if identity in visited:
        return set()
    visited.add(identity)

    if isinstance(value, Mapping):
        devices: set[str] = set()
        for item in value.values():
            devices.update(_device_strings(item, _visited=visited))
        return devices
    if isinstance(value, (tuple, list, set, frozenset)):
        devices = set()
        for item in value:
            devices.update(_device_strings(item, _visited=visited))
        return devices

    to_tuple = getattr(value, "to_tuple", None)
    if callable(to_tuple):
        try:
            return _device_strings(to_tuple(), _visited=visited)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return set()
    if hasattr(value, "__dict__"):
        return _device_strings(vars(value), _visited=visited)
    return set()


def _model_devices(model: object) -> set[str]:
    devices: set[str] = set()
    for accessor_name in ("parameters", "buffers"):
        accessor = getattr(model, accessor_name, None)
        if not callable(accessor):
            continue
        try:
            values = accessor()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            continue
        for value in values:
            if isinstance(value, torch.Tensor):
                devices.add(str(value.device))
    return devices


def _all_accelerator_devices(devices: list[str]) -> bool:
    return bool(devices) and all(torch.device(device).type == "cuda" for device in devices)


class TorchStageEvidenceRecorder:
    """Capture tensor placement and peak allocator state around inference."""

    def __init__(
        self,
        backend: ComputeBackend,
        *,
        stage: str,
        model_id: str,
        model: object,
        inputs: object,
        model_devices_required: bool = True,
    ) -> None:
        self.backend = backend
        self.stage = stage
        self.model_id = model_id
        self.model_devices_required = model_devices_required
        self.info = backend.info
        self.model_devices = sorted(_model_devices(model))
        self.input_devices = sorted(_device_strings(inputs))
        self.allocated_bytes_at_start: int | None = None
        self.measurement_error: str | None = None

        if self.info.runtime in _ACCELERATOR_RUNTIMES:
            try:
                torch.cuda.reset_peak_memory_stats(backend.torch_device)
                self.allocated_bytes_at_start = int(
                    torch.cuda.memory_allocated(backend.torch_device)
                )
            except (AssertionError, RuntimeError) as exc:
                self.measurement_error = f"{type(exc).__name__}: {exc}"

    def finish(self, outputs: object) -> TorchStageEvidence:
        synchronize = getattr(self.backend, "synchronize", None)
        if callable(synchronize):
            synchronize()

        output_devices = sorted(_device_strings(outputs))
        peak_allocated_bytes: int | None = None
        peak_reserved_bytes: int | None = None
        if self.info.runtime in _ACCELERATOR_RUNTIMES and self.measurement_error is None:
            try:
                peak_allocated_bytes = int(
                    torch.cuda.max_memory_allocated(self.backend.torch_device)
                )
                peak_reserved_bytes = int(
                    torch.cuda.max_memory_reserved(self.backend.torch_device)
                )
            except (AssertionError, RuntimeError) as exc:
                self.measurement_error = f"{type(exc).__name__}: {exc}"

        accelerator_tensors_verified = (
            self.info.runtime in _ACCELERATOR_RUNTIMES
            and (
                not self.model_devices_required
                or _all_accelerator_devices(self.model_devices)
            )
            and _all_accelerator_devices(self.input_devices)
            and _all_accelerator_devices(output_devices)
        )
        hip_version = str(torch.version.hip) if torch.version.hip else None
        amd_rocm_verified = (
            self.info.runtime == "rocm"
            and str(getattr(self.info, "vendor", "")).casefold() == "amd"
            and hip_version is not None
            and accelerator_tensors_verified
            and peak_allocated_bytes is not None
            and peak_allocated_bytes > 0
            and self.measurement_error is None
        )
        return TorchStageEvidence(
            stage=self.stage,
            model_id=self.model_id,
            runtime=self.info.runtime,
            vendor=str(getattr(self.info, "vendor", "unreported")),
            device_name=str(getattr(self.info, "name", "unreported")),
            torch_device=str(self.backend.torch_device),
            torch_version=str(
                getattr(self.info, "torch_version", torch.__version__)
            ),
            hip_version=hip_version,
            model_devices_required=self.model_devices_required,
            model_devices=self.model_devices,
            input_devices=self.input_devices,
            output_devices=output_devices,
            allocated_bytes_at_start=self.allocated_bytes_at_start,
            peak_allocated_bytes=peak_allocated_bytes,
            peak_reserved_bytes=peak_reserved_bytes,
            measurement_error=self.measurement_error,
            accelerator_tensors_verified=accelerator_tensors_verified,
            amd_rocm_verified=amd_rocm_verified,
        )


def require_amd_rocm_stage_evidence(evidence: TorchStageEvidence) -> None:
    """Fail closed unless a stage proves real AMD/ROCm tensor execution."""

    failures: list[str] = []
    if evidence.runtime != "rocm":
        failures.append(f"runtime={evidence.runtime}")
    if evidence.vendor.casefold() != "amd":
        failures.append(f"vendor={evidence.vendor}")
    if evidence.hip_version is None:
        failures.append("torch.version.hip is empty")
    if not evidence.accelerator_tensors_verified:
        failures.append(
            "model/input/output tensors were not all observed on the accelerator"
        )
    if not evidence.peak_allocated_bytes:
        failures.append("peak accelerator allocation is empty")
    if evidence.measurement_error:
        failures.append(f"allocator measurement failed: {evidence.measurement_error}")
    if failures:
        raise RuntimeError(
            f"AMD GPU-only stage {evidence.stage!r} failed: " + "; ".join(failures)
        )
