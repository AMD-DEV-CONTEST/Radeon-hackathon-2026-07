"""Validate the LeRobot dataset protocol used by the SmolVLA pipeline."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


REQUIRED_FEATURES = {
    "observation.state",
    "action",
    "observation.images.up",
    "observation.images.side",
}


def _import_lerobot():
    try:
        from lerobot.common.datasets.lerobot_dataset import (
            LeRobotDataset,
            LeRobotDatasetMetadata,
        )
    except ImportError:
        from lerobot.datasets.lerobot_dataset import (
            LeRobotDataset,
            LeRobotDatasetMetadata,
        )
    return LeRobotDataset, LeRobotDatasetMetadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    LeRobotDataset, LeRobotDatasetMetadata = _import_lerobot()
    metadata = LeRobotDatasetMetadata(args.dataset_id)
    features = metadata.features
    missing = sorted(REQUIRED_FEATURES - set(features))
    if missing:
        raise RuntimeError(f"missing required features: {missing}")

    state_shape = tuple(features["observation.state"]["shape"])
    action_shape = tuple(features["action"]["shape"])
    if state_shape != action_shape:
        raise RuntimeError(
            f"state/action dimensions differ: state={state_shape}, action={action_shape}"
        )
    if state_shape != (9,):
        raise RuntimeError(f"expected 9D Franka state/action, got {state_shape}")

    dataset = LeRobotDataset(args.dataset_id)
    if dataset.num_episodes < 1 or len(dataset) < dataset.num_episodes:
        raise RuntimeError("dataset has no valid episodes or frames")
    sample = dataset[0]
    missing_sample = sorted(key for key in REQUIRED_FEATURES if key not in sample)
    if missing_sample:
        raise RuntimeError(f"sample is missing required fields: {missing_sample}")

    summary = {
        "dataset_id": args.dataset_id,
        "episodes": int(metadata.total_episodes),
        "frames": int(metadata.total_frames),
        "fps": int(metadata.fps),
        "features": features,
        "sample_keys": sorted(sample.keys()),
        "protocol": "valid",
    }
    text = json.dumps(summary, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
