"""Film a teacher episode to mp4, with live state burned in.

Also prints the derived geometry, which is only asserted in EnvConfig and never
otherwise shown. Reach is reported at FULL TRAVEL rather than at the closed
drawer: the rail moves toward the robot as it opens, so it is the arm's INNER
workspace boundary that binds, not the outer one.

    uv run render
    uv run render --envs 4 --env 2 --nominal
    uv run render --over-pull --name over_pull
"""
from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path

import cv2
import numpy as np
import genesis as gs

from . import robot, task_state, teacher
from .config import EnvConfig, SIDES
from .randomize import sample_episode
from .scene import build_scene


def geometry(b, cfg: EnvConfig) -> None:
    cab, fr = cfg.cabinet, cfg.franka
    rails = task_state.rail_pos(b)[0]
    base_x = fr.pos[0]

    print("cabinet")
    print(f"  opening        {cab.opening_w * 1e3:.0f} x {cab.opening_h * 1e3:.0f} mm")
    print(f"  travel range   {cab.travel_range[0] * 1e3:.0f}..{cab.travel_range[1] * 1e3:.0f} mm")
    print("rails (world, drawer closed)")
    for name, p in zip(SIDES, rails):
        print(f"  {name:<6} {np.round(p, 4)}  reach {p[0] - base_x:.3f} m")
    print(f"  at full travel reach {rails[0][0] - cab.travel_range[1] - base_x:.3f} m")
    print("gripper")
    print(f"  hand at home   {np.round(robot.hand_pos(b)[0], 4)}")
    print(f"  clears cabinet top by "
          f"{(rails[0][2] + fr.hand_to_pad) - (cfg.table.top_z + cab.height):.3f} m")
    print(f"  jaws at q_open {fr.jaw_separation(cfg.teacher.q_open) * 1e3:.1f} mm "
          f"around a {cab.rail_thk * 1e3:.0f} mm rail")
    print(f"  slot depth     {cab.gap * 1e3:.0f} mm for a finger needing "
          f"{(cfg.teacher.q_open + fr.pad_face + 2 * fr.pad_half_thk) * 1e3:.1f} mm")
    print(f"tactile          {cfg.tactile.dim} dims, "
          f"{cfg.tactile.n_probes} probes x 2 fingers")


def write(frames: list[np.ndarray], path: Path, fps: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # cv2 accepts a mis-shaped frame without complaining -- it read a sliced
    # (W, 3) row as a one-pixel-wide image and wrote a black file.
    assert frames[0].ndim == 3 and frames[0].shape[2] == 3, frames[0].shape
    h, w = frames[0].shape[:2]
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    for f in frames:
        vw.write(cv2.cvtColor(f, cv2.COLOR_RGB2BGR))
    vw.release()
    print(f"wrote {path}  ({len(frames)} frames, {w}x{h}, {fps} fps)")


def main() -> None:
    ap = argparse.ArgumentParser(description="film a teacher episode")
    ap.add_argument("--envs", type=int, default=4)
    ap.add_argument("--env", type=int, default=0, help="which env to film")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--every", type=int, default=4, help="film every Nth control step")
    ap.add_argument("--fps", type=int, default=25)
    ap.add_argument("--out", default="out")
    ap.add_argument("--name", default="episode", help="basename for the mp4s")
    ap.add_argument("--nominal", action="store_true",
                    help="zero the cabinet jitter, to check the layout itself")
    ap.add_argument("--over-pull", action="store_true",
                    help="put the release threshold out of reach, so the arm "
                         "pulls into the stop for the whole budget")
    args = ap.parse_args()

    gs.init(backend=gs.gpu, logging_level="warning")
    cfg = EnvConfig(n_envs=args.envs, seed=args.seed,
                    add_camera=True, add_wrist_cams=True)
    if args.over_pull:
        # The release is what keeps the pull safe, so the only way to film what
        # it prevents is to make it unreachable: `pull` then ramps for all
        # pull_steps instead of stopping when the stop is felt.
        cfg = replace(cfg, teacher=replace(cfg.teacher, release_force=np.inf))
    b = build_scene(cfg)

    rng = np.random.default_rng(cfg.seed)
    setup = sample_episode(cfg, rng)
    if args.nominal:
        setup.cabinet_pos[:] = [cfg.cabinet.center_x, 0.0, cfg.table.top_z + 1e-4]
        setup.cabinet_quat[:] = [1.0, 0.0, 0.0, 0.0]
        setup.cabinet_yaw[:] = 0.0
    b.reset(setup)

    e = args.env
    print(f"\nprompt  {setup.prompts[e]}")
    print(f"stop    {setup.target_travel[e] * 1e3:.1f} mm\n")
    geometry(b, cfg)

    free, wrist = [], []

    def hook(cmd: np.ndarray) -> None:
        if b.step_count % args.every:
            return
        img = np.ascontiguousarray(b.render()[e])
        travel = b.drawer_travel()[e, setup.target_idx[e]]
        lines = [
            setup.prompts[e],
            f"travel {travel * 1e3:6.1f} / {setup.target_travel[e] * 1e3:.1f} mm",
            f"taxel  {b.tactile_peak()[e]:6.2f}",
            f"cab    {task_state.cabinet_shift(b)[e] * 1e3:6.1f} mm",
        ]
        for i, s in enumerate(lines):
            cv2.putText(img, s, (10, 24 + 22 * i), cv2.FONT_HERSHEY_SIMPLEX,
                        0.6, (255, 255, 255), 2, cv2.LINE_AA)
        free.append(img)
        wrist.append(np.ascontiguousarray(b.render_obs()["wrist"][e]))

    r = teacher.run_episode(b, setup, rng, on_step=hook)

    print(f"\nenv {e}: success={bool(r.success[e])} travel={r.travel[e] * 1e3:.1f} mm "
          f"shortfall={r.shortfall[e] * 1e3:.2f} mm shift={r.shift[e] * 1e3:.2f} mm "
          f"latency={r.latency[e]}")
    print(f"all envs: success {r.success.sum()}/{r.n}")

    out = Path(args.out)
    write(free, out / f"{args.name}.mp4", args.fps)
    write(wrist, out / f"{args.name}_wrist.mp4", args.fps)


if __name__ == "__main__":
    main()
