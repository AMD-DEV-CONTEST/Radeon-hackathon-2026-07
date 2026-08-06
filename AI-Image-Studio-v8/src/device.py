# -*- coding: utf-8 -*-
"""Device / runtime backend detection for AMD ROCm, CUDA and CPU.

v2 notes:
- channels_last is NOT applied (suspect in ROCm page-faults on gfx1100).
- SDPA attention is kept (PyTorch 2.x native; stable on ROCm 6.3,
  especially with TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL=1).
"""
from __future__ import annotations

import contextlib
import time
from dataclasses import dataclass

import torch


@dataclass
class DeviceInfo:
    device: torch.device
    dtype: torch.dtype
    backend: str            # "ROCm" | "CUDA" | "CPU"
    gpu_name: str = "CPU"
    vram_gb: float = 0.0

    @property
    def is_gpu(self) -> bool:
        return self.device.type == "cuda"

    def summary(self) -> str:
        if not self.is_gpu:
            return "CPU (no GPU detected)"
        return f"{self.backend} {torch.version.hip or ''} | {self.gpu_name} | VRAM {self.vram_gb:.1f} GB | {self.dtype}"


def detect_device(device_pref: str = "auto", dtype_pref: str = "auto") -> DeviceInfo:
    use_gpu = False
    if device_pref in ("auto", "cuda"):
        use_gpu = torch.cuda.is_available()
    if use_gpu:
        device = torch.device("cuda")
        backend = "ROCm" if torch.version.hip else "CUDA"
        gpu_name = torch.cuda.get_device_name(0)
        vram_gb = torch.cuda.get_device_properties(0).total_memory / 1024**3
        if dtype_pref == "auto":
            dtype = torch.float16
        else:
            dtype = {"fp16": torch.float16, "bf16": torch.bfloat16,
                     "fp32": torch.float32}[dtype_pref]
    else:
        device = torch.device("cpu")
        backend, gpu_name, vram_gb = "CPU", "CPU", 0.0
        dtype = torch.float32
    return DeviceInfo(device, dtype, backend, gpu_name, vram_gb)


def optimize_pipeline(pipe, info: DeviceInfo, low_vram: bool = False):
    """Move a diffusers pipeline onto the device with sane ROCm defaults."""
    if info.is_gpu:
        pipe = pipe.to(info.device, info.dtype)
        try:
            pipe.set_progress_bar_config(disable=True)
        except Exception:
            pass
        if low_vram:
            with contextlib.suppress(Exception):
                pipe.enable_attention_slicing()
            with contextlib.suppress(Exception):
                pipe.enable_vae_slicing()
            with contextlib.suppress(Exception):
                pipe.enable_vae_tiling()
    else:
        pipe = pipe.to(info.device, torch.float32)
    return pipe


def reset_peak_memory() -> None:
    if torch.cuda.is_available():
        with contextlib.suppress(Exception):
            torch.cuda.reset_peak_memory_stats()


def peak_memory_gb() -> float:
    if torch.cuda.is_available():
        with contextlib.suppress(Exception):
            return torch.cuda.max_memory_allocated() / 1024**3
    return 0.0


def free_vram_gb() -> float:
    if torch.cuda.is_available():
        with contextlib.suppress(Exception):
            free, _total = torch.cuda.mem_get_info()
            return free / 1024**3
    return 0.0


def sync() -> None:
    if torch.cuda.is_available():
        with contextlib.suppress(Exception):
            torch.cuda.synchronize()


class Timer:
    """Wall-clock timer with GPU sync."""

    def __init__(self):
        self.t0 = None
        self.elapsed = 0.0

    def __enter__(self):
        sync()
        self.t0 = time.perf_counter()
        return self

    def __exit__(self, *exc):
        sync()
        self.elapsed = time.perf_counter() - self.t0
        return False
