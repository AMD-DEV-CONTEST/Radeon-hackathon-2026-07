"""Validate a teleoperation dataset before spending GPU hours on it.

Checks, per episode:
  1. LIVENESS of both cameras — frame-to-frame change at a 1 s stride, longest static
     run. This is the check that would have caught the frozen-wrist recording described
     in the technical report (§6.1): a camera can return ok=True with an unchanging
     buffer, and shape/unit/fps checks all pass while the data is worthless.
  2. units/ranges — arm joints in the driver's degrees, gripper in RANGE_0_100
  3. the gripper actually closed and reopened (i.e. a pick happened)
  4. measured state tracks commanded action (teleop mirroring is sane)
  5. episode length, fps, task string
Optionally dumps the grasp-moment frames for visual review.

    python src/validate_camera_liveness.py --root datasets/so101_real_teleop
"""
import argparse
from pathlib import Path

import numpy as np
from PIL import Image

from lerobot.datasets.lerobot_dataset import LeRobotDataset

REPO_ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=str(REPO_ROOT / "datasets" / "so101_real_teleop"),
                    help="dataset root to validate")
    ap.add_argument("--repo-id", default=None,
                    help="LeRobot repo id (defaults to local/<root basename>)")
    ap.add_argument("--dump-frames", default=None, metavar="DIR",
                    help="write the grasp-moment frames here for visual review")
    args = ap.parse_args()

    root = Path(args.root)
    repo_id = args.repo_id or f"local/{root.name}"
    dump = Path(args.dump_frames) if args.dump_frames else None
    if dump:
        dump.mkdir(parents=True, exist_ok=True)

    ds = LeRobotDataset(repo_id, root=str(root))
    ep = ds.meta.episodes
    starts = np.array(ep["dataset_from_index"])
    lengths = np.array(ep["length"])
    print(f"episodes={ds.num_episodes} frames={ds.num_frames} fps={ds.fps}")
    print(f"task: {ds.meta.tasks.index.tolist()}")
    print(f"features: {[k for k in ds.features if 'image' in k or k in ('action','observation.state')]}")
    print()

    all_ok = True
    for e in range(ds.num_episodes):
        s, n = int(starts[e]), int(lengths[e])
        stride = 30  # 1 s
        idx = list(range(0, n, stride)) + [n - 1]
        probs = []

        # -- 1. liveness ------------------------------------------------------
        for cam in ("world", "wrist"):
            frames = [ds[s + i][f"observation.images.{cam}"].numpy() for i in idx]
            diffs = [float(np.abs(frames[k + 1] - frames[k]).mean() * 255)
                     for k in range(len(frames) - 1)]
            static = max_run = 0
            for d in diffs:
                static = static + 1 if d < 1.0 else 0
                max_run = max(max_run, static)
            if max_run >= 3:
                probs.append(f"{cam} static {max_run}s")
            if np.mean(diffs) < 1.0:
                probs.append(f"{cam} mostly static (mean {np.mean(diffs):.2f})")

        # -- 2-4. joints ------------------------------------------------------
        act = np.stack([ds[s + i]["action"].numpy() for i in range(0, n, 5)])
        st = np.stack([ds[s + i]["observation.state"].numpy() for i in range(0, n, 5)])
        arm_max = float(np.abs(act[:, :5]).max())
        if not 20 < arm_max < 200:
            probs.append(f"arm range odd (max|deg|={arm_max:.0f})")
        g = act[:, 5]
        if not (g.min() < 35 and g.max() > 60):
            probs.append(f"gripper never cycled (min {g.min():.0f} max {g.max():.0f})")
        track_err = float(np.abs(act[:, :5] - st[:, :5]).mean())
        if track_err > 8.0:
            probs.append(f"state lags action ({track_err:.1f} deg)")

        close_i = int(np.argmin(g)) * 5
        status = "OK " if not probs else "NG "
        all_ok &= not probs
        print(f"ep{e}: {status} n={n} ({n/30:.0f}s) grip[{g.min():.0f},{g.max():.0f}] "
              f"close@{close_i/30:.1f}s track_err={track_err:.1f}deg "
              f"{'| ' + '; '.join(probs) if probs else ''}")

        # -- grasp-moment frame dump (opt-in) --------------------------------
        if dump:
            item = ds[s + close_i]
            for cam in ("wrist", "world"):
                a = item[f"observation.images.{cam}"].numpy()
                Image.fromarray((np.transpose(a, (1, 2, 0)) * 255).astype(np.uint8)
                                ).save(dump / f"ep{e}_close_{cam}.png")

    print()
    print("VALIDATION_" + ("PASS" if all_ok else "FAIL"))


if __name__ == "__main__":
    main()
