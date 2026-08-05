#!/usr/bin/env python3
"""Convert the official 50-demo LIBERO Spatial task 7 HDF5 to LeRobot v3.0.

The output is written through LeRobot's public ``LeRobotDataset`` writer so it
can be consumed directly by ``lerobot-train`` without a QVGM dataset adapter.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import h5py
import numpy as np

from lerobot.datasets.lerobot_dataset import LeRobotDataset


TASK = "pick up the black bowl on the stove and place it on the plate"
EXPECTED_SHA256 = "1fcb3990cf9fd6185f56531cc9f6dec0a77a59bfa0c7f39dff95b7e43cf6aeaa"
EXPECTED_EPISODES = 50
EXPECTED_FRAMES = 7111

FEATURES = {
    "observation.images.agentview": {
        "dtype": "image",
        "shape": (128, 128, 3),
        "names": ["height", "width", "channels"],
    },
    "observation.images.wrist": {
        "dtype": "image",
        "shape": (128, 128, 3),
        "names": ["height", "width", "channels"],
    },
    "observation.state": {
        "dtype": "float32",
        "shape": (8,),
        "names": ["x", "y", "z", "rx", "ry", "rz", "rw", "gripper"],
    },
    "action": {
        "dtype": "float32",
        "shape": (7,),
        "names": ["x", "y", "z", "roll", "pitch", "yaw", "gripper"],
    },
}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def demo_names(handle: h5py.File) -> list[str]:
    return sorted(handle["data"], key=lambda name: int(name.rsplit("_", 1)[-1]))


def rotate_libero_image(image: np.ndarray) -> np.ndarray:
    """Match the dataset-oriented pixels used by SmolVLA LIBERO rollouts."""
    return np.ascontiguousarray(image[::-1, ::-1])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repo-id", default="local/libero_spatial_task7_stove_50")
    parser.add_argument(
        "--episode-indices",
        help="optional comma/range subset such as 0-9 or 0,2,4; defaults to all 50",
    )
    parser.add_argument("--skip-sha256", action="store_true")
    args = parser.parse_args()

    source = args.input.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing output: {output}")
    if not args.skip_sha256:
        actual_sha256 = file_sha256(source)
        if actual_sha256 != EXPECTED_SHA256:
            raise ValueError(f"HDF5 SHA256 mismatch: {actual_sha256}")

    with h5py.File(source, "r") as handle:
        names = demo_names(handle)
        frame_count = sum(int(handle["data"][name]["actions"].shape[0]) for name in names)
        if len(names) != EXPECTED_EPISODES or frame_count != EXPECTED_FRAMES:
            raise ValueError(
                f"expected {EXPECTED_EPISODES} demos/{EXPECTED_FRAMES} frames, "
                f"found {len(names)} demos/{frame_count} frames"
            )

        if args.episode_indices:
            selected_indices: set[int] = set()
            for item in args.episode_indices.split(","):
                item = item.strip()
                if "-" in item:
                    start, end = (int(value) for value in item.split("-", 1))
                    selected_indices.update(range(start, end + 1))
                elif item:
                    selected_indices.add(int(item))
            if not selected_indices or min(selected_indices) < 0 or max(selected_indices) >= len(names):
                raise ValueError(f"invalid episode indices: {args.episode_indices}")
            names = [name for index, name in enumerate(names) if index in selected_indices]

        dataset = LeRobotDataset.create(
            repo_id=args.repo_id,
            root=output,
            robot_type="panda",
            fps=10,
            features=FEATURES,
            use_videos=False,
            image_writer_threads=8,
        )
        for episode_index, name in enumerate(names):
            demo = handle["data"][name]
            obs = demo["obs"]
            actions = np.asarray(demo["actions"], dtype=np.float32)
            for frame_index, action in enumerate(actions):
                state = np.concatenate(
                    (
                        obs["ee_pos"][frame_index],
                        obs["ee_ori"][frame_index],
                        obs["gripper_states"][frame_index],
                    )
                ).astype(np.float32)
                dataset.add_frame(
                    {
                        "observation.images.agentview": rotate_libero_image(
                            np.asarray(obs["agentview_rgb"][frame_index])
                        ),
                        "observation.images.wrist": rotate_libero_image(
                            np.asarray(obs["eye_in_hand_rgb"][frame_index])
                        ),
                        "observation.state": state,
                        "action": action,
                        "task": TASK,
                    }
                )
            dataset.save_episode()
            print(f"converted episode {episode_index + 1}/{len(names)} ({len(actions)} frames)", flush=True)
        dataset.finalize()

    print(f"LeRobot v3.0 dataset written to {output}")


if __name__ == "__main__":
    main()
