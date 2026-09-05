#!/usr/bin/env python3
"""Write a sanitized machine-readable W7900/ROCm/vLLM environment record."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
from pathlib import Path

W7900_GPU_ARCH = "gfx1100"
# PyTorch reports this field as 48 WGPs on the Radeon Cloud image while some
# ROCm stacks expose the same W7900 as 96 compute units. Treat it as an
# implementation-dependent processor count and retain the observed value.
W7900_PROCESSOR_COUNTS = frozenset({48, 96})
W7900_MIN_MEMORY_BYTES = 47 * 1024**3
W7900_MAX_MEMORY_BYTES = 50 * 1024**3
W7900_PROFILE_NAME = "AMD Radeon PRO W7900 48GB"


def _read_optional(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def validate_w7900_hardware_profile(
    *,
    device_name_raw: str,
    gpu_arch_raw: str,
    compute_units: int,
    memory_bytes: int,
) -> dict[str, str | int | bool]:
    """Validate the stable W7900 hardware profile, independent of display name."""

    gpu_arch = gpu_arch_raw.strip().lower().split(":", 1)[0]
    mismatches = []
    if gpu_arch != W7900_GPU_ARCH:
        mismatches.append(f"architecture={gpu_arch or 'UNKNOWN'}")
    if compute_units not in W7900_PROCESSOR_COUNTS:
        mismatches.append(f"compute_units={compute_units}")
    if not W7900_MIN_MEMORY_BYTES <= memory_bytes <= W7900_MAX_MEMORY_BYTES:
        mismatches.append(f"memory_bytes={memory_bytes}")
    if mismatches:
        raise RuntimeError(
            "expected the W7900 hardware profile "
            f"({W7900_GPU_ARCH}, 48 WGP/96 CU representation, 48GB); observed "
            + ", ".join(mismatches)
        )
    return {
        "gpu_profile": W7900_PROFILE_NAME,
        "gpu_profile_match": True,
        "gpu_device_name_raw": device_name_raw,
        "gpu_arch": gpu_arch,
        "gpu_compute_units": compute_units,
        "gpu_memory_bytes": memory_bytes,
    }


def _gpu_arch_from_properties(properties: object) -> str:
    for attribute in ("gcnArchName", "gcn_arch_name"):
        value = getattr(properties, attribute, None)
        if isinstance(value, str) and value.strip():
            return value
    raise RuntimeError("ROCm device properties do not expose the GPU architecture")


def main() -> int:
    import torch
    from vllm.platforms import current_platform

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--code-commit", required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--model-manifest", type=Path, required=True)
    parser.add_argument("--base-url", required=True)
    args = parser.parse_args()

    if not torch.cuda.is_available():
        raise RuntimeError("PyTorch does not report an available ROCm device")
    device_name = torch.cuda.get_device_name(0)
    if type(current_platform).__name__ != "RocmPlatform":
        raise RuntimeError(
            f"expected vLLM RocmPlatform, got {type(current_platform).__name__}"
        )
    if not args.model_manifest.is_file():
        raise FileNotFoundError(args.model_manifest)
    gpu_properties = torch.cuda.get_device_properties(0)
    gpu_profile = validate_w7900_hardware_profile(
        device_name_raw=device_name,
        gpu_arch_raw=_gpu_arch_from_properties(gpu_properties),
        compute_units=gpu_properties.multi_processor_count,
        memory_bytes=gpu_properties.total_memory,
    )

    payload = {
        "schema_version": "w7900-environment/v1",
        "code_commit": args.code_commit,
        "hardware": {
            "architecture": platform.machine(),
            "cpu_count": os.cpu_count(),
            "cgroup_cpu_max": _read_optional(Path("/sys/fs/cgroup/cpu.max")),
            "cgroup_memory_max": _read_optional(Path("/sys/fs/cgroup/memory.max")),
            "gpu": device_name,
            **gpu_profile,
        },
        "software": {
            "os": platform.platform(),
            "python": platform.python_version(),
            "torch": torch.__version__,
            "hip": torch.version.hip,
            "vllm": importlib.metadata.version("vllm"),
            "vllm_platform": type(current_platform).__name__,
        },
        "model_and_serving": {
            "model_id": args.model_id,
            "model_path": str(args.model_path),
            "model_manifest": str(args.model_manifest),
            "model_manifest_sha256": hashlib.sha256(
                args.model_manifest.read_bytes()
            ).hexdigest(),
            "base_url": args.base_url,
            "loopback_only": args.base_url.startswith(
                ("http://127.0.0.1", "http://localhost", "http://[::1]")
            ),
        },
        "privacy": {
            "hostname_retained": False,
            "username_retained": False,
            "credentials_retained": False,
            "raw_prompt_or_response_retained": False,
        },
    }
    if not payload["model_and_serving"]["loopback_only"]:
        raise RuntimeError("W7900 evidence requires a loopback-only model endpoint")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"result": "PASS", "output": str(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
