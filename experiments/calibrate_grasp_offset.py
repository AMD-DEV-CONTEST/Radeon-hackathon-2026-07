"""Estimate a robust held-object offset from successful expert trajectories."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from data import RobotInteractionDataset


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=Path("datasets/expert_visual_stage34_marker"))
    parser.add_argument("--output", type=Path, default=Path("checkpoints/color_servo/grasp_offset.json"))
    parser.add_argument("--minimum-object-height", type=float, default=0.07)
    parser.add_argument("--maximum-eef-object-distance", type=float, default=0.12)
    args = parser.parse_args()
    dataset = RobotInteractionDataset(args.dataset, modalities=("state",))
    offsets: list[np.ndarray] = []
    for index in range(len(dataset)):
        state = dataset[index]["state"].numpy()
        eef_position, object_position = state[18:21], state[25:28]
        offset = object_position - eef_position
        if object_position[2] >= args.minimum_object_height and np.linalg.norm(offset) <= args.maximum_eef_object_distance:
            offsets.append(offset)
    dataset.close()
    if len(offsets) < 10:
        raise RuntimeError(f"only {len(offsets)} held-object samples found; cannot calibrate grasp offset")
    values = np.stack(offsets)
    median = np.median(values, axis=0)
    mad = np.median(np.abs(values - median), axis=0)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({
        "dataset": str(args.dataset), "held_samples": len(values),
        "median_offset": median.tolist(), "median_absolute_deviation": mad.tolist(),
    }, indent=2) + "\n")
    print({"grasp_offset": median.tolist(), "held_samples": len(values), "mad": mad.tolist()})


if __name__ == "__main__":
    main()
