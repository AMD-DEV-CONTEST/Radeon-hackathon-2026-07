"""Record inspection sample videos for the V2 industrial sorting scene.

Runs the scripted pick-and-place (run_pick_place) on the randomized scene and writes
per-episode world + wrist mp4s -- the same footage the dataset recorder sees, but as
standalone videos for visual inspection BEFORE any formal dataset build. This is the
standing pre-flight check: 3 episodes per part, both camera views, downloaded and
eyeball-checked by the user.

Usage:
    python sample_videos.py --reps 3 --picks gear nut bolt --seed 5000 \
        --video-dir /workspace/sample_videos/sort_v2
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import genesis as gs

from grasp_demo import TaskSpec, run_pick_place
from randomize import EnvRandomizer, RandomizationConfig
from record_dataset import EpisodeRecorder, task_description
from scene_config import SORT_TARGET

FPS = 30


def save_mp4(frames: list[np.ndarray], path: Path, fps: int = FPS) -> None:
    """Write uint8 RGB frames to h264 mp4 via an ffmpeg pipe (no intermediate files)."""
    if not frames:
        return
    h, w = frames[0].shape[:2]
    proc = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", f"{w}x{h}", "-r", str(fps), "-i", "pipe:0", "-c:v", "libx264",
         "-pix_fmt", "yuv420p", "-preset", "veryfast", "-crf", "23", str(path)],
        stdin=subprocess.PIPE,
    )
    for f in frames:
        proc.stdin.write(np.ascontiguousarray(f, dtype=np.uint8).tobytes())
    proc.stdin.close()
    proc.wait()


def main() -> None:
    parser = argparse.ArgumentParser(description="Record per-episode inspection sample videos.")
    parser.add_argument("--reps", type=int, default=3, help="Episodes per pick object.")
    parser.add_argument("--picks", nargs="+", default=["gear", "nut", "bolt"])
    parser.add_argument("--seed", type=int, default=5000, help="Base seed for pose randomization.")
    parser.add_argument("--video-dir", default="/workspace/sample_videos/sort_v2")
    parser.add_argument("--img-width", type=int, default=640)
    parser.add_argument("--img-height", type=int, default=360)
    # Same DR flags as the formal dataset build, so samples show the real distribution.
    parser.add_argument("--dr-runtime", action="store_true", help="Enable Layer-B runtime DR.")
    parser.add_argument(
        "--dr-friction", type=float, nargs=2, default=(0.7, 1.3), help="Friction ratio range."
    )
    parser.add_argument(
        "--dr-mass", type=float, nargs=2, default=(0.8, 1.2), help="Mass ratio range."
    )
    args = parser.parse_args()

    from build_scene import build_scene
    from randomize import DomainRandomizationConfig

    gs.init(backend=gs.gpu, logging_level="warning")
    bundle = build_scene(show_viewer=False, n_envs=1, add_world_cam=True, add_wrist_cam=True)
    dr_cfg = DomainRandomizationConfig(
        enabled=args.dr_runtime,
        friction_ratio_range=tuple(args.dr_friction),
        mass_ratio_range=tuple(args.dr_mass),
    )
    randomizer = EnvRandomizer(
        bundle, RandomizationConfig(randomize_pick=False, seed=args.seed, dr=dr_cfg)
    )
    recorder = EpisodeRecorder(bundle, fps=FPS, img_wh=(args.img_width, args.img_height))

    vdir = Path(args.video_dir)
    vdir.mkdir(parents=True, exist_ok=True)

    ep = 0
    n_ok = 0
    total = args.reps * len(args.picks)
    for rep in range(args.reps):
        for pick in args.picks:
            seed = args.seed + ep
            randomizer.reset(seed=seed)
            task = TaskSpec(pick_object=pick, place_target=SORT_TARGET[pick])

            recorder.reset()
            success, _ = run_pick_place(bundle, task, recorder=recorder)
            n_ok += int(success)

            tag = "ok" if success else "fail"
            print(f"[sample] {ep + 1}/{total} pick={pick} seed={seed} "
                  f"target={task.place_target} task='{task_description(pick)}' -> {tag} "
                  f"({len(recorder)} frames)")
            save_mp4(recorder.world_imgs, vdir / f"sample_ep{ep:02d}_s{seed}_{pick}_{tag}_world.mp4")
            save_mp4(recorder.wrist_imgs, vdir / f"sample_ep{ep:02d}_s{seed}_{pick}_{tag}_wrist.mp4")
            ep += 1

    print(f"\n[sample] RESULT: {n_ok}/{total} succeeded -> {vdir}")


if __name__ == "__main__":
    main()
