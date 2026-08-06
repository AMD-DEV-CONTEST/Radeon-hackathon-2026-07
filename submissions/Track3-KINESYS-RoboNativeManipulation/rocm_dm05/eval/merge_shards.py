#!/usr/bin/env python3
"""Merge disjoint BiGym evaluation shard summaries."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-seeds", required=True, nargs="+", type=int)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("summaries", nargs="+", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    shards = [json.loads(path.read_text(encoding="utf-8")) for path in args.summaries]
    episodes = sorted(
        [episode for shard in shards for episode in shard["episodes"]],
        key=lambda episode: episode["seed"],
    )
    seeds = [episode["seed"] for episode in episodes]
    expected_seeds = sorted(args.expected_seeds)
    if seeds != expected_seeds:
        raise ValueError(f"Unexpected or incomplete seed set: {seeds}")
    inference_calls = sum(item["inference_calls"] for item in episodes)
    inference_seconds = sum(item["inference_seconds"] for item in episodes)
    successes = sum(item["success"] for item in episodes)
    metadata_keys = (
        "model_path",
        "visual_shell_profile",
        "visual_shell_strict",
        "task",
        "prompt",
        "control_frequency",
        "policy_frequency",
        "chunk_size",
        "diffusion_steps",
        "execute_actions",
        "max_policy_steps",
        "model_max_length",
        "use_lora_wrapper",
        "reuse_kv_workspace",
        "state_definition",
    )
    result = {}
    for key in metadata_keys:
        values = [shard.get(key) for shard in shards]
        if any(value != values[0] for value in values[1:]):
            raise ValueError(f"Shard metadata mismatch for {key}: {values}")
        if key in shards[0]:
            result[key] = values[0]
    result.update(
        {
            "episodes": episodes,
            "expected_seeds": expected_seeds,
            "successes": successes,
            "success_rate": successes / len(episodes),
            "mean_success_policy_steps": (
                sum(item["policy_steps"] for item in episodes if item["success"])
                / max(successes, 1)
            ),
            "mean_inference_ms": 1000.0
            * inference_seconds
            / max(inference_calls, 1),
            "failed_seeds": [
                item["seed"] for item in episodes if not item["success"]
            ],
            "shard_summaries": [str(path) for path in args.summaries],
        }
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
