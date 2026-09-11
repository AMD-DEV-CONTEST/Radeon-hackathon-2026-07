from __future__ import annotations

from importlib import metadata
import platform
import sys
from typing import Any


def runtime_report() -> dict[str, Any]:
    report: dict[str, Any] = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
    }
    for package in ("genesis-world", "lerobot", "torch"):
        try:
            report[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            report[package] = None

    try:
        import torch

        report["torch"] = torch.__version__
        report["rocm"] = getattr(torch.version, "hip", None)
        report["cuda"] = getattr(torch.version, "cuda", None)
        report["gpu_available"] = torch.cuda.is_available()
        report["gpu_count"] = torch.cuda.device_count() if torch.cuda.is_available() else 0
        if torch.cuda.is_available():
            properties = torch.cuda.get_device_properties(0)
            report["gpu_name"] = properties.name
            report["gpu_total_memory_bytes"] = properties.total_memory
    except ImportError:
        report.update({"rocm": None, "cuda": None, "gpu_available": False, "gpu_count": 0})
    return report
