#!/usr/bin/env python3
"""NAG-601: maneuver-commit phase-gate benchmark (C4).

Preregistered in EXPERIMENT_PLAN.md M6 (2026-07-31 07:00 refinement). TR
scenario (tire jump) with one dynamic obstacle crossing at x=-0.6 whose
crossing time is anchored to jump events from a no-obstacle calibration run.
Arms: continuous (NeuPAN override, no freeze), ttc (straight feed + CM +
slow-to-min), oracle (freeze on GT phase), c4 (freeze on deployable phase
detector). Shared ep6 encoder, shared layouts, shared speed authority.
"""

from __future__ import annotations

import argparse
import json

import os
import shutil
import sys
import time
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
    ROBOT_JOINTS,
    ContactProbe,
    SourceDepthCamera,
    _video_metadata,
)
from run_static_2p5d import (  # noqa: E402
    JUMP_CLASSES,
    committed_delta_yaw,
    update_class_state,
)
from run_dynamic_planner import (  # noqa: E402
    COLLISION_DIST_M,
    build_neupan,
    obstacle_fragment,
    surface_points,
    ttc_slow,
)
from run_waypoint_envelope import (  # noqa: E402
    CURRENT_LOOKAHEAD_M,
    MAX_ABS_YAW_RAD,
    NEXT_LOOKAHEAD_M,
    _base_yaw,
    remaining_policy_path,
)
from source_tasks import (  # noqa: E402
    SCAN_X,
    SCAN_Y,
    TASKS,
    configured_fragment,
    flat_physics_terrain,
)
from static_2p5d import PATH_SPACING_M, SCENARIOS, plan_scenario  # noqa: E402
from unilab.algos.torch.quadrupedal_agility import (  # noqa: E402
    AgilityTscPolicyAdapter,
    agility_action_to_unilab,
)

RESULTS_ROOT = ROOT / "experiment-results/quadrupedal-agility/NAG-601"
GOAL_THRESHOLD_M = 0.4
EPISODE_STEPS = 500
REPLAN_PERIOD_STEPS = 5
NEUPAN_REF_SPEED = 0.8
CROSS_X = -0.6
TIMINGS = ("pre", "takeoff", "air", "land", "none")
ARMS = ("continuous", "ttc", "oracle", "c4")
AIRBORNE_CONSECUTIVE = 5
RECOVERY_CONSECUTIVE = 5
REFRESH_DEVIATION_RAD = 0.15
REFRESH_OBSTACLE_RADIUS_M = 2.0


def layout_for(
    timing: str, variant: int, reference_events: dict[str, int], ctrl_dt: float
) -> dict[str, float] | None:
    """One crossing obstacle anchored to calibrated jump events."""
    if timing == "none":
        return None
    offsets = {
        "pre": reference_events["skill2_onset"] * ctrl_dt - 1.0,
        "takeoff": reference_events["takeoff"] * ctrl_dt,
        "air": reference_events["air_mid"] * ctrl_dt,
        "land": reference_events["landing"] * ctrl_dt,
    }
    cross_t = max(offsets[timing], 0.5)
    direction = 1.0 if variant % 2 == 0 else -1.0
    speed = 0.4 + 0.05 * variant  # 0.4 .. 0.6
    return {
        "start_x": CROSS_X,
        "start_y": -direction * speed * cross_t,
        "vel_x": 0.0,
        "vel_y": direction * speed,
        "speed": speed,
        "cross_t": cross_t,
    }


