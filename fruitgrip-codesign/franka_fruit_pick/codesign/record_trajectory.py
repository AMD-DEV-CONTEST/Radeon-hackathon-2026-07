"""Session 6: dense per-step trajectory recording for the interactive 3D demo.

Reuses the exact contact instrumentation sim_episode.py's _MetricsTracker already
computes for the reward (pick_entity.get_contacts(with_entity=bundle.franka) ->
force_b/position/valid_mask) -- this just SAVES the per-step detail that
_MetricsTracker discards after reducing it to a running peak scalar, instead of
building new physics logging.

Non-invasive: wraps bundle.scene.step() (same technique as render_demo.py's dense
frame capture) so sim_episode.py's tested episode logic is untouched. Captures, every
physics step: hand world pose, object world pose, per-finger joint position, arm
joint positions (for a decorative arm-chain visual only -- not claimed as exact FK),
and every valid contact's position + force vector. This is raw recorded Genesis state,
not a re-simulation -- the whole point of the demo this feeds is real-data playback.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(_ROOT.parent))

import numpy as np  # noqa: E402

import genesis as gs  # noqa: E402
from build_scene import build_scene  # noqa: E402
from grasp_demo import TaskSpec  # noqa: E402
from randomize import EnvRandomizer, RandomizationConfig  # noqa: E402

from controller_adapt import adapt_grasp_profile  # noqa: E402
from evaluate import DEFAULT_DR  # noqa: E402
from gripper_gen import GripperParams, generate_gripper_xml  # noqa: E402
from sim_episode import GripperRuntime, run_pick_place  # noqa: E402

MOTORS_DOF = np.arange(7)


def _to_np(x) -> np.ndarray:
    return x.detach().cpu().numpy() if hasattr(x, "detach") else np.asarray(x)


def record_trajectory(params: GripperParams, *, seed: int, label: str, held_out: bool = False, backend=None) -> dict:
    if held_out:
        import scene_config
        import randomize as randomize_mod
        from held_out_eval import HELD_OUT_LAYOUT, HELD_OUT_POOL
        scene_config.YCB_LAYOUT.clear()
        scene_config.YCB_LAYOUT.update(HELD_OUT_LAYOUT)
        randomize_mod.RELIABLE_PICK_POOL = HELD_OUT_POOL

    params = params.clipped()
    xml_path = generate_gripper_xml(params)
    gs.init(backend=backend or gs.cpu)
    bundle = build_scene(show_viewer=False, n_envs=1, add_world_cam=False, add_wrist_cam=False, franka_xml_path=str(xml_path))

    rt = GripperRuntime(n_fingers=params.n_fingers, finger_open_travel=max(params.aperture / 2 - 0.002, 0.002))
    randomizer = EnvRandomizer(bundle, RandomizationConfig(randomize_pick=True, dr=DEFAULT_DR))
    task: TaskSpec = randomizer.reset(seed=seed)
    profile = adapt_grasp_profile(params, task.pick_object)

    hand = bundle.franka.get_link("hand")
    pick_entity = bundle.ycb[task.pick_object]

    steps: list[dict] = []
    orig_step = bundle.scene.step

    def wrapped_step(*a, **kw):
        r = orig_step(*a, **kw)
        hand_pos = _to_np(hand.get_pos()).reshape(-1).tolist()
        hand_quat = _to_np(hand.get_quat()).reshape(-1).tolist()
        obj_pos = _to_np(pick_entity.get_pos()).reshape(-1).tolist()
        obj_quat = _to_np(pick_entity.get_quat()).reshape(-1).tolist()
        dofs = _to_np(bundle.franka.get_dofs_position()).reshape(-1)
        arm_q = dofs[:7].tolist()
        finger_q = dofs[7:].tolist()

        contacts_out = []
        c = pick_entity.get_contacts(with_entity=bundle.franka)
        force_b = c.get("force_b")
        pos = c.get("position")
        valid = c.get("valid_mask")
        if force_b is not None:
            force_b = _to_np(force_b).reshape(-1, 3)
            pos_np = _to_np(pos).reshape(-1, 3) if pos is not None else np.zeros_like(force_b)
            valid_np = _to_np(valid).reshape(-1).astype(bool) if valid is not None else np.ones(len(force_b), dtype=bool)
            for i in range(force_b.shape[0]):
                if not valid_np[i]:
                    continue
                mag = float(np.linalg.norm(force_b[i]))
                if mag < 1e-6:
                    continue
                contacts_out.append({"p": [round(float(x), 5) for x in pos_np[i]], "f": [round(float(x), 4) for x in force_b[i]], "mag": round(mag, 4)})

        steps.append({
            "hand_p": [round(x, 5) for x in hand_pos], "hand_q": [round(x, 5) for x in hand_quat],
            "obj_p": [round(x, 5) for x in obj_pos], "obj_q": [round(x, 5) for x in obj_quat],
            "arm_q": [round(x, 5) for x in arm_q], "finger_q": [round(x, 5) for x in finger_q],
            "contacts": contacts_out,
        })
        return r

    bundle.scene.step = wrapped_step
    metrics = run_pick_place(bundle, rt, task, profile, save_frames=False)
    bundle.scene.step = orig_step
    gs.destroy()

    return {
        "label": label, "object": task.pick_object, "success": bool(metrics.success),
        "peak_contact_force": round(metrics.peak_contact_force, 3), "max_slip": round(metrics.max_slip, 4),
        "gripper": {"n_fingers": params.n_fingers, "finger_length": params.finger_length, "curvature_deg": params.curvature_deg, "aperture": params.aperture, "compliance": params.compliance},
        "n_steps": len(steps), "steps": steps,
    }


if __name__ == "__main__":
    import argparse
    from run_attribution import BASELINE_PARAMS, JOINT_BEST_PARAMS

    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=str, default=str(_ROOT.parent.parent / "demo" / "interactive_3d"))
    ap.add_argument("--backend", choices=["cpu", "amdgpu"], default="cpu")
    args = ap.parse_args()
    backend = {"cpu": gs.cpu, "amdgpu": gs.amdgpu}[args.backend]

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    jobs = [
        ("baseline_fail", BASELINE_PARAMS, 1005, False),
        ("winner_succeed", JOINT_BEST_PARAMS, 1005, False),
        ("winner_apple_fail", JOINT_BEST_PARAMS, 2001, True),
    ]
    for name, params, seed, held_out in jobs:
        print(f"recording {name} (seed={seed}, held_out={held_out}) ...")
        traj = record_trajectory(params, seed=seed, label=name, held_out=held_out, backend=backend)
        print(f"  -> object={traj['object']} success={traj['success']} n_steps={traj['n_steps']}")
        (out_dir / f"{name}.json").write_text(json.dumps(traj))
        print(f"  wrote {out_dir / f'{name}.json'} ({(out_dir / f'{name}.json').stat().st_size / 1024:.0f} KB)")
