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
from prooflaunch_remix.gtm_platform_generation_quality import (  # noqa: E402
    compile_platform_generation_quality_audit,
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
        description="Compile the deterministic pre-human quality gate for one 13-surface receipt."
    )
    parser.add_argument("--plan", required=True, type=_inside_project)
    parser.add_argument("--receipt", required=True, type=_inside_project)
    parser.add_argument("--output", required=True, type=_inside_project)
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    receipt = json.loads(args.receipt.read_text(encoding="utf-8"))
    audit = compile_platform_generation_quality_audit(plan=plan, receipt=receipt)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        args.output,
        json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    print(
        json.dumps(
            {
                "output": str(args.output.relative_to(ROOT)),
                "pre_human_quality_pass_count": audit["pre_human_quality_pass_count"],
                "blocked_count": audit["blocked_count"],
                "human_craft_review_completed_count": 0,
                "production_effect_observed": False,
                "content_sha256": audit["content_sha256"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if audit["pre_human_quality_pass_count"] == 13 else 2


if __name__ == "__main__":
    raise SystemExit(main())
