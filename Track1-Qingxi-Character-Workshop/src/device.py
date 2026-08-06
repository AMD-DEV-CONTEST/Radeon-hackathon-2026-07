from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class DeviceInfo:
    device_type: str  # cpu | cuda | mps
    name: str
    vram_gb: float | None
    rocm_hint: bool
    mock_mode: bool = False
    torch_version: str | None = None


def detect_device() -> DeviceInfo:
    mock_mode = os.environ.get("MOCK", "0").strip() in {"1", "true", "True", "yes"}
    try:
        import torch
    except ImportError:
        return DeviceInfo("cpu", "torch-not-installed", None, False, mock_mode, None)

    torch_version = getattr(torch, "__version__", None)
    rocm_hint = bool(getattr(torch.version, "hip", None)) or (
        "rocm" in (torch_version or "").lower()
    )

    if torch.cuda.is_available():
        idx = torch.cuda.current_device()
        name = torch.cuda.get_device_name(idx)
        props = torch.cuda.get_device_properties(idx)
        vram_gb = round(props.total_memory / (1024**3), 2)
        return DeviceInfo("cuda", name, vram_gb, rocm_hint, mock_mode, torch_version)

    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return DeviceInfo("mps", "apple-mps", None, False, mock_mode, torch_version)

    return DeviceInfo("cpu", "cpu", None, False, mock_mode, torch_version)


def vram_profile(info: DeviceInfo) -> str:
    if info.device_type != "cuda" or info.vram_gb is None:
        return "cpu"
    if info.vram_gb >= 20:
        return "24gb"
    if info.vram_gb >= 10:
        return "16gb"
    return "low"


def torch_device_string(info: DeviceInfo | None = None) -> str:
    info = info or detect_device()
    if info.device_type == "cuda":
        return "cuda"
    if info.device_type == "mps":
        return "mps"
    return "cpu"