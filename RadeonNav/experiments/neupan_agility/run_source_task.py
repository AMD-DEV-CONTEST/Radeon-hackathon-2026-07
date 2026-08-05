#!/usr/bin/env python3
"""Run one source-derived Quadrupedal-Agility task in UniLab for 10 seconds."""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

os.environ.setdefault("MUJOCO_GL", "egl")

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[2]
AGILITY_ROOT = ROOT / "quadrupedal-agility"
HIGH_CHECKPOINT = AGILITY_ROOT / "go2_deploy/models/high_policy/cruft/model.pt"
DEPLOYMENT_LOW_CHECKPOINT = (
    AGILITY_ROOT / "go2_deploy/models/ll_policy/3_model/model.pt"
)
SOURCE_LOW_CHECKPOINT = AGILITY_ROOT / "tsc/weights/bbc/model.pt"
RESULTS_ROOT = ROOT / "experiment-results/quadrupedal-agility"
sys.path.insert(0, str(ROOT / "experiments/cpp_adapter"))

from cpp_loco_sanity import _compose_env, _sha256  # noqa: E402
from run_bbc_sanity import _device, _live_env_contract, _write_json  # noqa: E402
from source_tasks import (  # noqa: E402
    GOAL_THRESHOLD_M,
    SCAN_X,
    SCAN_Y,
    SOURCE_FRICTION,
    TASKS,
    configured_fragment,
    flat_physics_terrain,
    goal_delta_yaw,
    proxy_height_scan,
    proxy_sampler,
    source_episode_complete,
)
from unilab.algos.torch.quadrupedal_agility import (  # noqa: E402
    AgilityBbcContract,
    AgilityTscPolicyAdapter,
    DEFAULT_AGILITY_BBC_CONTRACT,
    SOURCE_AGILITY_BBC_CONTRACT,
    agility_action_to_unilab,
)


@dataclass(frozen=True)
class PolicyProfile:
    low_checkpoint: Path
    low_contract: AgilityBbcContract
    low_mode_count: int

    @property
    def command_dim(self) -> int:
        return 6 + self.low_mode_count

    @property
    def bbc_input_dim(self) -> int:
        return 57 + 4 + 29 + 570 + self.command_dim


POLICY_PROFILES = {
    "deployment3": PolicyProfile(
        DEPLOYMENT_LOW_CHECKPOINT,
        DEFAULT_AGILITY_BBC_CONTRACT,
        3,
    ),
    "source5": PolicyProfile(
        SOURCE_LOW_CHECKPOINT,
        SOURCE_AGILITY_BBC_CONTRACT,
        5,
    ),
}

ROBOT_JOINTS = tuple(
    f"{leg}_{joint}_joint"
    for leg in ("FL", "FR", "RL", "RR")
    for joint in ("hip", "thigh", "calf")
)
FOOT_GEOMS = ("FL", "FR", "RL", "RR")
FORBIDDEN_GEOMS = {
    "base1",
    "base2",
    "base3",
    *(f"{leg}_hip_geom" for leg in ("FL", "FR", "RL", "RR")),
    *(f"{leg}_thigh_geom" for leg in ("FL", "FR", "RL", "RR")),
}
OBSTACLE_JOINT_QPOS = {
    "bar_jump": ("source_bar_joint", 0.20),
    "tire_jump": ("source_tire_joint", 0.475),
    "seesaw": ("source_seesaw_joint", -float(np.arcsin(0.25 / 1.5))),
}


def _run_id(args: argparse.Namespace) -> str:
    if args.run_id:
        return args.run_id
    if args.diagnostic:
        return "NAG-211B-D0"
    if args.perception_only:
        return f"{TASKS[args.task].run_id}-NC"
    run_id = TASKS[args.task].run_id
    if args.high_branch == "student":
        suffix = "S16" if args.precision == "float16" else "S32"
        if args.yaw_source == "waypoint":
            suffix += "-WY"
        if args.onehot_source == "gt":
            suffix += "-GO"
        if args.depth_encoder_checkpoint is not None:
            suffix += "-FT1"
        if args.high_actor_checkpoint is not None:
            suffix += "-T2"
        return f"{run_id}-{suffix}"
    return run_id


