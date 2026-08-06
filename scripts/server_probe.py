"""Cross-platform deployment probe with explicit server-only status."""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


def _device(path: str) -> bool | None:
    return Path(path).exists() if platform.system() == "Linux" else None


def _command(command: list[str]) -> str | None:
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    output = (result.stdout or result.stderr).strip()
    return output[:4000] or None


def probe() -> dict[str, Any]:
    linux = platform.system() == "Linux"
    torch_info: dict[str, Any] = {"installed": False}
    try:
        import torch

        torch_info = {
            "installed": True,
            "version": torch.__version__,
            "hip": getattr(torch.version, "hip", None),
            "gpu_available": torch.cuda.is_available(),
            "gpu_count": torch.cuda.device_count(),
            "gpu_names": [
                torch.cuda.get_device_name(index)
                for index in range(torch.cuda.device_count())
            ],
            "vram_bytes": [
                torch.cuda.get_device_properties(index).total_memory
                for index in range(torch.cuda.device_count())
            ],
        }
    except (ImportError, RuntimeError) as exc:
        torch_info["detail"] = str(exc)
    model_root = Path(os.environ.get("BG_MODELS", "models")).expanduser()
    disk_root = Path(os.environ.get("BG_ROOT", ".")).expanduser().resolve()
    disk = shutil.disk_usage(disk_root)
    return {
        "status": "SERVER_VALIDATION_REQUIRED" if not linux else "PROBED",
        "os": platform.platform(),
        "python": sys.version,
        "torch": torch_info,
        "dev_kfd": _device("/dev/kfd"),
        "dev_dri": _device("/dev/dri"),
        "model_directory": {
            "path": str(model_root),
            "exists": model_root.is_dir(),
        },
        "disk": {
            "path": str(disk_root),
            "total_bytes": disk.total,
            "free_bytes": disk.free,
        },
        "container": _command(["cat", "/proc/1/cgroup"]) if linux else None,
        "systemd": (
            _command(["systemctl", "is-system-running"])
            if linux and shutil.which("systemctl")
            else None
        ),
    }


if __name__ == "__main__":
    print(json.dumps(probe(), ensure_ascii=False, indent=2))
