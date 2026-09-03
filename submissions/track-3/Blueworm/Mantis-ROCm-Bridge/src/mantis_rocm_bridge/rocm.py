"""Collect a narrow, non-secret ROCm runtime receipt."""

from __future__ import annotations

import datetime as dt
import platform
import shutil
import subprocess
import sys
from typing import Any


def _command_version(command: str, args: list[str]) -> dict[str, Any]:
    path = shutil.which(command)
    if path is None:
        return {"available": False}
    try:
        completed = subprocess.run(
            [path, *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
        output = (completed.stdout or completed.stderr).strip().splitlines()
        return {
            "available": True,
            "path": path,
            "exit_code": completed.returncode,
            "first_line": output[0][:500] if output else "",
        }
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"available": True, "path": path, "error": type(exc).__name__}


def collect_rocm_receipt() -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "schema_version": 1,
        "captured_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "commands": {
            "rocminfo": _command_version("rocminfo", ["--version"]),
            "amd-smi": _command_version("amd-smi", ["version"]),
            "rocm-smi": _command_version("rocm-smi", ["--version"]),
        },
    }
    try:
        import torch

        hip_version = getattr(torch.version, "hip", None)
        device_count = torch.cuda.device_count() if torch.cuda.is_available() else 0
        devices = []
        for index in range(device_count):
            properties = torch.cuda.get_device_properties(index)
            devices.append(
                {
                    "index": index,
                    "name": torch.cuda.get_device_name(index),
                    "total_memory_bytes": properties.total_memory,
                }
            )
        receipt["torch"] = {
            "available": True,
            "version": torch.__version__,
            "hip_version": hip_version,
            "cuda_api_available": torch.cuda.is_available(),
            "device_count": device_count,
            "devices": devices,
        }
    except (ImportError, RuntimeError) as exc:
        receipt["torch"] = {"available": False, "error": type(exc).__name__}

    torch_receipt = receipt["torch"]
    receipt["strict_rocm_pass"] = bool(
        torch_receipt.get("available")
        and torch_receipt.get("hip_version")
        and torch_receipt.get("device_count", 0) > 0
    )
    return receipt

