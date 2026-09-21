#!/usr/bin/env python3
"""Cache current rollout observations in feature-cache transition order."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import torch

from smolvla_qvgm_rlinf.data.collected_episode_adapter import load_collected_episode
from smolvla_qvgm_rlinf.data.feature_cache import sha256_file, sha256_json, sha256_tensor
from smolvla_qvgm_rlinf.data.policy_observation_cache import validate_policy_feature_alignment


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--feature-cache", type=Path, required=True)
    parser.add_argument("--feature-manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def _as_rgb_uint8(value, *, name: str) -> torch.Tensor:
    tensor = torch.as_tensor(np.asarray(value))
    if tensor.ndim == 4:
        tensor = tensor[-1]
    if tensor.ndim != 3:
        raise ValueError(f"{name} must be one RGB image, got {tuple(tensor.shape)}")
    if tensor.shape[0] == 3 and tensor.shape[-1] != 3:
        tensor = tensor.permute(1, 2, 0)
    if tensor.shape[-1] != 3:
        raise ValueError(f"{name} has no RGB channel dimension")
    if tensor.dtype != torch.uint8:
        value = tensor.float()
        if value.numel() and value.max() <= 1:
            value = value * 255
        tensor = value.round().clamp(0, 255).to(torch.uint8)
    return tensor.contiguous()


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    cache_path = args.output_dir / "policy_observations.pt"
    manifest_path = args.output_dir / "policy_observations_manifest.json"
    if not args.overwrite and (cache_path.exists() or manifest_path.exists()):
        raise FileExistsError(f"output already exists under {args.output_dir}")

    feature_manifest = json.loads(args.feature_manifest.read_text())
    feature_cache = torch.load(
        args.feature_cache, map_location="cpu", weights_only=True, mmap=True
    )
    total = int(feature_manifest["transitions"])
    if total != len(feature_cache["z_state"]):
        raise ValueError("feature manifest/cache transition count mismatch")

    first_path = Path(feature_manifest["episodes"][0]["file"])
    first = load_collected_episode(first_path)["observations"][0]
    main_shape = _as_rgb_uint8(first["main_images"], name="main_images").shape
    wrist_shape = _as_rgb_uint8(first["wrist_images"], name="wrist_images").shape
    state_shape = torch.as_tensor(first["states"]).shape
    payload = {
        "main_images": torch.empty((total, *main_shape), dtype=torch.uint8),
        "wrist_images": torch.empty((total, *wrist_shape), dtype=torch.uint8),
        "states": torch.empty((total, *state_shape), dtype=torch.float32),
        "episode_index": torch.empty(total, dtype=torch.int32),
        "transition_index": torch.empty(total, dtype=torch.int32),
        "task_index": torch.empty(total, dtype=torch.int16),
        "reset_state_id": torch.empty(total, dtype=torch.int16),
    }
    tasks: list[str] = []
    task_to_index: dict[str, int] = {}
    records = []
    offset = 0
    for episode_index, record in enumerate(feature_manifest["episodes"]):
        path = Path(record["file"])
        episode = load_collected_episode(path)
        length = len(episode["actions"])
        if length != int(record["transitions"]):
            raise ValueError(f"transition count changed for {path}")
        stop = offset + length
        observations = episode["observations"][:-1]
        task_values = {str(observation["task_descriptions"]) for observation in observations}
        if len(task_values) != 1:
            raise ValueError(f"task description changes inside {path}")
        task = task_values.pop()
        task_index = task_to_index.setdefault(task, len(tasks))
        if task_index == len(tasks):
            tasks.append(task)
        payload["main_images"][offset:stop] = torch.stack(
            [_as_rgb_uint8(obs["main_images"], name="main_images") for obs in observations]
        )
        payload["wrist_images"][offset:stop] = torch.stack(
            [_as_rgb_uint8(obs["wrist_images"], name="wrist_images") for obs in observations]
        )
        payload["states"][offset:stop] = torch.stack(
            [torch.as_tensor(np.asarray(obs["states"]), dtype=torch.float32) for obs in observations]
        )
        payload["episode_index"][offset:stop] = episode_index
        payload["transition_index"][offset:stop] = torch.arange(length, dtype=torch.int32)
        payload["task_index"][offset:stop] = task_index
        state_id = record.get("task_reset_state_id")
        if state_id is None:
            raise ValueError(f"feature manifest has no reset state for {path}")
        payload["reset_state_id"][offset:stop] = int(state_id)
        records.append(
            {
                "file": str(path.resolve()),
                "file_size": path.stat().st_size,
                "transitions": length,
                "offset": offset,
                "task_index": task_index,
                "task_id": record.get("task_id"),
                "reset_state_id": int(state_id),
            }
        )
        offset = stop
        print(f"cached {episode_index + 1}/{len(feature_manifest['episodes'])}: {path.name}", flush=True)
    if offset != total:
        raise ValueError(f"wrote {offset} observations, expected {total}")
    validate_policy_feature_alignment(payload, feature_cache)
    torch.save(payload, cache_path)
    manifest = {
        "schema_version": 1,
        "transitions": total,
        "tasks": tasks,
        "episodes": records,
        "shapes": {key: list(value.shape) for key, value in payload.items()},
        "dtypes": {key: str(value.dtype) for key, value in payload.items()},
        "state_sha256": sha256_tensor(payload["states"]),
        "feature_cache": str(args.feature_cache.resolve()),
        "feature_cache_sha256": sha256_file(args.feature_cache),
        "feature_manifest": str(args.feature_manifest.resolve()),
        "feature_manifest_sha256": sha256_file(args.feature_manifest),
    }
    manifest["identity_sha256"] = sha256_json(manifest)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"cache": str(cache_path), "manifest": str(manifest_path), "transitions": total}))


if __name__ == "__main__":
    main()
