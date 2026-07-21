from __future__ import annotations

import subprocess


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
    def mem_util_pct() -> float:
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


class GpuSensor:
    def snapshot(self) -> dict[str, float]:
        if not torch_cuda.is_available():
            return {"mem_util_pct": 0.0}
        pct = torch_cuda.mem_util_pct()
        return {"mem_util_pct": float(max(0.0, min(100.0, pct)))}


def _rocm_smi_mem_util() -> float:
    try:
        subprocess.check_output(
            ["rocm-smi", "--showmeminfo", "vram"], stderr=subprocess.STDOUT, timeout=2.0
        )
    except Exception:
        return 0.0
    return 0.0