def _set_start_state(
    env: Any,
    task: str,
    low_contract: AgilityBbcContract,
    obstacle_joint: tuple[str, float] | None,
) -> None:
    spec = TASKS[task]
    qpos = np.asarray(env._init_qpos, dtype=np.float32).reshape(1, -1).copy()
    qvel = np.zeros_like(env._init_qvel, dtype=np.float32).reshape(1, -1)
    qpos[0, :3] = (*spec.start_xy, 0.42)
    qpos[0, 3:7] = (1.0, 0.0, 0.0, 0.0)
    indices = env._backend.get_joint_dof_pos_indices(ROBOT_JOINTS) + 7
    qpos[0, indices] = low_contract.source_default_dof
    if obstacle_joint is not None:
        joint_name, joint_qpos = obstacle_joint
        obstacle_index = (
            int(env._backend.get_joint_dof_pos_indices((joint_name,))[0]) + 7
        )
        qpos[0, obstacle_index] = joint_qpos
    env._backend.set_state(np.asarray([0], dtype=np.int32), qpos, qvel)


class ContactProbe:
    def __init__(self, env: Any) -> None:
        import mujoco

        self.mujoco = mujoco
        self.backend = env._backend
        self.model = self.backend.model
        self.data = mujoco.MjData(self.model)
        self.robot_body_ids = set(
            self.backend.get_body_subtree_ids(self.backend.get_body_id("base")).tolist()
        )

    def sample(self) -> dict[str, Any]:
        mujoco = self.mujoco
        mujoco.mj_setState(
            self.model,
            self.data,
            np.asarray(self.backend._physics_state[0], dtype=np.float64),
            mujoco.mjtState.mjSTATE_FULLPHYSICS,
        )
        mujoco.mj_forward(self.model, self.data)
        foot_force = dict.fromkeys(FOOT_GEOMS, 0.0)
        floor_foot_force = dict.fromkeys(FOOT_GEOMS, 0.0)
        pairs: list[str] = []
        forbidden: list[str] = []
        for contact_index in range(self.data.ncon):
            contact = self.data.contact[contact_index]
            geom1, geom2 = int(contact.geom[0]), int(contact.geom[1])
            body1 = int(self.model.geom_bodyid[geom1])
            body2 = int(self.model.geom_bodyid[geom2])
            if (body1 in self.robot_body_ids) == (body2 in self.robot_body_ids):
                continue
            robot_geom, other_geom = (
                (geom1, geom2) if body1 in self.robot_body_ids else (geom2, geom1)
            )
            robot_name = (
                mujoco.mj_id2name(self.model, mujoco.mjtObj.mjOBJ_GEOM, robot_geom)
                or f"geom_{robot_geom}"
            )
            other_name = (
                mujoco.mj_id2name(self.model, mujoco.mjtObj.mjOBJ_GEOM, other_geom)
                or f"geom_{other_geom}"
            )
            force = np.zeros(6, dtype=np.float64)
            mujoco.mj_contactForce(self.model, self.data, contact_index, force)
            force_norm = float(np.linalg.norm(force[:3]))
            pair = f"{robot_name}:{other_name}"
            pairs.append(pair)
            if robot_name in foot_force:
                foot_force[robot_name] = max(foot_force[robot_name], force_norm)
                if other_name == "floor":
                    floor_foot_force[robot_name] = max(
                        floor_foot_force[robot_name], force_norm
                    )
            if robot_name in FORBIDDEN_GEOMS and force_norm > 1.0:
                forbidden.append(pair)
        return {
            "foot_contact": np.asarray(
                [[foot_force[name] > 2.0 for name in FOOT_GEOMS]], dtype=np.float32
            ),
            "floor_foot_contact": np.asarray(
                [[floor_foot_force[name] > 2.0 for name in FOOT_GEOMS]],
                dtype=np.float32,
            ),
            "pairs": pairs,
            "forbidden": forbidden,
        }


def _preprocess_source_depth(depth: np.ndarray) -> np.ndarray:
    raw = np.asarray(depth, dtype=np.float32)
    if raw.shape != (60, 106):
        raise ValueError(f"raw depth must have shape (60, 106), got {raw.shape}")
    cropped = np.clip(raw[1:-1, 10:-9], 0.3, 4.0)
    return ((cropped - 0.3) / 3.7 - 0.5).astype(np.float32)


