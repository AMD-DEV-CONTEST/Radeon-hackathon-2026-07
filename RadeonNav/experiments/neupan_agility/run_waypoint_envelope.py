#!/usr/bin/env python3
"""Flat waypoint-acceptance-envelope run for the injected (cell-D) depth student.

Preregistered in EXPERIMENT_PLAN.md M3s/NAG-251: parameterized flat paths are
converted to the TSC current/next delta-yaw contract by bridge.path_to_tsc_waypoints
(lookahead 0.35/0.70 m, clip 0.60 rad) and injected into the frozen depth student
together with the free-space obstacle class. No obstacle fragment is loaded.
"""

from __future__ import annotations

import argparse
import math
import os
import shutil
import sys
import time
from collections import Counter
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
    RESULTS_ROOT,
    ROBOT_JOINTS,
    ContactProbe,
    SourceDepthCamera,
    _video_metadata,
)
from source_tasks import (  # noqa: E402
    GOAL_THRESHOLD_M,
    SCAN_X,
    SCAN_Y,
    SOURCE_FRICTION,
    flat_physics_terrain,
)
from unilab.algos.torch.quadrupedal_agility import (  # noqa: E402
    AgilityTscPolicyAdapter,
    agility_action_to_unilab,
)

ARC_LENGTH_M = 4.0
SAMPLE_SPACING_M = 0.05
CURRENT_LOOKAHEAD_M = 0.35
NEXT_LOOKAHEAD_M = 0.70
MAX_ABS_YAW_RAD = 0.60
# Free-space obstacle class for flat envelope runs (preregistered): frame (1).
# D-frame flat approach is clean and frame is the encoder's own dominant
# prediction on sparse scenes (M2e telemetry).
FREE_SPACE_OBSTACLE_INDEX = 1
SLALOM_WAVELENGTH_M = 4.0

CONDITIONS: dict[str, dict[str, float | str]] = {
    "K000": {"kind": "arc", "kappa": 0.0},
    "K020": {"kind": "arc", "kappa": 0.2},
    "K040": {"kind": "arc", "kappa": 0.4},
    "K070": {"kind": "arc", "kappa": 0.7},
    "K100": {"kind": "arc", "kappa": 1.0},
    "YP040": {"kind": "arc", "kappa": 0.0, "initial_yaw": 0.4},
    "YM040": {"kind": "arc", "kappa": 0.0, "initial_yaw": -0.4},
    "YP080": {"kind": "arc", "kappa": 0.0, "initial_yaw": 0.8},
    "YM080": {"kind": "arc", "kappa": 0.0, "initial_yaw": -0.8},
    "YP120": {"kind": "arc", "kappa": 0.0, "initial_yaw": 1.2},
    "YM120": {"kind": "arc", "kappa": 0.0, "initial_yaw": -1.2},
    "A050": {"kind": "slalom", "amplitude": 0.5},
    "A100": {"kind": "slalom", "amplitude": 1.0},
    "S050": {"kind": "arc", "kappa": 0.4, "spacing": 0.5},
    "S100": {"kind": "arc", "kappa": 0.4, "spacing": 1.0},
}


