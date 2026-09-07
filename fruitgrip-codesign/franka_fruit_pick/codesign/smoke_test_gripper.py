"""Standalone smoke test: load a few generated gripper variants into Genesis in
isolation (no arm/table/objects) and render them, so a generated MJCF's validity
and shape can be eyeballed before it's ever used inside a full pick-and-place scene.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(_ROOT.parent))

import numpy as np
import genesis as gs

from gripper_gen import GripperParams, generate_gripper_xml
from paths import OUTPUTS_DIR


VARIANTS = {
    "baseline_2f_straight": GripperParams(n_fingers=2, finger_length=0.045, curvature_deg=0.0, aperture=0.08, compliance=0.0),
    "3f_curved_wide": GripperParams(n_fingers=3, finger_length=0.05, curvature_deg=30.0, aperture=0.09, compliance=0.6),
    "2f_long_curved_narrow": GripperParams(n_fingers=2, finger_length=0.065, curvature_deg=50.0, aperture=0.05, compliance=0.9),
}


def main() -> None:
    out_dir = OUTPUTS_DIR / "gripper_smoke"
    out_dir.mkdir(parents=True, exist_ok=True)

    for name, params in VARIANTS.items():
        gs.init(backend=gs.cpu)
        xml_path = generate_gripper_xml(params)
        scene = gs.Scene(show_viewer=False)
        scene.add_entity(gs.morphs.Plane())
        franka = scene.add_entity(gs.morphs.MJCF(file=str(xml_path)))
        cam = scene.add_camera(res=(640, 480), pos=(0.3, 0.3, 0.6), lookat=(0.0, 0.0, 0.5), fov=40, GUI=False)
        scene.build()

        hand_pos = franka.get_link("hand").get_pos().cpu().numpy().reshape(-1)
        # Fingers extend ~0.03-0.07 m beyond the hand-link origin along its local
        # approach axis; look at a point offset below it and pull back far enough
        # to fit the whole palm+finger assembly in frame.
        look_at = (hand_pos[0], hand_pos[1], hand_pos[2] - 0.08)
        cam.set_pose(pos=(hand_pos[0] + 0.32, hand_pos[1] + 0.32, hand_pos[2] - 0.02), lookat=look_at)

        # Open the fingers fully so the aperture/curvature shape is visible, not
        # collapsed to the closed pose.
        n_dof = franka.n_dofs
        finger_dof = np.arange(n_dof - params.n_fingers, n_dof)
        open_target = np.zeros(n_dof)
        joint_range_max = 0.0
        for jn in params.joint_names():
            joint = franka.get_joint(jn)
            joint_range_max = max(joint_range_max, float(joint.dofs_limit[0][1]))
        open_target[finger_dof] = joint_range_max
        for _ in range(60):
            franka.control_dofs_position(open_target)
            scene.step()

        img = cam.render(rgb=True)[0]
        import imageio.v2 as imageio

        imageio.imwrite(out_dir / f"{name}.png", img)
        print(f"[smoke_test_gripper] {name}: n_dofs={n_dof}, joint_range_max={joint_range_max:.4f} -> saved frame")
        gs.destroy()


if __name__ == "__main__":
    main()
