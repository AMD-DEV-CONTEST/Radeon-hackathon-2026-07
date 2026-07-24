# -*- coding: utf-8 -*-
"""Textovid — GPU / VRAM utilities (PyTorch 2.11 compatible)"""

import torch


def get_gpu_info() -> dict:
    """Return GPU name, free / total VRAM in GB, and CUDA/ROCm version.

    PyTorch 2.11 renamed ``total_memory`` to ``mem_total`` on the
    ``torch.cuda.Device`` query object.  We try the new name first,
    then fall back to the legacy name, and finally to ``get_device_properties``.
    """
    if not torch.cuda.is_available():
        return {
            "available": False,
            "name": "No GPU found",
            "vram_free_gb": 0.0,
            "vram_total_gb": 0.0,
            "cuda_version": "",
        }

    try:
        props = torch.cuda.get_device_properties(0)
        gpu_name = getattr(props, "name", "Unknown AMD GPU")

        # --- total VRAM from properties ---
        vram_total = getattr(props, "total_memory", None)
        if vram_total is None:
            # PyTorch 2.11+ may use mem_total
            vram_total = getattr(props, "mem_total", None)
        if vram_total is None:
            vram_total = props.total_bytes if hasattr(props, "total_bytes") else 0

        # --- free VRAM from query ---
        query = torch.cuda.memory_stats(0) if torch.cuda.is_initialized() else {}
        vram_free = vram_total - query.get("allocated_bytes.all.current", 0)

        # --- CUDA / ROCm version string ---
        version = getattr(torch.version, "hip", None) or torch.version.cuda or ""

        return {
            "available": True,
            "name": gpu_name,
            "vram_free_gb": round(vram_free / 1e9, 2),
            "vram_total_gb": round(vram_total / 1e9, 2),
            "cuda_version": version,
        }
    except Exception as exc:
        return {
            "available": True,
            "name": f"AMD GPU (error: {exc})",
            "vram_free_gb": 0.0,
            "vram_total_gb": 0.0,
            "cuda_version": getattr(torch.version, "hip", "") or "",
        }


def vram_ok(required_gb: float = 18.0) -> bool:
    info = get_gpu_info()
    if not info["available"]:
        return False
    return info["vram_free_gb"] >= required_gb