def generate_path(
    kind: str,
    *,
    kappa: float = 0.0,
    amplitude: float = 0.0,
    spacing: float = SAMPLE_SPACING_M,
) -> np.ndarray:
    """Sample the first 4.0 m of arc length of the parameterized curve.

    The curve starts at the origin with tangent +x; the robot is spawned at the
    origin, so the first waypoint sits `spacing` metres of arc ahead of it.
    """
    if spacing <= 0.0 or spacing > ARC_LENGTH_M:
        raise ValueError("spacing must be in (0, 4.0] m")
    distances = np.arange(spacing, ARC_LENGTH_M + 1e-9, spacing)
    if kind == "arc":
        if abs(kappa) < 1e-12:
            return np.stack(
                (distances, np.zeros_like(distances)), axis=1
            ).astype(np.float64)
        radius = 1.0 / kappa
        angles = distances * kappa
        return np.stack(
            (radius * np.sin(angles), radius * (1.0 - np.cos(angles))), axis=1
        ).astype(np.float64)
    if kind == "slalom":
        dense_x = np.linspace(0.0, 2.0 * ARC_LENGTH_M, 32001)
        dense_y = amplitude * np.sin(2.0 * np.pi * dense_x / SLALOM_WAVELENGTH_M)
        points = np.stack((dense_x, dense_y), axis=1)
        segments = np.linalg.norm(np.diff(points, axis=0), axis=1)
        cumulative = np.concatenate(([0.0], np.cumsum(segments)))
        if cumulative[-1] < ARC_LENGTH_M:
            raise ValueError("slalom dense sampling does not cover 4.0 m of arc")
        indices = np.searchsorted(cumulative, distances)
        return points[np.minimum(indices, len(points) - 1)].astype(np.float64)
    raise ValueError(f"unknown path kind: {kind}")


def condition_paths(condition: str) -> tuple[np.ndarray, np.ndarray, float]:
    """Return (policy-facing path, dense metric path, initial robot yaw).

    The robot spawns aligned with the path tangent at the origin (preregistered
    "初始朝向为路径切向"), which for slaloms is atan2(A*2*pi, wavelength); the
    YP/YM conditions override it with an explicit approach-yaw offset.
    """
    spec = dict(CONDITIONS[condition])
    kind = str(spec.pop("kind"))
    if kind == "slalom":
        default_yaw = math.atan2(
            2.0 * math.pi * float(spec["amplitude"]), SLALOM_WAVELENGTH_M
        )
    else:
        default_yaw = 0.0
    initial_yaw = float(spec.pop("initial_yaw", default_yaw))
    spacing = float(spec.pop("spacing", SAMPLE_SPACING_M))
    parameters = {key: float(value) for key, value in spec.items()}
    policy_path = generate_path(kind, spacing=spacing, **parameters)
    dense_path = generate_path(kind, spacing=SAMPLE_SPACING_M, **parameters)
    return policy_path, dense_path, initial_yaw


def remaining_policy_path(
    policy_path: np.ndarray,
    policy_arc_m: np.ndarray,
    dense_path: np.ndarray,
    robot_xy: np.ndarray,
    consumed_points: int,
) -> tuple[np.ndarray, int]:
    """Drop policy waypoints the robot has already passed.

    path_to_tsc_waypoints measures its lookahead from the robot through the
    path points in order, so it requires planner remaining-path semantics
    (NeuPAN replans from the current state each cycle). Progress is the arc
    position of the nearest dense-curve sample and is kept monotone so slalom
    projection ambiguity cannot move the horizon backwards. The final waypoint
    is never consumed, so the bridge always receives a non-empty path.
    """
    nearest_dense = int(
        np.argmin(
            np.linalg.norm(
                dense_path - np.asarray(robot_xy, dtype=np.float64).reshape(1, 2),
                axis=1,
            )
        )
    )
    arc_progress_m = (nearest_dense + 1) * SAMPLE_SPACING_M
    consumed = max(
        consumed_points,
        int(np.searchsorted(policy_arc_m, arc_progress_m, side="left")),
    )
    return policy_path[min(consumed, len(policy_path) - 1) :], consumed


def cross_track_error_m(base_xy: np.ndarray, dense_path: np.ndarray) -> float:
    """Distance from the base to the nearest densely sampled path point."""
    deltas = dense_path - np.asarray(base_xy, dtype=np.float64).reshape(1, 2)
    return float(np.min(np.linalg.norm(deltas, axis=1)))


def _base_yaw(base_quat_wxyz: np.ndarray) -> float:
    w, x, y, z = np.asarray(base_quat_wxyz, dtype=np.float64).reshape(4)
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


