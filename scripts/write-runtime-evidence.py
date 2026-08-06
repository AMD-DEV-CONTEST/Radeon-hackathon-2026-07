#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from incident_commander.gpu_benchmark import collect_accelerator_info


def main() -> None:
    parser = argparse.ArgumentParser(description="Write sanitized Radeon runtime evidence")
    parser.add_argument("--models-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    with urllib.request.urlopen(args.models_url, timeout=10) as response:
        models = json.load(response)
    model_ids = {str(item.get("id")) for item in models.get("data", []) if isinstance(item, dict)}
    if args.model not in model_ids:
        raise SystemExit(f"served model {args.model!r} was not returned by {args.models_url}")

    gpu = collect_accelerator_info()
    required = (gpu.get("measured"), gpu.get("architecture"), gpu.get("vram_mb"), gpu.get("compute_units"))
    if not all(required):
        raise SystemExit("Radeon hardware discovery did not return the required public-safe fields")
    try:
        vllm_version = version("vllm")
    except PackageNotFoundError as exc:
        raise SystemExit("vLLM package metadata is unavailable") from exc

    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model": args.model,
        "rocm_version": gpu["rocm_version"],
        "gpu_architecture": gpu["architecture"],
        "vram_mb": gpu["vram_mb"],
        "compute_units": gpu["compute_units"],
        "vllm_version": vllm_version,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(args.output)
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
