"""Device selection and per-stage metrics helpers (contract sections 0 and 12).

torch is imported lazily inside functions and every CUDA/HIP call is guarded,
so this module works (and unit-tests) on machines without torch installed.
On AMD Radeon GPUs the ROCm build of torch exposes the HIP backend through
the ``torch.cuda`` API, so ``"cuda"`` is the correct device string there too.
"""

from __future__ import annotations

import logging
import os
import platform
import time
from contextlib import contextmanager
from typing import Any, Iterator

logger = logging.getLogger(__name__)

__all__ = ["get_device", "device_info", "require_rocm", "ensure_gpu", "stage_metrics"]


def _torch():
    """Return the torch module or None when unavailable."""
    try:
        import torch  # noqa: PLC0415 - lazy heavy import by design

        return torch
    except Exception:  # pragma: no cover - absence path
        return None


def _cuda_available(torch_mod: Any) -> bool:
    try:
        return bool(torch_mod is not None and torch_mod.cuda.is_available())
    except Exception:
        return False


def get_device() -> str:
    """Return ``"cuda"`` if a GPU is available via torch, else ``"cpu"``."""
    return "cuda" if _cuda_available(_torch()) else "cpu"


def device_info() -> dict:
    """Return GPU/torch environment info (contract section 12)."""
    torch_mod = _torch()
    info: dict = {
        "available": False,
        "name": "cpu",
        "torch_version": "not_installed",
        "hip_version": None,
        "rocm": False,
    }
    if torch_mod is None:
        info["name"] = f"cpu ({platform.machine()})"
        return info

    info["torch_version"] = str(getattr(torch_mod, "__version__", "unknown"))
    hip_version = getattr(getattr(torch_mod, "version", None), "hip", None)
    info["hip_version"] = str(hip_version) if hip_version else None
    info["rocm"] = bool(hip_version)

    if _cuda_available(torch_mod):
        info["available"] = True
        try:
            info["name"] = str(torch_mod.cuda.get_device_name(0))
        except Exception:
            info["name"] = "gpu"
    else:
        info["name"] = f"cpu ({platform.machine()})"
    return info


def require_rocm() -> bool:
    """True when the operator demanded GPU execution (no CPU fallback)."""
    if os.environ.get("POLICYCUT_REQUIRE_ROCM", "0") == "1":
        return True
    try:
        from policycut.config import get_settings  # local import: avoid cycles

        return bool(get_settings().require_rocm)
    except Exception:
        return False


def ensure_gpu(stage_name: str) -> None:
    """Raise RuntimeError if ROCm is required but no GPU is available.

    Called by core model stages before falling back to CPU. When
    ``POLICYCUT_REQUIRE_ROCM=1`` (or --require-rocm) a missing GPU is a hard
    error instead of a silent CPU fallback.
    """
    if not require_rocm():
        return
    if get_device() != "cuda":
        raise RuntimeError(
            f"Stage '{stage_name}' requires a ROCm GPU "
            "(POLICYCUT_REQUIRE_ROCM=1) but torch.cuda.is_available() is False. "
            "Refusing CPU fallback."
        )


@contextmanager
def stage_metrics(stage_name: str) -> Iterator[dict]:
    """Context manager measuring wall time and peak VRAM for one stage.

    Yields a dict the caller may fill (``frames``, ``precision``, ...).
    On exit sets ``wall_s`` and ``peak_vram_mb`` (0.0 without a GPU), and
    ``effective_fps`` when ``frames`` was provided. All torch.cuda calls are
    guarded by availability checks.
    """
    torch_mod = _torch()
    gpu = _cuda_available(torch_mod)

    if gpu:
        try:
            torch_mod.cuda.synchronize()
            torch_mod.cuda.reset_peak_memory_stats()
        except Exception:
            logger.warning("stage_metrics(%s): cuda pre-sync failed", stage_name)
            gpu = False

    metrics: dict = {}
    start = time.perf_counter()
    try:
        yield metrics
    finally:
        wall_s = time.perf_counter() - start
        peak_vram_mb = 0.0
        if gpu:
            try:
                torch_mod.cuda.synchronize()
                peak_vram_mb = float(torch_mod.cuda.max_memory_allocated()) / (
                    1024.0 * 1024.0
                )
            except Exception:
                logger.warning("stage_metrics(%s): cuda post-sync failed", stage_name)
        metrics["wall_s"] = round(wall_s, 3)
        metrics["peak_vram_mb"] = round(peak_vram_mb, 1)
        frames = metrics.get("frames")
        if isinstance(frames, (int, float)) and frames > 0 and wall_s > 0:
            metrics["effective_fps"] = round(float(frames) / wall_s, 2)
        logger.info(
            "stage %s finished: wall_s=%.3f peak_vram_mb=%.1f",
            stage_name,
            wall_s,
            peak_vram_mb,
        )