class SourceDepthCamera:
    """Render the source Go2 body-mounted depth observation from MuJoCo."""

    def __init__(self, env: Any, pitch_deg: float = 0.0) -> None:
        import mujoco

        self.mujoco = mujoco
        self.backend = env._backend
        spec = mujoco.MjSpec.from_file(self.backend.scene_visual_model_file)
        body = spec.body("base")
        if body is None:
            raise RuntimeError("MuJoCo scene has no Go2 base body")
        camera = body.add_camera()
        camera.name = "source_depth_camera"
        camera.pos = [0.305, 0.0175, 0.098]
        pitch = math.radians(pitch_deg)
        camera_axes = np.asarray(
            [
                [0.0, math.sin(pitch), -math.cos(pitch)],
                [-1.0, 0.0, 0.0],
                [0.0, math.cos(pitch), math.sin(pitch)],
            ],
            dtype=np.float64,
        )
        camera_quat = np.zeros(4, dtype=np.float64)
        mujoco.mju_mat2Quat(camera_quat, camera_axes.reshape(-1))
        camera.quat = camera_quat.tolist()
        camera.fovy = math.degrees(
            2.0 * math.atan(math.tan(math.radians(87.0) / 2.0) * 60.0 / 106.0)
        )
        self.model = spec.compile()
        source_state_size = mujoco.mj_stateSize(
            self.backend.model, mujoco.mjtState.mjSTATE_FULLPHYSICS
        )
        render_state_size = mujoco.mj_stateSize(
            self.model, mujoco.mjtState.mjSTATE_FULLPHYSICS
        )
        if source_state_size != render_state_size:
            raise RuntimeError(
                "depth render model changed the physics-state contract: "
                f"{source_state_size} != {render_state_size}"
            )
        self.data = mujoco.MjData(self.model)
        self.renderer = mujoco.Renderer(self.model, height=60, width=106)
        self.renderer.enable_depth_rendering()

    def capture(self) -> np.ndarray:
        mujoco = self.mujoco
        mujoco.mj_setState(
            self.model,
            self.data,
            np.asarray(self.backend._physics_state[0], dtype=np.float64),
            mujoco.mjtState.mjSTATE_FULLPHYSICS,
        )
        mujoco.mj_forward(self.model, self.data)
        self.renderer.update_scene(self.data, camera="source_depth_camera")
        return _preprocess_source_depth(self.renderer.render())[None]

    def close(self) -> None:
        self.renderer.close()


