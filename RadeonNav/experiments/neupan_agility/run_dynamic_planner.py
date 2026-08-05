#!/usr/bin/env python3
"""NAG-501: flat dynamic-obstacle benchmark — no-avoid vs TTC vs NeuPAN.

Preregistered in EXPERIMENT_PLAN.md M5 (2026-07-31 06:00 refinement). All
three arms share the frozen student-D chain (M-FT-2 ep6 encoder via CLI),
the straight reference path with the receding bridge feed, the same paired
dynamic-obstacle layouts, and the same command-level speed authority
(vx modulated within [skill range-min, actor vx]). Dynamic obstacles are
kinematic (no physical contact), visible to the depth camera; collision is
the geometric criterion dist(base, obstacle centre) < 0.55 m.
"""

from __future__ import annotations

import argparse
import math
import os
import shutil
import sys
import tempfile
import time
import types
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

os.environ.setdefault("MUJOCO_GL", "egl")

import numpy as np
import torch
import yaml

ROOT = Path(__file__).resolve().parents[2]
NEUPAN_ROOT = ROOT / "NeuPAN"
sys.path.insert(0, str(ROOT / "experiments/cpp_adapter"))

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
from bridge import path_to_tsc_waypoints  # noqa: E402
from source_tasks import (  # noqa: E402
    SCAN_X,
    SCAN_Y,
    flat_physics_terrain,
)
from static_2p5d import FREE_SPACE_CLASS, PATH_SPACING_M  # noqa: E402
from unilab.algos.torch.quadrupedal_agility import (  # noqa: E402
    AgilityTscPolicyAdapter,
    agility_action_to_unilab,
)

RESULTS_ROOT = ROOT / "experiment-results/quadrupedal-agility/NAG-501"
PLANNER_YAML = Path(__file__).resolve().parent / "go2_planner.yaml"
START_XY = (-4.0, 0.0)
GOAL_XY = (4.0, 0.0)
GOAL_THRESHOLD_M = 0.4
EPISODE_STEPS = 750  # 15 s at 50 Hz
OBSTACLE_RADIUS_M = 0.25
TIRE_OBSTACLE_RADIUS_M = 0.55
ROBOT_RADIUS_M = 0.30
COLLISION_DIST_M = OBSTACLE_RADIUS_M + ROBOT_RADIUS_M  # 0.55
REPLAN_PERIOD_STEPS = 5  # 10 Hz
TTC_HORIZON_S = 2.0
TTC_LATERAL_M = 0.6
TTC_FORWARD_BASE_M = 1.2
ROBOT_NOMINAL_SPEED = 0.7
SURFACE_POINTS_PER_OBSTACLE = 8
NEUPAN_REF_SPEED = 0.8
ARMS = ("noavoid", "ttc", "neupan")
LAYOUTS = ("dynamic", "tire-static")


def _headless_tkinter_shim() -> bool:
    try:
        import tkinter  # noqa: F401
    except ModuleNotFoundError:
        tkinter = types.ModuleType("tkinter")
        tkinter.Scale = object
        sys.modules["tkinter"] = tkinter
        return True
    return False


def sample_layout(seed: int) -> list[dict[str, float]]:
    """Two constant-velocity crossing obstacles; deterministic per seed."""
    rng = np.random.default_rng(seed)
    obstacles = []
    for index in range(2):
        side = 1.0 if rng.random() < 0.5 else -1.0
        angle = (-side) * math.radians(90.0 + rng.uniform(-30.0, 30.0))
        speed = rng.uniform(0.3, 0.8)
        cross_x = rng.uniform(-1.5, 1.5)
        cross_t = rng.uniform(3.0, 7.0)
        direction = np.asarray([math.cos(angle), math.sin(angle)])
        start = np.asarray([cross_x, 0.0]) - speed * cross_t * direction
        obstacles.append(
            {
                "index": index,
                "start_x": float(start[0]),
                "start_y": float(start[1]),
                "vel_x": float(speed * direction[0]),
                "vel_y": float(speed * direction[1]),
                "speed": speed,
                "cross_x": cross_x,
                "cross_t": cross_t,
            }
        )
    return obstacles


def tire_static_layout() -> list[dict[str, float]]:
    """One stationary upright tire centred on the straight reference path."""
    return [
        {
            "index": 0,
            "start_x": 0.0,
            "start_y": 0.0,
            "vel_x": 0.0,
            "vel_y": 0.0,
            "speed": 0.0,
            "cross_x": 0.0,
            "cross_t": 0.0,
        }
    ]


