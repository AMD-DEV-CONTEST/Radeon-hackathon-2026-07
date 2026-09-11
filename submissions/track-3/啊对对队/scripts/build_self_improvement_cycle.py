"""Build a fail-closed replay/promotion plan from a rollout summary."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from parcel_sorter.self_improvement import (
    promotion_gate,
    write_failure_replay_manifest,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", required=True, type=Path)
    parser.add_argument("--output-manifest", required=True, type=Path)
    parser.add_argument("--candidate-summary", type=Path)
    parser.add_argument("--holdout-episode", action="append", type=int, default=[])
    parser.add_argument("--force-threshold-n", type=float, default=35.0)
    parser.add_argument("--target-success-rate", type=float, default=0.80)
    parser.add_argument("--min-delta", type=float, default=0.02)
    args = parser.parse_args()
    write_failure_replay_manifest(
        args.summary,
        args.output_manifest,
        holdout_episode_ids=args.holdout_episode,
        force_threshold_n=args.force_threshold_n,
    )
    if args.candidate_summary is not None:
        gate = promotion_gate(
            json.loads(args.summary.read_text(encoding="utf-8")),
            json.loads(args.candidate_summary.read_text(encoding="utf-8")),
            target_success_rate=args.target_success_rate,
            min_delta=args.min_delta,
        )
        gate_path = args.output_manifest.with_name("promotion_gate.json")
        gate_path.write_text(json.dumps(gate, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(gate, ensure_ascii=False))
    print(args.output_manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
