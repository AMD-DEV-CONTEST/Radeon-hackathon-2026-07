from __future__ import annotations

import json
import logging
import subprocess

log = logging.getLogger("cortex.bench.gpu_sensor")


class _TorchCudaShim:
    """Indirection so tests can monkeypatch `cortex.bench.gpu_sensor.torch_cuda`."""

    @staticmethod
    def is_available() -> bool:
        try:
            import torch

            return bool(torch.cuda.is_available())
        except Exception:
            return False

    @staticmethod
    def device_name() -> str:
        try:
            import torch

            if torch.cuda.is_available():
                return torch.cuda.get_device_name(0)
        except Exception:
            pass
        return "unknown"

    @staticmethod
    def mem_util_pct() -> float:
        """torch.cuda memory utilisation (allocated / reserved)."""
        try:
            import torch

            reserved = torch.cuda.memory_reserved()
            if reserved <= 0:
                return 0.0
            allocated = torch.cuda.memory_allocated()
            return float(max(0.0, min(100.0, 100.0 * allocated / reserved)))
        except Exception:
            return 0.0


torch_cuda = _TorchCudaShim()


def _rocm_smi_mem_info() -> dict | None:
    """Query rocm-smi for GPU 0 VRAM info.

    Returns a dict with ``mem_util_pct`` and ``vram_total_mb``/``vram_used_mb``
    or None if rocm-smi is unavailable.
    """
    try:
        raw = subprocess.check_output(
            ["rocm-smi", "--showmeminfo", "vram", "--json"],
            stderr=subprocess.DEVNULL,
            timeout=3.0,
        )
        data = json.loads(raw.decode())
        # rocm-smi JSON layout varies by version; handle both known shapes.
        # Shape A (older):  {"card0": {"VRAM Total Memory (B)": "...",
        #                              "VRAM Total Used Memory (B)": "..."}}
        # Shape B (newer):  {"GPU[0]": {"vram_total": ..., "vram_used": ...}}
        for _key, vals in data.items():
            if not isinstance(vals, dict):
                continue
            total_b = vals.get("VRAM Total Memory (B)") or vals.get("vram_total")
            used_b = vals.get("VRAM Total Used Memory (B)") or vals.get("vram_used")
            if total_b is not None and used_b is not None:
                total = float(total_b)
                used = float(used_b)
                if total > 0:
                    return {
                        "mem_util_pct": max(0.0, min(100.0, 100.0 * used / total)),
                        "vram_total_mb": round(total / 1_048_576, 1),
                        "vram_used_mb": round(used / 1_048_576, 1),
                    }
    except FileNotFoundError:
        pass  # rocm-smi not installed — expected on non-Radeon hosts
    except Exception as exc:
        log.debug("rocm-smi query failed: %s", exc)
    return None


def _rocm_smi_device_name() -> str | None:
    """Return GPU 0 device name from rocm-smi, or None."""
    try:
        raw = subprocess.check_output(
            ["rocm-smi", "--showproductname", "--json"],
            stderr=subprocess.DEVNULL,
            timeout=3.0,
        )
        data = json.loads(raw.decode())
        for _key, vals in data.items():
            if not isinstance(vals, dict):
                continue
            name = (
                vals.get("Card SKU")
                or vals.get("card_series")
                or vals.get("product_name")
            )
            if name:
                return str(name)
    except Exception:
        pass
    return None


class GpuSensor:
    """Samples GPU utilisation metrics from rocm-smi (primary) or torch.cuda (fallback).

    ``snapshot()`` returns a dict always containing:
      - ``mem_util_pct``  : float [0, 100]
      - ``device_name``   : str — GPU product name or "unknown"
      - ``backend``       : "rocm-smi" | "torch" | "none"
    """

    def snapshot(self) -> dict:
        # --- Primary: rocm-smi (present on Radeon pod) ---
        rocm_info = _rocm_smi_mem_info()
        if rocm_info is not None:
            return {
                "mem_util_pct": rocm_info["mem_util_pct"],
                "vram_total_mb": rocm_info["vram_total_mb"],
                "vram_used_mb": rocm_info["vram_used_mb"],
                "device_name": _rocm_smi_device_name() or torch_cuda.device_name(),
                "backend": "rocm-smi",
            }

        # --- Fallback: torch.cuda (works on any CUDA/ROCm with torch wheel) ---
        if torch_cuda.is_available():
            mem = max(0.0, min(100.0, torch_cuda.mem_util_pct()))
            return {
                "mem_util_pct": mem,
                "device_name": torch_cuda.device_name(),
                "backend": "torch",
            }

        return {"mem_util_pct": 0.0, "device_name": "none", "backend": "none"}
