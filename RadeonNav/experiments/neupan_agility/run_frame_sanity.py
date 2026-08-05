#!/usr/bin/env python3
"""NAG-201S: one source-like frame obstacle with frozen TSC teacher + BBC."""

from __future__ import annotations

import argparse
import math
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[2]
AGILITY_ROOT = ROOT / "quadrupedal-agility"
HIGH_CHECKPOINT = AGILITY_ROOT / "go2_deploy/models/high_policy/cruft/model.pt"
DEPLOYMENT_LOW_CHECKPOINT = (
    AGILITY_ROOT / "go2_deploy/models/ll_policy/3_model/model.pt"
)
SOURCE_LOW_CHECKPOINT = AGILITY_ROOT / "tsc/weights/bbc/model.pt"
DEFAULT_OUTPUT = ROOT / "experiment-results/neupan-agility/NAG-201S/result.json"
SOURCE_OUTPUT = (
    ROOT / "experiment-results/quadrupedal-agility/NAG-202S/result.json"
)
sys.path.insert(0, str(ROOT / "experiments/cpp_adapter"))

from cpp_loco_sanity import _compose_env, _sha256  # noqa: E402
from run_bbc_sanity import _device, _live_env_contract, _write_json  # noqa: E402
from unilab.algos.torch.cpp_loco import (  # noqa: E402
    unilab_action_to_canonical_target,
)
from unilab.algos.torch.quadrupedal_agility import (  # noqa: E402
    AgilityTscPolicyAdapter,
    DEFAULT_AGILITY_BBC_CONTRACT,
    SOURCE_AGILITY_BBC_CONTRACT,
    agility_action_to_unilab,
)
from unilab.envs.locomotion.go2.rough import _force_norm_columns  # noqa: E402
from unilab.terrains import (  # noqa: E402
    SubTerrainCfg,
    TerrainHeightField,
    TerrainOutput,
)
from unilab.envs.locomotion.common.height_scan import height_scan_obs  # noqa: E402


FRAME_HALF_LENGTH_M = 1.4625
FRAME_HEIGHT_M = 0.333
FRAME_WIDTH_M = 0.6
SOURCE_FRAME_HALF_LENGTH_M = 1.45
START_X_M = -SOURCE_FRAME_HALF_LENGTH_M - 0.7
END_X_M = FRAME_HALF_LENGTH_M
SOURCE_SCAN_X = [0.1 * index for index in range(12)]
SOURCE_SCAN_Y = [0.1 * index for index in range(-5, 6)]
SOURCE_YAW_UPDATE_INTERVAL = 1
MIXED_YAW_UPDATE_INTERVAL = 5
SOURCE_GOAL_DELAY_STEPS = 1
SOURCE_GOAL_THRESHOLD_M = 0.4
FRAME_OBSTACLE_TYPE = 1
SKILL_NAMES = ("trot", "canter", "jump")
FRAME_GOALS_X = np.asarray(
    [
        START_X_M,
        -SOURCE_FRAME_HALF_LENGTH_M,
        0.0,
        SOURCE_FRAME_HALF_LENGTH_M,
    ],
    dtype=np.float32,
)


@dataclass(kw_only=True)
class SourceFrameTerrainCfg(SubTerrainCfg):
    horizontal_scale: float = 0.2
    vertical_scale: float = 0.005

    def function(self, difficulty: float, rng: np.random.Generator) -> TerrainOutput:
        del difficulty, rng
        size_x = int(round(self.size[0] / self.horizontal_scale))
        size_y = int(round(self.size[1] / self.horizontal_scale))
        noise = np.zeros((size_x, size_y), dtype=np.int16)
        center_x, center_y = size_x // 2, size_y // 2
        half_length = int(FRAME_HALF_LENGTH_M / self.horizontal_scale)
        width_cells = max(int(round(FRAME_WIDTH_M / self.horizontal_scale)), 1)
        peak = int(FRAME_HEIGHT_M / self.vertical_scale)
        ramp = np.floor(
            peak * (1.0 - np.abs(np.arange(-half_length, half_length + 1)) / half_length)
        ).astype(np.int16)
        noise[
            center_x - half_length : center_x + half_length + 1,
            center_y - width_cells // 2 : center_y - width_cells // 2 + width_cells,
        ] = ramp[:, None]
        max_height = float(peak * self.vertical_scale)
        heightfield = TerrainHeightField(
            noise=noise,
            size=self.size,
            horizontal_scale=self.horizontal_scale,
            vertical_scale=self.vertical_scale,
            elevation_min=0,
            elevation_max=peak,
            max_physical_height=max_height,
            base_thickness=max(max_height, 0.01),
            z_offset=0.0,
        )
        return TerrainOutput(
            origin=np.asarray(
                [self.size[0] / 2 + START_X_M, self.size[1] / 2, 0.0]
            ),
            heightfield=heightfield,
        )


