#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_multimodal_breakout_factory import compile_multimodal_breakout_factory


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DISTILLATION = ROOT / "evidence/v10/gtm-named-capability-distillation-v1.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compile a model-ready multimodal zero-budget GTM factory from an owner brief.")
    parser.add_argument("--brief", required=True, type=Path, help="Path to the owner brief JSON")
    parser.add_argument("--output", required=True, type=Path, help="Path for the sealed factory JSON")
    parser.add_argument("--distillation", type=Path, default=DEFAULT_DISTILLATION)
    parser.add_argument("--learning-memory", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    brief = json.loads(args.brief.read_text(encoding="utf-8"))
    distillation = json.loads(args.distillation.read_text(encoding="utf-8"))
    memory = json.loads(args.learning_memory.read_text(encoding="utf-8")) if args.learning_memory else None
    payload = compile_multimodal_breakout_factory(
        brief, named_capability_distillation=distillation, learning_memory=memory
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(args.output, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "output": str(args.output), "business_model": payload["brief"]["business_model"],
        "platform": payload["brief"]["platform"], "zero_budget_mode": payload["zero_budget_mode"],
        "candidate_campaign_count": len(payload["candidate_campaigns"]),
        "model_ready_work_order_count": payload["model_call_budget"]["total"],
        "content_sha256": payload["content_sha256"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
