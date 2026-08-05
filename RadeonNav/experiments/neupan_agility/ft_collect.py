#!/usr/bin/env python3
"""M-FT-1 data collection: student-acts episodes with teacher labels.

Preregistered in EXPERIMENT_PLAN.md M-FT-1. The frozen student acts in the
cell-D deployment configuration (injected GT/planner yaw + GT class, CM feed
for jump classes); a frozen teacher labels each step with its privileged-scan
actions. Per-episode randomization: friction U[0.6, 2.0], camera pitch
U[-5, 5] deg, source depth-noise model on the normalized image.

Episode files (.npz) store the sequences needed to fine-tune the depth
encoder against the source distillation loss with the deployment input
contract (encoder proprio slot 57 = wrapped absolute yaw; actor obs uses
zero history and the injected yaw/class).
"""

from __future__ import annotations

import argparse
import math
import os
import sys
import time
from contextlib import nullcontext
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
    OBSTACLE_JOINT_QPOS,
    POLICY_PROFILES,
    ROBOT_JOINTS,
    ContactProbe,
    SourceDepthCamera,
)
from run_static_2p5d import (  # noqa: E402
    JUMP_CLASSES,
    committed_delta_yaw,
    update_class_state,
)
from run_waypoint_envelope import (  # noqa: E402
    CONDITIONS,
    _base_yaw,
    condition_paths,
    remaining_policy_path,
)
from source_tasks import (  # noqa: E402
    TASKS,
    configured_fragment,
    flat_physics_terrain,
    goal_delta_yaw,
    proxy_height_scan,
    proxy_sampler,
    SCAN_X,
    SCAN_Y,
)
from static_2p5d import (  # noqa: E402
    FREE_SPACE_CLASS,
    PATH_SPACING_M,
    SCENARIOS,
    plan_scenario,
)
from unilab.algos.torch.quadrupedal_agility import (  # noqa: E402
    AgilityTscPolicyAdapter,
    agility_action_to_unilab,
)

DATA_ROOT = ROOT / "experiment-results/quadrupedal-agility/FT1-DATA"
EPISODE_STEPS = 500
DEPTH_NOISE_SCALE = 0.05
FRICTION_RANGE = (0.6, 2.0)
PITCH_RANGE_DEG = (-5.0, 5.0)
CURRENT_LOOKAHEAD_M = 0.35
NEXT_LOOKAHEAD_M = 0.70
MAX_ABS_YAW_RAD = 0.60
SOURCE_FAMILY = tuple(
    name for name in TASKS if name != "bar_jump"
)  # frame, tunnel, poles, tire_jump, seesaw
PLANNER_FAMILY = ("TF", "TR", "TS")
ENVELOPE_FAMILY = tuple(CONDITIONS)


class _FlatSampler:
    """Flat-ground proxy scan for obstacle-free envelope episodes."""

    @staticmethod
    def sample_height(xy: np.ndarray) -> np.ndarray:
        return np.zeros(np.asarray(xy, dtype=np.float64).shape[:-1])


def apply_source_depth_noise(
    depth: np.ndarray, rng: np.random.Generator, scale: float = DEPTH_NOISE_SCALE
) -> np.ndarray:
    """Source depth-noise model on the normalized image (legged_robot.py:154-174)."""
    noisy = depth + scale * 2.0 * (rng.random() - 0.5)
    amplitude = scale * rng.random()
    noisy = noisy + amplitude * 2.0 * (rng.random(size=depth.shape) - 0.5)
    return np.clip(noisy, -0.5, 0.5).astype(np.float32)