class PhaseMachine:
    """NORMAL -> COMMITTED (skill 2 onset) -> release after landing."""

    def __init__(self, use_probe_truth: bool) -> None:
        self.use_probe_truth = use_probe_truth
        self.committed = False
        self.airborne_seen = False
        self.off_count = 0
        self.on_count = 0
        self.enter_step: int | None = None
        self.takeoff_step: int | None = None
        self.release_step: int | None = None
        self.disarmed = False

    def update(self, step: int, skill: int, feet_on: int, in_jump: bool) -> bool:
        """One commitment per jump-class interval (aligned with the validated
        CM semantics): commit on skill-2 onset inside the interval, release on
        landing recovery or interval exit, then stay disarmed until the next
        interval."""
        if not in_jump:
            if self.committed:
                self.committed = False
                if self.release_step is None:
                    self.release_step = step
            self.disarmed = False
            return False
        if self.disarmed:
            return False
        if not self.committed:
            if skill == 2:
                self.committed = True
                if self.enter_step is None:
                    self.enter_step = step
                self.airborne_seen = False
                self.off_count = 0
                self.on_count = 0
            return self.committed
        if feet_on == 0:
            self.off_count += 1
            self.on_count = 0
            if self.off_count >= AIRBORNE_CONSECUTIVE and not self.airborne_seen:
                self.airborne_seen = True
                self.takeoff_step = step - AIRBORNE_CONSECUTIVE + 1
        else:
            self.off_count = 0
            if self.airborne_seen and feet_on >= 2:
                self.on_count += 1
                if self.on_count >= RECOVERY_CONSECUTIVE:
                    self.committed = False
                    self.release_step = step
                    self.disarmed = True
        return self.committed


