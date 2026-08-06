#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from prooflaunch_remix.files import atomic_write_text  # noqa: E402
from prooflaunch_remix.v10_sft_corpus import stable_sha256  # noqa: E402


def _command(command: list[str], timeout: int = 20) -> dict[str, Any]:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
        output = (result.stdout + result.stderr).strip()
        return {
            "available": True,
            "returncode": result.returncode,
            "output_sha256": hashlib.sha256(output.encode()).hexdigest(),
            "output_preview": output[:4_000],
        }
    except FileNotFoundError:
        return {"available": False, "returncode": None, "output_sha256": None, "output_preview": None}
    except subprocess.TimeoutExpired:
        return {"available": True, "returncode": None, "output_sha256": None, "output_preview": "timeout"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="evidence/v10/radeon-live-preflight.json")
    args = parser.parse_args()
    output = Path(args.output)
    if not output.is_absolute():
        output = ROOT / output

    report: dict[str, Any] = {
        "schema": "ProofLaunchRadeonLivePreflightV1",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "host": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "python": sys.version,
            "kernel": platform.release(),
        },
        "environment_flags": {
            "HIP_VISIBLE_DEVICES_set": "HIP_VISIBLE_DEVICES" in os.environ,
            "ROCR_VISIBLE_DEVICES_set": "ROCR_VISIBLE_DEVICES" in os.environ,
            "HSA_OVERRIDE_GFX_VERSION_set": "HSA_OVERRIDE_GFX_VERSION" in os.environ,
        },
        "commands": {
            "rocminfo": _command(["rocminfo"]),
            "rocm_smi": _command(["rocm-smi", "--showproductname", "--showmeminfo", "vram"]),
        },
        "torch": {"imported": False},
        "radeon_runtime_observed": False,
        "bf16_matmul_observed": False,
        "backward_observed": False,
        "sdpa_observed": False,
        "model_inference_observed": False,
        "training_observed": False,
    }
    try:
        import torch

        torch_data: dict[str, Any] = {
            "imported": True,
            "version": torch.__version__,
            "hip_version": getattr(torch.version, "hip", None),
            "cuda_api_available": torch.cuda.is_available(),
            "device_count": torch.cuda.device_count(),
            "devices": [],
        }
        for index in range(torch.cuda.device_count()):
            props = torch.cuda.get_device_properties(index)
            torch_data["devices"].append(
                {
                    "index": index,
                    "name": torch.cuda.get_device_name(index),
                    "total_memory_bytes": int(props.total_memory),
                    "multi_processor_count": int(props.multi_processor_count),
                }
            )
        report["torch"] = torch_data
        is_rocm = bool(torch_data["hip_version"] and torch_data["cuda_api_available"] and torch_data["device_count"])
        report["radeon_runtime_observed"] = is_rocm
        if is_rocm:
            device = torch.device("cuda:0")
            torch.manual_seed(42)
            torch.cuda.manual_seed_all(42)
            started = time.perf_counter()
            left = torch.randn((256, 256), device=device, dtype=torch.bfloat16, requires_grad=True)
            right = torch.randn((256, 256), device=device, dtype=torch.bfloat16)
            value = (left @ right).float().square().mean()
            report["bf16_matmul_observed"] = bool(torch.isfinite(value).item())
            value.backward()
            report["backward_observed"] = left.grad is not None and bool(torch.isfinite(left.grad).all().item())
            query = torch.randn((1, 4, 64, 32), device=device, dtype=torch.bfloat16)
            attention = torch.nn.functional.scaled_dot_product_attention(query, query, query)
            report["sdpa_observed"] = bool(torch.isfinite(attention).all().item())
            torch.cuda.synchronize()
            report["probe_elapsed_seconds"] = round(time.perf_counter() - started, 6)
            report["peak_memory_allocated_bytes"] = int(torch.cuda.max_memory_allocated(device))
            del attention, query, value, right, left
            torch.cuda.empty_cache()
    except Exception as error:
        report["torch_probe_error"] = {"type": type(error).__name__, "message": str(error)[:2_000]}

    report["preflight_passed"] = all(
        bool(report[key])
        for key in (
            "radeon_runtime_observed",
            "bf16_matmul_observed",
            "backward_observed",
            "sdpa_observed",
        )
    )
    report["truth_boundary"] = (
        "A pass proves a small ROCm BF16 forward/backward/SDPA runtime probe on the observed device. "
        "It does not prove model inference, training, quality, throughput, or competition submission."
    )
    report["content_sha256"] = stable_sha256(report)
    atomic_write_text(output, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"output": str(output), **report}, ensure_ascii=False))
    return 0 if report["preflight_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
