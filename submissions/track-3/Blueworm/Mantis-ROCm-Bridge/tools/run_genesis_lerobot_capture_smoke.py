#!/usr/bin/env python3
"""Exercise real Genesis state/action/camera sampling and expected dataset rejection."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
from pathlib import Path
from typing import Any

from mantis_rocm_bridge.camera_mounts import genesis_wrist_mounts
from mantis_rocm_bridge.contracts import load_json, validate_contract_pair
from mantis_rocm_bridge.episode_export import (
    MantisLeRobotExportSession,
    create_lerobot_dataset_sink,
)
from mantis_rocm_bridge.genesis_capture import (
    PolicyCaptureClock,
    genesis_rgb_array,
)
from mantis_rocm_bridge.genesis_smoke import (
    BACKENDS,
    physical_pose,
    resolve_backend,
    sha256_file,
)
from mantis_rocm_bridge.ops import begin_run, finish_run
from mantis_rocm_bridge.stack_bowls_env import (
    sample_source_reset_poses,
    validate_genesis_scene_contract,
)


ROOT = Path(__file__).resolve().parents[1]


def _vector(value: Any) -> list[float]:
    if hasattr(value, "detach"):
        value = value.detach()
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "numpy"):
        value = value.numpy()
    import numpy as np

    return np.asarray(value, dtype=float).reshape(-1).tolist()


def _dof_indices(robot: Any, names: list[str]) -> list[int]:
    result = []
    for name in names:
        indices = _vector(robot.get_joint(name).dofs_idx_local)
        if len(indices) != 1:
            raise RuntimeError(f"expected one DOF for {name}")
        result.append(int(indices[0]))
    return result


def _read_dofs(robot: Any, indices: list[int]) -> list[float]:
    try:
        return _vector(robot.get_dofs_position(dofs_idx_local=indices))
    except TypeError:
        return _vector(robot.get_dofs_position(indices))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mantis_urdf", type=Path)
    parser.add_argument("bowl_asset_root", type=Path)
    parser.add_argument("--ops-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--backend", choices=BACKENDS, required=True)
    parser.add_argument("--frames", type=int, default=3)
    parser.add_argument(
        "--scene-contract",
        type=Path,
        default=ROOT / "configs/stack-bowls-genesis-v1.json",
    )
    parser.add_argument(
        "--camera-contract",
        type=Path,
        default=ROOT / "configs/camera-extrinsics-v1.json",
    )
    parser.add_argument(
        "--port", type=Path, default=ROOT / "configs/mantis-port-config.json"
    )
    parser.add_argument(
        "--interface",
        type=Path,
        default=ROOT / "configs/mantis-lerobot-interface-v1.json",
    )
    parser.add_argument(
        "--source-task",
        type=Path,
        default=ROOT / "configs/source-task-stack-bowls-three.json",
    )
    parser.add_argument(
        "--task", type=Path, default=ROOT / "configs/task-pack-v1.json"
    )
    parser.add_argument(
        "--export-contract",
        type=Path,
        default=ROOT / "configs/sim-episode-export-v1.json",
    )
    args = parser.parse_args()
    if not 1 <= args.frames <= 31:
        parser.error("--frames must be in [1, 31]")
    bowl_urdf = args.bowl_asset_root / "urdf/robotwin_002_bowl_model3.urdf"
    bowl_manifest_path = args.bowl_asset_root / "manifest.json"
    for path in (args.mantis_urdf, bowl_urdf, bowl_manifest_path):
        if not path.is_file():
            parser.error(f"required asset file does not exist: {path}")

    port = load_json(args.port)
    interface = load_json(args.interface)
    source_task = load_json(args.source_task)
    task = load_json(args.task)
    scene_contract = load_json(args.scene_contract)
    camera_contract = load_json(args.camera_contract)
    export_contract = load_json(args.export_contract)
    bowl_manifest = load_json(bowl_manifest_path)
    validate_contract_pair(port, task, source_task)
    validate_genesis_scene_contract(scene_contract, source_task, port)
    mounts = genesis_wrist_mounts(camera_contract)
    if bowl_manifest.get("distribution_allowed") is not True:
        raise RuntimeError("bowl materialization is not licensed for distribution")

    seed = 1
    reset = sample_source_reset_poses(seed=seed)
    run_dir = args.ops_root / args.run_id
    begun = False
    receipt_written = False
    try:
        begin_run(
            args.ops_root,
            args.run_id,
            {
                "phase": "genesis_lerobot_capture_expected_rejection",
                "seed": seed,
                "frames": args.frames,
                "backend": args.backend,
                "scene_contract_sha256": sha256_file(args.scene_contract),
                "camera_contract_sha256": sha256_file(args.camera_contract),
                "interface_contract_sha256": sha256_file(args.interface),
                "export_contract_sha256": sha256_file(args.export_contract),
                "mantis_urdf_sha256": sha256_file(args.mantis_urdf),
                "bowl_urdf_sha256": sha256_file(bowl_urdf),
            },
        )
        begun = True
        import genesis as gs
        import numpy as np

        dt = float(scene_contract["control"]["physics_dt_s"])
        clock = PolicyCaptureClock(
            physics_dt_s=dt,
            policy_hz=float(task["policy_hz"]),
        )
        gs.init(
            backend=resolve_backend(gs, args.backend),
            seed=seed,
            logging_level="warning",
        )
        scene = gs.Scene(
            sim_options=gs.options.SimOptions(dt=dt),
            show_viewer=False,
        )
        scene.add_entity(
            gs.morphs.Plane(
                pos=(0.0, 0.0, float(scene_contract["world"]["table_plane_z_m"])),
                fixed=True,
            )
        )
        base = scene_contract["world"]["mantis_base"]
        robot = scene.add_entity(
            gs.morphs.URDF(
                file=str(args.mantis_urdf.resolve()),
                pos=tuple(base["position_xyz_m"]),
                quat=tuple(base["quaternion_wxyz"]),
                fixed=True,
            )
        )
        for pose in reset:
            scene.add_entity(
                gs.morphs.URDF(
                    file=str(bowl_urdf.resolve()),
                    pos=pose.position_xyz_m,
                    quat=pose.quaternion_wxyz,
                    fixed=False,
                    merge_fixed_links=False,
                    recompute_inertia=False,
                    file_meshes_are_zup=True,
                ),
                name=pose.name,
            )

        env_mount = camera_contract["mounts"]["env_cam"]
        env_position = np.asarray(env_mount["position_xyz_m"], dtype=float)
        env_forward = np.asarray(env_mount["forward_xyz"], dtype=float)
        cameras = {
            "observation.images.env_cam": scene.add_camera(
                res=(320, 240),
                pos=tuple(env_position),
                lookat=tuple(env_position + env_forward),
                fov=37.0,
                near=0.1,
                far=100.0,
                GUI=False,
            )
        }
        for name, feature_key in (
            ("left_wrist_cam", "observation.images.left_wrist_cam"),
            ("right_wrist_cam", "observation.images.right_wrist_cam"),
        ):
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
                robot.get_link(mounts[name]["parent"]),
                np.asarray(mounts[name]["offset_T"], dtype=float),
            )
            cameras[feature_key] = camera
        scene.build()

        physical_names = port["target"]["physical_joint_order"]
        indices = _dof_indices(robot, physical_names)
        target = np.asarray(physical_pose(port, 1.0), dtype=float)
        robot.set_qpos(target)
        robot.control_dofs_position(target, dofs_idx_local=indices)
        for _ in range(25):
            scene.step()

        rejected_root = run_dir / "rejected-lerobot-buffer"
        sink = create_lerobot_dataset_sink(
            repo_id="local/mantis_genesis_capture_expected_rejection",
            root=rejected_root,
            interface=interface,
            use_videos=False,
        )
        export_session = MantisLeRobotExportSession(
            sink=sink,
            port=port,
            interface=interface,
            task=task,
            export_contract=export_contract,
            allow_unverified_gripper=True,
        )
        export_session.begin_episode(seed=seed)
        export_session.complete_stage(
            task["stages"][0],
            policy_step=0,
            details={"reset_distribution": "exact_source"},
        )
        export_session.complete_stage(
            task["stages"][1],
            policy_step=0,
            details={"three_camera_capture": True},
        )

        schedule = []
        current_step = 0
        for frame_index in range(args.frames):
            tick = clock.tick(frame_index)
            while current_step < tick.physics_step:
                robot.control_dofs_position(target, dofs_idx_local=indices)
                scene.step()
                current_step += 1
            images = {
                key: genesis_rgb_array(
                    camera.render(rgb=True, force_render=True)
                )
                for key, camera in cameras.items()
            }
            state = _read_dofs(robot, indices)
            export_session.add_frame(
                timestamp_s=tick.policy_timestamp_s,
                physical_state=state,
                physical_action=target,
                images=images,
            )
            schedule.append(
                {
                    "frame_index": tick.frame_index,
                    "policy_timestamp_s": tick.policy_timestamp_s,
                    "physics_step": tick.physics_step,
                    "physics_timestamp_s": tick.physics_timestamp_s,
                    "sampling_skew_s": tick.sampling_skew_s,
                }
            )
        export_session.fail_stage(
            task["stages"][2],
            failure_stage="missed_grasp",
            policy_step=max(0, args.frames - 1),
            details={"reason": "deliberate_capture_rejection_smoke"},
        )
        rejection = export_session.finish_episode()
        sink.finalize()
        parquet_files = sorted(rejected_root.rglob("*.parquet"))
        image_files = sorted((rejected_root / "images").rglob("*.png"))
        zero_dataset_frames = sink.meta.total_frames == 0
        zero_dataset_episodes = sink.meta.total_episodes == 0
        capture_pass = (
            rejection["dataset_acceptance"] == "rejected"
            and rejection["frame_count"] == args.frames
            and zero_dataset_frames
            and zero_dataset_episodes
            and not parquet_files
            and not image_files
        )
        receipt = {
            "schema_version": 1,
            "runtime_capture_smoke_pass": capture_pass,
            "backend_requested": args.backend,
            "backend_active": str(gs.backend),
            "device": str(gs.device),
            "genesis_version": importlib.metadata.version("genesis-world"),
            "seed": seed,
            "frames_captured": args.frames,
            "camera_shapes": interface["camera_features"],
            "capture_schedule": schedule,
            "maximum_sampling_skew_s": max(
                row["sampling_skew_s"] for row in schedule
            ),
            "rejection_receipt": rejection,
            "dataset_frames_after_rejection": sink.meta.total_frames,
            "dataset_episodes_after_rejection": sink.meta.total_episodes,
            "parquet_files_after_rejection": [
                str(path.relative_to(rejected_root)) for path in parquet_files
            ],
            "image_files_after_rejection": len(image_files),
            "training_data_written": False,
            "task_success_claim": False,
            "g1_claim": False,
            "rocm_claim": False,
            "claim_boundary": (
                "Real Genesis state/action/three-camera capture and expected "
                "LeRobot rejection only; not a task attempt or demonstration."
            ),
        }
        receipt_path = run_dir / "receipt.json"
        receipt_path.write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        receipt_written = True
        receipt_hash = sha256_file(receipt_path)
        finish_run(
            args.ops_root,
            args.run_id,
            "completed" if capture_pass else "failed",
            {
                "receipt_sha256": receipt_hash,
                "runtime_capture_smoke_pass": capture_pass,
            },
        )
        print(json.dumps(receipt, indent=2, sort_keys=True))
        return 0 if capture_pass else 2
    except Exception as exc:
        if begun and not receipt_written:
            finish_run(
                args.ops_root,
                args.run_id,
                "failed",
                {"error_type": type(exc).__name__, "message": str(exc)},
            )
        raise


if __name__ == "__main__":
    raise SystemExit(main())
