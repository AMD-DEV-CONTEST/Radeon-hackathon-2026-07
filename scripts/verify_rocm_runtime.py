"""Validate a real ROCm PyTorch runtime without fabricating Windows results."""

from __future__ import annotations

import json
import platform
from typing import Any


def verify() -> tuple[int, dict[str, Any]]:
    if platform.system() != "Linux":
        return 0, {
            "status": "SERVER_VALIDATION_REQUIRED",
            "reason": "ROCm validation must run on the AMD Linux server.",
        }
    try:
        import torch
    except ImportError as exc:
        return 2, {"status": "FAIL", "reason": f"PyTorch unavailable: {exc}"}
    hip = getattr(torch.version, "hip", None)
    available = torch.cuda.is_available()
    names = [
        torch.cuda.get_device_name(index) for index in range(torch.cuda.device_count())
    ]
    payload = {
        "status": "PASS" if hip and available and names else "FAIL",
        "torch": torch.__version__,
        "hip": hip,
        "gpu_available": available,
        "gpu_names": names,
    }
    return (0 if payload["status"] == "PASS" else 2), payload


if __name__ == "__main__":
    code, result = verify()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(code)
