"""Hardware detection helpers for FinMuse Radeon.

The module avoids hard dependency on ROCm tools so the demo can run on any
machine while still recording the real AMD Radeon / ROCm detection result.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Dict, List


@dataclass
class GPUStatus:
    timestamp: str
    platform: str
    python: str
    rocm_smi_found: bool
    rocminfo_found: bool
    hip_visible_devices: str
    torch_found: bool
    torch_hip_available: bool
    devices: List[str]
    mode: str
    notes: List[str]


def _run(cmd: List[str], timeout: int = 8) -> str:
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, timeout=timeout, text=True)
        return out.strip()
    except Exception as exc:
        return f"ERROR: {exc}"


def detect_gpu() -> GPUStatus:
    rocm_smi = shutil.which("rocm-smi")
    rocminfo = shutil.which("rocminfo")
    devices: List[str] = []
    notes: List[str] = []

    if rocm_smi:
        smi = _run([rocm_smi, "--showproductname"])
        for line in smi.splitlines():
            clean = line.strip()
            if clean and "GPU" in clean.upper():
                devices.append(clean)
        notes.append("rocm-smi detected and queried.")
    else:
        notes.append("rocm-smi not found in PATH.")

    if rocminfo:
        info = _run([rocminfo])
        for line in info.splitlines():
            if "Marketing Name" in line or "Name:" in line and "gfx" in line:
                devices.append(line.strip())
        notes.append("rocminfo detected and queried.")
    else:
        notes.append("rocminfo not found in PATH.")

    torch_found = False
    torch_hip_available = False
    try:
        import torch  # type: ignore
        torch_found = True
        torch_hip_available = bool(getattr(torch.version, "hip", None)) and torch.cuda.is_available()
        if torch_hip_available:
            for i in range(torch.cuda.device_count()):
                devices.append(torch.cuda.get_device_name(i))
            notes.append("PyTorch ROCm/HIP backend is available.")
        else:
            notes.append("PyTorch found but ROCm/HIP backend is not available.")
    except Exception:
        notes.append("PyTorch not installed; skipped HIP runtime check.")

    visible = os.environ.get("HIP_VISIBLE_DEVICES", "not-set")
    amd_like = any("amd" in d.lower() or "radeon" in d.lower() or "gfx" in d.lower() for d in devices)
    mode = "amd_rocm_gpu" if (rocm_smi or rocminfo or torch_hip_available or amd_like) else "cpu_fallback"
    if mode == "cpu_fallback":
        notes.append("Running in CPU fallback mode. On AMD ROCm hardware, the same commands record GPU mode automatically.")

    unique_devices = []
    for d in devices:
        if d not in unique_devices:
            unique_devices.append(d)

    return GPUStatus(
        timestamp=datetime.utcnow().isoformat(timespec="seconds") + "Z",
        platform=platform.platform(),
        python=platform.python_version(),
        rocm_smi_found=bool(rocm_smi),
        rocminfo_found=bool(rocminfo),
        hip_visible_devices=visible,
        torch_found=torch_found,
        torch_hip_available=torch_hip_available,
        devices=unique_devices,
        mode=mode,
        notes=notes,
    )


def status_dict() -> Dict[str, object]:
    return asdict(detect_gpu())


def write_status(path: str) -> Dict[str, object]:
    data = status_dict()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return data
