"""Build a LeRobot dataset by mixing broad replay and targeted episodes.

The script copies complete episodes so temporal structure is preserved. It
verifies that both source datasets expose the same feature schema before
creating the output dataset.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np


# LeRobot creates these bookkeeping columns when an episode is saved. They
# belong in metadata/parquet output, but must not be passed back to add_frame().
_AUTO_FEATURES = {
    "timestamp",
    "frame_index",
    "episode_index",
    "index",
    "task_index",
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


def _plain(value):
    if hasattr(value, "detach"):
        value = value.detach().cpu().numpy()
    if isinstance(value, np.ndarray):
        if value.ndim == 0:
            return value.item()
        if value.ndim == 4 and value.shape[0] == 1:
            value = value[0]
        if value.ndim == 3 and value.shape[0] in (1, 3, 4) and value.shape[-1] not in (1, 3, 4):
            value = np.transpose(value, (1, 2, 0))
        return value
    if isinstance(value, (list, tuple)) and len(value) == 1:
        return value[0]
    return value


def _feature_signature(features: dict) -> dict:
    signature = {}
    for key, spec in features.items():
        signature[key] = {
            "dtype": str(spec.get("dtype")),
            "shape": list(spec.get("shape", [])),
            "names": spec.get("names"),
        }
    return signature


def _episode_bounds(dataset, episode_index: int) -> tuple[int, int]:
    if hasattr(dataset, "episode_data_index"):
        index = dataset.episode_data_index
        return int(index["from"][episode_index]), int(index["to"][episode_index])
    frames_per_episode = len(dataset) // dataset.num_episodes
    start = episode_index * frames_per_episode
    return start, start + frames_per_episode


def _episode_plan(n_original: int, n_targeted: int, original_per_targeted: int):
    plan = []
    original_index = targeted_index = 0
    while original_index < n_original or targeted_index < n_targeted:
        for _ in range(original_per_targeted):
            if original_index < n_original:
                plan.append(("original", original_index))
                original_index += 1
        if targeted_index < n_targeted:
            plan.append(("targeted", targeted_index))
            targeted_index += 1
    return plan


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original-id", required=True)
    parser.add_argument("--targeted-id", required=True)
    parser.add_argument("--output-id", required=True)
    parser.add_argument("--original-per-targeted", type=int, default=2)
    parser.add_argument("--max-original-episodes", type=int, default=None)
    parser.add_argument("--max-targeted-episodes", type=int, default=None)
    parser.add_argument("--output-dir", type=Path, default=Path("./output"))
    args = parser.parse_args()
    if args.original_per_targeted < 1:
        parser.error("--original-per-targeted must be >= 1")

    LeRobotDataset, LeRobotDatasetMetadata = _import_lerobot()
    original_meta = LeRobotDatasetMetadata(args.original_id)
    targeted_meta = LeRobotDatasetMetadata(args.targeted_id)
    original_sig = _feature_signature(original_meta.features)
    targeted_sig = _feature_signature(targeted_meta.features)
    if original_sig != targeted_sig:
        raise RuntimeError(
            "source feature schemas differ; regenerate targeted data with the "
            "same camera/state/action flags"
        )
    if original_meta.fps != targeted_meta.fps:
        raise RuntimeError("source datasets must use the same FPS")

    original = LeRobotDataset(args.original_id)
    targeted = LeRobotDataset(args.targeted_id)
    n_original = min(
        original.num_episodes,
        args.max_original_episodes or original.num_episodes,
    )
    n_targeted = min(
        targeted.num_episodes,
        args.max_targeted_episodes or targeted.num_episodes,
    )
    plan = _episode_plan(n_original, n_targeted, args.original_per_targeted)
    if not plan:
        raise RuntimeError("no episodes selected")

    use_videos = any(
        spec.get("dtype") == "video" for spec in original_meta.features.values()
    )
    out = LeRobotDataset.create(
        repo_id=args.output_id,
        fps=original_meta.fps,
        features=original_meta.features,
        robot_type=getattr(original_meta, "robot_type", "franka"),
        use_videos=use_videos,
    )

    source_datasets = {"original": original, "targeted": targeted}
    copied_frames = 0
    copied_episodes = {"original": 0, "targeted": 0}
    for new_episode, (source_name, source_episode) in enumerate(plan):
        dataset = source_datasets[source_name]
        start, end = _episode_bounds(dataset, source_episode)
        for frame_index in range(start, end):
            raw = dataset[frame_index]
            frame = {}
            for key in original_meta.features:
                if key in _AUTO_FEATURES:
                    continue
                if key not in raw:
                    raise RuntimeError(
                        f"frame {source_name}:{frame_index} is missing feature {key}"
                    )
                frame[key] = _plain(raw[key])
            task = _plain(raw.get("task", "Pick up the cube."))
            if isinstance(task, (list, tuple)):
                task = task[0]
            frame["task"] = str(task)
            out.add_frame(frame)
            copied_frames += 1
        out.save_episode()
        copied_episodes[source_name] += 1
        print(
            f"[mix] episode {new_episode + 1}/{len(plan)}: "
            f"{source_name}[{source_episode}] frames={end - start}"
        )

    if hasattr(out, "consolidate"):
        out.consolidate(run_compute_stats=True)

    summary = {
        "original_id": args.original_id,
        "targeted_id": args.targeted_id,
        "output_id": args.output_id,
        "original_per_targeted": args.original_per_targeted,
        "source_episodes": {"original": n_original, "targeted": n_targeted},
        "copied_episodes": copied_episodes,
        "copied_frames": copied_frames,
        "fps": original_meta.fps,
        "feature_schema": original_sig,
        "dataset_root": str(out.root),
    }
    summary_dir = args.output_dir / "data" / "mixed_replay"
    summary_dir.mkdir(parents=True, exist_ok=True)
    (summary_dir / "mix_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
