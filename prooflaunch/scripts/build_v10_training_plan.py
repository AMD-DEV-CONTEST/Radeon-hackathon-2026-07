#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.v10_training import default_v10_training_plan


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the fail-closed multi-GPU Radeon V10 training plan"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "config" / "cortex_x_v10_training_plan.json",
    )
    args = parser.parse_args()
    plan = default_v10_training_plan()
    payload = plan.to_dict()
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    payload["contract_sha256"] = hashlib.sha256(canonical).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        args.output,
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
    )
    print(
        json.dumps(
            {
                "schema": plan.schema,
                "output": str(args.output),
                "stage_count": len(plan.stages),
                "minimum_world_size": plan.minimum_world_size,
                "preferred_world_size": plan.preferred_world_size,
                "preferred_strategy": plan.preferred_strategy,
                "memory_fallback_strategy": plan.memory_fallback_strategy,
                "single_gpu_may_promote": plan.single_gpu_may_promote,
                "maximum_total_gpu_hours": plan.maximum_total_gpu_hours,
                "contract_sha256": payload["contract_sha256"],
                "status": "planned_not_executed",
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
