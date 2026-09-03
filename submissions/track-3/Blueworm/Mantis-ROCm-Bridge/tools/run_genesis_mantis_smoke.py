#!/usr/bin/env python3
"""Run a guarded fixed-base Mantis load, step, and optional render in Genesis."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import platform
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from mantis_rocm_bridge.contracts import (
    load_json,
    validate_fixed_base_plan,
    validate_port_contract,
)
from mantis_rocm_bridge.genesis_smoke import (
    BACKENDS,
    compare_joint_limits,
    gripper_geometry,
    max_abs_error,
    physical_pose,
    resolve_backend,
    sha256_file,
)
from mantis_rocm_bridge.ops import begin_run, finish_run


ROOT = Path(__file__).resolve().parents[1]


def _numpy_vector(value: Any) -> list[float]:
    if hasattr(value, "detach"):
        value = value.detach()
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "numpy"):
        value = value.numpy()
    import numpy as np

    return np.asarray(value, dtype=float).reshape(-1).tolist()


def _read_positions(robot: Any, indices: list[int]) -> list[float]:
    try:
        value = robot.get_dofs_position(dofs_idx_local=indices)
    except TypeError:
        value = robot.get_dofs_position(indices)
    return _numpy_vector(value)


def _set_positions(robot: Any, values: list[float], indices: list[int]) -> None:
    import numpy as np

    vector = np.asarray(values, dtype=np.float32)
    try:
        robot.set_dofs_position(vector, dofs_idx_local=indices)
    except TypeError:
        robot.set_dofs_position(vector, indices)


def _link_positions(robot: Any, names: list[str]) -> dict[str, list[float]]:
    return {name: _numpy_vector(robot.get_link(name).get_pos()) for name in names}


def _gripper_child_links(urdf: Path, physical_joints: list[str]) -> dict[str, str]:
    joints = {joint.get("name"): joint for joint in ET.parse(urdf).getroot().findall("joint")}
    result: dict[str, str] = {}
    for name in physical_joints:
        joint = joints.get(name)
        child = None if joint is None else joint.find("child")
        link = None if child is None else child.get("link")
        if not link:
            raise RuntimeError(f"cannot resolve gripper child link for {name}")
        result[name] = link
    return result


def _rgb_array(rendered: Any) -> Any:
    import numpy as np

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
    image = np.asarray(rendered)
    if image.ndim == 4 and image.shape[0] == 1:
        image = image[0]
    if image.ndim != 3 or image.shape[2] not in (3, 4):
        raise RuntimeError(f"unexpected Genesis RGB shape: {image.shape}")
    if image.dtype.kind == "f":
        image = np.clip(image, 0.0, 1.0) * 255.0
    return image.astype(np.uint8)


def _render(camera: Any, path: Path) -> str:
    from PIL import Image

    image = _rgb_array(camera.render(rgb=True, force_render=True))
    Image.fromarray(image).save(path)
    return sha256_file(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("urdf", type=Path)
    parser.add_argument("--port", type=Path, default=ROOT / "configs/mantis-port-config.json")
    parser.add_argument(
        "--fixed-plan", type=Path, default=ROOT / "configs/fixed-base-plan.json"
    )
    parser.add_argument("--ops-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--backend", choices=BACKENDS, required=True)
    parser.add_argument("--steps", type=int, default=2)
    parser.add_argument("--seed", type=int, default=20260722)
    parser.add_argument("--render", action="store_true")
    parser.add_argument("--camera-pos", type=float, nargs=3, default=(2.2, -2.2, 1.8))
    parser.add_argument("--camera-lookat", type=float, nargs=3, default=(0.0, 0.0, 0.55))
    args = parser.parse_args()
    if args.steps < 1:
        parser.error("--steps must be positive")
    if not args.urdf.is_file():
        parser.error(f"URDF does not exist: {args.urdf}")

    port = load_json(args.port)
    fixed_plan = load_json(args.fixed_plan)
    blockers = validate_port_contract(port)
    validate_fixed_base_plan(fixed_plan, port)
    urdf_sha256 = sha256_file(args.urdf)
    config_sha256 = sha256_file(args.port)
    fixed_plan_sha256 = sha256_file(args.fixed_plan)
    run_dir = args.ops_root / args.run_id
    begun = False
    try:
        begin_run(
            args.ops_root,
            args.run_id,
            {
                "phase": "genesis_mantis_runtime_smoke",
                "backend": args.backend,
                "render_requested": args.render,
                "urdf_sha256": urdf_sha256,
                "port_config_sha256": config_sha256,
                "fixed_plan_sha256": fixed_plan_sha256,
                "gripper_mapping_status": port["assets"]["virtual_gripper_mapping"]["status"],
            },
        )
        begun = True

        import genesis as gs

        gs.init(backend=resolve_backend(gs, args.backend), seed=args.seed, logging_level="warning")
        scene = gs.Scene(
            sim_options=gs.options.SimOptions(dt=0.01),
            show_viewer=False,
        )
        robot = scene.add_entity(
            gs.morphs.URDF(file=str(args.urdf.resolve()), fixed=True),
        )
        camera = None
        if args.render:
            camera = scene.add_camera(
                res=(640, 480),
                pos=tuple(args.camera_pos),
                lookat=tuple(args.camera_lookat),
                fov=40,
                GUI=False,
            )
        scene.build()

        joint_order = port["target"]["physical_joint_order"]
        indices = [robot.get_joint(name).dofs_idx_local[0] for name in joint_order]
        if len(indices) != len(set(indices)):
            raise RuntimeError("Genesis mapped multiple physical joints to the same DOF")
        try:
            actual_lower, actual_upper = robot.get_dofs_limit(dofs_idx_local=indices)
        except TypeError:
            actual_lower, actual_upper = robot.get_dofs_limit(indices)
        limit_audit = compare_joint_limits(
            joint_order,
            _numpy_vector(actual_lower),
            _numpy_vector(actual_upper),
            fixed_plan["joint_limits"],
        )

        closed = physical_pose(port, 0.0)
        opened = physical_pose(port, 1.0)
        physical_grippers = port["assets"]["physical_gripper_joint_order"]
        child_links = _gripper_child_links(args.urdf, physical_grippers)
        _set_positions(robot, closed, indices)
        closed_readback = _read_positions(robot, indices)
        closed_link_positions = _link_positions(robot, list(child_links.values()))
        closed_png = None
        if camera is not None:
            closed_png = _render(camera, run_dir / "mantis-closed.png")

        for _ in range(args.steps):
            scene.step()
        stepped_readback = _read_positions(robot, indices)

        _set_positions(robot, opened, indices)
        open_readback = _read_positions(robot, indices)
        open_link_positions = _link_positions(robot, list(child_links.values()))
        open_png = None
        if camera is not None:
            open_png = _render(camera, run_dir / "mantis-open.png")

        closed_error = max_abs_error(closed_readback, closed)
        open_error = max_abs_error(open_readback, opened)
        geometry = gripper_geometry(
            port, child_links, closed_link_positions, open_link_positions
        )
        kinematic_gripper_gate = all(
            details["kinematic_gate_pass"] for details in geometry.values()
        )
        _ = max_abs_error(stepped_readback, stepped_readback)
        receipt = {
            "schema_version": 1,
            "runtime_gate_pass": (
                closed_error <= 1e-6 and open_error <= 1e-6 and limit_audit["pass"]
            ),
            "visual_gripper_verified": False,
            "visual_verification_note": (
                "images_generated_but_direction_symmetry_and_contact_gap_require_review"
                if args.render
                else "render_not_requested"
            ),
            "backend_requested": args.backend,
            "backend_active": str(gs.backend),
            "device": str(gs.device),
            "genesis_version": importlib.metadata.version("genesis-world"),
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "urdf": str(args.urdf.resolve()),
            "urdf_sha256": urdf_sha256,
            "port_config_sha256": config_sha256,
            "fixed_plan_sha256": fixed_plan_sha256,
            "joint_order": joint_order,
            "dof_indices_local": indices,
            "joint_limit_audit": limit_audit,
            "closed_target": closed,
            "closed_readback": closed_readback,
            "open_target": opened,
            "open_readback": open_readback,
            "post_step_readback": stepped_readback,
            "closed_max_abs_error": closed_error,
            "open_max_abs_error": open_error,
            "kinematic_gripper_gate_pass": kinematic_gripper_gate,
            "gripper_geometry": geometry,
            "steps": args.steps,
            "rendered": args.render,
            "camera_pos": list(args.camera_pos) if args.render else None,
            "camera_lookat": list(args.camera_lookat) if args.render else None,
            "closed_png_sha256": closed_png,
            "open_png_sha256": open_png,
            "remaining_contract_blockers": blockers,
        }
        if not receipt["runtime_gate_pass"]:
            raise RuntimeError(
                f"Genesis DOF readback mismatch: closed={closed_error}, open={open_error}"
            )
        receipt_path = run_dir / "receipt.json"
        receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        finish_run(
            args.ops_root,
            args.run_id,
            "completed",
            {"receipt_sha256": sha256_file(receipt_path), "rendered": args.render},
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
