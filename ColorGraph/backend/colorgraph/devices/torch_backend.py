from __future__ import annotations

from contextlib import ExitStack, nullcontext

import torch

from colorgraph.devices.base import ComputeBackend, DeviceInfo, RuntimeKind


class TorchComputeBackend(ComputeBackend):
    """Select CUDA, ROCm or CPU without leaking vendor branches into algorithms.

    PyTorch intentionally exposes ROCm devices through the ``torch.cuda`` API.
    Business code should only consume ``torch_device`` and ``inference_context``.
    """

    def __init__(self, preference: str = "auto") -> None:
        normalized = preference.lower()
        if normalized not in {"auto", "cuda", "rocm", "cpu"}:
            raise ValueError("device preference must be auto, cuda, rocm or cpu")

        accelerator_available = torch.cuda.is_available()
        runtime: RuntimeKind = (
            ("rocm" if torch.version.hip else "cuda") if accelerator_available else "cpu"
        )

        if normalized == "cpu":
            runtime = "cpu"
        elif normalized in {"cuda", "rocm"} and runtime != normalized:
            raise RuntimeError(
                f"requested {normalized} but active PyTorch runtime is {runtime}; "
                "install the matching PyTorch wheel or use COLORGRAPH_DEVICE=auto"
            )

        self._runtime = runtime
        self._device = torch.device("cuda:0" if runtime in {"cuda", "rocm"} else "cpu")

    @property
    def torch_device(self) -> torch.device:
        return self._device

    @property
    def info(self) -> DeviceInfo:
        if self._runtime == "cpu":
            return DeviceInfo(
                available=True,
                runtime="cpu",
                vendor="Generic",
                name="CPU",
                torch_version=torch.__version__,
                migration_compatible=True,
            )

        properties = torch.cuda.get_device_properties(self._device)
        runtime_version = torch.version.hip if self._runtime == "rocm" else torch.version.cuda
        architecture = None
        if self._runtime == "rocm":
            architecture_value = str(getattr(properties, "gcnArchName", "")).strip()
            architecture = architecture_value.split(":", 1)[0] or None
        compute_units_value = int(getattr(properties, "multi_processor_count", 0))
        # PyTorch's gfx1100 device properties expose 48 RDNA work-group
        # processors, while AMD SMI and the product specifications express
        # the same hardware as 96 compute units.
        if self._runtime == "rocm" and architecture == "gfx1100" and compute_units_value == 48:
            compute_units_value = 96
        capability = None
        if self._runtime == "cuda":
            major, minor = torch.cuda.get_device_capability(self._device)
            capability = f"{major}.{minor}"

        return DeviceInfo(
            available=True,
            runtime=self._runtime,
            vendor="AMD" if self._runtime == "rocm" else "NVIDIA",
            name=properties.name,
            index=self._device.index or 0,
            total_memory_mb=round(properties.total_memory / 1024**2),
            allocated_memory_mb=round(torch.cuda.memory_allocated(self._device) / 1024**2),
            reserved_memory_mb=round(torch.cuda.memory_reserved(self._device) / 1024**2),
            torch_version=torch.__version__,
            runtime_version=runtime_version,
            architecture=architecture,
            compute_units=compute_units_value or None,
            capability=capability,
            migration_compatible=True,
        )

    def inference_context(self, *, mixed_precision: bool = True) -> ExitStack:
        stack = ExitStack()
        stack.enter_context(torch.inference_mode())
        if mixed_precision and self._runtime in {"cuda", "rocm"}:
            stack.enter_context(torch.amp.autocast("cuda", dtype=torch.float16))
        else:
            stack.enter_context(nullcontext())
        return stack

    def synchronize(self) -> None:
        if self._runtime in {"cuda", "rocm"}:
            torch.cuda.synchronize(self._device)

    def empty_cache(self) -> None:
        if self._runtime in {"cuda", "rocm"}:
            torch.cuda.empty_cache()