def run(args: argparse.Namespace) -> dict[str, Any]:
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    torch.cuda.manual_seed_all(args.seed)
    device = _device(args.device)
    profile = POLICY_PROFILES["deployment3"]
    scenario = SCENARIOS["TR"]
    plan = plan_scenario(scenario)
    dense_path = plan["dense_path"]
    intervals = plan["intervals"]
    policy_arc = (np.arange(len(dense_path)) + 1) * PATH_SPACING_M
    goal_xy = np.asarray(scenario.goal_xy, dtype=np.float64)
    if args.timing == "none":
        layout = None
    else:
        reference_events = json.loads(args.calibration_file.read_text())["metrics"][
            "events"
        ]
        layout = layout_for(args.timing, args.variant, reference_events, 0.02)

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
    override = torch.load(
        args.depth_encoder_checkpoint, map_location=device, weights_only=True
    )
    adapter.depth_encoder.load_state_dict(override)
    adapter.depth_encoder.half()
    adapter.depth_encoder.eval()

    planner = None
    shim = False
    if args.arm != "ttc":
        planner, shim = build_neupan()
        planner.reset()
        planner.pan.current_nom_values = [None] * 4

    with ExitStack() as stack:
        fragments = []
        tire_fragment = stack.enter_context(
            configured_fragment(TASKS["tire_jump"], bar_height=0.20)
        )
        fragments.append(str(tire_fragment))
        if layout is not None:
            dyn_fragment = stack.enter_context(obstacle_fragment(1))
            fragments.append(str(dyn_fragment))
        env = _compose_env(
            terrain_generator_override=flat_physics_terrain(args.seed),
            terrain_scan_override={
                "measured_points_x": list(SCAN_X),
                "measured_points_y": list(SCAN_Y),
                "vertical_offset": 0.3,
                "scale": 1.0,
            },
            scene_fragment_files=fragments,
            ground_friction=1.0,
            control_gains=(40.0, 1.0),
            simulate_action_latency=True,
        )
    depth_camera = SourceDepthCamera(env, 0.0)
    probe = ContactProbe(env)
    backend = env._backend
    ctrl_dt = float(env.cfg.ctrl_dt)
    obs_idx = None
    if layout is not None:
        jx = backend.model.joint("dyn_obs0_x")
        jy = backend.model.joint("dyn_obs0_y")
        nq = backend.model.nq
        obs_idx = {
            "qpos": (1 + int(jx.qposadr[0]), 1 + int(jy.qposadr[0])),
            "qvel": (1 + nq + int(jx.dofadr[0]), 1 + nq + int(jy.dofadr[0])),
        }

    phase = PhaseMachine(use_probe_truth=args.arm == "oracle")
    positions: list[list[float]] = []
    skills: list[int] = []
    gate_steps: list[int] = []
    refresh_steps: list[int] = []
    collision_steps: list[int] = []
    done_steps: list[int] = []
    neupan_latency_ms: list[float] = []
    reached_step: int | None = None
    consumed = 0
    class_arc = 0.0
    held_proposal: tuple[float, float] | None = None
    held_frac = 1.0
    frozen_yaw: tuple[float, float] | None = None
    frozen_frac = 1.0
    min_obstacle_dist = float("inf")
    previous_foot_contact = np.zeros((1, 4), dtype=np.float32)
    all_finite = True
    live_contract: dict[str, Any] = {}
    started = time.monotonic()

    def obstacle_centre(t: float) -> np.ndarray | None:
        if layout is None:
            return None
        return np.asarray(
            [
                layout["start_x"] + layout["vel_x"] * t,
                layout["start_y"] + layout["vel_y"] * t,
            ]
        )

    def initialize():
        nonlocal previous_foot_contact, live_contract
        live_contract = _live_env_contract(env)
        if not bool(live_contract["passed"]):
            raise RuntimeError(f"live UniLab action contract mismatch: {live_contract}")
        state = env.init_state()
        env.set_autoreset(False)
        qpos = np.asarray(env._init_qpos, dtype=np.float32).reshape(1, -1).copy()
        qvel = np.zeros_like(env._init_qvel, dtype=np.float32).reshape(1, -1)
        qpos[0, :3] = (scenario.start_xy[0], scenario.start_xy[1], 0.42)
        qpos[0, 3:7] = (1.0, 0.0, 0.0, 0.0)
        indices = backend.get_joint_dof_pos_indices(ROBOT_JOINTS) + 7
        qpos[0, indices] = profile.low_contract.source_default_dof
        tire = backend.get_joint_dof_pos_indices(("source_tire_joint",))[0] + 7
        qpos[0, int(tire)] = 0.475
        if layout is not None:
            ox = backend.get_joint_dof_pos_indices(("dyn_obs0_x",))[0] + 7
            oy = backend.get_joint_dof_pos_indices(("dyn_obs0_y",))[0] + 7
            qpos[0, int(ox)] = layout["start_x"]
            qpos[0, int(oy)] = layout["start_y"]
        backend.set_state(np.asarray([0], dtype=np.int32), qpos, qvel)
        state = env.update_state(state)
        adapter.reset()
        state.info["current_actions"] = agility_action_to_unilab(
            np.zeros((1, 12), dtype=np.float32), profile.low_contract
        )
        previous_foot_contact.fill(0.0)
        return state

    def step(state):
        nonlocal reached_step, consumed, class_arc
        nonlocal held_proposal, held_frac, frozen_yaw, frozen_frac
        nonlocal previous_foot_contact, all_finite, min_obstacle_dist
        step_index = len(positions) + 1
        t = (step_index - 1) * ctrl_dt
        centre = obstacle_centre(t)
        if centre is not None and obs_idx is not None:
            state_vec = backend._physics_state[0]
            state_vec[obs_idx["qpos"][0]] = centre[0]
            state_vec[obs_idx["qpos"][1]] = centre[1]
            state_vec[obs_idx["qvel"][0]] = layout["vel_x"]
            state_vec[obs_idx["qvel"][1]] = layout["vel_y"]
        base_quat = backend.get_base_quat().copy()
        base_pos = backend.get_base_pos().copy()
        robot_xy = base_pos[0, :2].astype(np.float64)
        base_yaw = _base_yaw(base_quat[0])
        if centre is not None:
            dist = float(np.linalg.norm(centre - robot_xy))
            min_obstacle_dist = min(min_obstacle_dist, dist)
            if reached_step is None and dist < COLLISION_DIST_M:
                collision_steps.append(step_index)
        if reached_step is None and (
            float(np.linalg.norm(robot_xy - goal_xy)) < GOAL_THRESHOLD_M
        ):
            reached_step = step_index - 1

        contact = probe.sample()
        sensor_floor = (np.linalg.norm(env.feet_force, axis=2) > 2.0).astype(np.float32)
        current_contact = np.maximum(contact["foot_contact"], sensor_floor)
        foot_contact = np.maximum(current_contact, previous_foot_contact)
        previous_foot_contact = current_contact
        # Phase signals: oracle uses probe truth; c4 uses the policy-side signal.
        feet_on_truth = int(contact["foot_contact"].sum())
        feet_on_policy = int((foot_contact > 0.5).sum())

        nearest = int(
            np.argmin(np.linalg.norm(dense_path - robot_xy.reshape(1, 2), axis=1))
        )
        class_arc, active_class = update_class_state(intervals, class_arc, nearest)
        in_jump = active_class in JUMP_CLASSES

        # Phase gate decision precedes the feed (refresh-policy input).
        gated = False
        if args.arm in ("oracle", "c4"):
            skill_hint = skills[-1] if skills else 0
            feet_on = feet_on_truth if args.arm == "oracle" else feet_on_policy
            gated = phase.update(step_index, skill_hint, feet_on, in_jump)
            if gated:
                gate_steps.append(step_index)

        # Base feed for ALL arms: validated straight-path CM contract.
        remaining, consumed = remaining_policy_path(
            dense_path, policy_arc, dense_path, robot_xy, consumed
        )
        waypoint = path_to_tsc_waypoints(
            remaining,
            np.asarray([robot_xy[0], robot_xy[1], base_yaw]),
            CURRENT_LOOKAHEAD_M,
            NEXT_LOOKAHEAD_M,
            MAX_ABS_YAW_RAD,
        )
        base_pair = (
            base_yaw + float(waypoint.delta_yaw),
            base_yaw + float(waypoint.delta_next_yaw),
        )
        # NeuPAN dodge-proposal source (non-ttc arms), 10 Hz.
        replan = (step_index - 1) % REPLAN_PERIOD_STEPS == 0
        if args.arm != "ttc" and replan:
            planner_started = time.perf_counter()
            if centre is not None:
                points = surface_points(centre.reshape(1, 2))
                velocities = np.tile(
                    [[layout["vel_x"]], [layout["vel_y"]]], (1, points.shape[1])
                )
            else:
                points, velocities = None, None
            action, info = planner(
                np.asarray([[robot_xy[0]], [robot_xy[1]], [base_yaw]]),
                points,
                velocities,
            )
            neupan_latency_ms.append((time.perf_counter() - planner_started) * 1000.0)
            if info["stop"] or info["arrive"]:
                held_proposal = None
                held_frac = 0.0 if info["stop"] else 1.0
            else:
                trajectory = np.hstack(planner.opt_trajectory).T
                proposal_wp = path_to_tsc_waypoints(
                    trajectory,
                    np.asarray([robot_xy[0], robot_xy[1], base_yaw]),
                    CURRENT_LOOKAHEAD_M,
                    NEXT_LOOKAHEAD_M,
                    MAX_ABS_YAW_RAD,
                )
                held_proposal = (
                    base_yaw + float(proposal_wp.delta_yaw),
                    base_yaw + float(proposal_wp.delta_next_yaw),
                )
                held_frac = float(np.clip(action[0, 0] / NEUPAN_REF_SPEED, 0.0, 1.0))
        obstacle_near = (
            centre is not None
            and float(np.linalg.norm(centre - robot_xy)) < REFRESH_OBSTACLE_RADIUS_M
        )
        current_heading = frozen_yaw[0] if frozen_yaw is not None else base_pair[0]
        proposal_active = (
            args.arm != "ttc"
            and obstacle_near
            and held_proposal is not None
            and abs(wrap_to_pi(held_proposal[0] - current_heading))
            > REFRESH_DEVIATION_RAD
        )
        adopt = proposal_active and (args.arm == "continuous" or not gated)
        # Planner speed modulation is part of the avoidance response: it only
        # engages near the obstacle; nominal walking runs at actor speed.
        frac_base = (
            held_frac if (args.arm != "ttc" and obstacle_near) else 1.0
        )

        if in_jump:
            if frozen_yaw is None:
                frozen_yaw = base_pair
                frozen_frac = frac_base
            if adopt and replan:
                frozen_yaw = held_proposal
                frozen_frac = frac_base
                refresh_steps.append(
                    {
                        "step": step_index,
                        "new_heading": round(held_proposal[0], 3),
                        "base_yaw": round(base_yaw, 3),
                    }
                )
            delta_yaw, _ = committed_delta_yaw(frozen_yaw, base_yaw)
            frac = frozen_frac
        else:
            frozen_yaw = None
            heading_pair = held_proposal if adopt else base_pair
            delta_yaw, _ = committed_delta_yaw(heading_pair, base_yaw)
            frac = frac_base
            if adopt:
                refresh_steps.append(
                    {
                        "step": step_index,
                        "new_heading": round(heading_pair[0], 3),
                        "base_yaw": round(base_yaw, 3),
                    }
                )
        if args.arm == "ttc":
            frac = 1.0
            if layout is not None and ttc_slow(robot_xy, base_yaw, [layout], t):
                frac = 0.0

        command, diagnostics = adapter.preview_command(
            base_quat_wxyz=base_quat,
            base_ang_vel=env.get_gyro().copy(),
            dof_pos=env.get_dof_pos().copy(),
            dof_vel=env.get_dof_vel().copy(),
            foot_contact=foot_contact,
            depth_image=depth_camera.capture(),
            delta_yaw=delta_yaw,
            obstacle_type=int(active_class),
        )
        skill = int(diagnostics["skill"][0])
        vx_min = float(adapter.commander.command_offset_mat[skill, 0])
        actor_vx = float(command[0, 0])
        command = command.copy()
        command[0, 0] = float(np.clip(frac * actor_vx, vx_min, max(actor_vx, vx_min)))
        action, low = adapter.bbc.act(
            base_quat_wxyz=base_quat,
            base_ang_vel=env.get_gyro().copy(),
            dof_pos=env.get_dof_pos().copy(),
            dof_vel=env.get_dof_vel().copy(),
            foot_contact=foot_contact,
            command=command,
            explicit=None,
        )
        adapter.bbc.history.fill(0.0)
        skills.append(skill)
        state = env.step(action)
        if np.any(state.terminated | state.truncated):
            done_steps.append(step_index)
        base_after = backend.get_base_pos().copy()
        positions.append(base_after[0].tolist())
        all_finite = all_finite and all(
            np.isfinite(v).all()
            for v in (action, delta_yaw, command, low["source_action"], base_after)
        )
        return state

    try:
        rendered = env.run_playback(
            initialize=initialize,
            step=step,
            num_steps=EPISODE_STEPS,
            output_video=args.output_video,
            headless=True,
            record_video=True,
            camera_kwargs={
                "cam_tracking": True,
                "cam_tracking_env_idx": 0,
                "cam_tracking_extra_envs": 0,
                "cam_distance": 4.0,
                "cam_elevation": -22.0,
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
    success = reached_step is not None and not collision_steps and not done_before
    # Jump-event extraction for calibration and gate-timing telemetry.
    skill_arr = np.asarray(skills)
    skill2 = np.nonzero(skill_arr == 2)[0]
    events = {
        "skill2_onset": int(skill2[0]) + 1 if len(skill2) else None,
        "takeoff": phase.takeoff_step,
        "landing": phase.release_step,
        "air_mid": (
            (phase.takeoff_step + phase.release_step) // 2
            if phase.takeoff_step is not None and phase.release_step is not None
            else None
        ),
        "gate_enter": phase.enter_step,
        "gate_release": phase.release_step,
    }
    checks = {
        "live_env_action_contract": bool(live_contract["passed"]),
        "rollout_finite": all_finite,
        "step_count": len(positions) == EPISODE_STEPS,
        "video_created": video_exists,
        "video_frame_count": video.get("frames") == EPISODE_STEPS,
    }
    elapsed = time.monotonic() - started
    return {
        "run_id": args.run_id,
        "arm": args.arm,
        "timing": args.timing,
        "variant": args.variant,
        "seed": args.seed,
        "status": "PASSED" if all(checks.values()) else "FAILED",
        "episode_success": success,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "evaluation_type": "simulation_only",
        "checks": checks,
        "metrics": {
            "reached_step": reached_step,
            "final_base_xyz_m": positions[-1],
            "collision_step_count": len(collision_steps),
            "min_obstacle_distance_m": (
                min_obstacle_dist if layout is not None else None
            ),
            "done_before_success_steps": done_before,
            "gate_step_count": len(gate_steps),
            "refresh_steps": refresh_steps,
            "gate_enter_step": phase.enter_step,
            "gate_release_step": phase.release_step,
            "events": events,
            "neupan_latency_ms_p95": (
                float(np.percentile(neupan_latency_ms, 95))
                if neupan_latency_ms
                else None
            ),
            "wall_time_sec": elapsed,
        },
        "layout": layout,
        "skill_counts": {
            str(int(s)): int(c)
            for s, c in zip(*np.unique(skill_arr, return_counts=True))
        },
        "contracts": {
            "scenario": "TR",
            "cross_x_m": CROSS_X,
            "collision_dist_m": COLLISION_DIST_M,
            "replan_period_steps": REPLAN_PERIOD_STEPS,
            "airborne_consecutive": AIRBORNE_CONSECUTIVE,
            "recovery_consecutive": RECOVERY_CONSECUTIVE,
            "phase_signal": (
                "probe truth" if args.arm == "oracle" else "policy foot_contact"
            ),
            "headless_tkinter_shim": shim,
            "depth_encoder_override_sha256": _sha256(args.depth_encoder_checkpoint),
            "high_checkpoint_sha256": _sha256(HIGH_CHECKPOINT),
            "runner_sha256": _sha256(Path(__file__)),
            "calibration_file": (
                str(args.calibration_file) if args.timing != "none" else None
            ),
        },
        "video": {
            "path": str(args.output_video),
            "sha256": _sha256(args.output_video) if video_exists else None,
            **video,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--arm", choices=ARMS, required=True)
    parser.add_argument("--timing", choices=TIMINGS, required=True)
    parser.add_argument("--variant", type=int, default=0)
    parser.add_argument("--calibration-file", type=Path)
    parser.add_argument("--depth-encoder-checkpoint", type=Path, required=True)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    if not 0 <= args.variant <= 4:
        parser.error("--variant must be in [0, 4]")
    if args.timing != "none" and (
        args.calibration_file is None or not args.calibration_file.is_file()
    ):
        parser.error("--calibration-file required (and existing) unless timing=none")
    if not args.depth_encoder_checkpoint.is_file():
        parser.error(f"missing checkpoint: {args.depth_encoder_checkpoint}")
    timing_index = TIMINGS.index(args.timing)
    args.seed = 800 + timing_index * 5 + args.variant
    args.run_id = f"NAG-601-{args.arm}-{args.timing}-v{args.variant}"
    args.output_dir = (
        args.output_dir or RESULTS_ROOT / args.arm / f"{args.timing}_v{args.variant}"
    )
    args.stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    args.output_video = args.output_dir / f"{args.run_id}.mp4"
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
            "arm": args.arm,
            "timing": args.timing,
            "variant": args.variant,
            "status": "FAILED",
            "episode_success": False,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "error": f"{type(exc).__name__}: {exc}",
        }
    _write_json(result_path, payload)
    shutil.copy2(result_path, args.output_dir / "result.json")
    print(f"{payload['status']} success={payload['episode_success']}: {result_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
