#!/usr/bin/env python3
"""Capture a reproducible AMD/ROCm/Python/vLLM environment fingerprint."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def run_command(
    name: str,
    command: list[str],
    *,
    next_step: str,
    required: bool = True,
    timeout: int = 60,
) -> dict[str, Any]:
    executable = shutil.which(command[0])
    if executable is None:
        return {
            "name": name,
            "command": command,
            "required": required,
            "status": "failed",
            "exit_code": None,
            "stdout": "",
            "stderr": f"{command[0]} not found",
            "failure_reason": f"Required command {command[0]!r} is unavailable.",
            "next_step": next_step,
        }
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "name": name,
            "command": command,
            "required": required,
            "status": "failed",
            "exit_code": None,
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
            "failure_reason": f"Command timed out after {timeout} seconds.",
            "next_step": next_step,
        }

    return {
        "name": name,
        "command": command,
        "required": required,
        "status": "passed" if completed.returncode == 0 else "failed",
        "exit_code": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
        "failure_reason": (
            "" if completed.returncode == 0 else f"Command exited with {completed.returncode}."
        ),
        "next_step": "" if completed.returncode == 0 else next_step,
    }


def python_runtime() -> dict[str, Any]:
    result: dict[str, Any] = {
        "python": sys.version,
        "executable": sys.executable,
        "platform": platform.platform(),
    }
    try:
        import torch

        result["torch"] = {
            "version": torch.__version__,
            "hip": torch.version.hip,
            "cuda_api_available": torch.cuda.is_available(),
            "device_count": torch.cuda.device_count(),
            "devices": [
                torch.cuda.get_device_name(index)
                for index in range(torch.cuda.device_count())
            ],
        }
        result["torch_status"] = (
            "passed"
            if torch.version.hip and torch.cuda.is_available()
            else "failed"
        )
        if result["torch_status"] == "failed":
            result["torch_failure_reason"] = (
                "PyTorch is not reporting an available ROCm GPU."
            )
            result["torch_next_step"] = (
                "Use the Radeon ROCm image or install a PyTorch build matching "
                "the instance ROCm version."
            )
    except Exception as exc:  # noqa: BLE001 - fingerprint must preserve import failure
        result["torch_status"] = "failed"
        result["torch_failure_reason"] = repr(exc)
        result["torch_next_step"] = (
            "Install the PyTorch ROCm build matching the instance driver."
        )

    try:
        import vllm

        result["vllm"] = {"version": getattr(vllm, "__version__", "unknown")}
        result["vllm_status"] = "passed"
    except Exception as exc:  # noqa: BLE001
        result["vllm_status"] = "failed"
        result["vllm_failure_reason"] = repr(exc)
        result["vllm_next_step"] = (
            "Install a vLLM ROCm build compatible with this Python and ROCm version."
        )

    try:
        import transformers

        result["transformers"] = {
            "version": getattr(transformers, "__version__", "unknown")
        }
    except Exception as exc:  # noqa: BLE001
        result["transformers"] = {"import_error": repr(exc)}
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        help="Output JSON path. Defaults to artifacts/environment-<UTC>.json.",
    )
    args = parser.parse_args()

    timestamp = datetime.now(timezone.utc)
    output = args.output or Path("artifacts") / (
        f"environment-{timestamp.strftime('%Y%m%dT%H%M%SZ')}.json"
    )

    checks = [
        run_command(
            "kernel",
            ["uname", "-a"],
            next_step="Confirm the instance is a supported Linux environment.",
            required=False,
        ),
        run_command(
            "os-release",
            ["cat", "/etc/os-release"],
            next_step="Record the container base image manually.",
            required=False,
        ),
        run_command(
            "gpu-pci",
            ["lspci", "-nn"],
            next_step="Use amd-smi/rocminfo or choose a GPU-enabled template.",
            required=False,
        ),
        run_command(
            "rocm-info",
            ["rocminfo"],
            next_step="Use a Radeon/ROCm image and confirm /dev/kfd is exposed.",
            timeout=120,
        ),
        run_command(
            "amd-smi-version",
            ["amd-smi", "version"],
            next_step="Install/enable AMD SMI or choose the official Radeon image.",
        ),
        run_command(
            "amd-smi-static",
            ["amd-smi", "static", "--gpu", "all"],
            next_step="Run `amd-smi --help` and record GPU properties manually.",
        ),
        run_command(
            "amd-smi-metric",
            ["amd-smi", "metric", "--gpu", "all"],
            next_step="Run `amd-smi --help`; use the image-supported metric command.",
        ),
        run_command(
            "listening-ports",
            ["ss", "-ltnp"],
            next_step="Install iproute2 or verify the listener with another local tool.",
            required=False,
        ),
    ]

    fingerprint = {
        "schema_version": 1,
        "captured_at_utc": timestamp.isoformat(),
        "cwd": os.getcwd(),
        "runtime": python_runtime(),
        "commands": checks,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(fingerprint, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(json.dumps(fingerprint, ensure_ascii=False, indent=2))
    print(f"\nSaved fingerprint: {output.resolve()}")
    failed = [
        item["name"]
        for item in checks
        if item["required"] and item["status"] == "failed"
    ]
    if fingerprint["runtime"].get("torch_status") != "passed":
        failed.append("pytorch-rocm")
    if fingerprint["runtime"].get("vllm_status") != "passed":
        failed.append("vllm")
    if failed:
        print(f"Fingerprint completed with failed checks: {', '.join(failed)}")
        return 1
    print("All environment checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
