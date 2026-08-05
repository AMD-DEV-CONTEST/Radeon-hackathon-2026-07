#!/usr/bin/env python3
"""Create an episode-aligned Q-VGM cache subset without recomputing VLM features."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch

from smolvla_qvgm_rlinf.data.feature_cache import sha256_file, sha256_json, sha256_tensor
from smolvla_qvgm_rlinf.data.policy_observation_cache import (
    validate_policy_feature_alignment,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--repeat-id", type=int, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output_files = (
        args.output_dir / "feature_cache.pt",
        args.output_dir / "feature_cache_manifest.json",
        args.output_dir / "policy_observations.pt",
        args.output_dir / "policy_observations_manifest.json",
    )
    if any(path.exists() for path in output_files):
        raise FileExistsError(f"subset output already exists under {args.output_dir}")

    feature_path = args.source_dir / "feature_cache.pt"
    feature_manifest_path = args.source_dir / "feature_cache_manifest.json"
    observation_path = args.source_dir / "policy_observations.pt"
    observation_manifest_path = args.source_dir / "policy_observations_manifest.json"
    feature_manifest = json.loads(feature_manifest_path.read_text())
    observation_manifest = json.loads(observation_manifest_path.read_text())
    features = torch.load(feature_path, map_location="cpu", weights_only=True, mmap=True)
    observations = torch.load(
        observation_path, map_location="cpu", weights_only=True, mmap=True
    )

    selected_episode_indices = [
        index
        for index, episode in enumerate(feature_manifest["episodes"])
        if int(episode["repeat_id"]) == args.repeat_id
    ]
    if not selected_episode_indices:
        raise ValueError(f"no episodes have repeat_id={args.repeat_id}")
    states = [
        int(feature_manifest["episodes"][index]["task_reset_state_id"])
        for index in selected_episode_indices
    ]
    if sorted(states) != list(range(50)):
        raise ValueError(f"selected repeat does not cover task7 states 0-49: {states}")

    offsets = []
    offset = 0
    for episode in feature_manifest["episodes"]:
        length = int(episode["transitions"])
        offsets.append((offset, offset + length))
        offset += length
    indices = torch.cat(
        [
            torch.arange(offsets[index][0], offsets[index][1])
            for index in selected_episode_indices
        ]
    )
    subset_features = {key: value[indices].clone() for key, value in features.items()}
    subset_observations = {
        key: value[indices].clone() for key, value in observations.items()
    }

    feature_episodes = [
        dict(feature_manifest["episodes"][index])
        for index in selected_episode_indices
    ]
    observation_episodes = []
    next_offset = 0
    for new_episode_index, source_index in enumerate(selected_episode_indices):
        feature_episode = feature_manifest["episodes"][source_index]
        length = int(feature_episode["transitions"])
        start = next_offset
        stop = start + length
        subset_observations["episode_index"][start:stop] = new_episode_index
        source_observation_episode = dict(observation_manifest["episodes"][source_index])
        source_observation_episode["offset"] = start
        observation_episodes.append(source_observation_episode)
        next_offset = stop

    validate_policy_feature_alignment(subset_observations, subset_features)
    if not all(
        torch.isfinite(value).all()
        for value in subset_features.values()
        if value.is_floating_point()
    ):
        raise RuntimeError("subset feature cache contains non-finite values")

    subset_feature_path = args.output_dir / "feature_cache.pt"
    subset_observation_path = args.output_dir / "policy_observations.pt"
    torch.save(subset_features, subset_feature_path)
    torch.save(subset_observations, subset_observation_path)

    subset_feature_manifest = {
        **feature_manifest,
        "episodes": feature_episodes,
        "transitions": len(indices),
        "shapes": {
            key: list(value.shape) for key, value in subset_features.items()
        },
        "cache": str(subset_feature_path.resolve()),
        "subset": {
            "source_cache": str(feature_path.resolve()),
            "source_cache_sha256": sha256_file(feature_path),
            "source_manifest": str(feature_manifest_path.resolve()),
            "source_manifest_sha256": sha256_file(feature_manifest_path),
            "repeat_id": args.repeat_id,
        },
    }
    subset_feature_manifest_path = args.output_dir / "feature_cache_manifest.json"
    subset_feature_manifest_path.write_text(
        json.dumps(subset_feature_manifest, indent=2) + "\n"
    )

    subset_observation_manifest = {
        **observation_manifest,
        "transitions": len(indices),
        "episodes": observation_episodes,
        "shapes": {
            key: list(value.shape) for key, value in subset_observations.items()
        },
        "dtypes": {
            key: str(value.dtype) for key, value in subset_observations.items()
        },
        "state_sha256": sha256_tensor(subset_observations["states"]),
        "feature_cache": str(subset_feature_path.resolve()),
        "feature_cache_sha256": sha256_file(subset_feature_path),
        "feature_manifest": str(subset_feature_manifest_path.resolve()),
        "feature_manifest_sha256": sha256_file(subset_feature_manifest_path),
        "subset": {
            "source_cache": str(observation_path.resolve()),
            "source_cache_sha256": sha256_file(observation_path),
            "source_manifest": str(observation_manifest_path.resolve()),
            "source_manifest_sha256": sha256_file(observation_manifest_path),
            "repeat_id": args.repeat_id,
        },
    }
    subset_observation_manifest.pop("identity_sha256", None)
    subset_observation_manifest["identity_sha256"] = sha256_json(
        subset_observation_manifest
    )
    (args.output_dir / "policy_observations_manifest.json").write_text(
        json.dumps(subset_observation_manifest, indent=2) + "\n"
    )
    print(
        json.dumps(
            {
                "episodes": len(selected_episode_indices),
                "states": sorted(states),
                "transitions": len(indices),
                "repeat_id": args.repeat_id,
                "feature_cache": str(subset_feature_path),
                "observation_cache": str(subset_observation_path),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
