"""Safe, read-only inference environment inspection.

PyTorch commonly exposes AMD ROCm devices through the ``torch.cuda`` API even
though the device is not an NVIDIA GPU. No reported value should be interpreted
as Radeon/ROCm proof without inspecting ``torch.version.hip``.
"""
import json
import platform
from typing import Any

def inspect_device() -> dict[str, Any]:
    result: dict[str, Any] = {
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "pytorch_installed": False,
        "torch_version": None,
        "cuda_api_available": False,
        "device_count": 0,
        "devices": [],
        "hip_version": None,
        "rocm_available": False,
        "message": "PyTorch is not installed.",
    }
    try:
        import torch
    except (ImportError, OSError) as exc:
        result["error_type"] = type(exc).__name__
        return result
    result["pytorch_installed"] = True
    result["torch_version"] = getattr(torch, "__version__", None)
    result["hip_version"] = getattr(getattr(torch, "version", None), "hip", None)
    result["rocm_available"] = bool(result["hip_version"])
    try:
        available = bool(torch.cuda.is_available())
        count = int(torch.cuda.device_count()) if available else 0
        result["cuda_api_available"] = available
        result["device_count"] = count
        for index in range(count):
            props = torch.cuda.get_device_properties(index)
            total = getattr(props, "total_memory", None)
            result["devices"].append({"index":index,"name":torch.cuda.get_device_name(index),"total_memory_bytes":int(total) if total is not None else None})
        result["message"] = "Device inspection completed." if available else "PyTorch is installed; no compatible GPU device is available."
    except (RuntimeError, AssertionError, OSError) as exc:
        result["message"] = "PyTorch is installed, but device inspection was unavailable."
        result["error_type"] = type(exc).__name__
    return result

if __name__ == "__main__":
    print(json.dumps(inspect_device(), indent=2))
