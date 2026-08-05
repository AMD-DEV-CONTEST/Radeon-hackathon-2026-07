#!/usr/bin/env python3
"""Record the pure-source Quadrupedal-Agility frame rollout in UniLab."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import numpy as np
import torch

from run_bbc_sanity import _device, _sha256, _write_json
from run_frame_sanity import (
    AGILITY_ROOT,
    FRAME_OBSTACLE_TYPE,
    HIGH_CHECKPOINT,
    SOURCE_GOAL_THRESHOLD_M,
    SOURCE_LOW_CHECKPOINT,
    SOURCE_SCAN_X,
    SOURCE_SCAN_Y,
    _compose_env,
    _frame_terrain,
    _set_start_state,
    frame_delta_yaw,
    height_scan_obs,
)
from unilab.algos.torch.quadrupedal_agility import (
    AgilityTscPolicyAdapter,
    SOURCE_AGILITY_BBC_CONTRACT,
    agility_action_to_unilab,
)


def run(args: argparse.Namespace) -> dict[str, Any]:
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    torch.cuda.manual_seed_all(args.seed)
    device = _device(args.device)
    adapter = AgilityTscPolicyAdapter(
        AGILITY_ROOT,
        HIGH_CHECKPOINT,
        SOURCE_LOW_CHECKPOINT,
        device=device,
        low_contract=SOURCE_AGILITY_BBC_CONTRACT,
        low_mode_count=5,
        command_profile="source",
    )
    env = _compose_env(
        terrain_generator_override=_frame_terrain(args.seed, 0.05),
        terrain_scan_override={
            "measured_points_x": SOURCE_SCAN_X,
            "measured_points_y": SOURCE_SCAN_Y,
            "vertical_offset": 0.3,
            "scale": 1.0,
        },
        control_gains=(40.0, 1.0),
        simulate_action_latency=True,
    )
    num_steps = int(round(args.duration / float(env.cfg.ctrl_dt)))
    args.output_video.parent.mkdir(parents=True, exist_ok=True)

    goal_index = 0
    reach_goal_timer = 0
    last_contact = np.zeros((1, 4), dtype=bool)
    done_count = 0
    all_finite = True
    positions: list[list[float]] = []
    skills: list[int] = []

    def initialize():
        nonlocal goal_index, reach_goal_timer, last_contact
        state = env.init_state()
        env.set_autoreset(False)
        _set_start_state(env, source=True)
        state = env.update_state(state)
        adapter.reset()
        state.info["current_actions"] = agility_action_to_unilab(
            np.zeros((1, 12), dtype=np.float32),
            SOURCE_AGILITY_BBC_CONTRACT,
        )
        goal_index = 0
        reach_goal_timer = 0
        last_contact.fill(False)
        return state

    def step(state):
        nonlocal all_finite, done_count, goal_index, reach_goal_timer, last_contact
        base_quat = env._backend.get_base_quat().copy()
        base_pos = env._backend.get_base_pos().copy()
        delta_yaw, goal_index, reach_goal_timer = frame_delta_yaw(
            base_pos,
            base_quat,
            goal_index,
            reach_goal_timer,
            SOURCE_GOAL_THRESHOLD_M,
        )
        raw_contact = np.linalg.norm(env.feet_force, axis=2) > 2.0
        foot_contact = np.logical_or(raw_contact, last_contact).astype(np.float32)
        last_contact = raw_contact
        scan = height_scan_obs(env, env._cfg.terrain_scan, 1)
        low_explicit = np.concatenate(
            (
                0.3 + scan[:, 67:68],
                env.get_local_linvel() * 0.5,
            ),
            axis=1,
        ).astype(np.float32)
        action, diagnostics = adapter.act(
            base_quat_wxyz=base_quat,
            base_ang_vel=env.get_gyro().copy(),
            dof_pos=env.get_dof_pos().copy(),
            dof_vel=env.get_dof_vel().copy(),
            foot_contact=foot_contact,
            height_scan=scan,
            delta_yaw=delta_yaw,
            obstacle_type=FRAME_OBSTACLE_TYPE,
            low_explicit=low_explicit,
        )
        state = env.step(action)
        done_count += int(np.count_nonzero(state.terminated | state.truncated))
        positions.append(env._backend.get_base_pos()[0].tolist())
        skills.append(int(diagnostics["skill"][0]))
        all_finite = all_finite and all(
            np.isfinite(value).all()
            for value in (
                action,
                scan,
                diagnostics["command"],
                diagnostics["source_action"],
                positions[-1],
            )
        )
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
                "cam_distance": 3.2,
                "cam_elevation": -20.0,
                "cam_azimuth": 135.0,
            },
        )
    finally:
        env.close()

    video_exists = rendered_path is not None and args.output_video.is_file()
    unique, counts = np.unique(skills, return_counts=True)
    return {
        "run_id": "NAG-V001",
        "status": (
            "PASSED"
            if video_exists and all_finite and len(positions) == num_steps
            else "FAILED"
        ),
        "scope": "10-second qualitative pure-source TSC→BBC frame rollout",
        "seed": args.seed,
        "duration_sec": args.duration,
        "ctrl_dt": float(env.cfg.ctrl_dt),
        "num_steps": num_steps,
        "device": str(device),
        "device_name": torch.cuda.get_device_name(device),
        "checks": {
            "video_created": video_exists,
            "rollout_finite": all_finite,
            "step_count": len(positions) == num_steps,
        },
        "metrics": {
            "done_count": done_count,
            "start_x_m": positions[0][0],
            "final_x_m": positions[-1][0],
            "forward_progress_m": positions[-1][0] - positions[0][0],
        },
        "skill_counts": {
            str(int(skill)): int(count)
            for skill, count in zip(unique, counts)
        },
        "video": {
            "path": str(args.output_video),
            "bytes": args.output_video.stat().st_size if video_exists else 0,
            "sha256": _sha256(args.output_video) if video_exists else None,
            "fps": int(round(1.0 / float(env.cfg.ctrl_dt))),
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-video", type=Path, required=True)
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--duration", type=float, default=10.0)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--device", default="auto")
    args = parser.parse_args()
    if args.duration <= 0:
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
            "run_id": "NAG-V001",
            "status": "FAILED",
            "error": f"{type(exc).__name__}: {exc}",
        }
    _write_json(args.output_json, payload)
    print(f"{payload['status']}: {args.output_video}")
    return 0 if payload["status"] == "PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
