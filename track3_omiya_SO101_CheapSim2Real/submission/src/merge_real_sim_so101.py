"""Merge a REAL teleop dataset into the SIM dataset for co-training.

Two things must happen before real and sim episodes can share a training batch:

1. **Unit conversion (critical).** ``lerobot-record`` stores whatever the driver
   reports: the 5 arm joints in DEGREES and the gripper on a 0-100 scale. The sim
   datasets store RADIANS for all six. Concatenating them without conversion feeds
   the policy two different coordinate systems for the same task — it silently
   destroys co-training. This script rewrites the real episodes into sim units
   using the same ``JointBridge`` the real-robot runner uses.

2. **Oversampling.** 10 real episodes (~4k frames) against 50 sim episodes
   (~42k frames) is ~9% of each batch. lerobot 0.6's train CLI takes a single
   dataset and no sampler weights, so the practical way to reach a target real
   fraction is to write the real episodes ``--repeat`` times into the merged set.

       repeat 1  ->  ~9% real      repeat 5  -> ~32% real (recommended)
       repeat 10 -> ~49% real (overfitting risk on 10 unique episodes)

Usage:
    uv run python -m franka_fruit_pick.merge_real_sim_so101 \
        --real-repo-id omiya239532/so101_real_teleop --real-root datasets/so101_real_teleop \
        --sim-repo-id  omiya239532/so101_cube_colors --sim-root  datasets/so101_cube_colors \
        --out-repo-id  omiya239532/so101_mixed --repeat 5
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from lerobot.configs.video import RGBEncoderConfig
from lerobot.datasets.lerobot_dataset import LeRobotDataset

from eval_policy_so101_real import ARM, JointBridge
from paths import DATASETS_DIR
from record_dataset_so101 import TASK, build_features

STATE_KEY = "observation.state"
IMAGE_KEYS = ("observation.images.world", "observation.images.wrist")


def _to_hwc_uint8(t, size_wh: tuple[int, int] | None = None) -> np.ndarray:
    """LeRobotDataset returns images as CHW float in [0,1]; add_frame wants HWC uint8.

    ``size_wh`` resizes to the merged dataset's resolution — the real teleop set is
    captured at 320x240 (USB bandwidth of the 120fps wrist camera), the sim set at
    640x480, and one merged dataset must have a single image shape."""
    import cv2
    a = t.numpy() if hasattr(t, "numpy") else np.asarray(t)
    if a.ndim == 3 and a.shape[0] in (1, 3):
        a = np.transpose(a, (1, 2, 0))
    if a.dtype != np.uint8:
        a = (np.clip(a, 0.0, 1.0) * 255).astype(np.uint8)
    if size_wh is not None and (a.shape[1], a.shape[0]) != size_wh:
        a = cv2.resize(a, size_wh, interpolation=cv2.INTER_AREA if a.shape[1] > size_wh[0]
                       else cv2.INTER_LINEAR)
    return np.ascontiguousarray(a)


def _episode_bounds(ds: LeRobotDataset) -> list[tuple[int, int]]:
    meta = ds.meta.episodes
    starts = np.asarray(meta["dataset_from_index"])
    lengths = np.asarray(meta["length"])
    return [(int(s), int(s) + int(n)) for s, n in zip(starts, lengths)]


def real_to_sim_units(vec: np.ndarray, bridge: JointBridge) -> np.ndarray:
    """Driver units (deg arm + 0-100 gripper) -> sim radians, elementwise on a 6-vector."""
    v = np.asarray(vec, dtype=np.float64).reshape(-1)
    out = np.empty(6, dtype=np.float64)
    out[ARM] = np.deg2rad((v[ARM] - bridge.offset) / bridge.sign)
    out[5] = bridge._grip_to_sim(v[5])
    return out.astype(np.float32)


def copy_episodes(src: LeRobotDataset, dst: LeRobotDataset, *, convert: bool,
                  repeat: int, bridge: JointBridge, label: str,
                  size_wh: tuple[int, int] = (640, 480)) -> int:
    bounds = _episode_bounds(src)
    n_written = 0
    for r in range(repeat):
        for ei, (lo, hi) in enumerate(bounds):
            for i in range(lo, hi):
                item = src[i]
                state = item[STATE_KEY].numpy().astype(np.float32)
                action = item["action"].numpy().astype(np.float32)
                if convert:
                    state = real_to_sim_units(state, bridge)
                    action = real_to_sim_units(action, bridge)
                dst.add_frame({
                    STATE_KEY: state,
                    "action": action,
                    IMAGE_KEYS[0]: _to_hwc_uint8(item[IMAGE_KEYS[0]], size_wh),
                    IMAGE_KEYS[1]: _to_hwc_uint8(item[IMAGE_KEYS[1]], size_wh),
                    "task": TASK,
                })
            dst.save_episode()
            n_written += 1
        print(f"[merge] {label}: pass {r + 1}/{repeat} done ({len(bounds)} episodes)")
    return n_written


def main() -> None:
    p = argparse.ArgumentParser(description="Merge real teleop + sim datasets for co-training.")
    p.add_argument("--real-repo-id", required=True)
    p.add_argument("--real-root", required=True)
    p.add_argument("--sim-repo-id", required=True)
    p.add_argument("--sim-root", required=True)
    p.add_argument("--out-repo-id", required=True)
    p.add_argument("--out-root", default=None)
    p.add_argument("--repeat", type=int, default=5,
                   help="How many times to write the real episodes (oversampling factor).")
    p.add_argument("--no-convert", action="store_true",
                   help="Skip deg->rad conversion (only if the real set is already in sim units).")
    p.add_argument("--img-width", type=int, default=640)
    p.add_argument("--img-height", type=int, default=480)
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--vcodec", default="libsvtav1")
    p.add_argument("--overwrite", action="store_true")
    args = p.parse_args()

    out_root = Path(args.out_root) if args.out_root else DATASETS_DIR / args.out_repo_id.split("/")[-1]
    if out_root.exists():
        if args.overwrite:
            shutil.rmtree(out_root)
        else:
            raise SystemExit(f"[merge] {out_root} exists. Use --overwrite.")

    real = LeRobotDataset(args.real_repo_id, root=args.real_root)
    sim = LeRobotDataset(args.sim_repo_id, root=args.sim_root)
    print(f"[merge] real: {real.num_episodes} eps / {real.num_frames} frames")
    print(f"[merge] sim : {sim.num_episodes} eps / {sim.num_frames} frames")
    frac = real.num_frames * args.repeat / (real.num_frames * args.repeat + sim.num_frames)
    print(f"[merge] repeat={args.repeat} -> real fraction {frac:.1%} of the merged set")

    out = LeRobotDataset.create(
        repo_id=args.out_repo_id,
        fps=args.fps,
        features=build_features((args.img_width, args.img_height)),
        root=out_root,
        robot_type="so101",
        use_videos=True,
        rgb_encoder=RGBEncoderConfig(vcodec=args.vcodec),
    )

    bridge = JointBridge()
    wh = (args.img_width, args.img_height)
    n_real = copy_episodes(real, out, convert=not args.no_convert, repeat=args.repeat,
                           bridge=bridge, label="real", size_wh=wh)
    n_sim = copy_episodes(sim, out, convert=False, repeat=1, bridge=bridge, label="sim", size_wh=wh)
    out.finalize()
    print(f"[merge] done: {n_real} real + {n_sim} sim episodes -> {out_root}")


if __name__ == "__main__":
    main()
