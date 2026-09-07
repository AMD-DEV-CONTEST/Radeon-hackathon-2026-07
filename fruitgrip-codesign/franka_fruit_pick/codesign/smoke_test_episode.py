"""Smoke test: run a full generalized pick-and-place episode with a *generated*
(non-stock) gripper design, to confirm sim_episode.py's N-finger generalization and
metrics collection work inside the real scene (arm + table + objects), not just in
isolation like smoke_test_gripper.py.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(_ROOT.parent))

import genesis as gs

from build_scene import build_scene
from grasp_demo import TaskSpec
from gripper_gen import GripperParams, generate_gripper_xml, hand_to_fingertip_z
from sim_episode import GraspProfile, GripperRuntime, run_pick_place


def run_one(name: str, params: GripperParams, close_force: float, center_align: bool, save_frames: bool) -> None:
    gs.init(backend=gs.cpu)
    xml_path = generate_gripper_xml(params)
    bundle = build_scene(show_viewer=False, n_envs=1, add_world_cam=True, add_wrist_cam=False, franka_xml_path=str(xml_path))

    rt = GripperRuntime(n_fingers=params.n_fingers, finger_open_travel=max(params.aperture / 2 - 0.002, 0.002))
    profile = GraspProfile(
        yaw_offset=0.0, hand_to_fingertip=hand_to_fingertip_z(params), close_force=close_force, center_align=center_align,
    )
    task = TaskSpec(pick_object="018_plum", place_target="024_bowl")

    metrics = run_pick_place(bundle, rt, task, profile, save_frames=save_frames)
    print(
        f"[{name}] success={metrics.success} peak_force={metrics.peak_contact_force:.3f}N "
        f"contact_uptime={metrics.contact_uptime_frac:.2f} max_slip={metrics.max_slip * 1000:.1f}mm "
        f"n_steps={metrics.n_metric_steps}"
    )
    if save_frames:
        import imageio.v2 as imageio

        from paths import OUTPUTS_DIR

        out_dir = OUTPUTS_DIR / "episode_smoke" / name
        out_dir.mkdir(parents=True, exist_ok=True)
        for tag, img in metrics.frames:
            imageio.imwrite(out_dir / f"{tag}.png", img)
    gs.destroy()


if __name__ == "__main__":
    # 1) Stock-equivalent geometry (2-finger, straight, original aperture/length) as a
    #    parity check against grasp_demo.py's known-good banana/plum runs.
    run_one(
        "stock_equivalent",
        GripperParams(n_fingers=2, finger_length=0.0454, curvature_deg=0.0, aperture=0.08, compliance=0.0),
        close_force=-12.0, center_align=True, save_frames=True,
    )
    # 2) A genuinely different design: 3 fingers, curved, softer.
    run_one(
        "3finger_curved_soft",
        GripperParams(n_fingers=3, finger_length=0.05, curvature_deg=25.0, aperture=0.075, compliance=0.7),
        close_force=-12.0, center_align=True, save_frames=True,
    )
