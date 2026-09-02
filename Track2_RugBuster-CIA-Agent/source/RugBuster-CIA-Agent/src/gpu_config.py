"""
Portable GPU / device configuration.

AMD Track 2 requires the submission to run both on the local dev box (Z13,
gfx1151 / Strix Halo) and on an AMD Radeon Cloud instance, which is very
likely a different, discrete Radeon GPU (different gfx target). The
project's existing training scripts (read-only reference: Trening/setup_unsloth_strixhalo.sh,
Trening/setup_unsloth_windows.ps1) hardcode gfx1151 in the ROCm nightly wheel
URL — that's fine for *training setup* on a single known machine, but wrong
to bake into the agent's *inference* code, which needs to run unmodified on
whatever Radeon GPU the cloud instance provides.

This module never hardcodes a gfx target. It resolves, in order:
  1. ROCM_GFX_TARGET env var, if the deployer wants to pin one explicitly.
  2. Auto-detection via `rocminfo` (if present on PATH).
  3. A generic ROCm/CUDA/CPU fallback with no specific gfx assumption.

`n_gpu_layers` for llama.cpp offload is also env-configurable so a smaller
Radeon Cloud card can offload fewer layers than the Z13 without a code change.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass


@dataclass
class DeviceConfig:
    backend: str  # "rocm", "cuda", or "cpu"
    gfx_target: str | None  # e.g. "gfx1151", "gfx1100" — None if unknown/not applicable
    n_gpu_layers: int  # llama.cpp GPU offload layer count, 0 = CPU-only


def _detect_gfx_target() -> str | None:
    env_target = os.getenv("ROCM_GFX_TARGET", "").strip()
    if env_target:
        return env_target

    rocminfo = shutil.which("rocminfo")
    if not rocminfo:
        return None
    try:
        output = subprocess.run([rocminfo], capture_output=True, text=True, timeout=10).stdout
        for line in output.splitlines():
            line = line.strip()
            if line.startswith("Name:") and "gfx" in line:
                return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return None


def _detect_backend() -> str:
    backend = os.getenv("CIA_LLM_BACKEND", "").strip().lower()
    if backend in {"rocm", "cuda", "cpu"}:
        return backend

    if shutil.which("rocminfo"):
        return "rocm"
    try:
        import torch  # optional; only used for CUDA fallback probing

        if torch.cuda.is_available():
            return "cuda"
    except ImportError:
        pass
    return "cpu"


def resolve_device_config() -> DeviceConfig:
    backend = _detect_backend()
    gfx_target = _detect_gfx_target() if backend == "rocm" else None

    default_layers = "0" if backend == "cpu" else "-1"  # -1 = offload all layers (llama.cpp convention)
    n_gpu_layers = int(os.getenv("CIA_LLM_GPU_LAYERS", default_layers))

    return DeviceConfig(backend=backend, gfx_target=gfx_target, n_gpu_layers=n_gpu_layers)
