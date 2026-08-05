#!/usr/bin/env python3
"""NAG-701-B capstone: one continuous long course, unified control law.

Course (course-x): dynamic pedestrian -> wall detour -> poles (dense zigzag
waypoints) -> tunnel -> stairs (riser 0.05) -> seesaw -> tire -> goal.
Unified law = NAG-601 final architecture: global waypoint path with receding
feed, CM commit in jump-class intervals, NeuPAN dodge proposals + speed
modulation near the dynamic obstacle, class scheduling from course affordance
rects. ep6 encoder. Demo milestone: gates are reach-goal + no fall; contacts
are recorded and reported.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

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
)
from run_dynamic_planner import (  # noqa: E402
    COLLISION_DIST_M,
    build_neupan,
    obstacle_fragment,
    surface_points,
)
from run_waypoint_envelope import (  # noqa: E402
    CURRENT_LOOKAHEAD_M,
    MAX_ABS_YAW_RAD,
    NEXT_LOOKAHEAD_M,
    _base_yaw,
    remaining_policy_path,
)
from source_tasks import HORIZONTAL_SCALE, SCAN_X, SCAN_Y, VERTICAL_SCALE  # noqa: E402
from static_2p5d import (  # noqa: E402
    FREE_SPACE_CLASS,
    PATH_SPACING_M,
    ClassInterval,
    Rect,
    class_at_arc,
    resample_polyline,
    wall_fragment,
)
from unilab.algos.torch.quadrupedal_agility import (  # noqa: E402
    AgilityTscPolicyAdapter,
    agility_action_to_unilab,
)
from unilab.terrains import HfFlatTerrainCfg  # noqa: E402

ASSETS = Path(__file__).resolve().parent / "assets"
RESULTS_ROOT = ROOT / "experiment-results/quadrupedal-agility/NAG-701-COURSE"
START_XY = (-17.5, 0.0)
GOAL_XY = (21.0, 0.0)
GOAL_THRESHOLD_M = 0.5
EPISODE_STEPS = 3000  # 60 s
REPLAN_PERIOD_STEPS = 5
NEUPAN_REF_SPEED = 0.8
REFRESH_DEVIATION_RAD = 0.15
REFRESH_OBSTACLE_RADIUS_M = 2.0
CLASS_EXIT_MARGIN_M = 0.5

WAYPOINTS = [
    (-17.5, 0.0),
    (-13.5, 0.0),
    (-12.8, -1.6),
    (-11.2, -1.6),
    (-10.5, 0.0),
    (-9.5, -0.6),
    (-8.5, -0.75),
    (-7.25, -0.75),
    (-5.75, 0.75),
    (-4.5, 0.75),
    (-3.5, 0.0),
    (21.0, 0.0),
]
# Course-level speed caps (deployment-plausible: slow down in clutter).
SEGMENT_SPEED_CAPS = [(Rect(-9.0, -4.0, -1.0, 1.0), 0.6)]
FRAGMENTS = [  # (asset file, course-x offset)
    ("poles.xml", -8.0),
    ("tunnel.xml", -1.5),
    ("stairs.xml", 5.0),
    ("seesaw.xml", 11.0),
    ("tire_jump.xml", 17.5),
]
WALL_X = -12.0
OBSTACLE_JOINTS = (("source_seesaw_joint", -float(np.arcsin(0.25 / 1.5))),
                   ("source_tire_joint", 0.475))
AFFORDANCE = [  # (rect, class, entry_margin_m)
    (Rect(-8.3, -4.7, -0.8, 0.8), 2, 2.0),    # poles
    (Rect(-1.6, 0.6, -0.5, 0.5), 5, 2.0),     # tunnel
    (Rect(9.4, 12.6, -0.3, 0.3), 3, 2.0),     # seesaw
    (Rect(17.1, 17.9, -0.35, 0.35), 4, 3.0),  # tire (jump class -> CM)
]
PEDESTRIAN = {
    "start_x": -15.5,
    "cross_t": 3.0,
    "speed": 0.5,
    "direction": -1.0,
}


@contextmanager
def translated_fragment(source: Path, dx: float, dy: float = 0.0) -> Iterator[Path]:
    """Shift a fragment's top-level bodies/geoms in the world plane."""
    tree = ET.parse(source)
    worldbody = tree.getroot().find("worldbody")
    for child in list(worldbody):
        if child.tag in ("body", "geom"):
            pos = (child.get("pos") or "0 0 0").split()
            pos[0] = f"{float(pos[0]) + dx:.4f}"
            pos[1] = f"{float(pos[1]) + dy:.4f}"
            child.set("pos", " ".join(pos))
    for mesh in tree.getroot().iter("mesh"):
        mesh_file = Path(mesh.get("file"))
        if not mesh_file.is_absolute():
            mesh.set("file", str((source.parent / mesh_file).resolve()))
    with tempfile.TemporaryDirectory(prefix="unilab-capstone-") as tmp:
        out = Path(tmp) / source.name
        tree.write(out, encoding="utf-8")
        yield out


