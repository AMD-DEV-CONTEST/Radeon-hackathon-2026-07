#!/usr/bin/env python3
"""NAG-701-A stairs probe: frozen student-D over box stairs (up+down).

Preregistered in EXPERIMENT_PLAN.md NAG-701 阶段 A. Straight-line receding
feed through the stairs (walk class frame(1); stairs are scan/latent terrain,
no new class). Gates: reach the far goal, no fall; forbidden contacts are
recorded but reported (stair-edge thigh brushes expected while climbing).
"""

from __future__ import annotations

import argparse

import os
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

os.environ.setdefault("MUJOCO_GL", "egl")

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "experiments/cpp_adapter"))

from bridge import path_to_tsc_waypoints  # noqa: E402
from cpp_loco_sanity import _compose_env, _sha256  # noqa: E402
from run_bbc_sanity import _device, _live_env_contract, _write_json  # noqa: E402
from run_source_task import (  # noqa: E402
    AGILITY_ROOT,
    HIGH_CHECKPOINT,
    POLICY_PROFILES,
    ROBOT_JOINTS,
    ContactProbe,
    SourceDepthCamera,
    _video_metadata,
)
from run_waypoint_envelope import (  # noqa: E402
    CURRENT_LOOKAHEAD_M,
    MAX_ABS_YAW_RAD,
    NEXT_LOOKAHEAD_M,
    _base_yaw,
    remaining_policy_path,
)
from source_tasks import SCAN_X, SCAN_Y, flat_physics_terrain  # noqa: E402
from static_2p5d import FREE_SPACE_CLASS, PATH_SPACING_M  # noqa: E402
from unilab.algos.torch.quadrupedal_agility import (  # noqa: E402
    AgilityTscPolicyAdapter,
    agility_action_to_unilab,
)

RESULTS_ROOT = ROOT / "experiment-results/quadrupedal-agility/NAG-701-STAIRS"
ASSET_DIR = Path(__file__).resolve().parent / "assets"
STAIRS_FRAGMENT = ASSET_DIR / "stairs.xml"
START_XY = (-3.0, 0.0)
GOAL_XY = (3.0, 0.0)
GOAL_THRESHOLD_M = 0.4
EPISODE_STEPS = 500  # default; override with --episode-steps


