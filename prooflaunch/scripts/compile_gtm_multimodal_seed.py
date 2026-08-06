#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from prooflaunch_remix.gtm_multimodal_seed_compiler import compile_multimodal_seed_files


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--admission",
        default=str(ROOT / "artifacts/aug3-gtm-employee-mission-v14/local-text-challenger/multimodal-production-admission.json"),
    )
    parser.add_argument(
        "--bindings",
        default=str(ROOT / "config/comfyui_execution_bindings_v1.json"),
    )
    parser.add_argument(
        "--gpu-handoff",
        default=str(ROOT / "artifacts/comfyui-gpu-handoff-20260801/handoff.json"),
    )
    parser.add_argument(
        "--output",
        default=str(ROOT / "artifacts/aug3-gtm-employee-mission-v14/multimodal-seed-compilation.json"),
    )
    args = parser.parse_args()
    receipt = compile_multimodal_seed_files(
        args.admission,
        args.bindings,
        args.gpu_handoff,
        args.output,
    )
    print(json.dumps({
        "output": str(Path(args.output).expanduser().resolve()),
        "status": receipt["status"],
        "stage_count": receipt["stage_count"],
        "content_sha256": receipt["content_sha256"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
