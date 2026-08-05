#!/usr/bin/env python3
"""Strict validation and summary for controlled task-7 critic rollouts."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import numpy as np

from smolvla_qvgm_rlinf.data.collection_plan import make_plan, parse_states
from smolvla_qvgm_rlinf.data.collected_episode_adapter import load_collected_episode


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pickle-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--states", default="0-39")
    parser.add_argument("--failure-states", default="0,3,7,9,13,15,17,18,24,31,36,39,41")
    args = parser.parse_args()
    expected = make_plan(parse_states(args.states), set(parse_states(args.failure_states)))
    expected_keys = {item.key for item in expected}
    paths = sorted(args.pickle_dir.glob("*.pkl"))
    rows = []
    keys = set()
    seeds = set()
    outcomes_by_state: dict[int, set[bool]] = defaultdict(set)
    for path in paths:
        episode = load_collected_episode(path)
        metadata = episode["qvgm_metadata"]
        key = metadata["collection_key"]
        if key in keys:
            raise RuntimeError(f"duplicate collection key: {key}")
        keys.add(key)
        sigma = float(metadata["sigma"])
        applied_count = 0
        previous_seed = None
        previous_offset = None
        for action, info in zip(episode["actions"], episode["infos"][1:], strict=True):
            perturbation = np.asarray(info["action_perturbation"], dtype=np.float32)
            base = np.asarray(info["base_executed_action"], dtype=np.float32)
            executed = np.asarray(action, dtype=np.float32)
            if perturbation.shape != (7,) or base.shape != (7,) or executed.shape != (7,):
                raise RuntimeError(f"invalid action metadata shape in {path}")
            if perturbation[-1] != 0:
                raise RuntimeError(f"gripper perturbation must be zero in {path}")
            if not np.allclose(executed, np.clip(base + perturbation, -1, 1), atol=1e-6):
                raise RuntimeError(f"executed action cannot be reconstructed in {path}")
            applied = bool(info["perturbation_applied"])
            applied_count += int(applied)
            if not applied and np.any(perturbation != 0):
                raise RuntimeError(f"nonzero perturbation marked inactive in {path}")
            seed = int(info["initial_noise_seed"])
            chunk_offset = info.get("chunk_offset")
            if chunk_offset is None or int(chunk_offset) == 0:
                if seed in seeds:
                    raise RuntimeError(f"duplicate flow query seed: {seed}")
                seeds.add(seed)
            else:
                chunk_offset = int(chunk_offset)
                if seed != previous_seed or chunk_offset != int(previous_offset) + 1:
                    raise RuntimeError(f"invalid within-chunk seed/offset sequence in {path}")
            previous_seed = seed
            previous_offset = int(chunk_offset) if chunk_offset is not None else 0
        state = int(metadata["state_id"])
        success = bool(episode["success"])
        outcomes_by_state[state].add(success)
        rows.append(
            {
                "key": key,
                "state": state,
                "sigma": sigma,
                "success": success,
                "steps": len(episode["actions"]),
                "perturbed_steps": applied_count,
                "path": str(path.resolve()),
            }
        )
    missing = sorted(expected_keys - keys)
    unexpected = sorted(keys - expected_keys)
    if missing or unexpected:
        raise RuntimeError(f"collection plan mismatch: missing={missing}, unexpected={unexpected}")

    sigmas = sorted({row["sigma"] for row in rows})
    summary = {
        "schema_version": 1,
        "pickle_dir": str(args.pickle_dir.resolve()),
        "episodes": len(rows),
        "transitions": sum(row["steps"] for row in rows),
        "successes": sum(row["success"] for row in rows),
        "failures": sum(not row["success"] for row in rows),
        "states": sorted({row["state"] for row in rows}),
        "state_count": len({row["state"] for row in rows}),
        "unique_flow_seeds": len(seeds),
        "unique_flow_query_seeds": len(seeds),
        "perturbed_steps": sum(row["perturbed_steps"] for row in rows),
        "outcome_flip_states": sorted(
            state for state, outcomes in outcomes_by_state.items() if len(outcomes) > 1
        ),
        "by_sigma": {
            str(sigma): {
                "episodes": sum(row["sigma"] == sigma for row in rows),
                "successes": sum(row["sigma"] == sigma and row["success"] for row in rows),
                "failures": sum(row["sigma"] == sigma and not row["success"] for row in rows),
                "transitions": sum(row["steps"] for row in rows if row["sigma"] == sigma),
            }
            for sigma in sigmas
        },
        "plan_complete": not missing and not unexpected,
        "records": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({key: value for key, value in summary.items() if key != "records"}, indent=2))


if __name__ == "__main__":
    main()
