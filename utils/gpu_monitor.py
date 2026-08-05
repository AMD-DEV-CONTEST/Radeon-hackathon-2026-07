"""GPU 显存监控 (AMD ROCm).

优先使用 ``rocm-smi`` 命令行; 不可用时回退到 pyrsmi / torch。
"""
from __future__ import annotations

import shutil
import subprocess
import re
from dataclasses import dataclass


@dataclass
class GPUInfo:
    """GPU 状态."""
    name: str = "unknown"
    vram_total_mb: int = 0
    vram_used_mb: int = 0
    vram_free_mb: int = 0
    utilization_pct: float = 0.0
    available: bool = False

    @property
    def vram_used_pct(self) -> float:
        if self.vram_total_mb <= 0:
            return 0.0
        return self.vram_used_mb / self.vram_total_mb * 100.0


def get_gpu_info() -> GPUInfo:
    """获取 GPU 显存与利用率信息.

    优先级: rocm-smi > pyrsmi > torch.cuda > 不可用。
    """
    if shutil.which("rocm-smi"):
        info = _via_rocm_smi()
        if info.available:
            return info
    info = _via_pyrsmi()
    if info.available:
        return info
    info = _via_torch()
    if info.available:
        return info
    return GPUInfo()


def _via_rocm_smi() -> GPUInfo:
    """通过 ``rocm-smi --showmeminfo vram --showuse`` 解析."""
    try:
        r = subprocess.run(
            ["rocm-smi", "--showproductname", "--showmeminfo", "vram",
             "--showuse", "gpu"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode != 0:
            return GPUInfo()
        out = r.stdout
        info = GPUInfo(available=True)

        # GPU 名称
        m = re.search(r"Card series:\s*(.+)", out)
        if m:
            info.name = m.group(1).strip()

        # VRAM (字节) - rocm-smi 输出 total 和 used 两行
        total = re.findall(r"VRAM Total Memory \(B\):\s*(\d+)", out)
        used_m = re.findall(r"VRAM Total Used Memory \(B\):\s*(\d+)", out)
        # 兼容其他 rocm-smi 输出格式
        if not total:
            total = re.findall(r"Memory\(B\):\s*total\s*(\d+)", out, re.I)
        if not used_m:
            used_m = re.findall(r"Memory\(B\):\s*used\s*(\d+)", out, re.I)

        if total:
            info.vram_total_mb = int(total[0]) // (1024 * 1024)
        if used_m:
            info.vram_used_mb = int(used_m[0]) // (1024 * 1024)
        info.vram_free_mb = max(0, info.vram_total_mb - info.vram_used_mb)

        # 利用率
        util = re.search(r"GPU use \(%\):\s*([\d.]+)", out)
        if util:
            info.utilization_pct = float(util.group(1))
        return info
    except (subprocess.SubprocessError, ValueError, OSError):
        return GPUInfo()


def _via_pyrsmi() -> GPUInfo:
    """通过 pyrsmi (AMD 官方 Python 接口)."""
    try:
        from pyrsmi import rocml  # type: ignore
        rocml.smi_initialize()
        try:
            info = GPUInfo(available=True)
            info.name = rocml.smi_get_device_name(0)
            total_b, used_b = rocml.smi_get_device_memory_total(0), \
                rocml.smi_get_device_memory_usage(0)
            info.vram_total_mb = int(total_b) // (1024 * 1024)
            info.vram_used_mb = int(used_b) // (1024 * 1024)
            info.vram_free_mb = info.vram_total_mb - info.vram_used_mb
            try:
                info.utilization_pct = float(
                    rocml.smi_get_device_utilization(0)
                )
            except Exception:
                pass
            return info
        finally:
            rocml.smi_shutdown()
    except Exception:
        return GPUInfo()


def _via_torch() -> GPUInfo:
    """通过 torch.cuda 回退 (ROCm 也走 cuda 接口)."""
    try:
        import torch
        if not torch.cuda.is_available():
            return GPUInfo()
        info = GPUInfo(available=True)
        info.name = torch.cuda.get_device_name(0)
        free_b, total_b = torch.cuda.mem_get_info(0)
        info.vram_total_mb = int(total_b) // (1024 * 1024)
        info.vram_used_mb = info.vram_total_mb - int(free_b) // (1024 * 1024)
        info.vram_free_mb = int(free_b) // (1024 * 1024)
        return info
    except Exception:
        return GPUInfo()


def format_gpu_status(info: GPUInfo | None = None) -> str:
    """格式化为 UI 状态条文本."""
    info = info or get_gpu_info()
    if not info.available:
        return "GPU: 不可用 (非 ROCm 环境?)"
    return (
        f"GPU: {info.name} | "
        f"VRAM: {info.vram_used_mb}/{info.vram_total_mb} MB "
        f"({info.vram_used_pct:.0f}%) | "
        f"利用率: {info.utilization_pct:.0f}%"
    )
