#!/usr/bin/env python3
"""Fail-fast hardware/model preflight for the AMD-local Track 2 service.

The active submission profile is Qwen3-14B BF16 on the RadeonX ``gfx1100``
instance.  This check deliberately validates the selected profile instead of
assuming that every Radeon has the same FP8 MoE capabilities.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


_GPU_RE = re.compile(r"^\s*Name:\s*(gfx\d+)\s*$", re.MULTILINE)
_MARKETING_RE = re.compile(r"^\s*Marketing Name:\s*(.+?)\s*$", re.MULTILINE)


def read_model_config(model_dir: Path) -> dict[str, Any]:
    config_path = model_dir / "config.json"
    if not config_path.is_file():
        return {"config_present": False}
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"config_present": False, "error": f"{type(exc).__name__}: {exc}"}
    return {
        "config_present": True,
        "model_type": payload.get("model_type"),
        "architectures": payload.get("architectures", []),
        "torch_dtype": payload.get("torch_dtype"),
    }


def parse_rocminfo(text: str) -> dict[str, Any]:
    """Extract the first accelerator identity from ``rocminfo`` output."""

    gpu_match = _GPU_RE.search(text)
    marketing_names = [m.group(1).strip() for m in _MARKETING_RE.finditer(text)]
    marketing = None
    if gpu_match:
        tail = text[gpu_match.start() :]
        adjacent = _MARKETING_RE.search(tail)
        if adjacent:
            marketing = adjacent.group(1).strip()
    if not marketing:
        marketing = marketing_names[-1] if marketing_names else None
    return {
        "gpu_arch": gpu_match.group(1) if gpu_match else None,
        "marketing_name": marketing,
        "has_gpu_agent": gpu_match is not None,
    }


def read_gpu_info() -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["rocminfo"], capture_output=True, text=True, timeout=20, check=False
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return {"has_gpu_agent": False, "error": str(exc)}
    info = parse_rocminfo(result.stdout + "\n" + result.stderr)
    if result.returncode != 0:
        info["rocminfo_returncode"] = result.returncode
    return info


def runtime_capability() -> dict[str, Any]:
    """Read BF16 support from the installed ROCm PyTorch runtime."""

    try:
        import torch  # type: ignore
        import vllm  # type: ignore

        return {
            "torch_version": torch.__version__,
            "vllm_version": getattr(vllm, "__version__", None),
            "bf16_supported": bool(torch.cuda.is_bf16_supported()),
        }
    except Exception as exc:  # pragma: no cover - depends on cloud runtime
        return {"bf16_supported": False, "error": f"{type(exc).__name__}: {exc}"}


def run_preflight(
    model_dir: Path,
    *,
    required_arch: str = "gfx1100",
    required_model_type: str = "qwen3",
) -> tuple[dict[str, Any], bool]:
    gpu = read_gpu_info()
    runtime = runtime_capability()
    model = read_model_config(model_dir)
    model_type = str(model.get("model_type") or "")
    architecture = " ".join(str(item) for item in model.get("architectures", []))
    report: dict[str, Any] = {
        "model_dir": str(model_dir),
        "model_present": model_dir.is_dir(),
        "gpu": gpu,
        "runtime": runtime,
        "model": model,
        "profile": {
            "required_gpu_arch": required_arch,
            "required_model_type": required_model_type,
        },
    }
    accepted = bool(
        report["model_present"]
        and gpu.get("has_gpu_agent")
        and (not required_arch or gpu.get("gpu_arch") == required_arch)
        and (not required_model_type or model_type == required_model_type or required_model_type in architecture.lower())
        and model.get("config_present")
        and runtime.get("bf16_supported")
    )
    report["accepted"] = accepted
    return report, accepted


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", required=True, type=Path)
    parser.add_argument("--required-gpu-arch", default="gfx1100")
    parser.add_argument("--required-model-type", default="qwen3")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report, accepted = run_preflight(
        args.model_dir,
        required_arch=args.required_gpu_arch,
        required_model_type=args.required_model_type,
    )
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    if not accepted:
        print(
            "BF16/Qwen3 preflight rejected this instance; do not start vLLM or SWE-bench.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
