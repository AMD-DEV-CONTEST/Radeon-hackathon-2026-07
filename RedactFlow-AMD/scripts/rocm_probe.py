from __future__ import annotations

import json
import platform
import shutil
import subprocess
from datetime import datetime, timezone


def command_output(command: list[str]) -> str | None:
    if not shutil.which(command[0]):
        return None
    completed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=20)
    return (completed.stdout or completed.stderr).strip()


report = {
    "captured_at": datetime.now(timezone.utc).isoformat(),
    "platform": platform.platform(),
    "rocm_smi": command_output(["rocm-smi", "--showproductname", "--showmeminfo", "vram"]),
    "rocminfo": command_output(["rocminfo"]),
}

try:
    import torch

    report["torch"] = {
        "version": torch.__version__,
        "hip": getattr(torch.version, "hip", None),
        "cuda_available": torch.cuda.is_available(),
        "device_count": torch.cuda.device_count(),
        "devices": [torch.cuda.get_device_name(index) for index in range(torch.cuda.device_count())],
    }
except Exception as error:  # pragma: no cover - depends on target hardware
    report["torch_error"] = str(error)

print(json.dumps(report, indent=2, ensure_ascii=False))