def _set_start_state(env: Any, initial_yaw: float, low_contract: Any) -> None:
    qpos = np.asarray(env._init_qpos, dtype=np.float32).reshape(1, -1).copy()
    qvel = np.zeros_like(env._init_qvel, dtype=np.float32).reshape(1, -1)
    qpos[0, :3] = (0.0, 0.0, 0.42)
    half = initial_yaw / 2.0
    qpos[0, 3:7] = (math.cos(half), 0.0, 0.0, math.sin(half))
    indices = env._backend.get_joint_dof_pos_indices(ROBOT_JOINTS) + 7
    qpos[0, indices] = low_contract.source_default_dof
    env._backend.set_state(np.asarray([0], dtype=np.int32), qpos, qvel)


def run(args: argparse.Namespace) -> dict[str, Any]:
    if args.duration != 10.0:
        raise ValueError("envelope gate requires exactly 10.0 seconds")
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    torch.cuda.manual_seed_all(args.seed)
    device = _device(args.device)
    profile = POLICY_PROFILES["deployment3"]
    policy_path, dense_path, initial_yaw = condition_paths(args.condition)
    path_end_xy = dense_path[-1]
    policy_spacing = float(
        CONDITIONS[args.condition].get("spacing", SAMPLE_SPACING_M)
    )
    policy_arc_m = (np.arange(len(policy_path)) + 1) * policy_spacing
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
    env = _compose_env(
        terrain_generator_override=flat_physics_terrain(args.seed),
        terrain_scan_override={
            "measured_points_x": list(SCAN_X),
            "measured_points_y": list(SCAN_Y),
            "vertical_offset": 0.3,
            "scale": 1.0,
        },
        scene_fragment_files=[],
        ground_friction=args.friction,
        control_gains=(40.0, 1.0),
        simulate_action_latency=True,
    )
    depth_camera = SourceDepthCamera(env, 0.0)
    num_steps = int(round(args.duration / float(env.cfg.ctrl_dt)))
    if num_steps != 500:
        raise RuntimeError(f"expected 500 control steps, got {num_steps}")
    args.output_video.parent.mkdir(parents=True, exist_ok=True)
    probe = ContactProbe(env)

    positions: list[list[float]] = []
    skills: list[int] = []
    commands: list[list[float]] = []
    injected_delta_yaws: list[list[float]] = []
    predicted_delta_yaws: list[list[float]] = []
    predicted_obstacles: list[int] = []
    cross_track_errors: list[float] = []
    yaw_clipped_steps: list[int] = []
    inference_ms: list[float] = []
    forbidden_steps: list[int] = []
    contact_pairs: Counter[str] = Counter()
    done_steps: list[int] = []
    reached_step: int | None = None
    reached_position: list[float] | None = None
    consumed_points = 0
    skill_switches = 0
    last_skill: int | None = None
    all_finite = True
    shape_contract = True
    previous_foot_contact = np.zeros((1, 4), dtype=np.float32)
    live_contract: dict[str, Any] = {}
    started = time.monotonic()

    def initialize():
        nonlocal previous_foot_contact, live_contract
        live_contract = _live_env_contract(env)
        if not bool(live_contract["passed"]):
            raise RuntimeError(f"live UniLab action contract mismatch: {live_contract}")
        state = env.init_state()
        env.set_autoreset(False)
        _set_start_state(env, initial_yaw, profile.low_contract)
        state = env.update_state(state)
        adapter.reset()
        state.info["current_actions"] = agility_action_to_unilab(
            np.zeros((1, 12), dtype=np.float32),
            profile.low_contract,
        )
        previous_foot_contact.fill(0.0)
        return state

    def step(state):
        nonlocal all_finite, reached_step, reached_position, shape_contract
        nonlocal skill_switches, last_skill, previous_foot_contact, consumed_points
        step_index = len(positions) + 1
        base_quat = env._backend.get_base_quat().copy()
        base_pos = env._backend.get_base_pos().copy()
        if reached_step is None and (
            float(np.linalg.norm(base_pos[0, :2] - path_end_xy)) < GOAL_THRESHOLD_M
        ):
            reached_step = step_index - 1
            reached_position = base_pos[0].tolist()
        remaining_path, consumed_points = remaining_policy_path(
            policy_path,
            policy_arc_m,
            dense_path,
            base_pos[0, :2],
            consumed_points,
        )
        waypoint = path_to_tsc_waypoints(
            remaining_path,
            np.asarray(
                [base_pos[0, 0], base_pos[0, 1], _base_yaw(base_quat[0])],
                dtype=np.float64,
            ),
            CURRENT_LOOKAHEAD_M,
            NEXT_LOOKAHEAD_M,
            MAX_ABS_YAW_RAD,
        )
        delta_yaw = np.asarray(
            [[waypoint.delta_yaw, waypoint.delta_next_yaw]], dtype=np.float32
        )
        if waypoint.yaw_clipped:
            yaw_clipped_steps.append(step_index)
        cross_track_errors.append(cross_track_error_m(base_pos[0, :2], dense_path))
        contact = probe.sample()
        sensor_floor_contact = (np.linalg.norm(env.feet_force, axis=2) > 2.0).astype(
            np.float32
        )
        current_foot_contact = np.maximum(contact["foot_contact"], sensor_floor_contact)
        foot_contact = np.maximum(current_foot_contact, previous_foot_contact)
        previous_foot_contact = current_foot_contact
        inference_started = time.perf_counter()
        action, diagnostics = adapter.act(
            base_quat_wxyz=base_quat,
            base_ang_vel=env.get_gyro().copy(),
            dof_pos=env.get_dof_pos().copy(),
            dof_vel=env.get_dof_vel().copy(),
            foot_contact=foot_contact,
            depth_image=depth_camera.capture(),
            delta_yaw=delta_yaw,
            obstacle_type=FREE_SPACE_OBSTACLE_INDEX,
        )
        if device.type == "cuda":
            torch.cuda.synchronize(device)
        inference_ms.append((time.perf_counter() - inference_started) * 1000.0)
        shape_contract = shape_contract and (
            diagnostics["high_input"].shape == (1, 771)
            and diagnostics["skill"].shape == (1,)
            and diagnostics["high_continuous"].shape == (1, 18)
            and diagnostics["command"].shape == (1, profile.command_dim)
            and diagnostics["low_input"].shape == (1, profile.bbc_input_dim)
            and diagnostics["source_action"].shape == (1, 12)
            and diagnostics["depth_image"].shape == (1, 58, 87)
            and diagnostics["depth_latent"].shape == (1, 40)
            and diagnostics["predicted_delta_yaw"].shape == (1, 2)
            and diagnostics["obstacle_probabilities"].shape == (1, 6)
            and diagnostics["actor_delta_yaw"].shape == (1, 2)
            and diagnostics["actor_obstacle_one_hot"].shape == (1, 6)
            and action.shape == (1, 12)
        )
        injected_delta_yaws.append(delta_yaw[0].tolist())
        predicted_delta_yaws.append(diagnostics["predicted_delta_yaw"][0].tolist())
        predicted_obstacles.append(int(diagnostics["predicted_obstacle"][0]))
        skill = int(diagnostics["skill"][0])
        if last_skill != skill and last_skill is not None:
            skill_switches += 1
        last_skill = skill
        skills.append(skill)
        commands.append(diagnostics["command"][0].tolist())
        state = env.step(action)
        if np.any(state.terminated | state.truncated):
            done_steps.append(step_index)
        base_after = env._backend.get_base_pos().copy()
        positions.append(base_after[0].tolist())
        after_contact = probe.sample()
        if after_contact["pairs"]:
            contact_pairs.update(after_contact["pairs"])
        if after_contact["forbidden"]:
            forbidden_steps.append(step_index)
        all_finite = all_finite and all(
            np.isfinite(value).all()
            for value in (
                action,
                delta_yaw,
                diagnostics["depth_image"],
                diagnostics["depth_latent"],
                diagnostics["high_input"],
                diagnostics["command"],
                diagnostics["low_input"],
                diagnostics["source_action"],
                base_after,
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
                "cam_distance": 3.5,
                "cam_elevation": -18.0,
                "cam_azimuth": 135.0,
            },
        )
    finally:
        depth_camera.close()
        env.close()

    video_exists = rendered_path is not None and args.output_video.is_file()
    video = _video_metadata(args.output_video) if video_exists else {}
    gate_end_step = reached_step or len(positions)
    forbidden_before_success = [
        step for step in forbidden_steps if step <= gate_end_step
    ]
    done_before_success = [step for step in done_steps if step <= gate_end_step]
    heights_before_success = [
        position[2] for position in positions[:gate_end_step]
    ]
    pre_success_cross_track = cross_track_errors[:gate_end_step]
    checks = {
        "live_env_action_contract": bool(live_contract["passed"]),
        "policy_io_contract": shape_contract,
        "rollout_finite": all_finite,
        "step_count": len(positions) == 500,
        "video_created": video_exists,
        "video_500_frames": video.get("frames") == 500,
        "video_50_fps": abs(float(video.get("fps", 0.0)) - 50.0) < 1.0e-6,
        "no_early_termination_before_success": not done_before_success,
        "no_forbidden_contact_before_success": not forbidden_before_success,
        "base_clearance_before_success": min(heights_before_success) > 0.16,
        "reached_path_end": reached_step is not None,
    }
    unique, counts = np.unique(skills, return_counts=True)
    prediction_error = np.abs(
        np.asarray(predicted_delta_yaws, dtype=np.float64)
        - np.asarray(injected_delta_yaws, dtype=np.float64)
    )
    elapsed = time.monotonic() - started
    return {
        "run_id": args.run_id,
        "condition": args.condition,
        "status": "PASSED" if all(checks.values()) else "FAILED",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "evaluation_type": "simulation_only",
        "scope": (
            "flat waypoint acceptance envelope; frozen depth student cell-D "
            "injection (bridge planner yaw + free-space one-hot)"
        ),
        "seed": args.seed,
        "duration_sec": args.duration,
        "ctrl_dt": float(env.cfg.ctrl_dt),
        "steps": len(positions),
        "device": str(device),
        "device_name": torch.cuda.get_device_name(device),
        "checks": checks,
        "metrics": {
            "initial_yaw_rad": initial_yaw,
            "path_end_xy_m": path_end_xy.tolist(),
            "final_base_xyz_m": positions[-1],
            "reached_step": reached_step,
            "reached_position_m": reached_position,
            "final_distance_to_path_end_m": float(
                np.linalg.norm(
                    np.asarray(positions[-1][:2], dtype=np.float64) - path_end_xy
                )
            ),
            "cross_track_error_mean_m": float(np.mean(pre_success_cross_track)),
            "cross_track_error_max_m": float(np.max(pre_success_cross_track)),
            "yaw_clipped_fraction": len(
                [step for step in yaw_clipped_steps if step <= gate_end_step]
            )
            / max(gate_end_step, 1),
            "min_base_z_before_success_m": min(heights_before_success),
            "skill_switch_count": skill_switches,
            "forbidden_contact_steps": forbidden_steps,
            "forbidden_contact_before_success_steps": forbidden_before_success,
            "done_steps": done_steps,
            "injected_delta_yaw_mean": np.mean(
                injected_delta_yaws, axis=0
            ).tolist(),
            "predicted_delta_yaw_mean": np.mean(
                predicted_delta_yaws, axis=0
            ).tolist(),
            "predicted_injected_yaw_abs_error_mean": np.mean(
                prediction_error, axis=0
            ).tolist(),
            "predicted_obstacle_counts": {
                str(index): predicted_obstacles.count(index)
                for index in sorted(set(predicted_obstacles))
            },
            "predicted_free_space_agreement_rate": float(
                np.mean(
                    [
                        index == FREE_SPACE_OBSTACLE_INDEX
                        for index in predicted_obstacles
                    ]
                )
            ),
            "inference_ms_mean": float(np.mean(inference_ms)),
            "inference_ms_p99": float(np.quantile(inference_ms, 0.99)),
            "wall_time_sec": elapsed,
            "gpu_hours": elapsed / 3600.0,
        },
        "skill_counts": {
            str(int(skill)): int(count) for skill, count in zip(unique, counts)
        },
        "contact_pair_counts": dict(contact_pairs.most_common()),
        "final_bbc_command": commands[-1],
        "contracts": {
            "condition_spec": {
                key: value for key, value in CONDITIONS[args.condition].items()
            },
            "arc_length_m": ARC_LENGTH_M,
            "policy_path_spacing_m": float(
                CONDITIONS[args.condition].get("spacing", SAMPLE_SPACING_M)
            ),
            "policy_path_points": len(policy_path),
            "path_feed": (
                "remaining-path (receding-horizon): passed waypoints consumed "
                "via monotone dense-curve arc projection, matching planner "
                "replan-from-current-state semantics; final waypoint retained"
            ),
            "current_lookahead_m": CURRENT_LOOKAHEAD_M,
            "next_lookahead_m": NEXT_LOOKAHEAD_M,
            "max_abs_yaw_rad": MAX_ABS_YAW_RAD,
            "goal_threshold_m": GOAL_THRESHOLD_M,
            "free_space_obstacle_index": FREE_SPACE_OBSTACLE_INDEX,
            "high_branch": "depth student depth_actor + depth_encoder",
            "precision": "float16",
            "actor_yaw_source": "bridge_planner_path",
            "actor_onehot_source": "free_space_constant",
            "high_checkpoint": str(HIGH_CHECKPOINT),
            "high_checkpoint_sha256": _sha256(HIGH_CHECKPOINT),
            "low_checkpoint": str(profile.low_checkpoint),
            "low_checkpoint_sha256": _sha256(profile.low_checkpoint),
            "bbc_input_dim": profile.bbc_input_dim,
            "history_semantics": "zero 570-D, matching go2_deploy HistoryWrapper.step()",
            "friction": args.friction,
            "physics": "flat hfield; no obstacle fragment",
            "perception": (
                "MuJoCo body-mounted depth; actor yaw=planner path, "
                "actor one-hot=free-space constant"
            ),
            "runner_sha256": _sha256(Path(__file__)),
            "bridge_sha256": _sha256(Path(__file__).resolve().parent / "bridge.py"),
            "adapter_sha256": _sha256(
                ROOT / "UniLab/src/unilab/algos/torch/quadrupedal_agility.py"
            ),
        },
        "video": {
            "path": str(args.output_video),
            "bytes": args.output_video.stat().st_size if video_exists else 0,
            "sha256": _sha256(args.output_video) if video_exists else None,
            **video,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--condition", choices=tuple(CONDITIONS), required=True)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--duration", type=float, default=10.0)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--friction", type=float, default=SOURCE_FRICTION)
    args = parser.parse_args()
    if not 0.6 <= args.friction <= 2.0:
        parser.error("--friction must stay within the source range [0.6, 2.0]")
    args.run_id = f"NAG-251-{args.condition}"
    args.output_dir = args.output_dir or RESULTS_ROOT / args.run_id
    args.stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    args.output_video = args.output_dir / f"envelope_{args.condition}_10s_{args.stamp}.mp4"
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
            "condition": args.condition,
            "status": "FAILED",
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "error": f"{type(exc).__name__}: {exc}",
        }
    _write_json(result_path, payload)
    shutil.copy2(result_path, args.output_dir / "result.json")
    if args.output_video.is_file():
        shutil.copy2(
            args.output_video,
            args.output_dir / f"envelope_{args.condition}_10s.mp4",
        )
    print(f"{payload['status']}: {result_path}")
    return 0 if payload["status"] == "PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