def run_episode(args: argparse.Namespace) -> dict[str, Any]:
    rng = np.random.default_rng(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    torch.cuda.manual_seed_all(args.seed)
    friction = float(rng.uniform(*FRICTION_RANGE))
    pitch_deg = float(rng.uniform(*PITCH_RANGE_DEG))
    device = _device(args.device)
    profile = POLICY_PROFILES["deployment3"]

    if args.family == "source":
        spec = TASKS[args.scene]
        task_name = args.scene
        start_xy, start_yaw = spec.start_xy, 0.0
        obstacle_joint = OBSTACLE_JOINT_QPOS.get(args.scene)
        plan = None
    elif args.family == "planner":
        scenario = SCENARIOS[args.scene]
        task_name = scenario.task_fragment
        plan = plan_scenario(scenario)
        start_xy, start_yaw = scenario.start_xy, float(plan["initial_yaw"])
        obstacle_joint = scenario.obstacle_joint
    else:  # envelope: obstacle-free flat path following, free-space class.
        _, dense_path_e, initial_yaw_e = condition_paths(args.scene)
        task_name = None
        # Canonical dense 0.05 m feed for training data (sparse variants were
        # NAG-251 robustness evals, not the deployment feed).
        plan = {"dense_path": dense_path_e, "intervals": ()}
        start_xy, start_yaw = (0.0, 0.0), initial_yaw_e
        obstacle_joint = None

    student = AgilityTscPolicyAdapter(
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
        student.depth_encoder.load_state_dict(override)
        student.depth_encoder.half()
        student.depth_encoder.eval()
    teacher = AgilityTscPolicyAdapter(
        AGILITY_ROOT,
        HIGH_CHECKPOINT,
        profile.low_checkpoint,
        device=device,
        low_contract=profile.low_contract,
        low_mode_count=profile.low_mode_count,
        command_profile="deployment",
        high_branch="teacher",
        use_half=False,
    )
    fragment_context = (
        configured_fragment(TASKS[task_name], bar_height=0.20)
        if task_name is not None
        else nullcontext(None)
    )
    with fragment_context as fragment:
        env = _compose_env(
            terrain_generator_override=flat_physics_terrain(args.seed),
            terrain_scan_override={
                "measured_points_x": list(SCAN_X),
                "measured_points_y": list(SCAN_Y),
                "vertical_offset": 0.3,
                "scale": 1.0,
            },
            scene_fragment_files=[str(fragment)] if fragment is not None else [],
            ground_friction=friction,
            control_gains=(40.0, 1.0),
            simulate_action_latency=True,
        )
    depth_camera = SourceDepthCamera(env, pitch_deg)
    sampler = (
        proxy_sampler(task_name, bar_height=0.20)
        if task_name is not None
        else _FlatSampler()
    )
    probe = ContactProbe(env)
    gt_class = (
        TASKS[task_name].obstacle_index if task_name is not None else FREE_SPACE_CLASS
    )

    if plan is not None:
        dense_path = plan["dense_path"]
        policy_arc_m = (np.arange(len(dense_path)) + 1) * PATH_SPACING_M
        intervals = plan["intervals"]

    records: dict[str, list] = {key: [] for key in (
        "depth", "proprio57", "abs_yaw", "explicit4", "injected_yaw",
        "gt_class", "gt_yaw", "teacher_idx", "teacher_c18", "done",
        "forbidden",
    )}
    goal_index = 0
    reach_goal_timer = 0
    consumed_points = 0
    class_arc_m = 0.0
    committed_headings: tuple[float, float] | None = None
    previous_foot_contact = np.zeros((1, 4), dtype=np.float32)

    def initialize():
        nonlocal previous_foot_contact
        live = _live_env_contract(env)
        if not bool(live["passed"]):
            raise RuntimeError(f"live UniLab action contract mismatch: {live}")
        state = env.init_state()
        env.set_autoreset(False)
        qpos = np.asarray(env._init_qpos, dtype=np.float32).reshape(1, -1).copy()
        qvel = np.zeros_like(env._init_qvel, dtype=np.float32).reshape(1, -1)
        qpos[0, :3] = (start_xy[0], start_xy[1], 0.42)
        half = start_yaw / 2.0
        qpos[0, 3:7] = (math.cos(half), 0.0, 0.0, math.sin(half))
        indices = env._backend.get_joint_dof_pos_indices(ROBOT_JOINTS) + 7
        qpos[0, indices] = profile.low_contract.source_default_dof
        if obstacle_joint is not None:
            joint_index = (
                int(env._backend.get_joint_dof_pos_indices((obstacle_joint[0],))[0]) + 7
            )
            qpos[0, joint_index] = obstacle_joint[1]
        env._backend.set_state(np.asarray([0], dtype=np.int32), qpos, qvel)
        state = env.update_state(state)
        student.reset()
        teacher.reset()
        state.info["current_actions"] = agility_action_to_unilab(
            np.zeros((1, 12), dtype=np.float32), profile.low_contract
        )
        previous_foot_contact.fill(0.0)
        return state

    def step(state):
        nonlocal goal_index, reach_goal_timer, consumed_points, class_arc_m
        nonlocal committed_headings, previous_foot_contact
        base_quat = env._backend.get_base_quat().copy()
        base_pos = env._backend.get_base_pos().copy()
        base_yaw_now = _base_yaw(base_quat[0])

        if plan is None:
            gt_yaw, goal_index, reach_goal_timer = goal_delta_yaw(
                TASKS[args.scene], base_pos, base_quat, goal_index, reach_goal_timer
            )
            injected_yaw = gt_yaw
            active_class = gt_class
        else:
            robot_xy = base_pos[0, :2]
            nearest = int(
                np.argmin(np.linalg.norm(dense_path - robot_xy.reshape(1, 2), axis=1))
            )
            class_arc_m, active_class = update_class_state(
                intervals, class_arc_m, nearest
            )
            remaining, consumed_points = remaining_policy_path(
                dense_path, policy_arc_m, dense_path, robot_xy, consumed_points
            )
            waypoint = path_to_tsc_waypoints(
                remaining,
                np.asarray(
                    [base_pos[0, 0], base_pos[0, 1], base_yaw_now], dtype=np.float64
                ),
                CURRENT_LOOKAHEAD_M,
                NEXT_LOOKAHEAD_M,
                MAX_ABS_YAW_RAD,
            )
            injected_yaw = np.asarray(
                [[waypoint.delta_yaw, waypoint.delta_next_yaw]], dtype=np.float32
            )
            # CM feed is the adopted jump-class deployment contract (M4b).
            if active_class in JUMP_CLASSES:
                if committed_headings is None:
                    committed_headings = (
                        base_yaw_now + float(injected_yaw[0, 0]),
                        base_yaw_now + float(injected_yaw[0, 1]),
                    )
                injected_yaw, _ = committed_delta_yaw(committed_headings, base_yaw_now)
            elif committed_headings is not None:
                committed_headings = None
            gt_yaw = injected_yaw

        contact = probe.sample()
        records["forbidden"].append(bool(contact["forbidden"]))
        sensor_floor = (np.linalg.norm(env.feet_force, axis=2) > 2.0).astype(np.float32)
        current_contact = np.maximum(contact["foot_contact"], sensor_floor)
        foot_contact = np.maximum(current_contact, previous_foot_contact)
        previous_foot_contact = current_contact

        depth_clean = depth_camera.capture()
        depth_noisy = apply_source_depth_noise(depth_clean[0], rng)[None]

        scan = proxy_height_scan(base_pos, base_quat, sampler)
        observations = {
            "base_quat_wxyz": base_quat,
            "base_ang_vel": env.get_gyro().copy(),
            "dof_pos": env.get_dof_pos().copy(),
            "dof_vel": env.get_dof_vel().copy(),
            "foot_contact": foot_contact,
        }
        _, teacher_diag = teacher.preview_command(
            **observations,
            height_scan=scan,
            delta_yaw=gt_yaw,
            obstacle_type=int(active_class),
        )
        action, student_diag = student.act(
            **observations,
            depth_image=depth_noisy,
            delta_yaw=injected_yaw,
            obstacle_type=int(active_class),
        )
        # Keep the teacher's internal BBC state mirroring the executed rollout
        # so its next-step proprio (previous action) and history stay valid.
        # First step full-fills the history like the teacher-chain contract
        # (AgilityTscPolicyAdapter.act _history_fill_steps semantics).
        teacher.bbc.previous_action[:] = student_diag["source_action"]
        if not records["done"]:
            teacher.bbc.history[:] = np.tile(student_diag["proprio"], (1, 10))
        else:
            teacher.bbc.history[:, :-57] = teacher.bbc.history[:, 57:]
            teacher.bbc.history[:, -57:] = student_diag["proprio"]

        records["depth"].append(depth_noisy[0].astype(np.float16))
        records["proprio57"].append(student_diag["proprio"][0].astype(np.float32))
        records["abs_yaw"].append(student_diag["absolute_yaw"][0].astype(np.float32))
        records["explicit4"].append(
            student_diag["high_explicit"][0].astype(np.float32)
        )
        records["injected_yaw"].append(np.asarray(injected_yaw[0], dtype=np.float32))
        records["gt_class"].append(np.int64(active_class))
        records["gt_yaw"].append(np.asarray(gt_yaw[0], dtype=np.float32))
        records["teacher_idx"].append(np.int64(teacher_diag["skill"][0]))
        records["teacher_c18"].append(
            teacher_diag["high_continuous"][0].astype(np.float32)
        )
        state = env.step(action)
        records["done"].append(
            bool(np.any(state.terminated | state.truncated))
        )
        return state

    started = time.monotonic()
    try:
        env.run_playback(
            initialize=initialize,
            step=step,
            num_steps=EPISODE_STEPS,
            output_video=args.output_dir / f"{args.tag}.mp4",
            headless=True,
            record_video=True,
        )
    finally:
        depth_camera.close()
        env.close()

    arrays = {key: np.stack(value) for key, value in records.items()}
    payload = {
        "family": args.family,
        "scene": args.scene,
        "seed": args.seed,
        "friction": friction,
        "camera_pitch_deg": pitch_deg,
        "steps": int(arrays["done"].shape[0]),
        "depth_noise_scale": DEPTH_NOISE_SCALE,
        "jump_feed": "commit" if args.family == "planner" else "n/a",
        "acting_encoder": (
            {
                "path": str(args.depth_encoder_checkpoint),
                "sha256": _sha256(args.depth_encoder_checkpoint),
            }
            if args.depth_encoder_checkpoint is not None
            else "released"
        ),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "high_checkpoint_sha256": _sha256(HIGH_CHECKPOINT),
        "collector_sha256": _sha256(Path(__file__)),
        "wall_time_sec": time.monotonic() - started,
    }
    np.savez_compressed(args.output_dir / f"{args.tag}.npz", **arrays)
    _write_json(args.output_dir / f"{args.tag}.json", payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--family", choices=("source", "planner", "envelope"), required=True
    )
    parser.add_argument("--scene", required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--output-dir", type=Path, default=DATA_ROOT)
    parser.add_argument("--depth-encoder-checkpoint", type=Path)
    args = parser.parse_args()
    if args.depth_encoder_checkpoint is not None and (
        not args.depth_encoder_checkpoint.is_file()
    ):
        parser.error(f"missing checkpoint: {args.depth_encoder_checkpoint}")
    valid = {
        "source": SOURCE_FAMILY,
        "planner": PLANNER_FAMILY,
        "envelope": ENVELOPE_FAMILY,
    }[args.family]
    if args.scene not in valid:
        parser.error(f"--scene must be one of {valid} for family {args.family}")
    args.tag = f"{args.family}_{args.scene}_seed{args.seed}"
    return args


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    payload = run_episode(args)
    print(f"COLLECTED {payload['steps']} steps: {args.tag} (mu={payload['friction']:.3f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
