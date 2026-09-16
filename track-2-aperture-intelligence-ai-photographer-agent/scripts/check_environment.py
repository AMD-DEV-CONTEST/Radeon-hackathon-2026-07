"""Print and validate the ROCm environment without modifying it."""

from __future__ import annotations

import json
import platform
import sys

import torch


def main() -> None:
    available = torch.cuda.is_available()
    report = {
        "python": platform.python_version(),
        "executable": sys.executable,
        "torch": torch.__version__,
        "torch_version_hip": torch.version.hip,
        "torch_cuda_is_available": available,
        "gpu": torch.cuda.get_device_name(0) if available else None,
        "gpu_count": torch.cuda.device_count(),
        "vram_gib": (
            round(torch.cuda.get_device_properties(0).total_memory / 1024**3, 2)
            if available
            else None
        ),
        "backend": "ROCm/HIP" if torch.version.hip else "not ROCm/HIP",
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not available or not torch.version.hip:
        raise SystemExit("ERROR: a ROCm/HIP PyTorch GPU is required.")


if __name__ == "__main__":
    main()
