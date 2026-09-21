#!/usr/bin/env python3
"""Validate the durable artifacts of a native LeRobot training checkpoint."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from safetensors import safe_open


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("checkpoint", type=Path)
    parser.add_argument("--expected-step", type=int, required=True)
    return parser.parse_args()


def require_file(path: Path) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        raise FileNotFoundError(f"missing or empty checkpoint artifact: {path}")


def safetensors_inventory(path: Path) -> dict[str, list[int]]:
    require_file(path)
    with safe_open(path, framework="pt", device="cpu") as handle:
        keys = list(handle.keys())
        if not keys:
            raise ValueError(f"safetensors file has no tensors: {path}")
        return {key: list(handle.get_slice(key).get_shape()) for key in keys}


def main() -> None:
    args = parse_args()
    checkpoint = args.checkpoint.resolve()
    model = checkpoint / "pretrained_model"
    state = checkpoint / "training_state"

    required = [
        model / "config.json",
        model / "model.safetensors",
        model / "policy_preprocessor.json",
        model / "policy_preprocessor_step_5_normalizer_processor.safetensors",
        model / "policy_postprocessor.json",
        model / "policy_postprocessor_step_0_unnormalizer_processor.safetensors",
        model / "train_config.json",
        state / "optimizer_param_groups.json",
        state / "optimizer_state.safetensors",
        state / "rng_state.safetensors",
        state / "scheduler_state.json",
        state / "training_step.json",
    ]
    for path in required:
        require_file(path)

    training_step = json.loads((state / "training_step.json").read_text())
    actual_step = training_step.get("step")
    if actual_step != args.expected_step:
        raise ValueError(f"training step is {actual_step}, expected {args.expected_step}")

    config = json.loads((model / "config.json").read_text())
    if config.get("chunk_size") != 50:
        raise ValueError(f"unexpected action chunk size: {config.get('chunk_size')}")
    if config.get("n_action_steps") != 50:
        raise ValueError(f"unexpected action horizon: {config.get('n_action_steps')}")

    inventories = {
        "model": safetensors_inventory(model / "model.safetensors"),
        "preprocessor": safetensors_inventory(
            model / "policy_preprocessor_step_5_normalizer_processor.safetensors"
        ),
        "postprocessor": safetensors_inventory(
            model / "policy_postprocessor_step_0_unnormalizer_processor.safetensors"
        ),
        "optimizer": safetensors_inventory(state / "optimizer_state.safetensors"),
        "rng": safetensors_inventory(state / "rng_state.safetensors"),
    }

    result = {
        "checkpoint": str(checkpoint),
        "step": actual_step,
        "files": {str(path.relative_to(checkpoint)): path.stat().st_size for path in required},
        "tensor_counts": {name: len(items) for name, items in inventories.items()},
        "normalizer_shapes": inventories["preprocessor"],
        "unnormalizer_shapes": inventories["postprocessor"],
    }
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
