#!/usr/bin/env python3
"""NAG-401: static 2.5D skill-aware closed loop for the injected depth student.

Preregistered in EXPERIMENT_PLAN.md M4: a two-channel static map is planned
with A*, the path is fed through the NAG-251 receding-horizon bridge contract,
and the obstacle one-hot follows the map-side path-arc class schedule. Frozen
student-D chain (FP16, deployment3 low, zero history), nominal mu = 1.0.
"""

from __future__ import annotations

import argparse
import math
import os
import shutil
import sys
import time
from collections import Counter
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

os.environ.setdefault("MUJOCO_GL", "egl")

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "experiments/cpp_adapter"))

from bridge import path_to_tsc_waypoints, wrap_to_pi  # noqa: E402
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
from run_waypoint_envelope import (  # noqa: E402
    CURRENT_LOOKAHEAD_M,
    MAX_ABS_YAW_RAD,
    NEXT_LOOKAHEAD_M,
    _base_yaw,
    cross_track_error_m,
    remaining_policy_path,
)
from source_tasks import (  # noqa: E402
    GOAL_THRESHOLD_M,
    SCAN_X,
    SCAN_Y,
    SOURCE_FRICTION,
    TASKS,
    configured_fragment,
    flat_physics_terrain,
)
from static_2p5d import (  # noqa: E402
    CLASS_ENTRY_MARGIN_M,
    CLASS_EXIT_MARGIN_M,
    FREE_SPACE_CLASS,
    INFLATION_RADIUS_M,
    PATH_SPACING_M,
    PLANNING_RESOLUTION_M,
    SCENARIOS,
    class_at_arc,
    path_heading_changes,
    plan_scenario,
    wall_fragment,
)
from unilab.algos.torch.quadrupedal_agility import (  # noqa: E402
    AgilityTscPolicyAdapter,
    agility_action_to_unilab,
)


# NAG-402: jump-approach feed revision (EXPERIMENT_PLAN.md M4b). Only these
# obstacle classes get a modified waypoint feed inside their class interval;
# walk-class intervals and free space use the NAG-251 contract unchanged.
JUMP_CLASSES = (0, 4)  # bar, tire
JUMP_LONGLOOK_M = (0.90, 1.80)  # source adjacent / next-next goal spacing


def feed_lookaheads(jump_feed: str, in_jump_interval: bool) -> tuple[float, float]:
    if jump_feed == "longlook" and in_jump_interval:
        return JUMP_LONGLOOK_M
    return (CURRENT_LOOKAHEAD_M, NEXT_LOOKAHEAD_M)


def committed_delta_yaw(
    committed_headings: tuple[float, float], base_yaw: float
) -> tuple[np.ndarray, bool]:
    """Delta-yaw pair holding the absolute headings committed at interval entry.

    Returns the clipped pair and whether the 0.60 rad clip engaged (recorded
    separately from the raw-feed yaw_clipped telemetry).
    """
    raw = (
        wrap_to_pi(committed_headings[0] - base_yaw),
        wrap_to_pi(committed_headings[1] - base_yaw),
    )
    clipped = any(abs(value) > MAX_ABS_YAW_RAD for value in raw)
    pair = np.asarray(
        [
            [
                float(np.clip(raw[0], -MAX_ABS_YAW_RAD, MAX_ABS_YAW_RAD)),
                float(np.clip(raw[1], -MAX_ABS_YAW_RAD, MAX_ABS_YAW_RAD)),
            ]
        ],
        dtype=np.float32,
    )
    return pair, clipped


def update_class_state(
    intervals: tuple,
    class_arc_m: float,
    nearest_dense_index: int,
) -> tuple[float, int]:
    """Monotone arc progress and the scheduled class at that arc."""
    class_arc_m = max(class_arc_m, (nearest_dense_index + 1) * PATH_SPACING_M)
    return class_arc_m, class_at_arc(intervals, class_arc_m)


def class_switch_event(
    step_index: int,
    previous: int,
    current: int,
    arc_m: float,
    skill: int,
    base_xyz: list[float],
) -> dict[str, Any]:
    return {
        "step": step_index,
        "from": previous,
        "to": current,
        "arc_m": arc_m,
        "skill": skill,
        "base_xyz_m": base_xyz,
    }