def run(args: argparse.Namespace) -> dict[str, Any]:
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    torch.cuda.manual_seed_all(args.seed)
    device = _device(args.device)
    profile = POLICY_PROFILES["deployment3"]
    length = GOAL_XY[0] - START_XY[0]
    path = np.stack(
        (
            np.arange(PATH_SPACING_M, length + 1e-9, PATH_SPACING_M) + START_XY[0],
            np.zeros(int(round(length / PATH_SPACING_M))),
        ),
        axis=1,
    )
    policy_arc = (np.arange(len(path)) + 1) * PATH_SPACING_M
    adapter = AgilityTscPolicyAdapter(
        AGILITY_ROOT,
        HIGH_CHECKPOINT,
        profile.low_checkpoint,
        device=device,
        low_contract=profile.low_contract,
        low_mode_count=profile.low_mode_count,
        command_profile="deployment",
        high_branch="student",
        use_half=True,
    )
    if args.depth_encoder_checkpoint is not None:
        override = torch.load(
            args.depth_encoder_checkpoint, map_location=device, weights_only=True
        )
        adapter.depth_encoder.load_state_dict(override)
        adapter.depth_encoder.half()
        adapter.depth_encoder.eval()
    if args.high_actor_checkpoint is not None:
        actor_override = torch.load(
            args.high_actor_checkpoint, map_location=device, weights_only=True
        )
        adapter.high_model.load_state_dict(actor_override)
        adapter.high_model.half()
        adapter.high_model.eval()
    if args.bbc_checkpoint is not None:
        bbc_override = torch.load(
            args.bbc_checkpoint, map_location=device, weights_only=True
        )
        adapter.bbc.model.load_state_dict(bbc_override)
        adapter.bbc.model.half()
        adapter.bbc.model.eval()
    if args.keep_bbc_history:
        # NAG-901 contract: trained BBC uses a real rolling history; the
        # student branch's per-step zeroing is disabled by swapping the
        # buffer for an ndarray subclass whose fill() is a no-op.
        class _NoFill(np.ndarray):
            def fill(self, value):  # noqa: ARG002
                return None

        adapter.bbc.history = (
            np.zeros((1, 570), dtype=np.float32).view(_NoFill)
        )
    env = _compose_env(
        terrain_generator_override=flat_physics_terrain(args.seed),
        terrain_scan_override={
            "measured_points_x": list(SCAN_X),
            "measured_points_y": list(SCAN_Y),
            "vertical_offset": 0.3,
            "scale": 1.0,
        },
        scene_fragment_files=[str(args.stairs_fragment)],
        ground_friction=1.0,
        control_gains=(40.0, 1.0),
        simulate_action_latency=True,
    )
    depth_camera = SourceDepthCamera(env, 0.0)
    probe = ContactProbe(env)
    backend = env._backend

    positions: list[list[float]] = []
    skills: list[int] = []
    forbidden_steps: list[int] = []
    done_steps: list[int] = []
    reached_step: int | None = None
    consumed = 0
    previous_foot_contact = np.zeros((1, 4), dtype=np.float32)
    all_finite = True
    live_contract: dict[str, Any] = {}
    started = time.monotonic()

    def initialize():
        nonlocal previous_foot_contact, live_contract
        live_contract = _live_env_contract(env)
        if not bool(live_contract["passed"]):
            raise RuntimeError(f"live UniLab action contract mismatch: {live_contract}")
        state = env.init_state()
        env.set_autoreset(False)
        qpos = np.asarray(env._init_qpos, dtype=np.float32).reshape(1, -1).copy()
        qvel = np.zeros_like(env._init_qvel, dtype=np.float32).reshape(1, -1)
        qpos[0, :3] = (START_XY[0], START_XY[1], 0.42)
        qpos[0, 3:7] = (1.0, 0.0, 0.0, 0.0)
        indices = backend.get_joint_dof_pos_indices(ROBOT_JOINTS) + 7
        qpos[0, indices] = profile.low_contract.source_default_dof
        backend.set_state(np.asarray([0], dtype=np.int32), qpos, qvel)
        state = env.update_state(state)
        adapter.reset()
        state.info["current_actions"] = agility_action_to_unilab(
            np.zeros((1, 12), dtype=np.float32), profile.low_contract
        )
        previous_foot_contact.fill(0.0)
        return state

    def step(state):
        nonlocal reached_step, consumed, previous_foot_contact, all_finite
        step_index = len(positions) + 1
        base_quat = backend.get_base_quat().copy()
        base_pos = backend.get_base_pos().copy()
        robot_xy = base_pos[0, :2].astype(np.float64)
        base_yaw = _base_yaw(base_quat[0])
        if reached_step is None and (
            float(np.linalg.norm(robot_xy - np.asarray(GOAL_XY))) < GOAL_THRESHOLD_M
        ):
            reached_step = step_index - 1
        remaining, consumed = remaining_policy_path(
            path, policy_arc, path, robot_xy, consumed
        )
        waypoint = path_to_tsc_waypoints(
            remaining,
            np.asarray([robot_xy[0], robot_xy[1], base_yaw]),
            CURRENT_LOOKAHEAD_M,
            NEXT_LOOKAHEAD_M,
            MAX_ABS_YAW_RAD,
        )
        delta_yaw = np.asarray(
            [[waypoint.delta_yaw, waypoint.delta_next_yaw]], dtype=np.float32
        )
        contact = probe.sample()
        sensor_floor = (np.linalg.norm(env.feet_force, axis=2) > 2.0).astype(np.float32)
        current_contact = np.maximum(contact["foot_contact"], sensor_floor)
        foot_contact = np.maximum(current_contact, previous_foot_contact)
        previous_foot_contact = current_contact
        action, diagnostics = adapter.act(
            base_quat_wxyz=base_quat,
            base_ang_vel=env.get_gyro().copy(),
            dof_pos=env.get_dof_pos().copy(),
            dof_vel=env.get_dof_vel().copy(),
            foot_contact=foot_contact,
            depth_image=depth_camera.capture(),
            delta_yaw=delta_yaw,
            obstacle_type=FREE_SPACE_CLASS,
        )
        skills.append(int(diagnostics["skill"][0]))
        state = env.step(action)
        if np.any(state.terminated | state.truncated):
            done_steps.append(step_index)
        base_after = backend.get_base_pos().copy()
        positions.append(base_after[0].tolist())
        after = probe.sample()
        if after["forbidden"]:
            forbidden_steps.append(step_index)
        all_finite = all_finite and all(
            np.isfinite(v).all()
            for v in (action, delta_yaw, diagnostics["command"], base_after)
        )
        return state

    try:
        rendered = env.run_playback(
            initialize=initialize,
            step=step,
            num_steps=args.episode_steps,
            output_video=args.output_video,
            headless=True,
            record_video=True,
            camera_kwargs={
                "cam_tracking": True,
                "cam_tracking_env_idx": 0,
                "cam_tracking_extra_envs": 0,
                "cam_distance": 4.0,
                "cam_elevation": -20.0,
                "cam_azimuth": 135.0,
            },
        )
    finally:
        depth_camera.close()
        env.close()

    video_exists = rendered is not None and args.output_video.is_file()
    video = _video_metadata(args.output_video) if video_exists else {}
    gate_end = reached_step if reached_step is not None else len(positions)
    done_before = [s for s in done_steps if s <= gate_end]
    forbidden_before = [s for s in forbidden_steps if s <= gate_end]
    zs = [p[2] for p in positions[:gate_end]]
    checks = {
        "live_env_action_contract": bool(live_contract["passed"]),
        "rollout_finite": all_finite,
        "step_count": len(positions) == args.episode_steps,
        "video_created": video_exists,
        "video_frame_count": video.get("frames") == args.episode_steps,
        "no_early_termination_before_success": not done_before,
        "reached_goal": reached_step is not None,
    }
    elapsed = time.monotonic() - started
    return {
        "run_id": args.run_id,
        "status": "PASSED" if all(checks.values()) else "FAILED",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "evaluation_type": "simulation_only",
        "scope": "stairs probe: frozen student-D, straight feed, walk class",
        "seed": args.seed,
        "checks": checks,
        "metrics": {
            "reached_step": reached_step,
            "final_base_xyz_m": positions[-1],
            "max_base_z_m": max(zs) if zs else None,
            "forbidden_contact_before_success_steps": forbidden_before,
            "forbidden_contact_step_count": len(forbidden_steps),
            "done_before_success_steps": done_before,
            "wall_time_sec": elapsed,
        },
        "skill_counts": {
            str(int(s)): int(c)
            for s, c in zip(*np.unique(np.asarray(skills), return_counts=True))
        },
        "contracts": {
            "stairs": "4x riser (see assets/stairs.xml) / tread 0.30 m up + 0.6 m platform + 4x down",
            "class": FREE_SPACE_CLASS,
            "fragment_sha256": _sha256(args.stairs_fragment),
            "depth_encoder_override_sha256": (
                _sha256(args.depth_encoder_checkpoint)
                if args.depth_encoder_checkpoint
                else None
            ),
            "high_checkpoint_sha256": _sha256(HIGH_CHECKPOINT),
            "runner_sha256": _sha256(Path(__file__)),
        },
        "video": {
            "path": str(args.output_video),
            "sha256": _sha256(args.output_video) if video_exists else None,
            **video,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--depth-encoder-checkpoint", type=Path)
    parser.add_argument("--high-actor-checkpoint", type=Path)
    parser.add_argument("--bbc-checkpoint", type=Path)
    parser.add_argument("--keep-bbc-history", action="store_true")
    parser.add_argument(
        "--stairs-fragment", type=Path, default=STAIRS_FRAGMENT
    )
    parser.add_argument("--episode-steps", type=int, default=EPISODE_STEPS)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    if args.depth_encoder_checkpoint is not None and (
        not args.depth_encoder_checkpoint.is_file()
    ):
        parser.error(f"missing checkpoint: {args.depth_encoder_checkpoint}")
    suffix = "-FT1" if args.depth_encoder_checkpoint is not None else ""
    args.run_id = f"NAG-701-STAIRS{suffix}"
    args.output_dir = args.output_dir or RESULTS_ROOT / (
        "ft1" if suffix else "released"
    )
    args.stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    args.output_video = args.output_dir / f"stairs_10s{suffix}.mp4"
    return args


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    result_path = args.output_dir / f"result_{args.stamp}.json"
    try:
        payload = run(args)
    except Exception as exc:
        payload = {
            "run_id": args.run_id,
            "status": "FAILED",
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "error": f"{type(exc).__name__}: {exc}",
        }
    _write_json(result_path, payload)
    shutil.copy2(result_path, args.output_dir / "result.json")
    print(f"{payload['status']}: {result_path}")
    return 0 if payload["status"] == "PASSED" else 1



if __name__ == "__main__":
    raise SystemExit(main())
