#!/usr/bin/env python3
"""Capture a secret-free, non-overwriting ROCm robot-port inventory."""

from __future__ import annotations

import argparse
import glob
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any


def _run(argv: list[str]) -> dict[str, Any]:
    try:
        process = subprocess.run(
            argv,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        return {
            "argv": argv,
            "returncode": process.returncode,
            "stdout": process.stdout[-12000:],
            "stderr": process.stderr[-4000:],
        }
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "argv": argv,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }


def _packages() -> dict[str, str | None]:
    result: dict[str, str | None] = {}
    for name in (
        "torch",
        "torchvision",
        "torchaudio",
        "triton",
        "genesis-world",
        "genesis",
        "lerobot",
    ):
        try:
            result[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            result[name] = None
    return result


def _torch_inventory() -> dict[str, Any]:
    try:
        import torch

        hip = getattr(torch.version, "hip", None)
        available = bool(torch.cuda.is_available())
        count = int(torch.cuda.device_count()) if available else 0
        result: dict[str, Any] = {
            "imported": True,
            "version": str(torch.__version__),
            "hip_version": str(hip) if hip else None,
            "cuda_available": available,
            "device_count": count,
        }
        if count:
            properties = torch.cuda.get_device_properties(0)
            result.update(
                {
                    "device_name": str(torch.cuda.get_device_name(0)),
                    "total_memory_bytes": int(properties.total_memory),
                }
            )
        return result
    except (ImportError, OSError, RuntimeError) as exc:
        return {
            "imported": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }


def _genesis_inventory() -> dict[str, Any]:
    try:
        import genesis as gs

        return {
            "imported": True,
            "version": str(getattr(gs, "__version__", "unknown")),
            "has_amdgpu": hasattr(gs, "amdgpu"),
        }
    except (ImportError, OSError, RuntimeError) as exc:
        return {
            "imported": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }


def _mount_inventory() -> dict[str, Any] | None:
    for line in Path("/proc/mounts").read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if len(fields) >= 4 and fields[1] in (
            "/persistent",
            "/workspace/persistent",
        ):
            return {
                "source": fields[0],
                "mountpoint": fields[1],
                "filesystem": fields[2],
                "options": fields[3].split(","),
            }
    return None


def capture() -> dict[str, Any]:
    persistent = Path("/workspace/persistent")
    return {
        "schema_version": 1,
        "kind": "wp_rocm_native_inventory",
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "hostname": platform.node(),
        "python_version": platform.python_version(),
        "persistence": {
            "requested": str(persistent),
            "resolved": str(persistent.resolve()),
            "is_dir": persistent.is_dir(),
            "writable": os.access(persistent, os.W_OK),
            "mount": _mount_inventory(),
        },
        "packages": _packages(),
        "torch": _torch_inventory(),
        "genesis": _genesis_inventory(),
        "official_wheels": [
            {
                "path": path,
                "size_bytes": Path(path).stat().st_size,
            }
            for path in sorted(glob.glob("/*.whl"))
        ],
        "rocm_smi_product": _run(
            ["rocm-smi", "--showproductname", "--showmeminfo", "vram"]
        ),
        "rocm_smi_pids": _run(["rocm-smi", "--showpids"]),
        "claim_boundary": (
            "Fresh inventory only; no package installation, runtime port, "
            "benchmark, training, inference, or task success is established."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(capture(), stream, indent=2, sort_keys=True)
            stream.write("\n")
    except (FileExistsError, OSError, RuntimeError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "status": "error",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
