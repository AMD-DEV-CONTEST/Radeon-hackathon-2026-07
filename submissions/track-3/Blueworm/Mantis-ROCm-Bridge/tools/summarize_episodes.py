#!/usr/bin/env python3
"""Validate an episode JSONL file and print a promotion summary."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mantis_rocm_bridge.contracts import load_json, validate_task_contract
from mantis_rocm_bridge.evidence import (
    evaluate_promotion,
    load_episode_jsonl,
    summarize_episodes,
    validate_episodes,
)


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("episodes", type=Path)
    parser.add_argument("--task", type=Path, default=ROOT / "configs/task-pack-v1.json")
    parser.add_argument("--gate", choices=["g1_smoke", "g2_early", "g3_compare", "g4_confirm"])
    args = parser.parse_args()
    task = load_json(args.task)
    validate_task_contract(task)
    evaluation = task["evaluation"]
    expected_seeds = evaluation["seed_sets"][args.gate] if args.gate else None
    episodes = validate_episodes(
        load_episode_jsonl(args.episodes),
        evaluation["failure_taxonomy"],
        expected_seeds,
    )
    summary = summarize_episodes(episodes)
    if args.gate in evaluation["promotion_rules"]:
        summary["promotion"] = evaluate_promotion(
            summary, evaluation["promotion_rules"][args.gate]
        )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