def course_terrain(seed: int) -> dict[str, Any]:
    return {
        "seed": seed,
        "curriculum": False,
        "size": [44.0, 12.0],
        "horizontal_scale": HORIZONTAL_SCALE,
        "vertical_scale": VERTICAL_SCALE,
        "border_width": 4.0,
        "num_rows": 1,
        "num_cols": 1,
        "sub_terrains": {
            "flat": HfFlatTerrainCfg(
                proportion=1.0,
                horizontal_scale=HORIZONTAL_SCALE,
                vertical_scale=VERTICAL_SCALE,
            )
        },
    }


def build_course_path() -> tuple[np.ndarray, tuple[ClassInterval, ...]]:
    dense = resample_polyline(np.asarray(WAYPOINTS, dtype=np.float64), PATH_SPACING_M)
    arc = (np.arange(len(dense)) + 1) * PATH_SPACING_M
    intervals = []
    for rect, label, entry_margin in AFFORDANCE:
        inside = rect.contains(dense)
        if not np.any(inside):
            continue
        centre = np.asarray(
            [(rect.x0 + rect.x1) / 2.0, (rect.y0 + rect.y1) / 2.0]
        )
        s_centre = float(
            arc[np.argmin(np.linalg.norm(dense - centre.reshape(1, 2), axis=1))]
        )
        intervals.append(
            ClassInterval(
                max(s_centre - entry_margin, 0.0),
                float(arc[inside].max()) + CLASS_EXIT_MARGIN_M,
                int(label),
            )
        )
    return dense, tuple(sorted(intervals, key=lambda i: i.s_start_m))