def _set_start_state(
    env: Any,
    start_xy: tuple[float, float],
    initial_yaw: float,
    low_contract: Any,
    obstacle_joint: tuple[str, float] | None,
) -> None:
    qpos = np.asarray(env._init_qpos, dtype=np.float32).reshape(1, -1).copy()
    qvel = np.zeros_like(env._init_qvel, dtype=np.float32).reshape(1, -1)
    qpos[0, :3] = (start_xy[0], start_xy[1], 0.42)
    half = initial_yaw / 2.0
    qpos[0, 3:7] = (math.cos(half), 0.0, 0.0, math.sin(half))
    indices = env._backend.get_joint_dof_pos_indices(ROBOT_JOINTS) + 7
    qpos[0, indices] = low_contract.source_default_dof
    if obstacle_joint is not None:
        joint_name, joint_qpos = obstacle_joint
        obstacle_index = (
            int(env._backend.get_joint_dof_pos_indices((joint_name,))[0]) + 7
        )
        qpos[0, obstacle_index] = joint_qpos
    env._backend.set_state(np.asarray([0], dtype=np.int32), qpos, qvel)


def run(args: argparse.Namespace) -> dict[str, Any]:
    spec = SCENARIOS[args.scenario]
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    torch.cuda.manual_seed_all(args.seed)
    device = _device(args.device)
    profile = POLICY_PROFILES["deployment3"]
    plan = plan_scenario(spec)
    dense_path: np.ndarray = plan["dense_path"]
    intervals = plan["intervals"]
    initial_yaw: float = plan["initial_yaw"]
    policy_path = dense_path
    policy_arc_m = (np.arange(len(policy_path)) + 1) * PATH_SPACING_M
    goal_xy = np.asarray(spec.goal_xy, dtype=np.float64)
    heading_changes = path_heading_changes(dense_path)
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
        class _NoFill(np.ndarray):
            def fill(self, value):  # noqa: ARG002
                return None

        adapter.bbc.history = (
            np.zeros((1, 570), dtype=np.float32).view(_NoFill)
        )
    with ExitStack() as stack:
        fragments: list[str] = []
        fragment_hashes: dict[str, str] = {}
        if spec.wall_position_xy is not None:
            wall_path = stack.enter_context(wall_fragment(spec.wall_position_xy))
            fragments.append(str(wall_path))
            fragment_hashes["wall"] = _sha256(wall_path)
        if spec.task_fragment is not None:
            task_spec = TASKS[spec.task_fragment]
            bar_height = 0.20
            if spec.task_fragment == "bar_jump" and spec.obstacle_joint:
                bar_height = spec.obstacle_joint[1]
            task_path = stack.enter_context(
                configured_fragment(task_spec, bar_height=bar_height)
            )
            fragments.append(str(task_path))
            fragment_hashes[spec.task_fragment] = _sha256(task_path)
        env = _compose_env(
            terrain_generator_override=flat_physics_terrain(args.seed),
            terrain_scan_override={
                "measured_points_x": list(SCAN_X),
                "measured_points_y": list(SCAN_Y),
                "vertical_offset": 0.3,
                "scale": 1.0,
            },
            scene_fragment_files=fragments,
            ground_friction=args.friction,
            control_gains=(40.0, 1.0),
            simulate_action_latency=True,
        )
    depth_camera = SourceDepthCamera(env, 0.0)
    num_steps = int(round(spec.duration_sec / float(env.cfg.ctrl_dt)))
    if num_steps != int(spec.duration_sec * 50):
        raise RuntimeError(
            f"expected {int(spec.duration_sec * 50)} control steps, got {num_steps}"
        )
    args.output_video.parent.mkdir(parents=True, exist_ok=True)
    probe = ContactProbe(env)
    obstacle_joint_index = (
        int(env._backend.get_joint_dof_pos_indices((spec.obstacle_joint[0],))[0])
        if spec.obstacle_joint is not None
        else None
    )

    positions: list[list[float]] = []
    skills: list[int] = []
    commands: list[list[float]] = []
    active_classes: list[int] = []
    class_switch_events: list[dict[str, Any]] = []
    injected_delta_yaws: list[list[float]] = []
    predicted_delta_yaws: list[list[float]] = []
    predicted_obstacles: list[int] = []
    cross_track_errors: list[float] = []
    arc_progress_trace: list[float] = []
    yaw_clipped_steps: list[int] = []
    obstacle_joint_positions: list[float] = []
    inference_ms: list[float] = []
    forbidden_steps: list[int] = []
    contact_pairs: Counter[str] = Counter()
    done_steps: list[int] = []
    reached_step: int | None = None
    reached_position: list[float] | None = None
    consumed_points = 0
    class_arc_m = 0.0
    committed_headings: tuple[float, float] | None = None
    commit_events: list[dict[str, Any]] = []
    commit_clip_steps: list[int] = []
    skill_switches = 0
    last_skill: int | None = None
    last_class: int | None = None
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
        _set_start_state(
            env,
            spec.start_xy,
            initial_yaw,
            profile.low_contract,
            spec.obstacle_joint,
        )
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
        nonlocal skill_switches, last_skill, last_class
        nonlocal previous_foot_contact, consumed_points, class_arc_m
        nonlocal committed_headings
        step_index = len(positions) + 1
        base_quat = env._backend.get_base_quat().copy()
        base_pos = env._backend.get_base_pos().copy()
        if reached_step is None and (
            float(np.linalg.norm(base_pos[0, :2] - goal_xy)) < GOAL_THRESHOLD_M
        ):
            reached_step = step_index - 1
            reached_position = base_pos[0].tolist()
        robot_xy = base_pos[0, :2]
        nearest_dense = int(
            np.argmin(np.linalg.norm(dense_path - robot_xy.reshape(1, 2), axis=1))
        )
        # Monotone arc progress, matching the receding-horizon path consumption
        # semantics, so projection ambiguity cannot flicker the class schedule.
        class_arc_m, active_class = update_class_state(
            intervals, class_arc_m, nearest_dense
        )
        arc_progress_trace.append(class_arc_m)
        remaining_path, consumed_points = remaining_policy_path(
            policy_path,
            policy_arc_m,
            dense_path,
            robot_xy,
            consumed_points,
        )
        base_yaw_now = _base_yaw(base_quat[0])
        in_jump_interval = active_class in JUMP_CLASSES
        current_lookahead, next_lookahead = feed_lookaheads(
            args.jump_feed, in_jump_interval
        )
        waypoint = path_to_tsc_waypoints(
            remaining_path,
            np.asarray(
                [base_pos[0, 0], base_pos[0, 1], base_yaw_now],
                dtype=np.float64,
            ),
            current_lookahead,
            next_lookahead,
            MAX_ABS_YAW_RAD,
        )
        delta_yaw = np.asarray(
            [[waypoint.delta_yaw, waypoint.delta_next_yaw]], dtype=np.float32
        )
        if waypoint.yaw_clipped:
            yaw_clipped_steps.append(step_index)
        if args.jump_feed == "commit":
            if in_jump_interval:
                if committed_headings is None:
                    committed_headings = (
                        base_yaw_now + float(delta_yaw[0, 0]),
                        base_yaw_now + float(delta_yaw[0, 1]),
                    )
                    commit_events.append(
                        {
                            "step": step_index,
                            "arc_m": class_arc_m,
                            "committed_headings_rad": list(committed_headings),
                        }
                    )
                delta_yaw, commit_clipped = committed_delta_yaw(
                    committed_headings, base_yaw_now
                )
                if commit_clipped:
                    commit_clip_steps.append(step_index)
            elif committed_headings is not None:
                committed_headings = None
                commit_events.append(
                    {"step": step_index, "arc_m": class_arc_m, "released": True}
                )
        cross_track_errors.append(cross_track_error_m(robot_xy, dense_path))
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
            obstacle_type=active_class,
        )
        if args.keep_bbc_history:
            # NAG-901 scheduled-history contract: jump-class intervals (entry
            # widened 1.0 m so the primitive settles into its validated
            # zero-history regime before takeoff) zero the rolling history;
            # walk/terrain segments keep it.
            in_hist_zero = any(
                interval.s_start_m - 1.0 <= class_arc_m <= interval.s_end_m
                for interval in intervals
                if interval.label in JUMP_CLASSES
            )
            if in_hist_zero:
                adapter.bbc.history[:, :] = 0.0
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
        skill = int(diagnostics["skill"][0])
        if last_class is not None and active_class != last_class:
            class_switch_events.append(
                class_switch_event(
                    step_index,
                    last_class,
                    active_class,
                    class_arc_m,
                    skill,
                    base_pos[0].tolist(),
                )
            )
        last_class = active_class
        active_classes.append(active_class)
        injected_delta_yaws.append(delta_yaw[0].tolist())
        predicted_delta_yaws.append(diagnostics["predicted_delta_yaw"][0].tolist())
        predicted_obstacles.append(int(diagnostics["predicted_obstacle"][0]))
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
        if obstacle_joint_index is not None:
            obstacle_joint_positions.append(
                float(env._backend._dof_pos_view[0, obstacle_joint_index])
            )
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
    heights_before_success = [position[2] for position in positions[:gate_end_step]]
    pre_success_cross_track = cross_track_errors[:gate_end_step]
    checks = {
        "live_env_action_contract": bool(live_contract["passed"]),
        "policy_io_contract": shape_contract,
        "rollout_finite": all_finite,
        "step_count": len(positions) == num_steps,
        "video_created": video_exists,
        "video_frame_count": video.get("frames") == num_steps,
        "video_50_fps": abs(float(video.get("fps", 0.0)) - 50.0) < 1.0e-6,
        "no_early_termination_before_success": not done_before_success,
        "no_forbidden_contact_before_success": not forbidden_before_success,
        "base_clearance_before_success": min(heights_before_success) > 0.16,
        "reached_global_goal": reached_step is not None,
    }
    unique, counts = np.unique(skills, return_counts=True)
    jump_steps = [index + 1 for index, skill in enumerate(skills) if skill == 2]
    jump_steps_outside_intervals = [
        step
        for step in jump_steps
        if class_at_arc(intervals, arc_progress_trace[step - 1]) == FREE_SPACE_CLASS
    ]
    elapsed = time.monotonic() - started
    return {
        "run_id": args.run_id,
        "scenario": spec.name,
        "status": "PASSED" if all(checks.values()) else "FAILED",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "evaluation_type": "simulation_only",
        "scope": (
            "static 2.5D skill-aware closed loop; A* over forbidden+affordance "
            "map, receding-horizon bridge yaw, path-arc class schedule, frozen "
            "depth student cell-D injection"
        ),
        "seed": args.seed,
        "duration_sec": spec.duration_sec,
        "ctrl_dt": float(env.cfg.ctrl_dt),
        "steps": len(positions),
        "device": str(device),
        "device_name": torch.cuda.get_device_name(device),
        "checks": checks,
        "metrics": {
            "start_xy_m": list(spec.start_xy),
            "goal_xy_m": list(spec.goal_xy),
            "initial_yaw_rad": initial_yaw,
            "path_arc_length_m": float(policy_arc_m[-1]),
            "path_max_heading_change_rad": (
                float(np.max(heading_changes)) if len(heading_changes) else 0.0
            ),
            "final_base_xyz_m": positions[-1],
            "reached_step": reached_step,
            "reached_position_m": reached_position,
            "final_distance_to_goal_m": float(
                np.linalg.norm(
                    np.asarray(positions[-1][:2], dtype=np.float64) - goal_xy
                )
            ),
            "cross_track_error_mean_m": float(np.mean(pre_success_cross_track)),
            "cross_track_error_max_m": float(np.max(pre_success_cross_track)),
            "yaw_clipped_fraction": len(
                [step for step in yaw_clipped_steps if step <= gate_end_step]
            )
            / max(gate_end_step, 1),
            "min_base_z_before_success_m": min(heights_before_success),
            "max_arc_progress_m": max(arc_progress_trace),
            "class_switch_events": class_switch_events,
            "commit_events": commit_events,
            "commit_clip_step_count": len(commit_clip_steps),
            "class_step_counts": {
                str(label): active_classes.count(label)
                for label in sorted(set(active_classes))
            },
            "active_class_trace": active_classes,
            "skill_trace": skills,
            "jump_step_count": len(jump_steps),
            "jump_steps_outside_class_intervals": jump_steps_outside_intervals,
            "skill_switch_count": skill_switches,
            "forbidden_contact_steps": forbidden_steps,
            "forbidden_contact_before_success_steps": forbidden_before_success,
            "done_steps": done_steps,
            "obstacle_joint_qpos_min_max": (
                [min(obstacle_joint_positions), max(obstacle_joint_positions)]
                if obstacle_joint_positions
                else None
            ),
            "injected_delta_yaw_mean": np.mean(injected_delta_yaws, axis=0).tolist(),
            "predicted_delta_yaw_mean": np.mean(
                predicted_delta_yaws, axis=0
            ).tolist(),
            "predicted_obstacle_counts": {
                str(index): predicted_obstacles.count(index)
                for index in sorted(set(predicted_obstacles))
            },
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
            "scenario": spec.name,
            "task_fragment": spec.task_fragment,
            "wall_position_xy_m": spec.wall_position_xy,
            "obstacle_joint": spec.obstacle_joint,
            "planning_resolution_m": PLANNING_RESOLUTION_M,
            "inflation_radius_m": INFLATION_RADIUS_M,
            "path_spacing_m": PATH_SPACING_M,
            "class_entry_margin_m": CLASS_ENTRY_MARGIN_M,
            "class_exit_margin_m": CLASS_EXIT_MARGIN_M,
            "class_arc_semantics": "monotone nearest-dense arc projection",
            "free_space_class": FREE_SPACE_CLASS,
            "class_intervals": [
                {
                    "s_start_m": interval.s_start_m,
                    "s_end_m": interval.s_end_m,
                    "label": interval.label,
                }
                for interval in intervals
            ],
            "path_feed": (
                "remaining-path (receding-horizon), NAG-251 contract; A* corners "
                "bounded by 0.785 rad within the NAG-251 recovery envelope"
            ),
            "jump_feed": args.jump_feed,
            "jump_classes": list(JUMP_CLASSES),
            "jump_longlook_m": (
                list(JUMP_LONGLOOK_M) if args.jump_feed == "longlook" else None
            ),
            "commit_semantics": (
                "absolute headings captured at jump-interval entry; per-step "
                "wrap(committed - base_yaw) clipped to 0.60; released at exit"
                if args.jump_feed == "commit"
                else None
            ),
            "current_lookahead_m": CURRENT_LOOKAHEAD_M,
            "next_lookahead_m": NEXT_LOOKAHEAD_M,
            "max_abs_yaw_rad": MAX_ABS_YAW_RAD,
            "goal_threshold_m": GOAL_THRESHOLD_M,
            "high_branch": "depth student depth_actor + depth_encoder",
            "precision": "float16",
            "actor_yaw_source": "static_2p5d_astar_path",
            "actor_onehot_source": "map_affordance_schedule",
            "high_checkpoint": str(HIGH_CHECKPOINT),
            "high_checkpoint_sha256": _sha256(HIGH_CHECKPOINT),
            "low_checkpoint": str(profile.low_checkpoint),
            "low_checkpoint_sha256": _sha256(profile.low_checkpoint),
            "bbc_input_dim": profile.bbc_input_dim,
            "history_semantics": "zero 570-D, matching go2_deploy HistoryWrapper.step()",
            "friction": args.friction,
            "physics": "flat hfield + physical obstacle fragments; map walls are virtual",
            "perception": (
                "MuJoCo body-mounted depth; actor yaw=A* path, actor "
                "one-hot=map affordance schedule"
            ),
            "fragment_sha256": fragment_hashes,
            "runner_sha256": _sha256(Path(__file__)),
            "planner_sha256": _sha256(
                Path(__file__).resolve().parent / "static_2p5d.py"
            ),
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
    parser.add_argument("--scenario", choices=tuple(SCENARIOS), required=True)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--friction", type=float, default=SOURCE_FRICTION)
    parser.add_argument(
        "--jump-feed",
        choices=("default", "longlook", "commit"),
        default="default",
    )
    parser.add_argument("--depth-encoder-checkpoint", type=Path)
    parser.add_argument("--high-actor-checkpoint", type=Path)
    parser.add_argument("--bbc-checkpoint", type=Path)
    parser.add_argument("--keep-bbc-history", action="store_true")
    args = parser.parse_args()
    if not 0.6 <= args.friction <= 2.0:
        parser.error("--friction must stay within the source range [0.6, 2.0]")
    if args.depth_encoder_checkpoint is not None and (
        not args.depth_encoder_checkpoint.is_file()
    ):
        parser.error(f"missing checkpoint: {args.depth_encoder_checkpoint}")
    if args.jump_feed == "default":
        args.run_id = f"NAG-401-{args.scenario}"
    else:
        suffix = "LL" if args.jump_feed == "longlook" else "CM"
        args.run_id = f"NAG-402-{args.scenario}-{suffix}"
    if args.depth_encoder_checkpoint is not None:
        args.run_id += "-FT1"
    args.output_dir = args.output_dir or RESULTS_ROOT / args.run_id
    args.stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    args.output_video = (
        args.output_dir / f"static2p5d_{args.scenario}_{args.stamp}.mp4"
    )
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
            "scenario": args.scenario,
            "status": "FAILED",
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "error": f"{type(exc).__name__}: {exc}",
        }
    _write_json(result_path, payload)
    shutil.copy2(result_path, args.output_dir / "result.json")
    if args.output_video.is_file():
        shutil.copy2(
            args.output_video,
            args.output_dir / f"static2p5d_{args.scenario}.mp4",
        )
    print(f"{payload['status']}: {result_path}")
    return 0 if payload["status"] == "PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