def obstacle_radius(layout_name: str) -> float:
    return (
        TIRE_OBSTACLE_RADIUS_M
        if layout_name == "tire-static"
        else OBSTACLE_RADIUS_M
    )


def _tire_ring_geoms(index: int, segments: int = 16) -> str:
    radius = 0.42
    centre_z = 0.52
    points = [
        (
            radius * math.cos(2.0 * math.pi * i / segments),
            centre_z + radius * math.sin(2.0 * math.pi * i / segments),
        )
        for i in range(segments)
    ]
    geoms = []
    for segment, ((y0, z0), (y1, z1)) in enumerate(
        zip(points, points[1:] + points[:1])
    ):
        geoms.append(
            f"""      <geom name="dyn_obs{index}_tire_{segment}" type="capsule"
        fromto="0 {y0:.5f} {z0:.5f} 0 {y1:.5f} {z1:.5f}" size="0.09"
        contype="0" conaffinity="0" rgba="0.06 0.06 0.07 1"/>"""
        )
    return "\n".join(geoms)


@contextmanager
def obstacle_fragment(count: int = 2, layout_name: str = "dynamic") -> Iterator[Path]:
    def visual(index: int) -> str:
        if layout_name == "tire-static":
            return _tire_ring_geoms(index)
        return f"""      <geom name="dyn_obs{index}_geom" type="cylinder"
        pos="0 0 0.45" size="{OBSTACLE_RADIUS_M:.2f} 0.45"
        contype="0" conaffinity="0" rgba="0.85 0.45 0.10 1"/>"""

    bodies = "\n".join(
        f"""    <body name=\"dyn_obs{i}\" pos=\"0 0 0\">
      <joint name=\"dyn_obs{i}_x\" type=\"slide\" axis=\"1 0 0\" range=\"-50 50\"/>
      <joint name=\"dyn_obs{i}_y\" type=\"slide\" axis=\"0 1 0\" range=\"-50 50\"/>
{visual(i)}
    </body>"""
        for i in range(count)
    )
    content = f"""<mujoco model=\"nag501 dynamic obstacles\">
  <worldbody>
{bodies}
  </worldbody>
</mujoco>
"""
    with tempfile.TemporaryDirectory(prefix="unilab-nag501-") as tmp:
        fragment = Path(tmp) / "dyn_obs.xml"
        fragment.write_text(content, encoding="utf-8")
        yield fragment


def obstacle_positions(layout: list[dict[str, float]], t: float) -> np.ndarray:
    return np.asarray(
        [
            [o["start_x"] + o["vel_x"] * t, o["start_y"] + o["vel_y"] * t]
            for o in layout
        ]
    )


def surface_points(
    centres: np.ndarray, radius: float = OBSTACLE_RADIUS_M
) -> np.ndarray:
    """(2, K*n) world-frame surface samples of the obstacle cylinders."""
    angles = np.linspace(0.0, 2.0 * np.pi, SURFACE_POINTS_PER_OBSTACLE, endpoint=False)
    offsets = radius * np.stack((np.cos(angles), np.sin(angles)), axis=0)
    columns = [centre.reshape(2, 1) + offsets for centre in centres]
    return np.hstack(columns)


def ttc_slow(
    robot_xy: np.ndarray,
    robot_yaw: float,
    layout: list[dict[str, float]],
    t: float,
) -> bool:
    """Preregistered rule: obstacle enters the forward corridor within 2 s."""
    heading = np.asarray([math.cos(robot_yaw), math.sin(robot_yaw)])
    lateral = np.asarray([-heading[1], heading[0]])
    for tau in np.arange(0.0, TTC_HORIZON_S + 1e-9, 0.1):
        robot_future = robot_xy + ROBOT_NOMINAL_SPEED * tau * heading
        for centre in obstacle_positions(layout, t + tau):
            rel = centre - robot_future
            forward = float(rel @ heading)
            side = float(rel @ lateral)
            if abs(side) < TTC_LATERAL_M and 0.0 < forward < TTC_FORWARD_BASE_M:
                return True
    return False