def run(args: argparse.Namespace) -> dict[str, Any]:
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    torch.cuda.manual_seed_all(args.seed)
    device = _device(args.device)
    profile = POLICY_PROFILES["deployment3"]
    dense_path, intervals = build_course_path()
    policy_arc = (np.arange(len(dense_path)) + 1) * PATH_SPACING_M
    goal_xy = np.asarray(GOAL_XY, dtype=np.float64)
    ped = dict(PEDESTRIAN)
    ped["start_y"] = -ped["direction"] * ped["speed"] * ped["cross_t"]
    ped["vel_x"], ped["vel_y"] = 0.0, ped["direction"] * ped["speed"]

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
    planner, shim = build_neupan()
    planner.reset()
    planner.pan.current_nom_values = [None] * 4
    planner.update_initial_path_from_waypoints(
        [
            np.asarray([[START_XY[0]], [START_XY[1]], [0.0]]),
            np.asarray([[GOAL_XY[0]], [GOAL_XY[1]], [0.0]]),
        ]
    )

    with ExitStack() as stack:
        fragments = []
        for name, dx in FRAGMENTS:
            frag = stack.enter_context(translated_fragment(ASSETS / name, dx))
            fragments.append(str(frag))
        fragments.append(str(stack.enter_context(wall_fragment((WALL_X, 0.0)))))
        fragments.append(str(stack.enter_context(obstacle_fragment(1))))
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
    ctrl_dt = float(env.cfg.ctrl_dt)
    jx = backend.model.joint("dyn_obs0_x")
    jy = backend.model.joint("dyn_obs0_y")
    nq = backend.model.nq
    obs_idx = {
        "qpos": (1 + int(jx.qposadr[0]), 1 + int(jy.qposadr[0])),
        "qvel": (1 + nq + int(jx.dofadr[0]), 1 + nq + int(jy.dofadr[0])),
    }

    positions: list[list[float]] = []
    skills: list[int] = []
    classes: list[int] = []
    class_switches: list[dict[str, Any]] = []
    refresh_steps: list[int] = []
    forbidden_steps: list[int] = []
    collision_steps: list[int] = []
    done_steps: list[int] = []
    neupan_latency_ms: list[float] = []
    segment_marks: dict[str, int] = {}
    reached_step: int | None = None
    consumed = 0
    class_arc = 0.0
    held_proposal: tuple[float, float] | None = None
    held_frac = 1.0
    frozen_yaw: tuple[float, float] | None = None
    frozen_frac = 1.0
    last_class: int | None = None
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
        for joint_name, joint_qpos in OBSTACLE_JOINTS:
            idx = backend.get_joint_dof_pos_indices((joint_name,))[0] + 7
            qpos[0, int(idx)] = joint_qpos
        ox = backend.get_joint_dof_pos_indices(("dyn_obs0_x",))[0] + 7
        oy = backend.get_joint_dof_pos_indices(("dyn_obs0_y",))[0] + 7
        qpos[0, int(ox)] = ped["start_x"]
        qpos[0, int(oy)] = ped["start_y"]
        backend.set_state(np.asarray([0], dtype=np.int32), qpos, qvel)
        state = env.update_state(state)
        adapter.reset()
        state.info["current_actions"] = agility_action_to_unilab(
            np.zeros((1, 12), dtype=np.float32), profile.low_contract
        )
        previous_foot_contact.fill(0.0)
        return state

    def step(state):
        nonlocal reached_step, consumed, class_arc, held_proposal, held_frac
        nonlocal frozen_yaw, frozen_frac, last_class
        nonlocal previous_foot_contact, all_finite
        step_index = len(positions) + 1
        t = (step_index - 1) * ctrl_dt
        centre = np.asarray(
            [
                ped["start_x"] + ped["vel_x"] * t,
                ped["start_y"] + ped["vel_y"] * t,
            ]
        )
        state_vec = backend._physics_state[0]
        state_vec[obs_idx["qpos"][0]] = centre[0]
        state_vec[obs_idx["qpos"][1]] = centre[1]
        state_vec[obs_idx["qvel"][0]] = ped["vel_x"]
        state_vec[obs_idx["qvel"][1]] = ped["vel_y"]

        base_quat = backend.get_base_quat().copy()
        base_pos = backend.get_base_pos().copy()
        robot_xy = base_pos[0, :2].astype(np.float64)
        base_yaw = _base_yaw(base_quat[0])
        if reached_step is None and (
            float(np.linalg.norm(robot_xy - goal_xy)) < GOAL_THRESHOLD_M
        ):
            reached_step = step_index - 1
        dist_obs = float(np.linalg.norm(centre - robot_xy))
        if reached_step is None and dist_obs < COLLISION_DIST_M:
            collision_steps.append(step_index)

        contact = probe.sample()
        sensor_floor = (np.linalg.norm(env.feet_force, axis=2) > 2.0).astype(np.float32)
        current_contact = np.maximum(contact["foot_contact"], sensor_floor)
        foot_contact = np.maximum(current_contact, previous_foot_contact)
        previous_foot_contact = current_contact

        nearest = int(
            np.argmin(np.linalg.norm(dense_path - robot_xy.reshape(1, 2), axis=1))
        )
        class_arc = max(class_arc, (nearest + 1) * PATH_SPACING_M)
        active_class = class_at_arc(intervals, class_arc)
        in_jump = active_class in JUMP_CLASSES
        if last_class is not None and active_class != last_class:
            class_switches.append(
                {"step": step_index, "from": last_class, "to": active_class}
            )
        last_class = active_class

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
        replan = (step_index - 1) % REPLAN_PERIOD_STEPS == 0
        if replan:
            planner_started = time.perf_counter()
            points = surface_points(centre.reshape(1, 2))
            velocities = np.tile(
                [[ped["vel_x"]], [ped["vel_y"]]], (1, points.shape[1])
            )
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
                pw = path_to_tsc_waypoints(
                    trajectory,
                    np.asarray([robot_xy[0], robot_xy[1], base_yaw]),
                    CURRENT_LOOKAHEAD_M,
                    NEXT_LOOKAHEAD_M,
                    MAX_ABS_YAW_RAD,
                )
                held_proposal = (
                    base_yaw + float(pw.delta_yaw),
                    base_yaw + float(pw.delta_next_yaw),
                )
                held_frac = float(np.clip(action[0, 0] / NEUPAN_REF_SPEED, 0.0, 1.0))
        obstacle_near = dist_obs < REFRESH_OBSTACLE_RADIUS_M
        current_heading = frozen_yaw[0] if frozen_yaw is not None else base_pair[0]
        adopt = (
            obstacle_near
            and held_proposal is not None
            and abs(wrap_to_pi(held_proposal[0] - current_heading))
            > REFRESH_DEVIATION_RAD
        )
        frac_base = held_frac if obstacle_near else 1.0
        for cap_rect, cap in SEGMENT_SPEED_CAPS:
            if cap_rect.contains(robot_xy.reshape(1, 2))[0]:
                frac_base = min(frac_base, cap)
        if in_jump:
            if frozen_yaw is None:
                frozen_yaw = base_pair
                frozen_frac = frac_base
            if adopt and replan:
                frozen_yaw = held_proposal
                frozen_frac = frac_base
                refresh_steps.append(step_index)
            delta_yaw, _ = committed_delta_yaw(frozen_yaw, base_yaw)
            frac = frozen_frac
        else:
            frozen_yaw = None
            heading_pair = held_proposal if adopt else base_pair
            delta_yaw, _ = committed_delta_yaw(heading_pair, base_yaw)
            frac = frac_base
            if adopt:
                refresh_steps.append(step_index)

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
        classes.append(active_class)
        state = env.step(action)
        if np.any(state.terminated):
            done_steps.append(step_index)
        base_after = backend.get_base_pos().copy()
        positions.append(base_after[0].tolist())
        for mark, x_line in (
            ("wall", WALL_X),
            ("poles", -5.0),
            ("tunnel", 0.5),
            ("stairs", 6.5),
            ("seesaw", 12.5),
            ("tire", 17.8),
        ):
            if mark not in segment_marks and base_after[0, 0] > x_line:
                segment_marks[mark] = step_index
        after = probe.sample()
        if after["forbidden"]:
            forbidden_steps.append(step_index)
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
                "cam_distance": 4.5,
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
    checks = {
        "live_env_action_contract": bool(live_contract["passed"]),
        "rollout_finite": all_finite,
        "step_count": len(positions) == EPISODE_STEPS,
        "video_created": video_exists,
        "no_fall_before_success": not done_before,
        "no_pedestrian_collision": not collision_steps,
        "reached_goal": reached_step is not None,
    }
    elapsed = time.monotonic() - started
    return {
        "run_id": args.run_id,
        "status": "PASSED" if all(checks.values()) else "FAILED",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "evaluation_type": "simulation_only",
        "scope": "capstone continuous course, unified control law, ep6 encoder",
        "seed": args.seed,
        "checks": checks,
        "metrics": {
            "reached_step": reached_step,
            "final_base_xyz_m": positions[-1],
            "segment_marks": segment_marks,
            "class_switches": class_switches,
            "collision_steps": collision_steps[:10],
            "forbidden_contact_step_count": len(
                [s for s in forbidden_steps if s <= gate_end]
            ),
            "refresh_steps": refresh_steps[:20],
            "neupan_latency_ms_p95": (
                float(np.percentile(neupan_latency_ms, 95))
                if neupan_latency_ms
                else None
            ),
            "done_before_success_steps": done_before,
            "wall_time_sec": elapsed,
        },
        "skill_counts": {
            str(int(s)): int(c)
            for s, c in zip(*np.unique(np.asarray(skills), return_counts=True))
        },
        "class_step_counts": {
            str(c): classes.count(c) for c in sorted(set(classes))
        },
        "contracts": {
            "course_waypoints": WAYPOINTS,
            "fragments": [[n, dx] for n, dx in FRAGMENTS],
            "wall_x": WALL_X,
            "pedestrian": ped,
            "class_intervals": [
                {"s_start_m": i.s_start_m, "s_end_m": i.s_end_m, "label": i.label}
                for i in intervals
            ],
            "free_space_class": FREE_SPACE_CLASS,
            "episode_steps": EPISODE_STEPS,
            "depth_encoder_override_sha256": _sha256(args.depth_encoder_checkpoint),
            "high_checkpoint_sha256": _sha256(HIGH_CHECKPOINT),
            "runner_sha256": _sha256(Path(__file__)),
            "headless_tkinter_shim": shim,
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
    args.run_id = f"NAG-701-COURSE-{args.tag}"
    args.output_dir = args.output_dir or RESULTS_ROOT / args.tag
    args.stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    args.output_video = args.output_dir / f"capstone_{args.tag}.mp4"
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
        print("segments:", payload["metrics"]["segment_marks"])
    return 0 if payload["status"] == "PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
