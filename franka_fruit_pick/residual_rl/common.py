"""CLI helpers shared by residual training and evaluation."""

from __future__ import annotations

import json
from pathlib import Path

import genesis as gs
import torch

from franka_fruit_pick.build_scene import build_scene
from franka_fruit_pick.eval_policy import load_policy


def initialize(policy_path: str, repo_id: str, dataset_root: str, device: str, *, use_amp: bool = False):
    gs.init(backend=gs.gpu if device != "cpu" else gs.cpu)
    bundle = build_scene(show_viewer=False, n_envs=1, add_world_cam=True, add_wrist_cam=True)
    policy = load_policy(policy_path, repo_id, dataset_root, device, use_amp=use_amp)
    policy.policy.requires_grad_(False)
    return bundle, policy


def append_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as stream:
        stream.write(json.dumps(row, sort_keys=True) + "\n")


def torch_device(text: str) -> torch.device:
    return torch.device(text if text != "cuda" or torch.cuda.is_available() else "cpu")
