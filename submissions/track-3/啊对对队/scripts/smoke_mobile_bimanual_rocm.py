"""Build and move the wheeled Bi-Franka embodiment on one Radeon GPU."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from parcel_sorter.genesis_env import initialize_genesis
from parcel_sorter.mobile_bimanual import BASE_JOINT_NAMES, build_mobile_bimanual_mjcf
from parcel_sorter.provenance import runtime_report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=("rocm", "cuda"), default="rocm")
    parser.add_argument("--steps", type=int, default=60)
    parser.add_argument("--speed-m-s", type=float, default=0.20)
    parser.add_argument("--hybrid-tools", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("outputs/mobile-bimanual-smoke"))
    args = parser.parse_args()
    if args.steps < 1 or args.speed_m_s <= 0:
        parser.error("steps and speed must be positive")
    gs, _, np = initialize_genesis(args.backend)
    source = (
        Path(gs.__file__).resolve().parent
        / "assets/xml/franka_sim/bi-franka_panda.xml"
    )
    asset = build_mobile_bimanual_mjcf(
        source,
        args.output / "mobile_bi_franka.xml",
        left_tri_suction=args.hybrid_tools,
        right_v_cradle=args.hybrid_tools,
    )
    scene = gs.Scene(
        sim_options=gs.options.SimOptions(dt=1.0 / 240.0, substeps=1),
        rigid_options=gs.options.RigidOptions(enable_collision=True),
        show_viewer=False,
    )
    scene.add_entity(gs.morphs.Plane())
    robot = scene.add_entity(gs.morphs.MJCF(file=str(asset)))
    scene.build()
    base_dofs = np.asarray(
        [robot.get_joint(name).dofs_idx_local[0] for name in BASE_JOINT_NAMES]
    )
    robot.set_dofs_kp(np.zeros(3), base_dofs)
    robot.set_dofs_kv(np.asarray((600.0, 600.0, 300.0)), base_dofs)
    robot.set_dofs_force_range(
        np.asarray((-2500.0, -2500.0, -1200.0)),
        np.asarray((2500.0, 2500.0, 1200.0)),
        base_dofs,
    )
    before = [float(value) for value in robot.get_qpos()[base_dofs].tolist()]
    robot.control_dofs_velocity(np.asarray((args.speed_m_s, 0.0, 0.0)), base_dofs)
    for _ in range(args.steps):
        scene.step()
    robot.control_dofs_velocity(np.zeros(3), base_dofs)
    after = [float(value) for value in robot.get_qpos()[base_dofs].tolist()]
    payload = {
        "runtime": runtime_report(),
        "upstream_asset": "Genesis franka_sim Bi-Franka, Apache-2.0",
        "generated_asset": str(asset),
        "base_joint_names": BASE_JOINT_NAMES,
        "dof_count": int(robot.n_dofs),
        "hybrid_tools": args.hybrid_tools,
        "left_tri_suction_collision_geoms": 3 if args.hybrid_tools else 0,
        "right_v_cradle_collision_geoms": 2 if args.hybrid_tools else 0,
        "qpos_before": before,
        "qpos_after": after,
        "delta_x_m": after[0] - before[0],
        "steps": args.steps,
        "command_speed_m_s": args.speed_m_s,
    }
    if payload["delta_x_m"] < 0.01:
        raise RuntimeError("mobile base did not complete the 1 cm forward smoke gate")
    args.output.mkdir(parents=True, exist_ok=True)
    result = args.output / "summary.json"
    result.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
