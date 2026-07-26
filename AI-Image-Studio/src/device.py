# -*- coding: utf-8 -*-
"""设备自动检测与推理优化。

检测优先级：显式指定 > ROCm/CUDA GPU > CPU。
ROCm 平台上 PyTorch 将 HIP 设备映射到 cuda 命名空间，因此 device 统一为 "cuda"，
通过 torch.version.hip 区分 ROCm 与 CUDA 以便在界面中正确展示。
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
    backend: str          # "ROCm" / "CUDA" / "CPU"
    backend_version: str  # 运行时版本号
    gpu_name: str
    vram_total_gb: float

    def summary(self) -> str:
        if self.device.type == "cuda":
            return (f"{self.backend} {self.backend_version} | {self.gpu_name} | "
                    f"显存 {self.vram_total_gb:.1f} GB | 精度 {self.dtype}")
        return f"CPU | 精度 {self.dtype}"


def detect_device(prefer: str = "auto", dtype_pref: str = "auto") -> DeviceInfo:
    if prefer in ("cuda", "gpu"):
        if not torch.cuda.is_available():
            raise RuntimeError("指定了 GPU 运行，但未检测到可用的 ROCm/CUDA 设备。")
        device = torch.device("cuda")
    elif prefer == "cpu":
        device = torch.device("cpu")
    else:
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    if device.type == "cuda":
        if dtype_pref == "auto":
            dtype = torch.float16
        else:
            dtype = {"fp16": torch.float16, "bf16": torch.bfloat16, "fp32": torch.float32}[dtype_pref]
        hip_ver = getattr(torch.version, "hip", None)
        if hip_ver:
            backend, version = "ROCm", hip_ver
        else:
            backend, version = "CUDA", (torch.version.cuda or "?")
        name = torch.cuda.get_device_name(0)
        total = torch.cuda.get_device_properties(0).total_memory / 1024**3
        _apply_gpu_flags()
    else:
        dtype = {"bf16": torch.bfloat16}.get(dtype_pref, torch.float32)
        backend, version, name, total = "CPU", "", "", 0.0

    return DeviceInfo(device, dtype, backend, version, name, total)


def _apply_gpu_flags() -> None:
    """开启对推理有益的底层开关（容错处理，不同硬件/驱动下自动跳过）。"""
    with contextlib.suppress(Exception):
        torch.backends.cuda.matmul.allow_tf32 = True
    with contextlib.suppress(Exception):
        torch.backends.cudnn.allow_tf32 = True


def optimize_pipeline(pipe, info: DeviceInfo, low_vram: bool = False):
    """对 diffusers pipeline 应用显存与速度优化。"""
    if info.device.type == "cuda":
        pipe = pipe.to(info.device, info.dtype)
        with contextlib.suppress(Exception):
            pipe.unet.to(memory_format=torch.channels_last)
        if low_vram:
            # 逐级显存压缩：注意力切片 + VAE 切片/分块
            with contextlib.suppress(Exception):
                pipe.enable_attention_slicing()
            with contextlib.suppress(Exception):
                pipe.enable_vae_slicing()
            with contextlib.suppress(Exception):
                pipe.enable_vae_tiling()
    else:
        pipe = pipe.to(info.device, info.dtype)
    # PyTorch 2.x SDPA 注意力（ROCm 5.4+ 原生支持，diffusers 默认启用）
    pipe.set_progress_bar_config(disable=True)
    return pipe


def reset_peak_memory() -> None:
    if torch.cuda.is_available():
        with contextlib.suppress(Exception):
            torch.cuda.reset_peak_memory_stats()


def peak_memory_gb() -> float:
    if not torch.cuda.is_available():
        return 0.0
    with contextlib.suppress(Exception):
        return torch.cuda.max_memory_allocated() / 1024**3
    return 0.0


def free_vram_gb() -> float:
    if not torch.cuda.is_available():
        return 0.0
    with contextlib.suppress(Exception):
        free, _ = torch.cuda.mem_get_info()
        return free / 1024**3
    return 0.0


def synchronize() -> None:
    if torch.cuda.is_available():
        torch.cuda.synchronize()


class Timer:
    """统计 GPU/CPU 推理耗时（自动同步）。"""

    def __init__(self) -> None:
        self.elapsed = 0.0

    def __enter__(self) -> "Timer":
        synchronize()
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, *exc) -> None:
        synchronize()
        self.elapsed = time.perf_counter() - self._t0
