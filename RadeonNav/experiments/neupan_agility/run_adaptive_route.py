#!/usr/bin/env python3
"""NAG-801 physical validations: capability-cost routing + online reroute.

fork: profile marks bar IMPASSABLE / tire TRAVERSABLE; the A* route must
pick the south (tire) opening and the robot follows it to the goal.
stairs-trap: map (riser-0.05 evidence) says stairs are traversable, the
physical scene has riser-0.10 stairs; the robot stalls, the runner marks
the region blocked, replans, and detours around the stairwell flank.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
import time
from collections import deque
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

os.environ.setdefault("MUJOCO_GL", "egl")

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "experiments/cpp_adapter"))

from adaptive_scenarios import (  # noqa: E402
    BlockedProfileView,
    FORK_BARRIER_BOXES,
    FORK_SPEC,
    ROUTING_TO_TSC,
    STAIRS_TRAP_SPEC,
    STAIRS_TRAP_WALL_BOXES,
    crossing_y,
    plan_with_profile,
    spec_with_escape_margin,
    straighten_jump_approaches,
    widen_jump_entries,
)
from bridge import path_to_tsc_waypoints  # noqa: E402
from capability_profile import build_profile, profile_to_json  # noqa: E402
from cpp_loco_sanity import _compose_env, _sha256  # noqa: E402
from run_bbc_sanity import _device, _live_env_contract, _write_json  # noqa: E402
from run_capstone import course_terrain, translated_fragment  # noqa: E402
from run_source_task import (  # noqa: E402
    AGILITY_ROOT,
    HIGH_CHECKPOINT,
    POLICY_PROFILES,
    ROBOT_JOINTS,
    ContactProbe,
    SourceDepthCamera,
    _video_metadata,
)
from run_static_2p5d import JUMP_CLASSES, committed_delta_yaw  # noqa: E402
from run_waypoint_envelope import (  # noqa: E402
    CURRENT_LOOKAHEAD_M,
    MAX_ABS_YAW_RAD,
    NEXT_LOOKAHEAD_M,
    _base_yaw,
    remaining_policy_path,
)
from source_tasks import SCAN_X, SCAN_Y  # noqa: E402
from static_2p5d import (  # noqa: E402
    FREE_SPACE_CLASS,
    PATH_SPACING_M,
    class_at_arc,
    class_schedule,
    resample_polyline,
)
from unilab.algos.torch.quadrupedal_agility import (  # noqa: E402
    AgilityTscPolicyAdapter,
    agility_action_to_unilab,
)

ASSETS = Path(__file__).resolve().parent / "assets"
RESULTS_ROOT = ROOT / "experiment-results/quadrupedal-agility/NAG-801"
GOAL_THRESHOLD_M = 0.5
STALL_WINDOW_STEPS = 250      # 5 s
STALL_MIN_ARC_M = 0.15
STALL_SEGMENT_FBD_STEPS = 60
STALL_ARM_STEP = 150

SCENARIOS = {
    "fork": {
        "spec": FORK_SPEC,
        "steps": 750,
        "fragments": (
            ("tire_jump.xml", 0.0, -1.5),
            ("bar_jump.xml", 0.0, 1.5),
        ),
        "boxes": ("fork_barrier", FORK_BARRIER_BOXES),
        "joints": (("source_tire_joint", 0.475), ("source_bar_joint", 0.125)),
    },
    "stairs-trap": {
        "spec": STAIRS_TRAP_SPEC,
        "steps": 1600,
        "fragments": (("stairs_r010.xml", 1.0, 0.0),),
        "boxes": ("stairwell_walls", STAIRS_TRAP_WALL_BOXES),
        "joints": (),
    },
}


@contextmanager
def boxes_fragment(name: str, boxes) -> Iterator[Path]:
    """Static box obstacles (cx, cy, half_x, half_y), height 0.5 m."""
    geoms = "\n".join(
        f'    <geom name="{name}_{i}" type="box" pos="{cx:.4f} {cy:.4f} 0.25"'
        f' size="{hx:.4f} {hy:.4f} 0.25"'
        ' friction="1 0.005 0.0001" rgba="0.75 0.30 0.25 1"/>'
        for i, (cx, cy, hx, hy) in enumerate(boxes)
    )
    content = (
        f'<mujoco model="{name}">\n  <worldbody>\n{geoms}\n'
        "  </worldbody>\n</mujoco>\n"
    )
    with tempfile.TemporaryDirectory(prefix=f"unilab-{name}-") as tmp:
        fragment = Path(tmp) / f"{name}.xml"
        fragment.write_text(content, encoding="utf-8")
        yield fragment


def run(args: argparse.Namespace) -> dict[str, Any]:
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    torch.cuda.manual_seed_all(args.seed)
    device = _device(args.device)
    profile = build_profile()
    scenario = SCENARIOS[args.scenario]
    spec = scenario["spec"]
    plan = plan_with_profile(spec, profile)
    route_crossing_y = (
        crossing_y(plan["polyline"]) if args.scenario == "fork" else None
    )
    goal_xy = np.asarray(spec.goal_xy, dtype=np.float64)

    profile_obj = profile
    polyline = straighten_jump_approaches(plan["polyline"], spec)
    dense_path = resample_polyline(polyline, PATH_SPACING_M)
    intervals = widen_jump_entries(class_schedule(spec, dense_path))
    policy_arc = (np.arange(len(dense_path)) + 1) * PATH_SPACING_M

    adapter = AgilityTscPolicyAdapter(
        AGILITY_ROOT,
        HIGH_CHECKPOINT,
        POLICY_PROFILES["deployment3"].low_checkpoint,
        device=device,
        low_contract=POLICY_PROFILES["deployment3"].low_contract,
        low_mode_count=POLICY_PROFILES["deployment3"].low_mode_count,
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

    low_contract = POLICY_PROFILES["deployment3"].low_contract
    with ExitStack() as stack:
        fragments = []
        for name, dx, dy in scenario["fragments"]:
            frag = stack.enter_context(translated_fragment(ASSETS / name, dx, dy))
            fragments.append(str(frag))
        box_name, boxes = scenario["boxes"]
        fragments.append(str(stack.enter_context(boxes_fragment(box_name, boxes))))
        env = _compose_env(
            terrain_generator_override=course_terrain(args.seed),
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

    positions: list[list[float]] = []
    skills: list[int] = []
    class_switches: list[dict[str, Any]] = []
    forbidden_steps: list[int] = []
    done_steps: list[int] = []
    reroute_events: list[dict[str, Any]] = []
    reached_step: int | None = None
    consumed = 0
    class_arc = 0.0
    frozen_yaw: tuple[float, float] | None = None
    last_class: int | None = None
    blocked_labels: set[int] = set()
    arc_history: deque[tuple[int, float]] = deque()
    segment_fbd = 0
    segment_label: int | None = None
    last_progress_step = 0
    last_arc_seen = 0.0
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
        qpos[0, :3] = (spec.start_xy[0], spec.start_xy[1], 0.42)
        qpos[0, 3:7] = (1.0, 0.0, 0.0, 0.0)
        indices = backend.get_joint_dof_pos_indices(ROBOT_JOINTS) + 7
        qpos[0, indices] = low_contract.source_default_dof
        for joint_name, joint_qpos in scenario["joints"]:
            idx = backend.get_joint_dof_pos_indices((joint_name,))[0] + 7
            qpos[0, int(idx)] = joint_qpos
        backend.set_state(np.asarray([0], dtype=np.int32), qpos, qvel)
        state = env.update_state(state)
        adapter.reset()
        state.info["current_actions"] = agility_action_to_unilab(
            np.zeros((1, 12), dtype=np.float32), low_contract
        )
        previous_foot_contact.fill(0.0)
        return state

    def reroute(step_index: int, robot_xy: np.ndarray, reason: str, label: int):
        nonlocal dense_path, intervals, policy_arc, consumed, class_arc
        nonlocal frozen_yaw, segment_fbd, last_class, last_arc_seen
        nonlocal last_progress_step
        blocked_labels.add(label)
        old_path_length_m = float(len(dense_path) * PATH_SPACING_M)
        stall_latency_s = (step_index - last_progress_step) * 0.02
        view = BlockedProfileView(profile_obj, blocked_labels)
        escape_spec = spec_with_escape_margin(spec, blocked_labels)
        try:
            new_plan = plan_with_profile(escape_spec, view, start_xy=tuple(robot_xy))
        except (RuntimeError, ValueError) as exc:
            # No alternative route: keep the current path, record the attempt.
            reroute_events.append(
                {"step": step_index, "reason": reason, "blocked_label": label,
                 "stall_latency_s": stall_latency_s,
                 "outcome": f"no_alternative ({exc})"}
            )
            return
        new_polyline = straighten_jump_approaches(new_plan["polyline"], spec)
        dense_path = resample_polyline(new_polyline, PATH_SPACING_M)
        intervals = widen_jump_entries(class_schedule(spec, dense_path))
        policy_arc = (np.arange(len(dense_path)) + 1) * PATH_SPACING_M
        consumed = 0
        class_arc = 0.0
        last_arc_seen = 0.0
        last_progress_step = step_index
        frozen_yaw = None
        last_class = None
        segment_fbd = 0
        arc_history.clear()
        reroute_events.append(
            {
                "step": step_index,
                "reason": reason,
                "blocked_label": label,
                "stall_latency_s": stall_latency_s,
                "old_path_length_m": old_path_length_m,
                "new_path_length_m": float(len(dense_path) * PATH_SPACING_M),
            }
        )

    def step(state):
        nonlocal reached_step, consumed, class_arc, frozen_yaw, last_class
        nonlocal previous_foot_contact, all_finite, segment_fbd
        nonlocal segment_label, last_progress_step, last_arc_seen
        step_index = len(positions) + 1
        base_quat = backend.get_base_quat().copy()
        base_pos = backend.get_base_pos().copy()
        robot_xy = base_pos[0, :2].astype(np.float64)
        base_yaw = _base_yaw(base_quat[0])
        if reached_step is None and (
            float(np.linalg.norm(robot_xy - goal_xy)) < GOAL_THRESHOLD_M
        ):
            reached_step = step_index - 1

        contact = probe.sample()
        sensor_floor = (np.linalg.norm(env.feet_force, axis=2) > 2.0).astype(np.float32)
        current_contact = np.maximum(contact["foot_contact"], sensor_floor)
        foot_contact = np.maximum(current_contact, previous_foot_contact)
        previous_foot_contact = current_contact

        nearest = int(
            np.argmin(np.linalg.norm(dense_path - robot_xy.reshape(1, 2), axis=1))
        )
        class_arc = max(class_arc, (nearest + 1) * PATH_SPACING_M)
        routing_class = class_at_arc(intervals, class_arc)
        active_class = ROUTING_TO_TSC.get(routing_class, routing_class)
        if last_class is not None and active_class != last_class:
            class_switches.append(
                {"step": step_index, "from": last_class, "to": active_class}
            )
        last_class = active_class

        # Online stall detection while an affordance interval is active.
        if class_arc > last_arc_seen + 1e-6:
            last_arc_seen = class_arc
            last_progress_step = step_index
        if routing_class != segment_label:
            segment_label = routing_class
            segment_fbd = 0
        arc_history.append((step_index, class_arc))
        while arc_history and arc_history[0][0] < step_index - STALL_WINDOW_STEPS:
            arc_history.popleft()
        if (
            reached_step is None
            and step_index > STALL_ARM_STEP
            and routing_class not in blocked_labels
            and routing_class != FREE_SPACE_CLASS  # an interval is active
        ):
            window_full = arc_history[0][0] <= step_index - STALL_WINDOW_STEPS + 1
            arc_gain = class_arc - arc_history[0][1]
            arc_stalled = window_full and arc_gain < STALL_MIN_ARC_M
            contact_stalled = segment_fbd > STALL_SEGMENT_FBD_STEPS
            if arc_stalled or contact_stalled:
                reroute(
                    step_index,
                    robot_xy,
                    "arc_stall" if arc_stalled else "contact",
                    routing_class,
                )
                routing_class = class_at_arc(intervals, class_arc)
                active_class = ROUTING_TO_TSC.get(routing_class, routing_class)

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
        if active_class in JUMP_CLASSES:
            if frozen_yaw is None:
                frozen_yaw = base_pair
            delta_yaw, _ = committed_delta_yaw(frozen_yaw, base_yaw)
        else:
            frozen_yaw = None
            delta_yaw, _ = committed_delta_yaw(base_pair, base_yaw)

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
        skills.append(int(diagnostics["skill"][0]))
        state = env.step(action)
        if np.any(state.terminated):
            done_steps.append(step_index)
        base_after = backend.get_base_pos().copy()
        positions.append(base_after[0].tolist())
        after = probe.sample()
        if after["forbidden"]:
            forbidden_steps.append(step_index)
            if routing_class != FREE_SPACE_CLASS:
                segment_fbd += 1
        all_finite = all_finite and all(
            np.isfinite(v).all()
            for v in (action, delta_yaw, command, low["source_action"], base_after)
        )
        return state

    try:
        rendered = env.run_playback(
            initialize=initialize,
            step=step,
            num_steps=scenario["steps"],
            output_video=args.output_video,
            headless=True,
            record_video=True,
            camera_kwargs={
                "cam_tracking": True,
                "cam_tracking_env_idx": 0,
                "cam_tracking_extra_envs": 0,
                "cam_distance": 4.5,
                "cam_elevation": -22.0,
                "cam_azimuth": 135.0,
            },
        )
    finally:
        depth_camera.close()
        env.close()

    video_exists = rendered is not None and args.output_video.is_file()
    gate_end = reached_step if reached_step is not None else len(positions)
    done_before = [s for s in done_steps if s <= gate_end]
    xy = np.asarray(positions, dtype=np.float64)[:, :2]
    robot_crossing_y = None
    cross = np.nonzero((xy[:-1, 0] < 0.0) & (xy[1:, 0] >= 0.0))[0]
    if len(cross):
        i = int(cross[0])
        t = (0.0 - xy[i, 0]) / (xy[i + 1, 0] - xy[i, 0])
        robot_crossing_y = float(xy[i, 1] + t * (xy[i + 1, 1] - xy[i, 1]))
    successful_reroutes = [e for e in reroute_events if "new_path_length_m" in e]
    checks = {
        "live_env_action_contract": bool(live_contract["passed"]),
        "rollout_finite": all_finite,
        "video_created": video_exists,
        "no_fall_before_success": not done_before,
        "reached_goal": reached_step is not None,
    }
    if args.scenario == "fork":
        checks["route_through_tire_opening"] = (
            route_crossing_y is not None and -1.85 < route_crossing_y < -1.15
        )
        checks["robot_through_tire_mouth"] = (
            robot_crossing_y is not None and -1.85 < robot_crossing_y < -1.15
        )
        checks["no_reroute_expected"] = not reroute_events
    else:
        checks["stall_detected_and_rerouted"] = len(successful_reroutes) >= 1
        checks["stall_latency_within_8s"] = bool(successful_reroutes) and all(
            e["stall_latency_s"] <= 8.0 for e in successful_reroutes
        )
    return {
        "run_id": args.run_id,
        "status": "PASSED" if all(checks.values()) else "FAILED",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "evaluation_type": "simulation_only",
        "scope": f"NAG-801 {args.scenario}: capability routing validation",
        "seed": args.seed,
        "checks": checks,
        "metrics": {
            "reached_step": reached_step,
            "final_base_xyz_m": positions[-1],
            "route_crossing_y_m": route_crossing_y,
            "robot_crossing_y_m": robot_crossing_y,
            "reroute_events": reroute_events,
            "done_steps_all": done_steps[:20],
            "class_switches": class_switches,
            "forbidden_contact_step_count": len(
                [s for s in forbidden_steps if s <= gate_end]
            ),
            "done_before_success_steps": done_before,
            "wall_time_sec": time.monotonic() - started,
        },
        "skill_counts": {
            str(int(s)): int(c)
            for s, c in zip(*np.unique(np.asarray(skills), return_counts=True))
        },
        "contracts": {
            "scenario": args.scenario,
            "capability_profile": profile_to_json(profile),
            "stall_window_steps": STALL_WINDOW_STEPS,
            "stall_min_arc_m": STALL_MIN_ARC_M,
            "stall_segment_fbd_steps": STALL_SEGMENT_FBD_STEPS,
            "stall_arm_step": STALL_ARM_STEP,
            "depth_encoder_override_sha256": _sha256(args.depth_encoder_checkpoint),
            "high_checkpoint_sha256": _sha256(HIGH_CHECKPOINT),
            "runner_sha256": _sha256(Path(__file__)),
        },
        "video": {
            "path": str(args.output_video),
            "sha256": _sha256(args.output_video) if video_exists else None,
            **(_video_metadata(args.output_video) if video_exists else {}),
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), required=True)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--device", default="auto")
    parser.add_argument(
        "--depth-encoder-checkpoint",
        type=Path,
        default=ROOT
        / "experiment-results/quadrupedal-agility/M-ROCM-6-HISTDATA/TRAIN/ft1_depth_encoder_epoch6.pt",
    )
    parser.add_argument("--tag", default="dryrun")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    if not args.depth_encoder_checkpoint.is_file():
        parser.error(f"missing checkpoint: {args.depth_encoder_checkpoint}")
    args.run_id = f"NAG-801-{args.scenario.upper()}-{args.tag}"
    args.output_dir = args.output_dir or RESULTS_ROOT / f"{args.scenario}-{args.tag}"
    args.stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    args.output_video = args.output_dir / f"{args.scenario}_{args.tag}.mp4"
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
    if "metrics" in payload:
        print(
            "reached:", payload["metrics"]["reached_step"],
            "| reroutes:", payload["metrics"]["reroute_events"],
        )
    return 0 if payload["status"] == "PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
