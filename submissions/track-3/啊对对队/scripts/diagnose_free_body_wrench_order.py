#!/usr/bin/env python3
"""Audit Genesis free-body generalized-force ordering with unit impulses."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from parcel_sorter.genesis_env import initialize_genesis


def _flat(value: object) -> list[float]:
    if hasattr(value, "detach"):
        value = value.detach().cpu()  # type: ignore[union-attr]
    if hasattr(value, "reshape"):
        value = value.reshape(-1)  # type: ignore[union-attr]
    return [float(item) for item in value]  # type: ignore[union-attr]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("rocm", "cuda"), default="rocm")
    args = parser.parse_args()

    gs, _, np = initialize_genesis(args.backend)
    scene = gs.Scene(
        sim_options=gs.options.SimOptions(
            dt=1.0 / 240.0,
            substeps=1,
            gravity=(0.0, 0.0, 0.0),
        ),
        rigid_options=gs.options.RigidOptions(enable_collision=False),
        show_viewer=False,
    )
    body = scene.add_entity(
        gs.morphs.Box(size=(0.064, 0.0375, 0.0285), pos=(0.0, 0.0, 1.0))
    )
    scene.build()

    joint = body.joints[0]
    initial_qpos = body.get_qpos().clone()
    responses = []
    for dof_index in range(6):
        body.set_qpos(initial_qpos)
        body.set_dofs_velocity(np.zeros(6, dtype=np.float32))
        command = np.zeros(6, dtype=np.float32)
        command[dof_index] = 1.0
        body.control_dofs_force(command)
        scene.step()
        responses.append(
            {
                "dof": dof_index,
                "linear_velocity_m_s": _flat(body.get_vel()),
                "angular_velocity_rad_s": _flat(body.get_ang()),
            }
        )

    print(
        json.dumps(
            {
                "dofs_motion_ang": np.asarray(joint.dofs_motion_ang).tolist(),
                "dofs_motion_vel": np.asarray(joint.dofs_motion_vel).tolist(),
                "unit_force_responses": responses,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
