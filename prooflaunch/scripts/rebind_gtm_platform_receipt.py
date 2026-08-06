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
    CREATIVE_FIELDS,
    compile_platform_native_receipt,
    verify_platform_native_challenger_plan,
    verify_platform_native_receipt,
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
        description="Rebind accepted creative text to an equivalent updated plan without new inference."
    )
    parser.add_argument("--source-plan", required=True, type=_inside_project)
    parser.add_argument("--source-receipt", required=True, type=_inside_project)
    parser.add_argument("--target-plan", required=True, type=_inside_project)
    parser.add_argument("--output", required=True, type=_inside_project)
    args = parser.parse_args()
    source_plan = json.loads(args.source_plan.read_text(encoding="utf-8"))
    source_receipt = json.loads(args.source_receipt.read_text(encoding="utf-8"))
    target_plan = json.loads(args.target_plan.read_text(encoding="utf-8"))
    verify_platform_native_challenger_plan(source_plan)
    verify_platform_native_receipt(source_receipt, plan=source_plan)
    verify_platform_native_challenger_plan(target_plan)
    if (
        source_plan["brief"] != target_plan["brief"]
        or source_plan["business_model"] != target_plan["business_model"]
        or source_receipt["accepted_surface_count"] != 13
    ):
        raise SystemExit("source and target plans are not content-equivalent")
    attempts = {
        row["surface_id"]: [
            {
                "raw_output": json.dumps(
                    {field: row[field] for field in CREATIVE_FIELDS},
                    ensure_ascii=False,
                ),
                "source": "deterministic_accepted_candidate_rebind",
                "elapsed_seconds": 0,
                "generated_token_count": 0,
            }
        ]
        for row in source_receipt["accepted_candidates"]
    }
    receipt = compile_platform_native_receipt(
        plan=target_plan,
        model={
            "provider": "deterministic_candidate_rebind",
            "source_plan_sha256": source_plan["content_sha256"],
            "source_receipt_sha256": source_receipt["content_sha256"],
            "new_model_calls": 0,
            "network_download_performed": False,
            "external_publish_executed": False,
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
                "output": str(args.output.relative_to(ROOT)),
                "accepted_surface_count": receipt["accepted_surface_count"],
                "new_model_calls": 0,
                "content_sha256": receipt["content_sha256"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if receipt["accepted_surface_count"] == 13 else 2


if __name__ == "__main__":
    raise SystemExit(main())
