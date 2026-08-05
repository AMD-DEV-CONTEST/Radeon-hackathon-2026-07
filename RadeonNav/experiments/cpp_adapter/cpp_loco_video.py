#!/usr/bin/env python3
"""Record the frozen CPP Go2 policy executing a smooth multi-axis command sequence."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import numpy as np
import torch

from cpp_loco_sanity import (
    DEFAULT_CHECKPOINT,
    _compose_env,
    _resolve_device,
    _sha256,
    _write_json,
)
from unilab.algos.torch.cpp_loco import CppLocoPolicyAdapter
from unilab.terrains import pyramid_stairs


CONSERVATIVE_COMMAND_ANCHORS = np.asarray(
    [
        [0.35, 0.00, 0.00],
        [0.30, 0.25, 0.00],
        [0.30, 0.00, -0.65],
        [0.05, -0.25, 0.45],
        [-0.20, 0.00, 0.50],
        [0.40, 0.00, 0.00],
    ],
    dtype=np.float32,
)

CPP_TERRAIN_COMMAND_ANCHORS = np.asarray(
    [
        [1.00, 0.00, 0.00],
        [0.70, 0.80, 0.00],
        [0.80, 0.00, -1.50],
        [0.30, -0.80, 1.20],
        [-0.60, 0.00, 1.50],
        [1.00, 0.00, 0.00],
    ],
    dtype=np.float32,
)

COMMAND_PROFILES = {
    "conservative": CONSERVATIVE_COMMAND_ANCHORS,
    "cpp_terrain": CPP_TERRAIN_COMMAND_ANCHORS,
}

STAIRS_METADATA = {
    "type": "pyramid_stairs",
    "difficulty": 0.8,
    "step_height_range_m": [0.06, 0.10],
    "nominal_step_height_m": 0.092,
    "heightfield_step_height_m": 0.09,
    "step_width_m": 0.4,
    "platform_width_m": 2.0,
}


def _command_at(step: int, num_steps: int, anchors: np.ndarray) -> np.ndarray:
    position = step * (len(anchors) - 1) / max(num_steps - 1, 1)
    left = min(int(position), len(anchors) - 2)
    alpha = np.float32(position - left)
    return (1.0 - alpha) * anchors[left] + alpha * anchors[left + 1]


def _terrain_override(name: str, seed: int) -> dict[str, Any] | None:
    if name == "default":
        return None
    return {
        "seed": seed,
        "curriculum": False,
        "num_rows": 1,
        "num_cols": 1,
        "difficulty_range": (0.8, 0.8),
        "border_width": 4.0,
        "sub_terrains": {
            "pyramid_stairs": pyramid_stairs(
                proportion=1.0,
                step_height_range=(0.06, 0.10),
                step_width=0.4,
                platform_width=2.0,
                border_width=0.4,
            )
        },
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    device = _resolve_device(args.device)
    anchors = COMMAND_PROFILES[args.command_profile]
    env = _compose_env(
        terrain_generator_override=_terrain_override(args.terrain, args.seed)
    )
    adapter = CppLocoPolicyAdapter(args.checkpoint, device=device)
    num_steps = max(1, int(round(args.duration / float(env.cfg.ctrl_dt))))
    args.output_video.parent.mkdir(parents=True, exist_ok=True)

    rewards: list[float] = []
    done_count = 0
    max_abs_cpp_action = 0.0
    all_finite = True
    step_index = 0

    def initialize():
        adapter.reset()
        return env.init_state()

    def step(state):
        nonlocal all_finite, done_count, max_abs_cpp_action, step_index
        command = _command_at(step_index, num_steps, anchors).reshape(1, 3)
        state.info["commands"][:] = command
        state.obs["obs"][:, 6:9] = command
        action, diagnostics = adapter.act(
            state.obs["obs"], projected_gravity=env.get_projected_gravity()
        )
        state = env.step(action)
        done = state.terminated | state.truncated
        if bool(done[0]):
            adapter.reset()
        done_count += int(np.count_nonzero(done))
        rewards.append(float(state.reward[0]))
        max_abs_cpp_action = max(
            max_abs_cpp_action, float(np.max(np.abs(diagnostics["cpp_action"])))
        )
        all_finite = all_finite and all(
            np.isfinite(value).all()
            for value in (
                state.obs["obs"],
                state.reward,
                action,
                diagnostics["cpp_action"],
                diagnostics["expert_weights"],
                diagnostics["latent"],
            )
        )
        step_index += 1
        return state

    try:
        rendered_path = env.run_playback(
            initialize=initialize,
            step=step,
            num_steps=num_steps,
            output_video=args.output_video,
            headless=True,
            record_video=True,
            camera_kwargs={
                "cam_tracking": True,
                "cam_tracking_env_idx": 0,
                "cam_tracking_extra_envs": 0,
                "cam_distance": 2.6,
                "cam_elevation": -18.0,
                "cam_azimuth": 135.0,
            },
        )
    finally:
        env.close()

    video_exists = rendered_path is not None and args.output_video.is_file()
    passed = video_exists and all_finite and len(rewards) == num_steps
    return {
        "run_id": args.run_id,
        "status": "PASSED" if passed else "FAILED",
        "scope": "qualitative complex-command video; not robustness evidence",
        "device": device,
        "device_name": (
            torch.cuda.get_device_name(torch.device(device))
            if torch.device(device).type == "cuda"
            else None
        ),
        "checkpoint": str(args.checkpoint),
        "checkpoint_sha256": _sha256(args.checkpoint),
        "seed": args.seed,
        "duration_sec": args.duration,
        "ctrl_dt": args.duration / num_steps,
        "num_steps": num_steps,
        "command_profile": args.command_profile,
        "command_anchors_si": anchors.tolist(),
        "terrain": (
            {"profile": "default"}
            if args.terrain == "default"
            else {"profile": args.terrain, **STAIRS_METADATA}
        ),
        "checks": {
            "video_created": video_exists,
            "rollout_finite": all_finite,
            "step_count": len(rewards) == num_steps,
        },
        "metrics": {
            "mean_reward": float(np.mean(rewards)),
            "done_count": done_count,
            "max_abs_cpp_action": max_abs_cpp_action,
        },
        "video": {
            "path": str(args.output_video),
            "bytes": args.output_video.stat().st_size if video_exists else 0,
            "sha256": _sha256(args.output_video) if video_exists else None,
            "fps": int(round(num_steps / args.duration)),
        },
        "source_sha256": {
            "video_runner": _sha256(Path(__file__).resolve()),
            "adapter": _sha256(
                Path(__file__).resolve().parents[2]
                / "UniLab/src/unilab/algos/torch/cpp_loco.py"
            ),
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--run-id", default="CPP-V001")
    parser.add_argument("--output-video", type=Path, required=True)
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--duration", type=float, default=10.0)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument(
        "--command-profile",
        choices=sorted(COMMAND_PROFILES),
        default="cpp_terrain",
    )
    parser.add_argument("--terrain", choices=("default", "stairs"), default="stairs")
    args = parser.parse_args()
    if args.duration <= 0.0:
        parser.error("--duration must be positive")
    if args.output_json is None:
        args.output_json = args.output_video.with_suffix(".json")
    return args


def main() -> int:
    args = parse_args()
    try:
        payload = run(args)
    except Exception as exc:
        payload = {
            "run_id": args.run_id,
            "status": "FAILED",
            "error": f"{type(exc).__name__}: {exc}",
        }
    _write_json(args.output_json, payload)
    print(f"{payload['status']}: {args.output_video}")
    return 0 if payload["status"] == "PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