def _frame_terrain(seed: int, horizontal_scale: float) -> dict[str, Any]:
    return {
        "seed": seed,
        "curriculum": False,
        "size": [8.0, 8.0],
        "horizontal_scale": horizontal_scale,
        "vertical_scale": 0.005,
        "border_width": 10.0,
        "num_rows": 1,
        "num_cols": 1,
        "sub_terrains": {
            "source_frame": SourceFrameTerrainCfg(
                proportion=1.0,
                horizontal_scale=horizontal_scale,
            )
        },
    }


def _set_start_state(env: Any, *, source: bool) -> None:
    qpos = np.asarray(env._init_qpos, dtype=np.float32).reshape(1, -1).copy()
    qpos[0, :2] = (START_X_M, 0.0)
    if source:
        qpos[0, 2] = 0.42
        qpos[0, -12:] = SOURCE_AGILITY_BBC_CONTRACT.source_default_dof
    env._backend.set_state(
        np.asarray([0], dtype=np.int32),
        qpos,
        np.zeros_like(env._init_qvel, dtype=np.float32).reshape(1, -1),
    )


def _undesired_contact(env: Any) -> bool:
    threshold = float(env._reward_cfg.contact_threshold)
    for name in env._cfg.sensor.undesired_contact:
        force = np.asarray(env._backend.get_sensor_data(name), dtype=np.float32)
        if np.any(_force_norm_columns(force, 1) > threshold):
            return True
    return False


def frame_delta_yaw(
    base_pos: np.ndarray,
    base_quat_wxyz: np.ndarray,
    goal_index: int,
    reach_goal_timer: int,
    goal_threshold: float = 0.2,
) -> tuple[np.ndarray, int, int]:
    position = np.asarray(base_pos, dtype=np.float32).reshape(1, 3)
    quat = np.asarray(base_quat_wxyz, dtype=np.float32).reshape(1, 4)
    if (
        goal_index < len(FRAME_GOALS_X) - 1
        and reach_goal_timer > SOURCE_GOAL_DELAY_STEPS
    ):
        goal_index += 1
        reach_goal_timer = 0
    reached = (
        np.linalg.norm(
            position[0, :2] - np.asarray([FRAME_GOALS_X[goal_index], 0.0])
        )
        < goal_threshold
    )
    if reached:
        reach_goal_timer += 1
    targets = FRAME_GOALS_X[
        [goal_index, min(goal_index + 1, len(FRAME_GOALS_X) - 1)]
    ]
    target_yaw = np.arctan2(-position[0, 1], targets - position[0, 0])
    w, x, y, z = quat[0]
    base_yaw = np.arctan2(
        2.0 * (w * z + x * y),
        1.0 - 2.0 * (y * y + z * z),
    )
    delta = (target_yaw - base_yaw + np.pi) % (2.0 * np.pi) - np.pi
    return (
        delta.reshape(1, 2).astype(np.float32),
        goal_index,
        reach_goal_timer,
    )


