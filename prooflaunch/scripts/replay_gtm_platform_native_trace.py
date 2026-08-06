#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

from prooflaunch_remix.files import atomic_write_text  # noqa: E402
from prooflaunch_remix.gtm_platform_native_challenger import (  # noqa: E402
    compile_platform_native_receipt,
    verify_platform_native_challenger_plan,
)


def _inside_project(value: str) -> Path:
    path = Path(value).expanduser().resolve()
    try:
        path.relative_to(ROOT.resolve())
    except ValueError as error:
        raise argparse.ArgumentTypeError("path must remain inside the project root") from error
    return path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Replay a private platform-native raw trace through the current deterministic Harness."
    )
    parser.add_argument("--plan", required=True, type=_inside_project)
    parser.add_argument("--trace", required=True, type=_inside_project)
    parser.add_argument("--output", required=True, type=_inside_project)
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    trace = json.loads(args.trace.read_text(encoding="utf-8"))
    verify_platform_native_challenger_plan(plan)
    if trace.get("plan_sha256") != plan.get("content_sha256"):
        raise SystemExit("private trace does not match the frozen plan")
    attempts = trace.get("attempts_by_surface")
    if not isinstance(attempts, dict):
        raise SystemExit("private trace has no attempt map")
    receipt = compile_platform_native_receipt(
        plan=plan,
        model={
            "provider": "mlx_local_replay",
            "device_family": "Apple Metal",
            "model_id": trace.get("model_id"),
            "model_revision": trace.get("model_revision"),
            "model_manifest_sha256": trace.get("model_manifest_sha256"),
            "network_download_performed": False,
            "cloud_api_calls": 0,
            "raw_trace_replayed_without_new_model_calls": True,
        },
        attempts_by_surface=attempts,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        args.output,
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "status": receipt["status"],
                "accepted_surface_count": receipt["accepted_surface_count"],
                "content_sha256": receipt["content_sha256"],
                "new_model_calls": 0,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if receipt["accepted_surface_count"] == 13 else 2


if __name__ == "__main__":
    raise SystemExit(main())
