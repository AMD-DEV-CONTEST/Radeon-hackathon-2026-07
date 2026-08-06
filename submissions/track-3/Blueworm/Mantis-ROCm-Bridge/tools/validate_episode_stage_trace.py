#!/usr/bin/env python3
"""Validate an ordered task-stage trace and emit a strict episode receipt."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mantis_rocm_bridge.contracts import ContractError, load_json
from mantis_rocm_bridge.episode_state import replay_stage_trace


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("trace", type=Path)
    parser.add_argument(
        "--task-contract",
        type=Path,
        default=ROOT / "configs/task-pack-v1.json",
    )
    parser.add_argument("--claim-g1", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    trace = load_json(args.trace)
    receipt = replay_stage_trace(
        load_json(args.task_contract),
        trace,
        g1_claim=args.claim_g1,
    )
    rendered = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        if args.output.exists():
            parser.error(f"refusing to overwrite output: {args.output}")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if receipt["success"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
