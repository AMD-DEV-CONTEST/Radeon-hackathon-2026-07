"""Session 4, Priority 4: demo video assets.

Two clips, both frozen designs, both with Genesis's contact-force-arrow
visualization (`visualize_contacts=True` on build_scene, session 4 addition) on:

1. side_by_side.mp4 -- baseline (fails) vs winner (succeeds), the SAME object and
   SAME trial seed for both (seed 1005, lemon -- mined from
   results/confirmation_eval.json's per-trial data: baseline failed, winner
   succeeded, both drawn from the identical domain-randomization instance since both
   used seed_base=1000 and trial index 5). Frames are captured densely (every few
   physics steps, not sim_episode.py's normal ~8 sparse keyframes) via a non-invasive
   wrapper around `scene.step` -- no changes to the tested episode/eval logic.

2. apple_failure_honesty.mp4 -- the winner design failing to pick the held-out apple
   (seed 2001, from results/held_out_eval.json), included deliberately per the
   project brief: showing the honest limit (0/8 on apple, aperture-clearance issue
   identified in session 3) is more credible than only showing wins.

Both motion scripts run a FIXED number of steps per phase regardless of
success/failure (see sim_episode.py's _goto_interp/_goto_direct calls, which use a
constant `steps=` argument, not an early-exit-on-success condition), so a
success-run and a failure-run of the same script produce the same frame count --
which is what makes frame-by-frame side-by-side stacking valid without any
re-timing/alignment step.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(_ROOT.parent))

import imageio.v2 as imageio  # noqa: E402
import numpy as np  # noqa: E402

import genesis as gs  # noqa: E402
from build_scene import build_scene  # noqa: E402
from grasp_demo import TaskSpec  # noqa: E402
from randomize import DomainRandomizationConfig, EnvRandomizer, RandomizationConfig  # noqa: E402

from controller_adapt import adapt_grasp_profile  # noqa: E402
from evaluate import DEFAULT_DR  # noqa: E402
from gripper_gen import GripperParams, generate_gripper_xml  # noqa: E402
from paths import OUTPUTS_DIR  # noqa: E402
from run_attribution import BASELINE_PARAMS, JOINT_BEST_PARAMS  # noqa: E402
from sim_episode import GripperRuntime, run_pick_place  # noqa: E402

CAPTURE_EVERY = 3  # physics steps between captured frames -- dense enough to look
                    # smooth at the demo's playback fps without an excessive frame count


def record_episode(params: GripperParams, *, seed: int, backend=None, held_out: bool = False) -> tuple[list[np.ndarray], bool, str]:
    """Runs one scripted episode with dense frame capture. Returns (frames, success,
    pick_object). `held_out` swaps in the apple/pear scene+pool (session 3's
    held_out_eval.py mechanism) instead of the default banana/lemon/plum pool.
    """
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
    bundle = build_scene(show_viewer=False, n_envs=1, add_world_cam=True, add_wrist_cam=False, franka_xml_path=str(xml_path), visualize_contacts=True)

    rt = GripperRuntime(n_fingers=params.n_fingers, finger_open_travel=max(params.aperture / 2 - 0.002, 0.002))
    randomizer = EnvRandomizer(bundle, RandomizationConfig(randomize_pick=True, dr=DEFAULT_DR))
    task: TaskSpec = randomizer.reset(seed=seed)
    profile = adapt_grasp_profile(params, task.pick_object)

    frames: list[np.ndarray] = []
    orig_step = bundle.scene.step
    step_count = 0

    def wrapped_step(*a, **kw):
        nonlocal step_count
        r = orig_step(*a, **kw)
        step_count += 1
        if step_count % CAPTURE_EVERY == 0:
            frames.append(bundle.world_cam.render(rgb=True)[0])
        return r

    bundle.scene.step = wrapped_step
    metrics = run_pick_place(bundle, rt, task, profile, save_frames=False)
    bundle.scene.step = orig_step

    gs.destroy()
    return frames, metrics.success, task.pick_object


def side_by_side(frames_a: list[np.ndarray], frames_b: list[np.ndarray], label_a: str, label_b: str) -> list[np.ndarray]:
    n = min(len(frames_a), len(frames_b))
    out = []
    for i in range(n):
        a, b = frames_a[i], frames_b[i]
        h = min(a.shape[0], b.shape[0])
        gap = np.full((h, 8, 3), 30, dtype=np.uint8)
        out.append(np.concatenate([a[:h], gap, b[:h]], axis=1))
    return out


def main() -> None:
    out_dir = OUTPUTS_DIR / "demo_render"
    out_dir.mkdir(parents=True, exist_ok=True)
    SEED = 1005  # lemon; baseline fails, winner succeeds (mined from confirmation_eval.json)

    print(f"recording baseline @ seed={SEED} ...")
    t0 = time.time()
    frames_base, ok_base, obj_base = record_episode(BASELINE_PARAMS, seed=SEED)
    print(f"  baseline: {len(frames_base)} frames, success={ok_base}, object={obj_base}, {time.time()-t0:.1f}s")

    print(f"recording winner @ seed={SEED} ...")
    t0 = time.time()
    frames_win, ok_win, obj_win = record_episode(JOINT_BEST_PARAMS, seed=SEED)
    print(f"  winner: {len(frames_win)} frames, success={ok_win}, object={obj_win}, {time.time()-t0:.1f}s")

    assert obj_base == obj_win, f"object mismatch: {obj_base} vs {obj_win} -- seed didn't produce a matched pair"

    combined = side_by_side(frames_base, frames_win, "baseline", "winner")
    sxs_path = out_dir / "side_by_side.mp4"
    imageio.mimwrite(sxs_path, combined, fps=20, quality=7)
    print(f"wrote {sxs_path} ({len(combined)} frames, baseline_success={ok_base}, winner_success={ok_win}, object={obj_base})")

    APPLE_SEED = 2001
    print(f"\nrecording winner-on-apple (honesty shot) @ seed={APPLE_SEED} ...")
    t0 = time.time()
    frames_apple, ok_apple, obj_apple = record_episode(JOINT_BEST_PARAMS, seed=APPLE_SEED, held_out=True)
    print(f"  winner/apple: {len(frames_apple)} frames, success={ok_apple}, object={obj_apple}, {time.time()-t0:.1f}s")

    apple_path = out_dir / "apple_failure_honesty.mp4"
    imageio.mimwrite(apple_path, frames_apple, fps=20, quality=7)
    print(f"wrote {apple_path} ({len(frames_apple)} frames, success={ok_apple}, object={obj_apple})")

    print(f"\nfile sizes: {sxs_path.stat().st_size/1e6:.1f}MB, {apple_path.stat().st_size/1e6:.1f}MB")


if __name__ == "__main__":
    main()