def build_neupan(planner_yaml: Path = PLANNER_YAML):
    planner_yaml = Path(planner_yaml).resolve()
    if not planner_yaml.is_file():
        raise FileNotFoundError(f"NeuPAN planner config missing: {planner_yaml}")
    checkpoint = NEUPAN_ROOT / "example/model/go2_diff_070_040/model_2000.pth"
    if not checkpoint.is_file():
        raise FileNotFoundError(
            f"Go2 DUNE checkpoint missing: {checkpoint} (never fall back to the "
            "source 1.6x2.0 DUNE or interactive ad-hoc training)"
        )
    shim = _headless_tkinter_shim()
    previous = os.getcwd()
    os.chdir(NEUPAN_ROOT)
    try:
        from neupan import neupan

        planner = neupan.init_from_yaml(str(planner_yaml), time_print=False)
    finally:
        os.chdir(previous)
    planner.update_initial_path_from_waypoints(planner.waypoints)
    return planner, shim


def neupan_runtime_contract(
    planner, planner_yaml: Path = PLANNER_YAML
) -> dict[str, Any]:
    planner_yaml = Path(planner_yaml).resolve()
    config = yaml.safe_load(planner_yaml.read_text())
    pan_config = config.get("pan", {})
    adjust_config = config.get("adjust", {})
    dune = planner.pan.dune_layer
    nrmp = planner.pan.nrmp_layer
    dune_device = str(dune.model_device) if dune is not None else None
    dune_dtype = str(dune.inference_dtype) if dune is not None else None
    nrmp_device = str(nrmp.G.device)
    expected_dune_device = torch.device(
        pan_config.get("dune_device", config.get("device", "cpu"))
    ).type
    expected_dune_dtype = pan_config.get("dune_dtype", "float32").lower()
    expected_nrmp_backend = pan_config.get(
        "nrmp_backend", "cvxpylayers_cpu"
    ).lower()
    if expected_nrmp_backend in ("cpu", "cvxpy", "cvxpylayers"):
        expected_nrmp_backend = "cvxpylayers_cpu"
    expected_nrmp_solver = adjust_config.get("solver", "ECOS")
    matches_config = (
        dune is not None
        and dune.model_device.type == expected_dune_device
        and str(dune.inference_dtype).removeprefix("torch.")
        == expected_dune_dtype
        and nrmp.nrmp_backend == expected_nrmp_backend
        and nrmp.solver == expected_nrmp_solver
        and nrmp.G.device.type == torch.device(config.get("device", "cpu")).type
    )
    return {
        "planner_config": str(planner_yaml),
        "planner_config_sha256": _sha256(planner_yaml),
        "dune_device": dune_device,
        "dune_dtype": dune_dtype,
        "nrmp_backend_requested": nrmp.nrmp_backend_requested,
        "nrmp_backend_active": nrmp.nrmp_backend,
        "nrmp_backend_reason": nrmp.nrmp_backend_reason,
        "nrmp_solver": nrmp.solver,
        "nrmp_device": nrmp_device,
        "matches_planner_config": matches_config,
        "hybrid_rocm_dune_cpu_nrmp": (
            dune is not None
            and dune.model_device.type == "cuda"
            and dune.inference_dtype == torch.float32
            and nrmp.nrmp_backend == "cvxpylayers_cpu"
            and nrmp.G.device.type == "cpu"
            and nrmp.solver == "ECOS"
        ),
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    torch.cuda.manual_seed_all(args.seed)
    device = _device(args.device)
    profile = POLICY_PROFILES["deployment3"]
    layout = (
        tire_static_layout()
        if args.layout == "tire-static"
        else sample_layout(args.seed)
    )
    radius = obstacle_radius(args.layout)
    collision_dist = radius + ROBOT_RADIUS_M
    straight = np.stack(
        (
            np.arange(PATH_SPACING_M, 8.0 + 1e-9, PATH_SPACING_M) + START_XY[0],
            np.zeros(int(round(8.0 / PATH_SPACING_M))),
        ),
        axis=1,
    )
    policy_arc = (np.arange(len(straight)) + 1) * PATH_SPACING_M
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
    planner = None
    planner_runtime = None
    shim = False
    if args.arm == "neupan":
        planner, shim = build_neupan(args.planner_config)
        planner.reset()
        planner.pan.current_nom_values = [None] * 4
        planner_runtime = neupan_runtime_contract(planner, args.planner_config)

    with obstacle_fragment(len(layout), args.layout) as fragment:
        env = _compose_env(
            terrain_generator_override=flat_physics_terrain(args.seed),
            terrain_scan_override={
                "measured_points_x": list(SCAN_X),
                "measured_points_y": list(SCAN_Y),
                "vertical_offset": 0.3,
                "scale": 1.0,
            },
            scene_fragment_files=[str(fragment)],
            ground_friction=args.friction,
            control_gains=(40.0, 1.0),
            simulate_action_latency=True,
        )
    depth_camera = SourceDepthCamera(env, 0.0)
    probe = ContactProbe(env)
    backend = env._backend
    import mujoco

    nq = backend.model.nq
    obs_state_indices = []
    for i in range(len(layout)):
        jx = backend.model.joint(f"dyn_obs{i}_x")
        jy = backend.model.joint(f"dyn_obs{i}_y")
        obs_state_indices.append(
            {
                "qpos": (1 + int(jx.qposadr[0]), 1 + int(jy.qposadr[0])),
                "qvel": (1 + nq + int(jx.dofadr[0]), 1 + nq + int(jy.dofadr[0])),
            }
        )
    del mujoco
    ctrl_dt = float(env.cfg.ctrl_dt)

    def place_obstacles(t: float) -> np.ndarray:
        centres = obstacle_positions(layout, t)
        state = backend._physics_state[0]
        for o, centre, idx in zip(layout, centres, obs_state_indices):
            state[idx["qpos"][0]] = centre[0]
            state[idx["qpos"][1]] = centre[1]
            state[idx["qvel"][0]] = o["vel_x"]
            state[idx["qvel"][1]] = o["vel_y"]
        return centres

    positions: list[list[float]] = []
    skills: list[int] = []
    vx_commanded: list[float] = []
    vx_actor: list[float] = []
    slow_steps: list[int] = []
    collision_steps: list[int] = []
    min_obstacle_dist = float("inf")
    neupan_latency_ms: list[float] = []
    neupan_stop_steps: list[int] = []
    done_steps: list[int] = []
    reached_step: int | None = None
    consumed = 0
    held_yaw = np.zeros((1, 2), dtype=np.float32)
    held_frac = 1.0
    path_length = 0.0
    previous_xy: np.ndarray | None = None
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
        for i, o in enumerate(layout):
            jx = backend.get_joint_dof_pos_indices((f"dyn_obs{i}_x",))[0] + 7
            jy = backend.get_joint_dof_pos_indices((f"dyn_obs{i}_y",))[0] + 7
            qpos[0, int(jx)] = o["start_x"]
            qpos[0, int(jy)] = o["start_y"]
        backend.set_state(np.asarray([0], dtype=np.int32), qpos, qvel)
        state = env.update_state(state)
        adapter.reset()
        state.info["current_actions"] = agility_action_to_unilab(
            np.zeros((1, 12), dtype=np.float32), profile.low_contract
        )
        previous_foot_contact.fill(0.0)
        return state

    def step(state):
        nonlocal reached_step, consumed, held_yaw, held_frac, path_length
        nonlocal previous_xy, previous_foot_contact, all_finite, min_obstacle_dist
        step_index = len(positions) + 1
        t = (step_index - 1) * ctrl_dt
        centres = place_obstacles(t)
        base_quat = backend.get_base_quat().copy()
        base_pos = backend.get_base_pos().copy()
        robot_xy = base_pos[0, :2].astype(np.float64)
        base_yaw = _base_yaw(base_quat[0])
        if previous_xy is not None and reached_step is None:
            path_length += float(np.linalg.norm(robot_xy - previous_xy))
        previous_xy = robot_xy.copy()
        dists = np.linalg.norm(centres - robot_xy.reshape(1, 2), axis=1)
        min_obstacle_dist = min(min_obstacle_dist, float(dists.min()))
        if reached_step is None and float(dists.min()) < collision_dist:
            collision_steps.append(step_index)
        if reached_step is None and (
            float(np.linalg.norm(robot_xy - np.asarray(GOAL_XY))) < GOAL_THRESHOLD_M
        ):
            reached_step = step_index - 1

        frac = 1.0
        if args.arm == "neupan":
            if (step_index - 1) % REPLAN_PERIOD_STEPS == 0:
                planner_started = time.perf_counter()
                points = surface_points(centres, radius)
                velocities = np.hstack(
                    [
                        np.tile([[o["vel_x"]], [o["vel_y"]]], (1, SURFACE_POINTS_PER_OBSTACLE))
                        for o in layout
                    ]
                )
                action, info = planner(
                    np.asarray([[robot_xy[0]], [robot_xy[1]], [base_yaw]]),
                    points,
                    velocities,
                )
                neupan_latency_ms.append(
                    (time.perf_counter() - planner_started) * 1000.0
                )
                if info["stop"] or info["arrive"]:
                    neupan_stop_steps.append(step_index)
                    remaining, consumed = remaining_policy_path(
                        straight, policy_arc, straight, robot_xy, consumed
                    )
                    waypoint = path_to_tsc_waypoints(
                        remaining,
                        np.asarray([robot_xy[0], robot_xy[1], base_yaw]),
                        CURRENT_LOOKAHEAD_M,
                        NEXT_LOOKAHEAD_M,
                        MAX_ABS_YAW_RAD,
                    )
                    held_frac = 0.0 if info["stop"] else 1.0
                else:
                    trajectory = np.hstack(planner.opt_trajectory).T
                    waypoint = path_to_tsc_waypoints(
                        trajectory,
                        np.asarray([robot_xy[0], robot_xy[1], base_yaw]),
                        CURRENT_LOOKAHEAD_M,
                        NEXT_LOOKAHEAD_M,
                        MAX_ABS_YAW_RAD,
                    )
                    held_frac = float(np.clip(action[0, 0] / NEUPAN_REF_SPEED, 0.0, 1.0))
                held_yaw = np.asarray(
                    [[waypoint.delta_yaw, waypoint.delta_next_yaw]], dtype=np.float32
                )
            delta_yaw = held_yaw
            frac = held_frac
        else:
            remaining, consumed = remaining_policy_path(
                straight, policy_arc, straight, robot_xy, consumed
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
            if args.arm == "ttc" and ttc_slow(robot_xy, base_yaw, layout, t):
                frac = 0.0
        if frac < 1.0:
            slow_steps.append(step_index)

        contact = probe.sample()
        sensor_floor = (np.linalg.norm(env.feet_force, axis=2) > 2.0).astype(np.float32)
        current_contact = np.maximum(contact["foot_contact"], sensor_floor)
        foot_contact = np.maximum(current_contact, previous_foot_contact)
        previous_foot_contact = current_contact

        command, diagnostics = adapter.preview_command(
            base_quat_wxyz=base_quat,
            base_ang_vel=env.get_gyro().copy(),
            dof_pos=env.get_dof_pos().copy(),
            dof_vel=env.get_dof_vel().copy(),
            foot_contact=foot_contact,
            depth_image=depth_camera.capture(),
            delta_yaw=delta_yaw,
            obstacle_type=FREE_SPACE_CLASS,
        )
        skill = int(diagnostics["skill"][0])
        vx_min = float(adapter.commander.command_offset_mat[skill, 0])
        actor_vx = float(command[0, 0])
        command = command.copy()
        command[0, 0] = float(np.clip(frac * actor_vx, vx_min, max(actor_vx, vx_min)))
        vx_actor.append(actor_vx)
        vx_commanded.append(command[0, 0])
        action, low = adapter.bbc.act(
            base_quat_wxyz=base_quat,
            base_ang_vel=env.get_gyro().copy(),
            dof_pos=env.get_dof_pos().copy(),
            dof_vel=env.get_dof_vel().copy(),
            foot_contact=foot_contact,
            command=command,
            explicit=None,
        )
        # Student deployment zero-history contract (adapter.act replica).
        adapter.bbc.history.fill(0.0)
        skills.append(skill)
        state = env.step(action)
        if np.any(state.terminated | state.truncated):
            done_steps.append(step_index)
        base_after = backend.get_base_pos().copy()
        positions.append(base_after[0].tolist())
        all_finite = all_finite and all(
            np.isfinite(value).all()
            for value in (action, delta_yaw, command, low["source_action"], base_after)
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
                "cam_elevation": -25.0,
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
    success = (
        reached_step is not None and not collision_steps and not done_before
    )
    shortest = 8.0
    spl = (
        shortest / max(path_length, shortest) if success else 0.0
    )
    checks = {
        "live_env_action_contract": bool(live_contract["passed"]),
        "rollout_finite": all_finite,
        "step_count": len(positions) == EPISODE_STEPS,
        "video_created": video_exists,
        "video_frame_count": video.get("frames") == EPISODE_STEPS,
    }
    if planner_runtime is not None:
        checks["neupan_runtime_matches_planner_config"] = bool(
            planner_runtime["matches_planner_config"]
        )
    elapsed = time.monotonic() - started
    return {
        "run_id": args.run_id,
        "arm": args.arm,
        "layout_name": args.layout,
        "seed": args.seed,
        "status": "PASSED" if all(checks.values()) else "FAILED",
        "episode_success": success,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "evaluation_type": "simulation_only",
        "checks": checks,
        "metrics": {
            "reached_step": reached_step,
            "collision_step_count": len(collision_steps),
            "collision_steps": collision_steps[:20],
            "min_obstacle_distance_m": min_obstacle_dist,
            "path_length_m": path_length,
            "spl": spl,
            "slow_step_count": len(slow_steps),
            "done_before_success_steps": done_before,
            "vx_actor_mean": float(np.mean(vx_actor)),
            "vx_commanded_mean": float(np.mean(vx_commanded)),
            "neupan_latency_ms_p50": (
                float(np.percentile(neupan_latency_ms, 50))
                if neupan_latency_ms
                else None
            ),
            "neupan_latency_ms_p95": (
                float(np.percentile(neupan_latency_ms, 95))
                if neupan_latency_ms
                else None
            ),
            "neupan_latency_ms_p99": (
                float(np.percentile(neupan_latency_ms, 99))
                if neupan_latency_ms
                else None
            ),
            "neupan_calls": len(neupan_latency_ms),
            "neupan_latency_ms": [round(x, 3) for x in neupan_latency_ms],
            "neupan_stop_steps": neupan_stop_steps[:20],
            "wall_time_sec": elapsed,
            "gpu_hours": elapsed / 3600.0,
        },
        "layout": layout,
        "skill_counts": {
            str(int(s)): int(c) for s, c in zip(*np.unique(skills, return_counts=True))
        },
        "contracts": {
            "start_xy": list(START_XY),
            "goal_xy": list(GOAL_XY),
            "goal_threshold_m": GOAL_THRESHOLD_M,
            "collision_dist_m": collision_dist,
            "obstacle_radius_m": radius,
            "episode_steps": EPISODE_STEPS,
            "replan_period_steps": REPLAN_PERIOD_STEPS,
            "ttc_rule": {
                "horizon_s": TTC_HORIZON_S,
                "lateral_m": TTC_LATERAL_M,
                "forward_m": TTC_FORWARD_BASE_M,
                "robot_nominal_speed": ROBOT_NOMINAL_SPEED,
            },
            "speed_authority": "vx = clip(frac * actor_vx, skill_range_min, actor_vx)",
            "free_space_class": FREE_SPACE_CLASS,
            "planner_yaml": str(args.planner_config),
            "planner_yaml_sha256": _sha256(args.planner_config),
            "neupan_runtime": planner_runtime,
            "dune_checkpoint_sha256": (
                _sha256(NEUPAN_ROOT / "example/model/go2_diff_070_040/model_2000.pth")
                if args.arm == "neupan"
                else None
            ),
            "headless_tkinter_shim": shim,
            "depth_encoder_override": (
                {
                    "path": str(args.depth_encoder_checkpoint),
                    "sha256": _sha256(args.depth_encoder_checkpoint),
                }
                if args.depth_encoder_checkpoint is not None
                else None
            ),
            "high_checkpoint_sha256": _sha256(HIGH_CHECKPOINT),
            "runner_sha256": _sha256(Path(__file__)),
            "bridge_sha256": _sha256(Path(__file__).resolve().parent / "bridge.py"),
            "friction": args.friction,
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
    parser.add_argument("--layout", choices=LAYOUTS, default="dynamic")
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--planner-config", type=Path, default=PLANNER_YAML)
    parser.add_argument("--friction", type=float, default=1.0)
    parser.add_argument("--depth-encoder-checkpoint", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    if args.depth_encoder_checkpoint is not None and (
        not args.depth_encoder_checkpoint.is_file()
    ):
        parser.error(f"missing checkpoint: {args.depth_encoder_checkpoint}")
    args.planner_config = args.planner_config.resolve()
    if not args.planner_config.is_file():
        parser.error(f"missing planner config: {args.planner_config}")
    args.run_id = f"NAG-501-{args.layout}-{args.arm}-s{args.seed}"
    args.output_dir = args.output_dir or RESULTS_ROOT / args.arm / f"s{args.seed}"
    args.stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    args.output_video = (
        args.output_dir / f"nag501_{args.layout}_{args.arm}_s{args.seed}.mp4"
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
            "arm": args.arm,
            "seed": args.seed,
            "status": "FAILED",
            "episode_success": False,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "error": f"{type(exc).__name__}: {exc}",
        }
    _write_json(result_path, payload)
    shutil.copy2(result_path, args.output_dir / "result.json")
    print(
        f"{payload['status']} success={payload['episode_success']}: {result_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
