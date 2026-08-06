#!/usr/bin/env python3
"""Run a faithful, evidence-producing Mantis ACT policy loop on AMD ROCm."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import shlex
import subprocess
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_LEROBOT_VERSION = "0.6.2"
EXPECTED_GENESIS_VERSION = "1.3.0"
IMAGE_FEATURES = (
    "observation.images.env_cam",
    "observation.images.left_wrist_cam",
    "observation.images.right_wrist_cam",
)
PROCESSOR_FILES = (
    "policy_preprocessor.json",
    "policy_postprocessor.json",
)
ALLOWED_PROXIMAL_COLLISION_LINKS = (
    "pelvis_link",
    "right_shoulder_yaw_link",
)


class LiveInferenceError(RuntimeError):
    """A fail-closed live-inference contract violation."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LiveInferenceError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise LiveInferenceError(f"JSON root must be an object: {path}")
    return value


def require_absolute_file(value: str, *, label: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise LiveInferenceError(f"{label} must be an absolute path: {path}")
    if not path.is_file():
        raise LiveInferenceError(f"{label} is not a regular file: {path}")
    return path.resolve()


def require_absolute_directory(value: str, *, label: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise LiveInferenceError(f"{label} must be an absolute path: {path}")
    if not path.is_dir():
        raise LiveInferenceError(f"{label} is not a directory: {path}")
    return path.resolve()


def require_fresh_output(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise LiveInferenceError(f"--output-dir must be an absolute path: {path}")
    if path.exists() or path.is_symlink():
        raise LiveInferenceError(f"refusing existing output path: {path}")
    parent = path.parent.resolve()
    if not parent.is_dir():
        raise LiveInferenceError(f"output parent is not a directory: {parent}")
    return parent / path.name


def validate_finite_vector(
    values: Sequence[float], *, expected: int, label: str
) -> list[float]:
    result = [float(value) for value in values]
    if len(result) != expected:
        raise LiveInferenceError(
            f"{label} must contain {expected} values, got {len(result)}"
        )
    if not all(math.isfinite(value) for value in result):
        raise LiveInferenceError(f"{label} contains a non-finite value")
    return result


def resolve_dof_indices(robot: Any, names: Sequence[str]) -> list[int]:
    indices: list[int] = []
    for name in names:
        joint = robot.get_joint(str(name))
        raw = joint.dofs_idx_local
        if hasattr(raw, "detach"):
            raw = raw.detach()
        if hasattr(raw, "cpu"):
            raw = raw.cpu()
        if hasattr(raw, "tolist"):
            raw = raw.tolist()
        values = list(raw) if isinstance(raw, (list, tuple)) else [raw]
        if len(values) != 1:
            raise LiveInferenceError(f"expected one named DOF for {name}: {values}")
        indices.append(int(values[0]))
    if len(indices) != len(set(indices)):
        raise LiveInferenceError("physical joint order resolves to duplicate DOF indices")
    return indices


def read_named_dofs(robot: Any, indices: Sequence[int]) -> list[float]:
    try:
        raw = robot.get_dofs_position(dofs_idx_local=list(indices))
    except TypeError:
        raw = robot.get_dofs_position(list(indices))
    if hasattr(raw, "detach"):
        raw = raw.detach()
    if hasattr(raw, "cpu"):
        raw = raw.cpu()
    if hasattr(raw, "tolist"):
        raw = raw.tolist()
    return validate_finite_vector(raw, expected=len(indices), label="named 18D readback")


def bound_virtual_grippers(
    action: Sequence[float], port: dict[str, Any]
) -> tuple[list[float], list[dict[str, Any]]]:
    virtual_order = list(port["target"]["joint_order"])
    result = validate_finite_vector(
        action, expected=len(virtual_order), label="postprocessed virtual action"
    )
    grippers = set(
        port["assets"]["virtual_gripper_mapping"]["coefficients"].keys()
    )
    diagnostics: list[dict[str, Any]] = []
    for index, name in enumerate(virtual_order):
        if name not in grippers:
            continue
        raw = result[index]
        bounded = min(1.0, max(0.0, raw))
        result[index] = bounded
        diagnostics.append(
            {
                "index": index,
                "name": name,
                "raw": raw,
                "bounded": bounded,
                "changed": raw != bounded,
            }
        )
    if set(row["name"] for row in diagnostics) != grippers:
        raise LiveInferenceError("virtual gripper mapping is not covered by joint order")
    return result, diagnostics


def resolve_readback_tolerance(
    port: dict[str, Any], requested: float | None
) -> float:
    try:
        frozen = float(
            port["training"]["strict_simulation_dataset_runtime"]
            ["gripper_contract"]["range_tolerance_normalized"]
        )
    except (KeyError, TypeError, ValueError) as exc:
        if requested is None:
            raise LiveInferenceError(
                "port config has no valid gripper readback tolerance; "
                "--readback-range-tolerance is required"
            ) from exc
        frozen = float(requested)
    if not math.isfinite(frozen) or frozen < 0:
        raise LiveInferenceError("gripper readback tolerance must be finite and nonnegative")
    if requested is not None and not math.isclose(
        float(requested), frozen, rel_tol=0.0, abs_tol=1e-12
    ):
        raise LiveInferenceError(
            "--readback-range-tolerance disagrees with the port contract: "
            f"{requested} != {frozen}"
        )
    return frozen


def apply_allowed_collision_filter(scene: Any, robot: Any, np: Any) -> dict[str, Any]:
    geom_ids = {
        link: [int(geom.idx) for geom in robot.get_link(link).geoms]
        for link in ALLOWED_PROXIMAL_COLLISION_LINKS
    }
    collider = scene.rigid_solver.collider
    collision_pair_idx = collider._collider_info.collision_pair_idx.to_numpy()
    filtered: list[dict[str, int]] = []
    for geom_a in geom_ids[ALLOWED_PROXIMAL_COLLISION_LINKS[0]]:
        for geom_b in geom_ids[ALLOWED_PROXIMAL_COLLISION_LINKS[1]]:
            lower, upper = sorted((geom_a, geom_b))
            original = int(collision_pair_idx[lower, upper])
            if original >= 0:
                collision_pair_idx[lower, upper] = -1
                filtered.append(
                    {
                        "geom_a": lower,
                        "geom_b": upper,
                        "original_pair_index": original,
                    }
                )
    collider._collider_info.collision_pair_idx.from_numpy(collision_pair_idx)
    if not filtered:
        raise LiveInferenceError(
            "accepted proximal collision pair was not active before filtering"
        )
    readback = collider._collider_info.collision_pair_idx.to_numpy()
    if any(
        int(readback[row["geom_a"], row["geom_b"]]) != -1 for row in filtered
    ):
        raise LiveInferenceError("proximal collision-filter readback failed")
    return {
        "links": list(ALLOWED_PROXIMAL_COLLISION_LINKS),
        "filtered_pair_entries": filtered,
    }


def checkpoint_artifacts(pretrained_model: Path) -> list[Path]:
    required = [pretrained_model / "config.json", pretrained_model / "model.safetensors"]
    required.extend(pretrained_model / name for name in PROCESSOR_FILES)
    missing = [str(path) for path in required if not path.is_file() or path.stat().st_size == 0]
    if missing:
        raise LiveInferenceError(f"checkpoint artifacts are missing or empty: {missing}")
    processor_sidecars = sorted(
        path
        for pattern in ("policy_preprocessor*", "policy_postprocessor*")
        for path in pretrained_model.glob(pattern)
        if path.is_file()
    )
    artifacts = sorted(set(required + processor_sidecars))
    return artifacts


def rgb_array(rendered: Any, np: Any) -> Any:
    if isinstance(rendered, dict):
        rendered = rendered.get("rgb")
    elif isinstance(rendered, (tuple, list)):
        rendered = rendered[0]
    if hasattr(rendered, "detach"):
        rendered = rendered.detach()
    if hasattr(rendered, "cpu"):
        rendered = rendered.cpu()
    if hasattr(rendered, "numpy"):
        rendered = rendered.numpy()
    array = np.asarray(rendered)
    if array.ndim == 4 and array.shape[0] == 1:
        array = array[0]
    if array.ndim != 3 or array.shape[2] not in (3, 4):
        raise LiveInferenceError(f"unexpected Genesis RGB shape: {array.shape}")
    if array.dtype.kind == "f":
        if not np.isfinite(array).all():
            raise LiveInferenceError("Genesis RGB contains non-finite values")
        array = np.clip(array, 0.0, 1.0) * 255.0
    return array[:, :, :3].astype(np.uint8)


def render_once(cameras: dict[str, Any], np: Any) -> dict[str, Any]:
    arrays: dict[str, Any] = {}
    for feature in IMAGE_FEATURES:
        name = feature.rsplit(".", 1)[-1]
        arrays[feature] = rgb_array(
            cameras[name].render(rgb=True, force_render=True), np
        )
    return arrays


def write_text_exclusive(path: Path, text: str) -> None:
    with path.open("x", encoding="utf-8") as stream:
        stream.write(text)


def write_json_exclusive(path: Path, value: Any) -> None:
    write_text_exclusive(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def build_manifest(output_dir: Path) -> str:
    rows: list[str] = []
    for path in sorted(output_dir.rglob("*")):
        if not path.is_file() or path.name == "SHA256SUMS":
            continue
        relative = path.relative_to(output_dir).as_posix()
        rows.append(f"{sha256_file(path)}  {relative}\n")
    return "".join(rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--urdf", required=True)
    parser.add_argument("--bowl-asset-root", required=True)
    parser.add_argument("--pretrained-model", required=True)
    parser.add_argument("--port-config", required=True)
    parser.add_argument("--camera-contract", required=True)
    parser.add_argument("--scene-contract", required=True)
    parser.add_argument("--source-task", required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--steps", type=int, default=120)
    parser.add_argument("--settle-steps", type=int, default=25)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--ffmpeg", default="/usr/bin/ffmpeg")
    parser.add_argument("--readback-range-tolerance", type=float)
    return parser


def validate_args(args: argparse.Namespace) -> dict[str, Path]:
    if args.steps <= 0 or args.settle_steps < 0:
        raise LiveInferenceError("step counts must be positive (settle may be zero)")
    if args.seed < 0:
        raise LiveInferenceError("--seed must be nonnegative")
    if args.fps <= 0:
        raise LiveInferenceError("--fps must be positive")
    if args.readback_range_tolerance is not None and (
        not math.isfinite(args.readback_range_tolerance)
        or args.readback_range_tolerance < 0
    ):
        raise LiveInferenceError(
            "--readback-range-tolerance must be finite and nonnegative"
        )
    paths = {
        "urdf": require_absolute_file(args.urdf, label="--urdf"),
        "bowl_asset_root": require_absolute_directory(
            args.bowl_asset_root, label="--bowl-asset-root"
        ),
        "pretrained_model": require_absolute_directory(
            args.pretrained_model, label="--pretrained-model"
        ),
        "port_config": require_absolute_file(args.port_config, label="--port-config"),
        "camera_contract": require_absolute_file(
            args.camera_contract, label="--camera-contract"
        ),
        "scene_contract": require_absolute_file(
            args.scene_contract, label="--scene-contract"
        ),
        "source_task": require_absolute_file(args.source_task, label="--source-task"),
        "ffmpeg": require_absolute_file(args.ffmpeg, label="--ffmpeg"),
        "output_dir": require_fresh_output(args.output_dir),
    }
    paths["bowl_urdf"] = require_absolute_file(
        str(paths["bowl_asset_root"] / "urdf/robotwin_002_bowl_model3.urdf"),
        label="bowl URDF",
    )
    paths["bowl_manifest"] = require_absolute_file(
        str(paths["bowl_asset_root"] / "manifest.json"), label="bowl manifest"
    )
    checkpoint_artifacts(paths["pretrained_model"])
    return paths


def runtime_identity(torch: Any, lerobot: Any, genesis: Any) -> dict[str, Any]:
    try:
        genesis_version = importlib.metadata.version("genesis-world")
    except importlib.metadata.PackageNotFoundError:
        genesis_version = str(getattr(genesis, "__version__", "unknown"))
    lerobot_version = str(getattr(lerobot, "__version__", "unknown"))
    if lerobot_version != EXPECTED_LEROBOT_VERSION:
        raise LiveInferenceError(
            f"LeRobot must be {EXPECTED_LEROBOT_VERSION}, got {lerobot_version}"
        )
    if genesis_version != EXPECTED_GENESIS_VERSION:
        raise LiveInferenceError(
            f"Genesis must be {EXPECTED_GENESIS_VERSION}, got {genesis_version}"
        )
    hip = getattr(getattr(torch, "version", None), "hip", None)
    if not hip or not torch.cuda.is_available() or int(torch.cuda.device_count()) != 1:
        raise LiveInferenceError("exactly one ROCm torch device is required")
    device_name = str(torch.cuda.get_device_name(0))
    if not any(token in device_name.lower() for token in ("amd", "radeon", "gfx")):
        raise LiveInferenceError(f"visible device is not AMD Radeon: {device_name}")
    return {
        "python": sys.version,
        "torch": str(torch.__version__),
        "hip": str(hip),
        "device_count": int(torch.cuda.device_count()),
        "device_name": device_name,
        "lerobot": lerobot_version,
        "genesis": genesis_version,
        "backend": "gs.amdgpu",
        "offline": {
            name: os.environ.get(name)
            for name in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_LEROBOT_HOME")
        },
    }


def execute(
    args: argparse.Namespace,
    paths: dict[str, Path],
    output_dir: Path,
    contracts: dict[str, dict[str, Any]],
    readback_tolerance: float,
) -> None:
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    sys.path.insert(0, str(ROOT / "src"))

    import numpy as np
    import torch
    import genesis as gs
    import lerobot
    from PIL import Image
    from lerobot.policies.act.modeling_act import ACTPolicy
    from lerobot.policies.factory import make_pre_post_processors
    from mantis_rocm_bridge.camera_mounts import genesis_wrist_mounts
    from mantis_rocm_bridge.genesis_smoke import physical_pose
    from mantis_rocm_bridge.gripper import (
        project_physical_to_virtual,
        virtual_to_physical,
    )
    from mantis_rocm_bridge.stack_bowls_env import (
        sample_source_reset_poses,
        validate_genesis_scene_contract,
    )

    identity = runtime_identity(torch, lerobot, gs)
    write_json_exclusive(output_dir / "environment.json", identity)

    port = contracts["port"]
    camera_contract = contracts["camera"]
    scene_contract = contracts["scene"]
    source_task = contracts["source_task"]
    validate_genesis_scene_contract(scene_contract, source_task, port)
    physical_names = list(port["target"]["physical_joint_order"])
    virtual_names = list(port["target"]["joint_order"])
    if len(physical_names) != 18 or len(virtual_names) != 16:
        raise LiveInferenceError("Mantis contracts must declare 18D physical and 16D virtual orders")

    device = torch.device("cuda:0")
    policy = ACTPolicy.from_pretrained(
        str(paths["pretrained_model"]), local_files_only=True
    )
    policy.to(device)
    policy.eval()
    try:
        parameter_device = str(next(policy.parameters()).device)
    except (AttributeError, StopIteration) as exc:
        raise LiveInferenceError("loaded ACT policy exposes no parameter device") from exc
    if parameter_device != "cuda:0":
        raise LiveInferenceError(f"ACT policy parameters are on {parameter_device}")
    processors = make_pre_post_processors(
        policy_cfg=policy.config,
        pretrained_path=str(paths["pretrained_model"]),
    )
    if not isinstance(processors, tuple) or len(processors) != 2:
        raise LiveInferenceError("saved processor factory did not return a pre/post pair")
    preprocessor, postprocessor = processors
    reset = getattr(policy, "reset", None)
    if callable(reset):
        reset()

    dynamics = scene_contract["bimanual_rim_hook_probe"]
    physics_dt = float(scene_contract["control"]["physics_dt_s"])
    policy_hz = float(scene_contract["control"]["policy_hz"])
    if physics_dt <= 0 or policy_hz <= 0:
        raise LiveInferenceError("scene timing contract must be positive")
    gs.init(backend=gs.amdgpu, seed=args.seed, logging_level="warning")
    scene = gs.Scene(
        sim_options=gs.options.SimOptions(dt=physics_dt),
        show_viewer=False,
    )
    table = scene.add_entity(
        gs.morphs.Plane(
            pos=(0.0, 0.0, float(scene_contract["world"]["table_plane_z_m"])),
            fixed=True,
        )
    )
    base = scene_contract["world"]["mantis_base"]
    robot = scene.add_entity(
        gs.morphs.URDF(
            file=str(paths["urdf"]),
            pos=tuple(base["position_xyz_m"]),
            quat=tuple(base["quaternion_wxyz"]),
            fixed=True,
        )
    )
    reset_poses = sample_source_reset_poses(seed=args.seed)
    bowls = {
        pose.name: scene.add_entity(
            gs.morphs.URDF(
                file=str(paths["bowl_urdf"]),
                pos=pose.position_xyz_m,
                quat=pose.quaternion_wxyz,
                fixed=False,
                merge_fixed_links=False,
                recompute_inertia=False,
                file_meshes_are_zup=True,
            ),
            name=pose.name,
        )
        for pose in reset_poses
    }
    env_mount = camera_contract["mounts"]["env_cam"]
    env_position = np.asarray(env_mount["position_xyz_m"], dtype=float)
    env_forward = np.asarray(env_mount["forward_xyz"], dtype=float)
    cameras: dict[str, Any] = {
        "env_cam": scene.add_camera(
            res=(320, 240),
            pos=tuple(env_position),
            lookat=tuple(env_position + env_forward),
            fov=37.0,
            near=0.1,
            far=100.0,
            GUI=False,
        )
    }
    for name, mount in genesis_wrist_mounts(camera_contract).items():
        camera = scene.add_camera(
            res=(424, 240),
            pos=(0.0, 0.0, 1.0),
            lookat=(0.0, 0.0, 0.0),
            fov=37.0,
            near=0.1,
            far=100.0,
            GUI=False,
        )
        camera.attach(
            robot.get_link(mount["parent"]), np.asarray(mount["offset_T"], dtype=float)
        )
        cameras[name] = camera
    scene.build()

    indices = resolve_dof_indices(robot, physical_names)
    collision_filter = apply_allowed_collision_filter(scene, robot, np)
    for bowl in bowls.values():
        bowl.set_friction(float(dynamics["bowl_friction_coefficient"]))
    for geom in robot.geoms:
        if any(
            geom.link.name.startswith(f"{side}_clamp")
            for side in ("left", "right")
        ):
            geom.set_friction(float(dynamics["finger_friction_coefficient"]))
    arm_names = {
        f"{side}_{joint}_joint"
        for side in ("left", "right")
        for joint in (
            "shoulder_pitch",
            "shoulder_roll",
            "shoulder_yaw",
            "elbow",
            "wrist_roll",
            "wrist_pitch",
            "wrist_yaw",
        )
    }
    arm_indices = {
        index for name, index in zip(physical_names, indices) if name in arm_names
    }
    if len(arm_indices) != 14:
        raise LiveInferenceError("physical contract must resolve exactly 14 arm DOFs")
    robot.set_dofs_kp(
        [
            float(dynamics["arm_kp"] if index in arm_indices else dynamics["gripper_kp"])
            for index in indices
        ],
        dofs_idx_local=indices,
    )
    robot.set_dofs_kv(
        [
            float(dynamics["arm_kv"] if index in arm_indices else dynamics["gripper_kv"])
            for index in indices
        ],
        dofs_idx_local=indices,
    )
    lower_force = [
        -float(
            dynamics["arm_force_limit"]
            if index in arm_indices
            else dynamics["gripper_force_limit"]
        )
        for index in indices
    ]
    robot.set_dofs_force_range(
        lower_force, [-value for value in lower_force], dofs_idx_local=indices
    )
    home = np.asarray(physical_pose(port, 1.0), dtype=float)
    validate_finite_vector(home, expected=18, label="open-gripper home pose")
    robot.set_qpos(home)
    robot.control_dofs_position(home, dofs_idx_local=indices)
    for _ in range(args.settle_steps):
        scene.step()

    write_json_exclusive(
        output_dir / "scene.json",
        {
            "schema_version": 1,
            "task_id": source_task["task_id"],
            "scene_id": scene_contract["scene_id"],
            "seed": args.seed,
            "physics_dt_s": physics_dt,
            "policy_hz": policy_hz,
            "readback_range_tolerance_normalized": readback_tolerance,
            "reset_poses": [pose.as_dict() for pose in reset_poses],
            "bowl_names": list(bowls),
            "table_geom_count": len(table.geoms),
            "collision_filter": collision_filter,
            "dynamics": {
                name: dynamics[name]
                for name in (
                    "arm_kp",
                    "arm_kv",
                    "gripper_kp",
                    "gripper_kv",
                    "arm_force_limit",
                    "gripper_force_limit",
                    "bowl_friction_coefficient",
                    "finger_friction_coefficient",
                )
            },
        },
    )

    frames = output_dir / "frames"
    frames.mkdir(exist_ok=False)
    actions_path = output_dir / "policy_steps.jsonl"
    with actions_path.open("x", encoding="utf-8") as action_stream:
        simulated_policy_steps = 0
        for step in range(args.steps):
            physical = read_named_dofs(robot, indices)
            projection = project_physical_to_virtual(
                physical,
                port,
                allow_unverified=True,
                range_tolerance=readback_tolerance,
            )
            state = validate_finite_vector(
                projection.vector, expected=16, label="projected virtual state"
            )
            arrays = render_once(cameras, np)
            image_tensors = {
                name: (
                    torch.from_numpy(array.transpose(2, 0, 1).astype("float32") / 255.0)
                    .to(device)
                    .unsqueeze(0)
                )
                for name, array in arrays.items()
            }
            state_tensor = torch.tensor(
                state, dtype=torch.float32, device=device
            ).unsqueeze(0)
            preprocessed = preprocessor(
                {"observation.state": state_tensor, **image_tensors}
            )
            with torch.inference_mode():
                action_tensor = policy.select_action(preprocessed)
            postprocessed = postprocessor(action_tensor)
            if tuple(int(dim) for dim in postprocessed.shape) != (1, 16):
                raise LiveInferenceError(
                    f"postprocessed action shape must be (1, 16), got {tuple(postprocessed.shape)}"
                )
            raw_action = postprocessed[0].detach().to("cpu").tolist()
            action, gripper_diagnostics = bound_virtual_grippers(raw_action, port)
            physical_target = validate_finite_vector(
                virtual_to_physical(action, port, allow_unverified=True),
                expected=18,
                label="named physical target",
            )
            robot.control_dofs_position(
                np.asarray(physical_target, dtype=float), dofs_idx_local=indices
            )
            target_physics_steps = math.ceil(
                ((step + 1) / policy_hz) / physics_dt - 1e-12
            )
            physics_steps = target_physics_steps - simulated_policy_steps
            if physics_steps <= 0:
                raise LiveInferenceError("policy-to-physics schedule did not advance")
            for _ in range(physics_steps):
                scene.step()
            simulated_policy_steps = target_physics_steps
            frame_path = frames / f"frame_{step:06d}.png"
            Image.fromarray(arrays["observation.images.env_cam"]).save(frame_path)
            row = {
                "schema_version": 1,
                "policy_step": step,
                "physical_joint_order": physical_names,
                "virtual_joint_order": virtual_names,
                "physical_readback_18d": physical,
                "virtual_state_16d": state,
                "raw_virtual_action_16d": [float(value) for value in raw_action],
                "bounded_virtual_action_16d": action,
                "physical_target_18d": physical_target,
                "gripper_action_projection": gripper_diagnostics,
                "gripper_readback_projection": [
                    {
                        "virtual_name": item.virtual_name,
                        "physical_names": list(item.physical_names),
                        "estimates": [float(value) for value in item.estimates],
                        "projected_mean": float(item.projected_mean),
                        "spread": float(item.spread),
                    }
                    for item in projection.grippers
                ],
                "readback_range_tolerance_normalized": readback_tolerance,
                "physics_steps_applied": physics_steps,
                "physics_steps_cumulative": simulated_policy_steps,
                "camera_shapes_hwc": {
                    name: [int(value) for value in array.shape]
                    for name, array in arrays.items()
                },
                "frame": frame_path.relative_to(output_dir).as_posix(),
            }
            action_stream.write(json.dumps(row, sort_keys=True) + "\n")
            action_stream.flush()

    mp4 = output_dir / "mantis_live_infer.mp4"
    command = [
        str(paths["ffmpeg"]),
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-framerate",
        str(args.fps),
        "-i",
        str(frames / "frame_%06d.png"),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        str(mp4),
    ]
    write_text_exclusive(output_dir / "ffmpeg_command.txt", shlex.join(command) + "\n")
    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    write_text_exclusive(output_dir / "ffmpeg.stdout.log", completed.stdout)
    write_text_exclusive(output_dir / "ffmpeg.stderr.log", completed.stderr)
    if completed.returncode != 0 or not mp4.is_file() or mp4.stat().st_size == 0:
        raise LiveInferenceError(f"ffmpeg failed with exit code {completed.returncode}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        paths = validate_args(args)
        contracts = {
            "port": load_json(paths["port_config"]),
            "camera": load_json(paths["camera_contract"]),
            "scene": load_json(paths["scene_contract"]),
            "source_task": load_json(paths["source_task"]),
        }
        readback_tolerance = resolve_readback_tolerance(
            contracts["port"], args.readback_range_tolerance
        )
    except LiveInferenceError as exc:
        print(f"live inference admission failed: {exc}", file=sys.stderr)
        return 2

    output_dir = paths["output_dir"]
    output_dir.mkdir(exist_ok=False)
    write_json_exclusive(
        output_dir / "started.json",
        {
            "schema_version": 1,
            "started_at_utc": utc_now(),
            "argv": list(sys.argv if argv is None else [sys.argv[0], *argv]),
            "seed": args.seed,
            "readback_range_tolerance_normalized": readback_tolerance,
            "claim_boundary": (
                "This run may establish a saved-processor policy-in-loop simulation "
                "clip. It does not establish task success, held-out performance, "
                "robustness, real-robot safety, or submission acceptance."
            ),
        },
    )
    write_text_exclusive(
        output_dir / "command.txt",
        shlex.join(sys.argv if argv is None else [sys.argv[0], *argv]) + "\n",
    )
    input_paths = [
        paths["urdf"],
        paths["bowl_urdf"],
        paths["bowl_manifest"],
        paths["port_config"],
        paths["camera_contract"],
        paths["scene_contract"],
        paths["source_task"],
        ROOT / "tools/mantis_live_infer.py",
        ROOT / "src/mantis_rocm_bridge/camera_mounts.py",
        ROOT / "src/mantis_rocm_bridge/contracts.py",
        ROOT / "src/mantis_rocm_bridge/genesis_smoke.py",
        ROOT / "src/mantis_rocm_bridge/gripper.py",
        ROOT / "src/mantis_rocm_bridge/stack_bowls_env.py",
        *checkpoint_artifacts(paths["pretrained_model"]),
    ]
    write_text_exclusive(
        output_dir / "input_files.SHA256SUMS",
        "".join(f"{sha256_file(path)}  {path}\n" for path in input_paths),
    )

    exit_code = 0
    status = "PASS"
    try:
        execute(args, paths, output_dir, contracts, readback_tolerance)
    except Exception as exc:  # evidence boundary: all runtime errors are terminal
        exit_code = 2
        status = "FAIL"
        write_json_exclusive(
            output_dir / "error.json",
            {
                "type": type(exc).__name__,
                "message": str(exc),
                "traceback": traceback.format_exc(),
            },
        )
    write_text_exclusive(output_dir / "finished_at_utc.txt", utc_now() + "\n")
    write_text_exclusive(output_dir / "exit_code.txt", f"{exit_code}\n")
    write_text_exclusive(output_dir / "status", status + "\n")
    write_text_exclusive(output_dir / "SHA256SUMS", build_manifest(output_dir))
    if exit_code:
        print(f"live inference failed; evidence preserved at {output_dir}", file=sys.stderr)
    else:
        print(f"live inference passed; evidence preserved at {output_dir}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
