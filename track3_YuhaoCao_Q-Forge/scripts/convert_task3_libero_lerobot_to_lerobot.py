#!/usr/bin/env python3
"""Convert LIBERO Spatial task 3 (cookie box) episodes from the public
``libero_spatial_image`` LeRobot v3.0 dataset into a native LeRobot v3.0
dataset matching the task-7 20D layout (128x128 agentview/wrist, images dir).

The public conversion stores dataset-oriented (180-degree rotated) pixels, so
frames are used verbatim (only downscaled to 128x128).
"""

from __future__ import annotations

import argparse
import io
import os
from pathlib import Path

import numpy as np
from PIL import Image

from lerobot.datasets.lerobot_dataset import LeRobotDataset

from smolvla_qvgm_rlinf.data.libero_lerobot import (
    AGENTVIEW_COLUMN,
    WRIST_COLUMN,
    _read_episode_index,
)

TASK = "pick up the black bowl on the cookie box and place it on the plate"
DEFAULT_SOURCE = Path(
    os.environ.get("LIBERO_SPATIAL_IMAGE_ROOT", "data/libero_spatial_image")
)

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

COLUMNS = [
    AGENTVIEW_COLUMN,
    WRIST_COLUMN,
    "observation.state",
    "action",
    "episode_index",
    "frame_index",
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source",
        type=Path,
        default=DEFAULT_SOURCE,
        help="Root of the public libero_spatial_image LeRobot v3.0 dataset.",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repo-id", default="local/libero_spatial_task3_cookiebox_20d")
    parser.add_argument("--episodes", default="0-19")
    args = parser.parse_args()

    root = args.source.resolve()
    records = [r for r in _read_episode_index(root) if r["task"] == TASK]
    if not records:
        raise ValueError(f"task {TASK!r} not found in {root}")
    records.sort(key=lambda r: r["episode_index"])
    wanted: set[int] = set()
    for item in args.episodes.split(","):
        item = item.strip()
        if "-" in item:
            start, end = (int(v) for v in item.split("-", 1))
            wanted.update(range(start, end + 1))
        elif item:
            wanted.add(int(item))
    records = [r for rank, r in enumerate(records) if rank in wanted]
    records.sort(key=lambda r: r["episode_index"])
    if not records or len(records) != len(wanted):
        raise ValueError(f"selected {len(records)} episodes, expected {len(wanted)}")
    print(
        f"selected task-3 positional episodes {sorted(wanted)} "
        f"(global indices {sorted(r['episode_index'] for r in records)})"
    )

    import pyarrow as pa
    import pyarrow.parquet as pq

    shards: dict[tuple[int, int], set[int]] = {}
    for record in records:
        shards.setdefault((record["chunk_index"], record["file_index"]), set()).add(
            record["episode_index"]
        )

    episodes: dict[int, dict] = {}
    for (chunk_index, file_index), wanted_eps in sorted(shards.items()):
        path = root / "data" / f"chunk-{chunk_index:03d}" / f"file-{file_index:03d}.parquet"
        table = pq.read_table(path, columns=COLUMNS)
        mask = np.isin(np.asarray(table.column("episode_index")), sorted(wanted_eps))
        rows = table.filter(pa.array(mask)).to_pylist()
        rows.sort(key=lambda row: (row["episode_index"], row["frame_index"]))
        for row in rows:
            episode = episodes.setdefault(
                int(row["episode_index"]),
                {"agentview": [], "wrist": [], "state": [], "action": []},
            )
            episode["agentview"].append(row[AGENTVIEW_COLUMN]["bytes"])
            episode["wrist"].append(row[WRIST_COLUMN]["bytes"])
            episode["state"].append(row["observation.state"])
            episode["action"].append(row["action"])

    dataset = LeRobotDataset.create(
        repo_id=args.repo_id,
        root=args.output,
        robot_type="panda",
        fps=10,
        features=FEATURES,
        use_videos=False,
        image_writer_threads=8,
    )

    def decode_resize(payload: bytes) -> np.ndarray:
        array = np.asarray(Image.open(io.BytesIO(payload)).convert("RGB"))
        if array.shape[:2] != (128, 128):
            array = np.asarray(Image.fromarray(array).resize((128, 128), Image.BILINEAR))
        return np.ascontiguousarray(array)

    for record in records:
        episode = episodes[record["episode_index"]]
        states = np.asarray(episode["state"], dtype=np.float32)
        actions = np.asarray(episode["action"], dtype=np.float32)
        if len(states) != record["length"]:
            raise ValueError(
                f"episode {record['episode_index']}: {len(states)} rows vs {record['length']}"
            )
        for frame_index, action in enumerate(actions):
            dataset.add_frame(
                {
                    "observation.images.agentview": decode_resize(
                        episode["agentview"][frame_index]
                    ),
                    "observation.images.wrist": decode_resize(
                        episode["wrist"][frame_index]
                    ),
                    "observation.state": states[frame_index],
                    "action": action,
                    "task": TASK,
                }
            )
        dataset.save_episode()
        print(
            f"converted episode {record['episode_index']} ({len(actions)} frames)",
            flush=True,
        )
    dataset.finalize()
    print(f"native LeRobot v3.0 dataset written to {args.output}")


if __name__ == "__main__":
    main()
