#!/usr/bin/env python3
"""Validate the exact 50-episode task7 Q-training rollout set."""

from __future__ import annotations

import argparse
import hashlib
import json
import pickle
from pathlib import Path

import numpy as np
import torch


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("pickle_dir", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    paths = sorted(args.pickle_dir.glob("*.pkl"))
    if len(paths) != 50:
        raise ValueError(f"expected exactly 50 pickle episodes, found {len(paths)}")

    records = []
    states = set()
    successes = 0
    total_steps = 0
    all_actions_finite = True
    digest = hashlib.sha256()
    for path in paths:
        with path.open("rb") as handle:
            episode = pickle.load(handle)
        metadata = episode["qvgm_metadata"]
        state = int(metadata["task_reset_state_id"])
        expected_global = 350 + state
        if metadata["suite"] != "libero_spatial" or int(metadata["task_id"]) != 7:
            raise ValueError(f"wrong suite/task metadata in {path}")
        if int(metadata["global_reset_state_id"]) != expected_global:
            raise ValueError(f"wrong global reset ID in {path}")
        if int(metadata["repeat_id"]) != 0 or int(metadata["seed"]) != 3000:
            raise ValueError(f"wrong repeat/seed in {path}")
        if int(metadata["action_steps_per_replan"]) != 5:
            raise ValueError(f"wrong action/replan count in {path}")
        if state in states:
            raise ValueError(f"duplicate local reset state {state}")
        states.add(state)

        length = len(episode["actions"])
        expected_lengths = {
            "observations": length + 1,
            "rewards": length + 1,
            "terminated": length + 1,
            "truncated": length + 1,
            "infos": length + 1,
        }
        for key, expected in expected_lengths.items():
            if len(episode[key]) != expected:
                raise ValueError(f"{path}: {key} has {len(episode[key])}, expected {expected}")
        actions = torch.stack([torch.as_tensor(action) for action in episode["actions"]])
        if actions.shape != (length, 7):
            raise ValueError(f"{path}: unexpected action shape {tuple(actions.shape)}")
        finite = bool(torch.isfinite(actions).all())
        all_actions_finite &= finite
        observation = episode["observations"][0]
        if np.asarray(observation["states"]).shape != (8,):
            raise ValueError(f"{path}: unexpected state shape")
        for key in ("main_images", "wrist_images"):
            image = np.asarray(observation[key])
            if image.ndim != 3 or image.shape[-1] != 3:
                raise ValueError(f"{path}: malformed {key} shape {image.shape}")
        if observation["task_descriptions"] != (
            "pick up the black bowl on the stove and place it on the plate"
        ):
            raise ValueError(f"{path}: unexpected task instruction")

        file_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        digest.update(f"{path.name}:{file_sha256}\n".encode())
        success = bool(episode["success"])
        successes += int(success)
        total_steps += length
        records.append(
            {
                "file": str(path.resolve()),
                "file_size": path.stat().st_size,
                "sha256": file_sha256,
                "state": state,
                "global_state": expected_global,
                "success": success,
                "steps": length,
                "actions_finite": finite,
            }
        )

    if states != set(range(50)):
        raise ValueError(f"state coverage mismatch: {sorted(states)}")
    failures = 50 - successes
    if successes == 0 or failures == 0:
        raise ValueError("Q training requires both successful and failed rollouts")
    summary = {
        "schema_version": 1,
        "pickle_dir": str(args.pickle_dir.resolve()),
        "episodes": 50,
        "states": list(range(50)),
        "successes": successes,
        "failures": failures,
        "success_rate": successes / 50,
        "total_steps": total_steps,
        "mean_steps": total_steps / 50,
        "all_actions_finite": all_actions_finite,
        "dataset_identity_sha256": digest.hexdigest(),
        "records": sorted(records, key=lambda record: record["state"]),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({key: value for key, value in summary.items() if key != "records"}, indent=2))


if __name__ == "__main__":
    main()
