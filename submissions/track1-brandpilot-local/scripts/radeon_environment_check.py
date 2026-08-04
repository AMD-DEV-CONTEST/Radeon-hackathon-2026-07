"""Capture a non-secret, failure-tolerant Radeon/ROCm environment report."""
from __future__ import annotations

import argparse
import json
import os
import platform
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SAFE_ENV_KEYS = (
    "CUDA_VISIBLE_DEVICES",
    "HIP_VISIBLE_DEVICES",
    "ROCR_VISIBLE_DEVICES",
    "HSA_OVERRIDE_GFX_VERSION",
    "PYTORCH_ROCM_ARCH",
    "ROCM_PATH",
    "HIP_PATH",
    "DEVICE",
    "DTYPE",
    "MODEL_ID",
    "MODEL_REVISION",
    "MODEL_CACHE_DIR",
    "OUTPUT_DIR",
)


def collect_report() -> dict[str, Any]:
    report: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "operating_system": platform.platform(),
        "python_version": platform.python_version(),
        "pytorch_version": None,
        "hip_rocm_version": None,
        "gpu_available": False,
        "gpu_count": 0,
        "devices": [],
        "memory": None,
        "environment": {key: os.environ[key] for key in SAFE_ENV_KEYS if key in os.environ},
        "errors": [],
    }

    try:
        import torch
    except (ImportError, OSError) as exc:
        report["errors"].append(f"PyTorch unavailable: {type(exc).__name__}: {exc}")
        report["summary"] = {"status": "FAIL", "message": "PyTorch is unavailable; ROCm inference is not ready."}
        return report

    report["pytorch_version"] = getattr(torch, "__version__", None)
    report["hip_rocm_version"] = getattr(getattr(torch, "version", None), "hip", None)

    try:
        report["gpu_available"] = bool(torch.cuda.is_available())
        report["gpu_count"] = int(torch.cuda.device_count()) if report["gpu_available"] else 0
        for index in range(report["gpu_count"]):
            properties = torch.cuda.get_device_properties(index)
            device = {
                "index": index,
                "name": torch.cuda.get_device_name(index),
                "total_memory_bytes": getattr(properties, "total_memory", None),
            }
            report["devices"].append(device)
        if report["gpu_count"]:
            memory: dict[str, Any] = {
                "allocated_bytes": int(torch.cuda.memory_allocated(0)),
                "reserved_bytes": int(torch.cuda.memory_reserved(0)),
            }
            try:
                free_bytes, total_bytes = torch.cuda.mem_get_info(0)
                memory.update({"free_bytes": int(free_bytes), "total_bytes": int(total_bytes)})
            except (AttributeError, RuntimeError, OSError) as exc:
                report["errors"].append(f"Free-memory query unavailable: {type(exc).__name__}: {exc}")
            report["memory"] = memory
    except (AssertionError, AttributeError, RuntimeError, OSError) as exc:
        report["errors"].append(f"GPU query unavailable: {type(exc).__name__}: {exc}")

    passed = bool(
        report["pytorch_version"]
        and report["hip_rocm_version"]
        and report["gpu_available"]
        and report["gpu_count"] > 0
    )
    report["summary"] = {
        "status": "PASS" if passed else "FAIL",
        "message": (
            "PyTorch reports at least one HIP/ROCm GPU."
            if passed
            else "Required PyTorch, HIP/ROCm, or GPU evidence is missing."
        ),
    }
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect PyTorch and Radeon/ROCm readiness without exposing secrets.")
    parser.add_argument("--output", type=Path, help="Optional path for the JSON report.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = collect_report()
    rendered = json.dumps(report, indent=2)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
        print(f"Saved report: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
