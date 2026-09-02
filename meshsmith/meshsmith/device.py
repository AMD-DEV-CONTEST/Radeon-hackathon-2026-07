"""GPU backend detection. Works identically on ROCm and CUDA builds of PyTorch:
ROCm PyTorch exposes the HIP device through the `cuda` API, so `torch.cuda.*`
is the portable path on both vendors.
"""
from __future__ import annotations

import torch


def preflight() -> None:
    """Fail with an actionable message instead of a cryptic ModuleNotFoundError
    from deep inside Hunyuan3D. torchvision is an import-time dependency of
    hy3dgen but is not declared by its setup.py."""
    try:
        import torchvision  # noqa: F401
    except ModuleNotFoundError as exc:
        index = "rocm6.2" if getattr(torch.version, "hip", None) else "cu124"
        raise SystemExit(
            "MeshSmith needs torchvision (Hunyuan3D imports it at load time), and it "
            "is missing.\nInstall it from the same index as your torch build:\n"
            f"    pip install torchvision --index-url https://download.pytorch.org/whl/{index}\n"
            "Do not install it from plain PyPI — that pulls a torch wheel that can "
            "shadow your current build."
        ) from exc


def pick_device() -> torch.device:
    """Return the CUDA/HIP device with the most VRAM, else CPU."""
    if not torch.cuda.is_available():
        return torch.device("cpu")
    best, best_mem = 0, 0
    for i in range(torch.cuda.device_count()):
        mem = torch.cuda.get_device_properties(i).total_memory
        if mem > best_mem:
            best, best_mem = i, mem
    return torch.device(f"cuda:{best}")


def backend_name() -> str:
    if not torch.cuda.is_available():
        return "CPU"
    if getattr(torch.version, "hip", None):
        return f"AMD ROCm {torch.version.hip}"
    return f"NVIDIA CUDA {torch.version.cuda}"


def device_banner(device: torch.device | None = None) -> dict:
    """Everything the UI / benchmark needs to state where inference ran."""
    device = device or pick_device()
    info = {
        "backend": backend_name(),
        "torch": torch.__version__,
        "device": str(device),
        "gpu": "none (CPU mode)",
        "vram_gb": 0.0,
    }
    if device.type == "cuda":
        props = torch.cuda.get_device_properties(device)
        info["gpu"] = props.name
        info["vram_gb"] = round(props.total_memory / 1024**3, 1)
    return info


def vram_used_gb(device: torch.device) -> float:
    if device.type != "cuda":
        return 0.0
    return round(torch.cuda.memory_allocated(device) / 1024**3, 2)


def vram_peak_gb(device: torch.device) -> float:
    if device.type != "cuda":
        return 0.0
    return round(torch.cuda.max_memory_allocated(device) / 1024**3, 2)


def reset_vram_peak(device: torch.device) -> None:
    if device.type == "cuda":
        torch.cuda.reset_peak_memory_stats(device)


def empty_cache() -> None:
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