def _video_metadata(path: Path) -> dict[str, Any]:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-count_frames",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=avg_frame_rate,nb_read_frames,width,height",
        "-of",
        "json",
        str(path),
    ]
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    stream = json.loads(completed.stdout)["streams"][0]
    numerator, denominator = (
        int(value) for value in stream["avg_frame_rate"].split("/")
    )
    return {
        "frames": int(stream["nb_read_frames"]),
        "fps": numerator / denominator,
        "width": int(stream["width"]),
        "height": int(stream["height"]),
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    if args.duration != 10.0:
        raise ValueError("source task gate requires exactly 10.0 seconds")
    spec = TASKS[args.task]
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    torch.cuda.manual_seed_all(args.seed)
    device = _device(args.device)
    profile = POLICY_PROFILES[args.policy_profile]
    if args.high_branch == "student" and args.policy_profile != "deployment3":
        raise ValueError("depth student checkpoint requires deployment3 low policy")
    obstacle_joint = OBSTACLE_JOINT_QPOS.get(args.task)
    if args.task == "bar_jump":
        obstacle_joint = ("source_bar_joint", args.bar_height)
    if args.perception_only:
        obstacle_joint = None
    adapter = AgilityTscPolicyAdapter(
        AGILITY_ROOT,
        HIGH_CHECKPOINT,
        profile.low_checkpoint,
        device=device,
        low_contract=profile.low_contract,
        low_mode_count=profile.low_mode_count,
        command_profile="deployment",
        high_branch=args.high_branch,
        use_half=args.precision == "float16",
    )
    if args.depth_encoder_checkpoint is not None:
        override = torch.load(
            args.depth_encoder_checkpoint, map_location=device, weights_only=True
        )
        adapter.depth_encoder.load_state_dict(override)
        if args.precision == "float16":
            adapter.depth_encoder.half()
        adapter.depth_encoder.eval()
    if args.high_actor_checkpoint is not None:
        actor_override = torch.load(
            args.high_actor_checkpoint, map_location=device, weights_only=True
        )
        adapter.high_model.load_state_dict(actor_override)
        if args.precision == "float16":
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
    with configured_fragment(spec, bar_height=args.bar_height) as fragment:
        effective_fragment_sha256 = _sha256(fragment)
        env = _compose_env(
            terrain_generator_override=flat_physics_terrain(args.seed),
            terrain_scan_override={
                "measured_points_x": list(SCAN_X),
                "measured_points_y": list(SCAN_Y),
                "vertical_offset": 0.3,
                "scale": 1.0,
            },
            scene_fragment_files=([] if args.perception_only else [str(fragment)]),
            ground_friction=args.friction,
            control_gains=(40.0, 1.0),
            simulate_action_latency=True,
        )
    depth_camera = (
        SourceDepthCamera(env, args.camera_pitch_deg)
        if args.high_branch == "student"
        else None
    )
    num_steps = int(round(args.duration / float(env.cfg.ctrl_dt)))
    if num_steps != 500:
        raise RuntimeError(f"expected 500 control steps, got {num_steps}")
    args.output_video.parent.mkdir(parents=True, exist_ok=True)
    sampler = proxy_sampler(args.task, bar_height=args.bar_height)
    probe = ContactProbe(env)
    obstacle_joint_index = (
        int(env._backend.get_joint_dof_pos_indices((obstacle_joint[0],))[0])
        if obstacle_joint is not None
        else None
    )
    positions: list[list[float]] = []
    skills: list[int] = []
    skill_transition_events: list[dict[str, Any]] = []
    commands: list[list[float]] = []
    predicted_delta_yaws: list[list[float]] = []
    gt_delta_yaws: list[list[float]] = []
    actor_delta_yaws: list[list[float]] = []
    predicted_obstacles: list[int] = []
    obstacle_probabilities: list[list[float]] = []
    depth_statistics: list[list[float]] = []
    obstacle_joint_positions: list[float] = []
    obstacle_joint_velocities: list[float] = []
    inference_ms: list[float] = []
    contact_steps: list[int] = []
    obstacle_contact_steps: list[int] = []
    first_obstacle_contact_pairs: list[str] = []
    forbidden_steps: list[int] = []
    contact_pairs: Counter[str] = Counter()
    goal_index = 0
    reach_goal_timer = 0
    goal_advance_steps: list[int] = []
    reached_final_step: int | None = None
    skill_switches = 0
    last_skill: int | None = None
    done_steps: list[int] = []
    all_finite = True
    shape_contract = True
    contact_probe_agreement: list[bool] = []
    contact_probe_mismatch_steps: list[int] = []
    episode_success_steps: list[int] = []
    episode_success_positions: list[list[float]] = []
    previous_foot_contact = np.zeros((1, 4), dtype=np.float32)
    live_contract: dict[str, Any] = {}
    started = time.monotonic()

    def initialize():
        nonlocal goal_index, reach_goal_timer, previous_foot_contact, live_contract
        live_contract = _live_env_contract(env)
        if not bool(live_contract["passed"]):
            raise RuntimeError(f"live UniLab action contract mismatch: {live_contract}")
        state = env.init_state()
        env.set_autoreset(False)
        _set_start_state(
            env,
            args.task,
            profile.low_contract,
            obstacle_joint,
        )
        state = env.update_state(state)
        adapter.reset()
        state.info["current_actions"] = agility_action_to_unilab(
            np.zeros((1, 12), dtype=np.float32),
            profile.low_contract,
        )
        goal_index = 0
        reach_goal_timer = 0
        previous_foot_contact.fill(0.0)
        return state

    def step(state):
        nonlocal all_finite, goal_index, reach_goal_timer, reached_final_step
        nonlocal skill_switches, shape_contract, previous_foot_contact, last_skill
        step_index = len(positions) + 1
        if reached_final_step is None and source_episode_complete(
            spec, goal_index, reach_goal_timer
        ):
            terminal_position = env._backend.get_base_pos()[0].tolist()
            episode_success_steps.append(step_index - 1)
            episode_success_positions.append(terminal_position)
            reached_final_step = step_index - 1
        base_quat = env._backend.get_base_quat().copy()
        base_pos = env._backend.get_base_pos().copy()
        previous_goal_index = goal_index
        delta_yaw, goal_index, reach_goal_timer = goal_delta_yaw(
            spec,
            base_pos,
            base_quat,
            goal_index,
            reach_goal_timer,
        )
        if goal_index != previous_goal_index:
            goal_advance_steps.append(step_index)
        contact = probe.sample()
        sensor_floor_contact = (np.linalg.norm(env.feet_force, axis=2) > 2.0).astype(
            np.float32
        )
        contact_agrees = bool(
            np.array_equal(contact["floor_foot_contact"], sensor_floor_contact)
        )
        contact_probe_agreement.append(contact_agrees)
        if not contact_agrees:
            contact_probe_mismatch_steps.append(step_index)
        current_foot_contact = np.maximum(contact["foot_contact"], sensor_floor_contact)
        foot_contact = np.maximum(current_foot_contact, previous_foot_contact)
        previous_foot_contact = current_foot_contact
        scan = proxy_height_scan(base_pos, base_quat, sampler)
        low_explicit = np.concatenate(
            (0.3 + scan[:, 67:68], env.get_local_linvel() * 0.5),
            axis=1,
        ).astype(np.float32)
        policy_observations: dict[str, Any] = {
            "base_quat_wxyz": base_quat,
            "base_ang_vel": env.get_gyro().copy(),
            "dof_pos": env.get_dof_pos().copy(),
            "dof_vel": env.get_dof_vel().copy(),
            "foot_contact": foot_contact,
        }
        if depth_camera is None:
            policy_observations.update(
                {
                    "height_scan": scan,
                    "delta_yaw": delta_yaw,
                    "obstacle_type": spec.obstacle_index,
                    "low_explicit": low_explicit,
                }
            )
        else:
            policy_observations["depth_image"] = depth_camera.capture()
            if args.yaw_source == "waypoint":
                policy_observations["delta_yaw"] = delta_yaw
            if args.onehot_source == "gt":
                policy_observations["obstacle_type"] = spec.obstacle_index
            gt_delta_yaws.append(delta_yaw[0].tolist())
        inference_started = time.perf_counter()
        action, diagnostics = adapter.act(**policy_observations)
        if device.type == "cuda":
            torch.cuda.synchronize(device)
        inference_ms.append((time.perf_counter() - inference_started) * 1000.0)
        shape_contract = shape_contract and (
            diagnostics["high_input"].shape == (1, 771)
            and diagnostics["skill"].shape == (1,)
            and diagnostics["high_continuous"].shape == (1, 18)
            and diagnostics["command"][:, :5].shape == (1, 5)
            and diagnostics["command"].shape == (1, profile.command_dim)
            and diagnostics["low_input"].shape == (1, profile.bbc_input_dim)
            and diagnostics["source_action"].shape == (1, 12)
            and action.shape == (1, 12)
        )
        if depth_camera is not None:
            shape_contract = shape_contract and (
                diagnostics["depth_image"].shape == (1, 58, 87)
                and diagnostics["depth_latent"].shape == (1, 40)
                and diagnostics["predicted_delta_yaw"].shape == (1, 2)
                and diagnostics["obstacle_probabilities"].shape == (1, 6)
                and diagnostics["actor_delta_yaw"].shape == (1, 2)
                and diagnostics["actor_obstacle_one_hot"].shape == (1, 6)
            )
            predicted_delta_yaws.append(diagnostics["predicted_delta_yaw"][0].tolist())
            actor_delta_yaws.append(diagnostics["actor_delta_yaw"][0].tolist())
            predicted_obstacles.append(int(diagnostics["predicted_obstacle"][0]))
            obstacle_probabilities.append(
                diagnostics["obstacle_probabilities"][0].tolist()
            )
            depth = diagnostics["depth_image"]
            depth_statistics.append(
                [
                    float(np.min(depth)),
                    float(np.mean(depth)),
                    float(np.max(depth)),
                ]
            )
        skill = int(diagnostics["skill"][0])
        if last_skill != skill:
            skill_transition_events.append(
                {
                    "step": step_index,
                    "from": last_skill,
                    "to": skill,
                    "base_xyz_m": base_pos[0].tolist(),
                }
            )
            if last_skill is not None:
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
            obstacle_joint_velocities.append(
                float(env._backend._dof_vel_view[0, obstacle_joint_index])
            )
        after_contact = probe.sample()
        if after_contact["pairs"]:
            contact_steps.append(step_index)
            contact_pairs.update(after_contact["pairs"])
        obstacle_pairs = [
            pair for pair in after_contact["pairs"] if not pair.endswith(":floor")
        ]
        if obstacle_pairs:
            obstacle_contact_steps.append(step_index)
            if not first_obstacle_contact_pairs:
                first_obstacle_contact_pairs.extend(sorted(set(obstacle_pairs)))
        if after_contact["forbidden"]:
            forbidden_steps.append(step_index)
        all_finite = all_finite and all(
            np.isfinite(value).all()
            for value in (
                action,
                scan,
                *(
                    (diagnostics["depth_image"], diagnostics["depth_latent"])
                    if depth_camera is not None
                    else ()
                ),
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
        if depth_camera is not None:
            depth_camera.close()
        env.close()

    video_exists = rendered_path is not None and args.output_video.is_file()
    video = _video_metadata(args.output_video) if video_exists else {}
    final_goal_distance = float(
        np.linalg.norm(
            np.asarray(positions[-1][:2], dtype=np.float32)
            - np.asarray(spec.goals[-1][:2], dtype=np.float32)
        )
    )
    gate_end_step = reached_final_step or len(positions)
    forbidden_before_success = [
        step for step in forbidden_steps if step <= gate_end_step
    ]
    done_before_success = [step for step in done_steps if step <= gate_end_step]
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
        "contact_probe_floor_agreement": all(contact_probe_agreement),
        "reached_final_goal": reached_final_step is not None,
    }
    required_checks = tuple(
        name for name in checks if name != "contact_probe_floor_agreement"
    )
    unique, counts = np.unique(skills, return_counts=True)
    peak_base_step = int(np.argmax(np.asarray(positions)[:, 2])) + 1
    elapsed = time.monotonic() - started
    return {
        "run_id": _run_id(args),
        "task": spec.name,
        "status": (
            "PASSED" if all(checks[name] for name in required_checks) else "FAILED"
        ),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "evaluation_type": "simulation_only",
        "diagnostic_only": args.perception_only or args.diagnostic,
        "unlock_eligible": not (args.perception_only or args.diagnostic),
        "scope": (
            (
                "source-derived single-task frozen depth student "
                f"(yaw={args.yaw_source}, one-hot={args.onehot_source}) "
                "to deployment3 BBC"
            )
            if args.high_branch == "student"
            else "source-derived single-task frozen TSC teacher to deployment3 BBC"
            if args.policy_profile == "deployment3"
            else "source-derived single-task frozen TSC teacher to source5 BBC"
        ),
        "policy_profile": args.policy_profile,
        "high_branch": args.high_branch,
        "precision": args.precision,
        "seed": args.seed,
        "duration_sec": args.duration,
        "ctrl_dt": float(env.cfg.ctrl_dt),
        "steps": len(positions),
        "device": str(device),
        "device_name": torch.cuda.get_device_name(device),
        "checks": checks,
        "metrics": {
            "start_xy_m": list(spec.start_xy),
            "final_base_xyz_m": positions[-1],
            "forward_progress_m": (
                episode_success_positions[0][0] - spec.start_xy[0]
                if episode_success_positions
                else positions[-1][0] - spec.start_xy[0]
            ),
            "final_goal_distance_m": final_goal_distance,
            "reached_final_step": reached_final_step,
            "episode_success_steps": episode_success_steps,
            "episode_success_positions_m": episode_success_positions,
            "final_goal_index": goal_index,
            "goal_advance_steps": goal_advance_steps,
            "skill_switch_count": skill_switches,
            "skill_transition_events": skill_transition_events,
            "peak_base_z_m": positions[peak_base_step - 1][2],
            "peak_base_z_step": peak_base_step,
            "peak_base_xyz_m": positions[peak_base_step - 1],
            "obstacle_joint_qpos_m_or_rad": (
                {
                    "target": obstacle_joint[1],
                    "minimum": min(obstacle_joint_positions),
                    "maximum": max(obstacle_joint_positions),
                    "final": obstacle_joint_positions[-1],
                }
                if obstacle_joint_positions
                else None
            ),
            "obstacle_joint_qvel_mps_or_radps": (
                {
                    "minimum": min(obstacle_joint_velocities),
                    "maximum": max(obstacle_joint_velocities),
                    "maximum_absolute": max(
                        abs(value) for value in obstacle_joint_velocities
                    ),
                    "final": obstacle_joint_velocities[-1],
                }
                if obstacle_joint_velocities
                else None
            ),
            "contact_step_count": len(contact_steps),
            "contact_steps": contact_steps,
            "obstacle_contact_step_count": len(obstacle_contact_steps),
            "obstacle_contact_steps": obstacle_contact_steps,
            "first_obstacle_contact_step": (
                obstacle_contact_steps[0] if obstacle_contact_steps else None
            ),
            "first_obstacle_contact_pairs": first_obstacle_contact_pairs,
            "forbidden_contact_step_count": len(forbidden_steps),
            "forbidden_contact_steps": forbidden_steps,
            "forbidden_contact_before_success_steps": forbidden_before_success,
            "done_steps": done_steps,
            "done_before_success_steps": done_before_success,
            "contact_probe_floor_mismatch_count": len(contact_probe_mismatch_steps),
            "contact_probe_floor_mismatch_steps": contact_probe_mismatch_steps,
            "inference_ms_mean": float(np.mean(inference_ms)),
            "inference_ms_p99": float(np.quantile(inference_ms, 0.99)),
            "wall_time_sec": elapsed,
            "gpu_hours": elapsed / 3600.0,
            "predicted_delta_yaw_mean": (
                np.mean(predicted_delta_yaws, axis=0).tolist()
                if predicted_delta_yaws
                else None
            ),
            "gt_delta_yaw_mean": (
                np.mean(gt_delta_yaws, axis=0).tolist() if gt_delta_yaws else None
            ),
            "actor_delta_yaw_mean": (
                np.mean(actor_delta_yaws, axis=0).tolist()
                if actor_delta_yaws
                else None
            ),
            "predicted_gt_delta_yaw_abs_error_mean": (
                np.mean(
                    np.abs(
                        np.asarray(predicted_delta_yaws, dtype=np.float64)
                        - np.asarray(gt_delta_yaws, dtype=np.float64)
                    ),
                    axis=0,
                ).tolist()
                if predicted_delta_yaws
                else None
            ),
            "predicted_obstacle_gt_agreement_rate": (
                float(
                    np.mean(
                        [
                            index == spec.obstacle_index
                            for index in predicted_obstacles
                        ]
                    )
                )
                if predicted_obstacles
                else None
            ),
            "predicted_obstacle_counts": (
                {
                    str(index): predicted_obstacles.count(index)
                    for index in sorted(set(predicted_obstacles))
                }
                if predicted_obstacles
                else None
            ),
            "obstacle_probability_mean": (
                np.mean(obstacle_probabilities, axis=0).tolist()
                if obstacle_probabilities
                else None
            ),
            "normalized_depth_min_mean_max": (
                {
                    "minimum": float(np.min(np.asarray(depth_statistics)[:, 0])),
                    "mean": float(np.mean(np.asarray(depth_statistics)[:, 1])),
                    "maximum": float(np.max(np.asarray(depth_statistics)[:, 2])),
                }
                if depth_statistics
                else None
            ),
        },
        "skill_counts": {
            str(int(skill)): int(count) for skill, count in zip(unique, counts)
        },
        "contact_pair_counts": dict(contact_pairs.most_common()),
        "final_bbc_command": commands[-1],
        "contracts": {
            "high_input_dim": 771,
            "high_branch": (
                "depth student depth_actor_state_dict + depth_encoder_state_dict"
                if args.high_branch == "student"
                else "privileged teacher model_state_dict.actor"
            ),
            "precision": args.precision,
            "high_checkpoint": str(HIGH_CHECKPOINT),
            "high_checkpoint_sha256": _sha256(HIGH_CHECKPOINT),
            "high_output": "1 discrete skill + 5 continuous command values",
            "high_raw_continuous_dim": 18,
            "low_checkpoint": str(profile.low_checkpoint),
            "low_checkpoint_sha256": _sha256(profile.low_checkpoint),
            "low_mode_count": profile.low_mode_count,
            "bbc_command_dim": profile.command_dim,
            "bbc_input_dim": profile.bbc_input_dim,
            "bbc_action_dim": 12,
            "history_semantics": (
                "zero 570-D, matching go2_deploy HistoryWrapper.step()"
                if args.high_branch == "student"
                else "teacher migration rolling 570-D with first-frame fill"
            ),
            "hip_scale_reduction": profile.low_contract.source_hip_scale_reduction,
            "command_profile": adapter.command_profile,
            "scan_shape": [12, 11],
            "scan_resolution_m": 0.05,
            "obstacle_one_hot_index": (
                spec.obstacle_index
                if args.high_branch != "student" or args.onehot_source == "gt"
                else None
            ),
            "depth_encoder_override": (
                {
                    "path": str(args.depth_encoder_checkpoint),
                    "sha256": _sha256(args.depth_encoder_checkpoint),
                }
                if args.depth_encoder_checkpoint is not None
                else None
            ),
            "high_actor_override": (
                {
                    "path": str(args.high_actor_checkpoint),
                    "sha256": _sha256(args.high_actor_checkpoint),
                }
                if args.high_actor_checkpoint is not None
                else None
            ),
            "actor_yaw_source": (
                args.yaw_source if args.high_branch == "student" else "gt_waypoint"
            ),
            "actor_onehot_source": (
                args.onehot_source if args.high_branch == "student" else "gt"
            ),
            "depth_camera": (
                {
                    "raw_shape": [60, 106],
                    "cropped_shape": [58, 87],
                    "crop": "[1:-1, 10:-9]",
                    "position_base_m": [0.305, 0.0175, 0.098],
                    "pitch_deg": args.camera_pitch_deg,
                    "horizontal_fov_deg": 87.0,
                    "clip_m": [0.3, 4.0],
                    "normalization": "(depth-0.3)/(4.0-0.3)-0.5",
                    "noise": "none; ideal MuJoCo depth",
                    "real_camera_gap": (
                        "RealSense DepthProcess(108,60), inpainting, and "
                        "[1:-1,11:-10] are not simulated"
                    ),
                }
                if args.high_branch == "student"
                else None
            ),
            "goals": [
                [
                    goal[0],
                    goal[1],
                    (
                        args.bar_height + 0.30
                        if args.task == "bar_jump" and index == 2
                        else goal[2]
                    ),
                ]
                for index, goal in enumerate(spec.goals)
            ],
            "goal_threshold_m": GOAL_THRESHOLD_M,
            "friction": args.friction,
            "joint_mode": (
                f"stiff_slide@{args.bar_height:.2f}m,k=20000,d=1000"
                if args.task == "bar_jump"
                else spec.joint_mode
            ),
            "bar_height_m": args.bar_height if args.task == "bar_jump" else None,
            "obstacle_fragment": str(spec.fragment_file),
            "obstacle_fragment_sha256": _sha256(spec.fragment_file),
            "effective_obstacle_fragment_sha256": effective_fragment_sha256,
            "runner_sha256": _sha256(Path(__file__)),
            "adapter_sha256": _sha256(
                ROOT / "UniLab/src/unilab/algos/torch/quadrupedal_agility.py"
            ),
            "physics": (
                "flat hfield; obstacle collision removed for paired diagnosis"
                if args.perception_only
                else "flat hfield + source-derived obstacle collision"
            ),
            "perception": (
                (
                    "MuJoCo body-mounted depth; no privileged scan; actor "
                    f"yaw={args.yaw_source}, actor one-hot={args.onehot_source}"
                )
                if args.high_branch == "student"
                else "independent source proxy height map"
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
    parser.add_argument("--task", choices=tuple(TASKS), required=True)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--duration", type=float, default=10.0)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--friction", type=float, default=SOURCE_FRICTION)
    parser.add_argument("--bar-height", type=float, default=0.20)
    parser.add_argument(
        "--policy-profile",
        choices=tuple(POLICY_PROFILES),
        default="deployment3",
    )
    parser.add_argument(
        "--high-branch",
        choices=("teacher", "student"),
        default="teacher",
    )
    parser.add_argument(
        "--precision",
        choices=("float32", "float16"),
        default="float32",
    )
    parser.add_argument("--camera-pitch-deg", type=float, default=0.0)
    parser.add_argument(
        "--yaw-source",
        choices=("depth", "waypoint"),
        default="depth",
    )
    parser.add_argument(
        "--onehot-source",
        choices=("depth", "gt"),
        default="depth",
    )
    parser.add_argument("--run-id")
    parser.add_argument("--depth-encoder-checkpoint", type=Path)
    parser.add_argument("--high-actor-checkpoint", type=Path)
    parser.add_argument("--bbc-checkpoint", type=Path)
    parser.add_argument("--keep-bbc-history", action="store_true")
    parser.add_argument("--perception-only", action="store_true")
    parser.add_argument("--diagnostic", action="store_true")
    args = parser.parse_args()
    if not 0.6 <= args.friction <= 2.0:
        parser.error("--friction must stay within the source range [0.6, 2.0]")
    if not 0.05 <= args.bar_height <= 0.30:
        parser.error(
            "--bar-height must stay within the source maximum curriculum range "
            "[0.05, 0.30]"
        )
    if args.task != "bar_jump" and args.bar_height != 0.20:
        parser.error("--bar-height is only valid with --task bar_jump")
    if not -5.0 <= args.camera_pitch_deg <= 5.0:
        parser.error("--camera-pitch-deg must stay in the source range [-5, 5]")
    if args.high_branch == "student" and args.policy_profile != "deployment3":
        parser.error("--high-branch student requires --policy-profile deployment3")
    if args.high_branch != "student" and (
        args.yaw_source != "depth" or args.onehot_source != "depth"
    ):
        parser.error(
            "--yaw-source/--onehot-source overrides require --high-branch student"
        )
    if (args.perception_only or args.diagnostic) and (
        args.yaw_source != "depth" or args.onehot_source != "depth"
    ):
        parser.error("diagnostic modes cannot be combined with injection overrides")
    if args.depth_encoder_checkpoint is not None:
        if args.high_branch != "student":
            parser.error("--depth-encoder-checkpoint requires --high-branch student")
        if not args.depth_encoder_checkpoint.is_file():
            parser.error(f"missing checkpoint: {args.depth_encoder_checkpoint}")
        if args.run_id:
            parser.error(
                "--run-id cannot be combined with --depth-encoder-checkpoint "
                "(the -FT1 suffix protects archived run IDs)"
            )
    if args.run_id and (args.diagnostic or args.perception_only):
        parser.error("--run-id cannot be combined with diagnostic modes")
    if args.diagnostic and (args.task != "bar_jump" or args.perception_only):
        parser.error("--diagnostic is only valid for physical bar_jump")
    run_id = _run_id(args)
    args.output_dir = args.output_dir or RESULTS_ROOT / run_id
    args.stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    args.output_video = args.output_dir / f"{args.task}_10s_{args.stamp}.mp4"
    return args


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    result_path = args.output_dir / f"result_{args.stamp}.json"
    try:
        payload = run(args)
    except Exception as exc:
        payload = {
            "run_id": _run_id(args),
            "task": args.task,
            "status": "FAILED",
            "diagnostic_only": args.perception_only or args.diagnostic,
            "unlock_eligible": False,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "error": f"{type(exc).__name__}: {exc}",
        }
    _write_json(result_path, payload)
    shutil.copy2(result_path, args.output_dir / "result.json")
    if args.output_video.is_file():
        shutil.copy2(args.output_video, args.output_dir / f"{args.task}_10s.mp4")
    print(f"{payload['status']}: {result_path}")
    return 0 if payload["status"] == "PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
