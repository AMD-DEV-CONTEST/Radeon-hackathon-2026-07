#!/usr/bin/env python3
"""Load Mantis, three licensed bowls, and frozen wrist cameras in Genesis."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import math
import platform
from pathlib import Path
from typing import Any

from mantis_rocm_bridge.camera_mounts import genesis_wrist_mounts
from mantis_rocm_bridge.contracts import (
    load_json,
    validate_contract_pair,
    validate_scene_gate_contracts,
)
from mantis_rocm_bridge.genesis_smoke import BACKENDS, resolve_backend, sha256_file
from mantis_rocm_bridge.ops import begin_run, finish_run


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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mantis_urdf", type=Path)
    parser.add_argument("bowl_asset_root", type=Path)
    parser.add_argument("--port", type=Path, default=ROOT / "configs/mantis-port-config.json")
    parser.add_argument("--source-task", type=Path, default=ROOT / "configs/source-task-stack-bowls-three.json")
    parser.add_argument("--task", type=Path, default=ROOT / "configs/task-pack-v1.json")
    parser.add_argument("--control", type=Path, default=ROOT / "configs/control-resampling-v1.json")
    parser.add_argument("--cameras", type=Path, default=ROOT / "configs/camera-extrinsics-v1.json")
    parser.add_argument("--bowl-plan", type=Path, default=ROOT / "configs/bowl-asset-plan.json")
    parser.add_argument("--ops-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--backend", choices=BACKENDS, required=True)
    parser.add_argument("--steps", type=int, default=10)
    args = parser.parse_args()
    if args.steps < 1:
        parser.error("--steps must be positive")
    bowl_urdf = args.bowl_asset_root / "urdf/robotwin_002_bowl_model3.urdf"
    manifest_path = args.bowl_asset_root / "manifest.json"
    for path in (args.mantis_urdf, bowl_urdf, manifest_path):
        if not path.is_file():
            parser.error(f"required asset file does not exist: {path}")

    port = load_json(args.port)
    source_task = load_json(args.source_task)
    task = load_json(args.task)
    control = load_json(args.control)
    cameras = load_json(args.cameras)
    bowl_plan = load_json(args.bowl_plan)
    validate_contract_pair(port, task, source_task)
    validate_scene_gate_contracts(port, control, cameras, bowl_plan)
    bowl_manifest = load_json(manifest_path)
    if bowl_manifest.get("distribution_allowed") is not True:
        raise RuntimeError("bowl materialization is not licensed for distribution")
    collision_representation = bowl_manifest.get(
        "collision_representation",
        "source_multiple_convex_glb",
    )
    parser_boundary = (
        "explicit STL collision parts avoid the Genesis GLB legacy collision-parser fallback"
        if collision_representation == "source_multiple_convex_stl_parts"
        else "Genesis 1.2.3 uses its legacy URDF parser fallback for GLB collision meshes"
    )
    mounts = genesis_wrist_mounts(cameras)
    run_dir = args.ops_root / args.run_id
    begun = False
    try:
        begin_run(
            args.ops_root,
            args.run_id,
            {
                "phase": "genesis_stack_bowls_scene_gate",
                "backend": args.backend,
                "port_config_sha256": sha256_file(args.port),
                "source_task_contract_sha256": sha256_file(args.source_task),
                "target_task_contract_sha256": sha256_file(args.task),
                "mantis_urdf_sha256": sha256_file(args.mantis_urdf),
                "bowl_urdf_sha256": sha256_file(bowl_urdf),
                "bowl_manifest_sha256": sha256_file(manifest_path),
                "camera_contract_sha256": sha256_file(args.cameras),
                "control_contract_sha256": sha256_file(args.control),
            },
        )
        begun = True
        import genesis as gs
        import numpy as np

        gs.init(backend=resolve_backend(gs, args.backend), seed=20260722, logging_level="warning")
        scene = gs.Scene(sim_options=gs.options.SimOptions(dt=0.004), show_viewer=False)
        scene.add_entity(gs.morphs.Plane(pos=(0.0, 0.0, 0.74), fixed=True))
        robot = scene.add_entity(gs.morphs.URDF(file=str(args.mantis_urdf.resolve()), fixed=True))
        reset_xyz = ((-0.2, -0.13, 0.741), (0.2, 0.0, 0.741), (-0.2, 0.13, 0.741))
        bowls = [
            scene.add_entity(
                gs.morphs.URDF(
                    file=str(bowl_urdf.resolve()),
                    pos=position,
                    quat=(0.5, 0.5, 0.5, 0.5),
                    fixed=False,
                    merge_fixed_links=False,
                    recompute_inertia=False,
                    file_meshes_are_zup=True,
                ),
                name=f"bowl{index}",
            )
            for index, position in enumerate(reset_xyz, start=1)
        ]

        camera_contract = cameras["mounts"]
        env = camera_contract["env_cam"]
        env_position = np.asarray(env["position_xyz_m"], dtype=float)
        env_forward = np.asarray(env["forward_xyz"], dtype=float)
        scene.add_camera(
            res=(320, 240),
            pos=tuple(env_position),
            lookat=tuple(env_position + env_forward),
            fov=37.0,
            near=0.1,
            far=100.0,
            GUI=False,
        )
        attached: dict[str, str] = {}
        for name in ("left_wrist_cam", "right_wrist_cam"):
            camera = scene.add_camera(
                res=(424, 240),
                pos=(0.0, 0.0, 1.0),
                lookat=(0.0, 0.0, 0.0),
                fov=37.0,
                near=0.1,
                far=100.0,
                GUI=False,
            )
            parent = mounts[name]["parent"]
            camera.attach(robot.get_link(parent), np.asarray(mounts[name]["offset_T"], dtype=float))
            attached[name] = parent
        scene.build()

        initial_positions = [_vector(bowl.get_pos()) for bowl in bowls]
        for _ in range(args.steps):
            scene.step()
        final_positions = [_vector(bowl.get_pos()) for bowl in bowls]
        finite = all(math.isfinite(value) for row in initial_positions + final_positions for value in row)
        table_contact_gate = finite and all(0.70 < row[2] < 0.77 for row in final_positions)
        link = bowls[0].links[0]
        actual_mass = float(link.inertial_mass)
        actual_inertia = np.asarray(link.inertial_i, dtype=float)
        actual_principal = sorted(np.linalg.eigvalsh(actual_inertia).tolist())
        expected_mass = float(bowl_plan["source_physics_receipt"]["mass_kg"])
        expected_principal = sorted(bowl_plan["source_physics_receipt"]["principal_inertia_kg_m2"])
        mass_error = abs(actual_mass - expected_mass)
        inertia_error = max(
            abs(actual - expected)
            for actual, expected in zip(actual_principal, expected_principal)
        )
        receipt = {
            "schema_version": 1,
            "runtime_gate_pass": table_contact_gate and mass_error <= 1e-9 and inertia_error <= 1e-8,
            "backend_requested": args.backend,
            "backend_active": str(gs.backend),
            "device": str(gs.device),
            "genesis_version": importlib.metadata.version("genesis-world"),
            "python_version": platform.python_version(),
            "port_config_sha256": sha256_file(args.port),
            "source_task_contract_sha256": sha256_file(args.source_task),
            "target_task_contract_sha256": sha256_file(args.task),
            "mantis_urdf_sha256": sha256_file(args.mantis_urdf),
            "bowl_urdf_sha256": sha256_file(bowl_urdf),
            "bowl_manifest_sha256": sha256_file(manifest_path),
            "bowl_collision_representation": collision_representation,
            "camera_contract_sha256": sha256_file(args.cameras),
            "control_contract_sha256": sha256_file(args.control),
            "attached_wrist_cameras": attached,
            "initial_bowl_positions": initial_positions,
            "final_bowl_positions": final_positions,
            "table_contact_gate_pass": table_contact_gate,
            "actual_mass_kg": actual_mass,
            "expected_mass_kg": expected_mass,
            "mass_abs_error_kg": mass_error,
            "actual_principal_inertia_kg_m2": actual_principal,
            "expected_principal_inertia_kg_m2": expected_principal,
            "principal_inertia_max_abs_error": inertia_error,
            "steps": args.steps,
            "urdf_parser_boundary": parser_boundary,
            "hardware_camera_claim": False,
        }
        if not receipt["runtime_gate_pass"]:
            raise RuntimeError(f"Genesis scene gate failed: {receipt}")
        receipt_path = run_dir / "receipt.json"
        receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        finish_run(
            args.ops_root,
            args.run_id,
            "completed",
            {"receipt_sha256": sha256_file(receipt_path)},
        )
        print(json.dumps(receipt, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        if begun:
            finish_run(
                args.ops_root,
                args.run_id,
                "failed",
                {"error_type": type(exc).__name__, "message": str(exc)},
            )
        raise


if __name__ == "__main__":
    raise SystemExit(main())