def run(args: argparse.Namespace) -> dict[str, Any]:
    if args.steps != 256:
        raise ValueError("frame sanity requires exactly 256 steps")
    if args.seed != 7:
        raise ValueError("frame sanity requires seed 7")
    source_profile = args.profile == "source"
    run_id = "NAG-202S" if source_profile else "NAG-201S"
    low_checkpoint = (
        SOURCE_LOW_CHECKPOINT
        if source_profile
        else DEPLOYMENT_LOW_CHECKPOINT
    )
    low_contract = (
        SOURCE_AGILITY_BBC_CONTRACT
        if source_profile
        else DEFAULT_AGILITY_BBC_CONTRACT
    )
    horizontal_scale = 0.05 if source_profile else 0.2
    yaw_update_interval = (
        SOURCE_YAW_UPDATE_INTERVAL
        if source_profile
        else MIXED_YAW_UPDATE_INTERVAL
    )
    goal_threshold = SOURCE_GOAL_THRESHOLD_M if source_profile else 0.2
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    torch.cuda.manual_seed_all(args.seed)
    device = _device(args.device)
    adapter = AgilityTscPolicyAdapter(
        AGILITY_ROOT,
        HIGH_CHECKPOINT,
        low_checkpoint,
        device=device,
        low_contract=low_contract,
        low_mode_count=5 if source_profile else 3,
        command_profile="source" if source_profile else "deployment",
    )
    env = _compose_env(
        terrain_generator_override=_frame_terrain(
            args.seed, horizontal_scale
        ),
        terrain_scan_override={
            "measured_points_x": SOURCE_SCAN_X,
            "measured_points_y": SOURCE_SCAN_Y,
            "vertical_offset": 0.3,
            "scale": 1.0,
        },
        control_gains=(40.0, 1.0),
        simulate_action_latency=source_profile,
    )

    positions: list[list[float]] = []
    clearances: list[float] = []
    surface_heights: list[float] = []
    tilts: list[float] = []
    skills: list[int] = []
    commands: list[list[float]] = []
    scan_deltas: list[float] = []
    inference_ms: list[float] = []
    forbidden_contact_steps: list[int] = []
    done_count = 0
    all_finite = True
    goal_index = 0
    reach_goal_timer = 0
    delta_yaw = np.zeros((1, 2), dtype=np.float32)
    max_abs_delta_yaw = 0.0
    started = time.monotonic()
    try:
        live_contract = _live_env_contract(env)
        if not bool(live_contract["passed"]):
            raise RuntimeError(f"live UniLab action contract mismatch: {live_contract}")
        state = env.init_state()
        _set_start_state(env, source=source_profile)
        state = env.update_state(state)
        adapter.reset()
        initial_latency_action = agility_action_to_unilab(
            np.zeros((1, 12), dtype=np.float32), low_contract
        )
        initial_latency_target_error = float(
            np.max(
                np.abs(
                    unilab_action_to_canonical_target(initial_latency_action)
                    - np.asarray(
                        low_contract.source_default_dof, dtype=np.float32
                    )
                )
            )
        )
        if source_profile:
            state.info["current_actions"] = initial_latency_action.copy()

        generated = env._terrain_surface_sampler
        command_offset = (
            adapter.commander.command_offset_mat.detach().cpu().numpy()
        )
        command_high = command_offset + (
            adapter.commander.command_range_mat.detach().cpu().numpy()
        )
        expected_command_low = np.asarray(
            [
                [0.5, -0.3, -1.57, 0.45, 0.25],
                [0.8, -0.5, -0.5, 0.45, 0.25],
                [0.8, -0.3, -0.5, 0.45, 0.25],
            ],
            dtype=np.float32,
        )
        expected_command_high = np.asarray(
            [
                [1.5, 0.3, 1.57, 0.58, 0.34],
                [2.5, 0.5, 0.5, 0.58, 0.34],
                [2.0, 0.3, 0.5, 0.58, 0.34],
            ],
            dtype=np.float32,
        )
        source_command_mapping = bool(
            np.allclose(command_offset, expected_command_low)
            and np.allclose(command_high, expected_command_high)
        )
        terrain_peak = float(
            np.max(
                generated.z_min
                + generated.heights_uint16.astype(np.float64)
                / np.iinfo(np.uint16).max
                * generated.height_extent
            )
        )
        last_contact = np.zeros((1, 4), dtype=bool)
        for step in range(1, args.steps + 1):
            base_quat = env._backend.get_base_quat().copy()
            base_pos_before_step = env._backend.get_base_pos().copy()
            fresh_delta_yaw, goal_index, reach_goal_timer = frame_delta_yaw(
                base_pos_before_step,
                base_quat,
                goal_index,
                reach_goal_timer,
                goal_threshold,
            )
            if (step - 1) % yaw_update_interval == 0:
                delta_yaw = fresh_delta_yaw
            max_abs_delta_yaw = max(
                max_abs_delta_yaw, float(np.max(np.abs(delta_yaw)))
            )
            gyro = env.get_gyro().copy()
            dof_pos = env.get_dof_pos().copy()
            dof_vel = env.get_dof_vel().copy()
            raw_contact = (
                np.linalg.norm(env.feet_force, axis=2) > 2.0
                if source_profile
                else env._foot_contact_mask().copy() > 0.5
            )
            foot_contact = np.logical_or(raw_contact, last_contact).astype(
                np.float32
            )
            last_contact = raw_contact
            scan = height_scan_obs(env, env._cfg.terrain_scan, 1)
            low_explicit = (
                np.concatenate(
                    (
                        0.3 + scan[:, 67:68],
                        env.get_local_linvel() * 0.5,
                    ),
                    axis=1,
                ).astype(np.float32)
                if source_profile
                else None
            )
            observations = {
                "base_quat_wxyz": base_quat,
                "base_ang_vel": gyro,
                "dof_pos": dof_pos,
                "dof_vel": dof_vel,
                "foot_contact": foot_contact,
                "height_scan": scan,
                "delta_yaw": delta_yaw,
                "obstacle_type": FRAME_OBSTACLE_TYPE,
                "low_explicit": low_explicit,
            }
            zero_command, _ = adapter.preview_command(
                **{**observations, "height_scan": np.zeros_like(scan)}
            )
            inference_started = time.perf_counter()
            action, diagnostics = adapter.act(**observations)
            torch.cuda.synchronize(device)
            inference_ms.append((time.perf_counter() - inference_started) * 1000.0)
            scan_deltas.append(
                float(np.max(np.abs(diagnostics["command"] - zero_command)))
            )
            skills.append(int(diagnostics["skill"][0]))
            commands.append(diagnostics["command"][0].tolist())

            state = env.step(action)
            done = state.terminated | state.truncated
            done_count += int(np.count_nonzero(done))
            base_pos = env._backend.get_base_pos().copy()
            ground_height = float(env._terrain_surface_sample_height(base_pos[:, :2])[0])
            gravity = env.get_projected_gravity()[0]
            tilt = math.acos(float(np.clip(-gravity[2], -1.0, 1.0)))
            positions.append(base_pos[0].tolist())
            clearances.append(float(base_pos[0, 2] - ground_height))
            surface_heights.append(ground_height)
            tilts.append(tilt)
            if _undesired_contact(env):
                forbidden_contact_steps.append(step)
            all_finite = all_finite and all(
                np.isfinite(value).all()
                for value in (
                    action,
                    scan,
                    diagnostics["high_input"],
                    diagnostics["skill_logits"],
                    diagnostics["command"],
                    diagnostics["source_action"],
                    state.obs["obs"],
                    base_pos,
                )
            )
            if done_count:
                break
    finally:
        env.close()

    elapsed = time.monotonic() - started
    final_x = positions[-1][0]
    frame_y = [
        abs(position[1])
        for position in positions
        if abs(position[0]) <= FRAME_HALF_LENGTH_M
    ]
    checks = {
        "live_env_contract": bool(live_contract["passed"]),
        "source_command_mapping": (
            source_command_mapping if source_profile else True
        ),
        "native_action_latency": bool(
            env._cfg.control_config.simulate_action_latency
        )
        == source_profile,
        "latency_initial_target": (
            initial_latency_target_error <= 1.0e-6
            if source_profile
            else True
        ),
        "terrain_peak": 0.328 <= terrain_peak <= 0.338,
        "scan_dimension": len(SOURCE_SCAN_X) * len(SOURCE_SCAN_Y) == 132,
        "rollout_finite": all_finite,
        "scan_changes_high_command": max(scan_deltas) > 1.0e-6,
        "crossed_frame": final_x >= END_X_M,
        "stayed_in_frame_corridor": bool(frame_y)
        and max(frame_y) <= FRAME_WIDTH_M / 2.0,
        "reached_frame_peak": max(surface_heights) >= 0.30,
        "base_clearance": min(clearances) > 0.16,
        "tilt": max(tilts) < 1.2,
        "no_early_done": done_count == 0,
        "no_forbidden_contact": not forbidden_contact_steps,
    }
    passed = all(checks.values())
    unique, counts = np.unique(skills, return_counts=True)
    return {
        "run_id": run_id,
        "status": "PASSED" if passed else "FAILED",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "evaluation_type": "simulation_only",
        "scope": (
            "N=1 pure source teacher/source BBC frame sanity"
            if source_profile
            else "N=1 teacher/deployment-BBC mixed frame diagnostic"
        ),
        "profile": args.profile,
        "seed": args.seed,
        "steps_requested": args.steps,
        "steps_completed": len(positions),
        "device": str(device),
        "device_name": torch.cuda.get_device_name(device),
        "torch_version": torch.__version__,
        "checks": checks,
        "metrics": {
            "terrain_peak_m": terrain_peak,
            "final_base_x_m": final_x,
            "forward_progress_m": final_x - START_X_M,
            "min_base_clearance_m": min(clearances),
            "max_surface_height_under_base_m": max(surface_heights),
            "max_abs_y_in_frame_m": max(frame_y) if frame_y else None,
            "max_tilt_rad": max(tilts),
            "forbidden_contact_step_count": len(forbidden_contact_steps),
            "forbidden_contact_steps": forbidden_contact_steps,
            "done_count": done_count,
            "max_scan_command_delta": max(scan_deltas),
            "max_abs_delta_yaw_rad": max_abs_delta_yaw,
            "latency_initial_target_max_abs_error_rad": (
                initial_latency_target_error
            ),
            "final_goal_index": goal_index,
            "final_reach_goal_timer": reach_goal_timer,
            "inference_ms_mean": float(np.mean(inference_ms)),
            "inference_ms_p99": float(np.quantile(inference_ms, 0.99)),
            "duration_sec": elapsed,
            "gpu_hours": elapsed / 3600.0,
        },
        "skill_counts": {
            SKILL_NAMES[int(skill)]: int(count)
            for skill, count in zip(unique, counts)
        },
        "final_command": commands[-1],
        "geometry_contract": {
            "half_length_m": FRAME_HALF_LENGTH_M,
            "height_m": FRAME_HEIGHT_M,
            "width_m": FRAME_WIDTH_M,
            "physical_hfield_horizontal_scale_m": horizontal_scale,
            "source_hfield_horizontal_scale_m": 0.05,
            "start_x_m": START_X_M,
            "success_x_m": END_X_M,
            "scan_points_x": SOURCE_SCAN_X,
            "scan_points_y": SOURCE_SCAN_Y,
            "obstacle_type": "frame",
            "obstacle_one_hot_index": FRAME_OBSTACLE_TYPE,
            "goals_x_m": FRAME_GOALS_X.tolist(),
            "yaw_update_interval_steps": yaw_update_interval,
            "goal_delay_steps": SOURCE_GOAL_DELAY_STEPS,
            "goal_threshold_m": goal_threshold,
        },
        "source_runtime_contract": {
            "contact_force_threshold_n": 2.0 if source_profile else None,
            "contact_filter": "current OR previous",
            "history_initial_full_fill_steps": 1 if source_profile else 0,
            "native_action_latency_steps": 1 if source_profile else 0,
        },
        "checkpoint_sha256": {
            "high_teacher": _sha256(HIGH_CHECKPOINT),
            "low_bbc": _sha256(low_checkpoint),
        },
        "source_sha256": {
            "adapter": _sha256(
                ROOT / "UniLab/src/unilab/algos/torch/quadrupedal_agility.py"
            ),
            "runner": _sha256(Path(__file__).resolve()),
            "source_obstacle": _sha256(
                AGILITY_ROOT / "tsc/legged_gym/utils/obstacle.py"
            ),
            "compose_env": _sha256(
                ROOT / "experiments/cpp_adapter/cpp_loco_sanity.py"
            ),
            "bbc_runner": _sha256(
                ROOT / "experiments/neupan_agility/run_bbc_sanity.py"
            ),
            "height_scan": _sha256(
                ROOT
                / "UniLab/src/unilab/envs/locomotion/common/height_scan.py"
            ),
            "rough_env": _sha256(
                ROOT / "UniLab/src/unilab/envs/locomotion/go2/rough.py"
            ),
            "terrain_generator": _sha256(
                ROOT / "UniLab/src/unilab/terrains/terrain_generator.py"
            ),
            "mujoco_model": _sha256(
                ROOT / "UniLab/src/unilab/assets/robots/go2/go2_mujoco.xml"
            ),
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=("mixed", "source"), default="mixed")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--steps", type=int, default=256)
    parser.add_argument("--seed", type=int, default=7)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.output is None:
        args.output = SOURCE_OUTPUT if args.profile == "source" else DEFAULT_OUTPUT
    try:
        payload = run(args)
    except Exception as exc:
        payload = {
            "run_id": "NAG-202S" if args.profile == "source" else "NAG-201S",
            "status": "FAILED",
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "error": f"{type(exc).__name__}: {exc}",
        }
    _write_json(args.output, payload)
    print(f"{payload['status']}: {args.output}")
    return 0 if payload["status"] == "PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
