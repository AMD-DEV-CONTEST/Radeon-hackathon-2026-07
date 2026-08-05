"""Write teacher demonstrations to a LeRobot dataset.

    uv run collect                                # 128 x 8 episodes
    uv run collect --envs 8 --batches 2 --dry-run

Only successful episodes are written. The teacher is at 100% today so nothing
is dropped, but the filter has to exist before that stops being true -- a
dragged cabinet is a demonstration of failing.

`observation.tactile` is a feature in its own right, never folded into
`observation.state`. pi0.5 digitizes state into 256 bins and pastes it into the
text prompt, which is a poor channel for a contact signal that is quiet for
most of an episode and then steps; kept separate it stays continuous and can be
encoded straight into the action expert's conditioning.
"""
from __future__ import annotations

import argparse
import time

import numpy as np
import genesis as gs

from . import teacher
from .config import DATASET_REPO_ID, DATASET_ROOT, EnvConfig
from .randomize import sample_episode
from .record import ACTION_DIM, STATE_DIM, Recorder
from .scene import build_scene

JOINTS = [f"joint_{i}" for i in range(7)] + ["finger_0", "finger_1"]
STATE_NAMES = JOINTS
ACTION_NAMES = [f"d_{j}" for j in JOINTS]

# The one non-default lerobot setting here, and the only one worth changing.
# For `video` features add_frame writes a PNG per frame per camera, and with the
# default of 0 writer threads it does so INLINE, inside the collection loop.
# lerobot's own record script uses 4 threads per camera.
WRITER_THREADS_PER_CAMERA = 4


def device_used() -> str:
    """Whole-device memory in use. Genesis allocates outside the torch
    allocator, so torch's own accounting would miss the physics and the
    renderer -- most of what is actually resident during a scaling probe."""
    try:
        import torch
        if not torch.cuda.is_available():
            return "-"
        free, total = torch.cuda.mem_get_info()
        return f"{(total - free) / 2**30:.1f}G"
    except Exception:
        return "-"


def dataset_features(cfg: EnvConfig) -> dict:
    """LeRobot feature spec matching exactly what `Recorder` produces.

    Images are declared `video` so they are encoded to mp4 rather than stored
    as raw frames, which is the difference between ~100 MB and a few MB per
    episode on disk.
    """
    h, w = cfg.wrist.res
    feats = {
        f"observation.images.{name}": {
            "dtype": "video", "shape": (h, w, 3),
            "names": ["height", "width", "channels"],
            "info": {"is_depth_map": False},
        }
        for name, _, _ in cfg.wrist.mounts
    }
    feats["observation.state"] = {
        "dtype": "float32", "shape": (STATE_DIM,), "names": STATE_NAMES}
    feats["observation.tactile"] = {
        "dtype": "float32", "shape": (cfg.tactile.dim,),
        "names": [f"taxel_{i}" for i in range(cfg.tactile.dim)]}
    feats["action"] = {
        "dtype": "float32", "shape": (ACTION_DIM,), "names": ACTION_NAMES}
    return feats


def episode_frames(rec: Recorder, i: int, prompt: str):
    """Yield one LeRobot frame dict per timestep for env `i`."""
    ep = rec.episode(i)
    for t in range(len(ep["action"])):
        frame = {f"observation.images.{name}": ep["images"][name][t]
                 for name in ep["images"]}
        frame["observation.state"] = ep["state"][t]
        frame["observation.tactile"] = ep["tactile"][t]
        frame["action"] = ep["action"][t]
        frame["task"] = prompt
        yield frame


def collect(cfg: EnvConfig, batches: int, *, repo_id: str, root: str | None = None,
            dry_run: bool = False) -> dict:
    b = build_scene(cfg)
    rng = np.random.default_rng(cfg.seed)

    ds = None
    if not dry_run:
        from lerobot.datasets.lerobot_dataset import LeRobotDataset
        ds = LeRobotDataset.create(
            repo_id=repo_id, fps=int(cfg.record_hz), features=dataset_features(cfg),
            root=root, robot_type="franka_panda", use_videos=True,
            image_writer_threads=WRITER_THREADS_PER_CAMERA * len(cfg.wrist.mounts))

    kept = dropped = frames = 0
    t0 = time.perf_counter()
    for batch in range(batches):
        setup = sample_episode(cfg, rng)
        b.reset(setup)
        rec = Recorder(b)
        result = teacher.run_episode(b, setup, rng, on_step=rec)

        for i in range(cfg.n_envs):
            if not result.success[i]:
                dropped += 1
                continue
            if ds is not None:
                for frame in episode_frames(rec, i, setup.prompts[i]):
                    ds.add_frame(frame)
                ds.save_episode()
            kept += 1
            frames += rec.n_frames
        print(f"  batch {batch + 1}/{batches}: kept {result.success.sum()}/{cfg.n_envs}"
              f"  {rec.n_frames} frames/ep  buffered {rec.nbytes() / 1e9:.1f} GB")

    if ds is not None:
        # Without this the parquet footers are never written and the dataset is
        # invalid on read-back.
        ds.finalize()
    wall = time.perf_counter() - t0
    return {"episodes": kept, "dropped": dropped, "frames": frames,
            "wall": wall, "eps_per_min": kept / wall * 60 if wall else 0.0}


def scaling_probe(sizes: list[int], seed: int = 0) -> None:
    """One recorded batch at each N, in the configuration `collect` really uses.

    `rollout --scaling` renders nothing, so its curve says little about this.
    Here the wrist camera is on and a Recorder is attached, which is what makes
    N expensive: a whole batch of frames is held in RAM until it is written, so
    expect host RAM to bind before the GPU does.

    Stops at the first N that fails, so run it upward and take the last row
    that finished.
    """
    print(f"{'N':>5} {'wall':>8} {'frames':>7} {'buffered':>9} {'device':>8}  success")
    for n in sizes:
        cfg = EnvConfig(n_envs=n, seed=seed, add_wrist_cams=True)
        try:
            b = build_scene(cfg)
            rng = np.random.default_rng(seed)
            setup = sample_episode(cfg, rng)
            b.reset(setup)
            rec = Recorder(b)
            t0 = time.perf_counter()
            r = teacher.run_episode(b, setup, rng, on_step=rec)
            wall = time.perf_counter() - t0
        except Exception as e:                      # OOM arrives by many names
            print(f"{n:>5}  FAILED  {type(e).__name__}: {str(e)[:60]}")
            break
        print(f"{n:>5} {wall:>7.1f}s {rec.n_frames:>7} "
              f"{rec.nbytes() / 1e9:>8.1f}G {device_used():>8}  {r.success.sum()}/{n}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--envs", type=int, default=128)
    ap.add_argument("--batches", type=int, default=8)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--repo-id", default=DATASET_REPO_ID)
    ap.add_argument("--root", default=DATASET_ROOT,
                    help=f"dataset dir (default {DATASET_ROOT}); "
                         f"pass empty to use $HF_LEROBOT_HOME")
    ap.add_argument("--dry-run", action="store_true",
                    help="capture everything, write nothing (needs no lerobot)")
    ap.add_argument("--scaling", default=None,
                    help="comma-separated n_envs to probe for the RAM ceiling")
    args = ap.parse_args()

    gs.init(backend=gs.gpu, logging_level="warning")
    if args.scaling:
        scaling_probe([int(x) for x in args.scaling.split(",")], args.seed)
        return

    cfg = EnvConfig(n_envs=args.envs, seed=args.seed, add_wrist_cams=True)
    print(f"recording at {cfg.record_hz:.0f} Hz "
          f"(every {cfg.record_every} control steps of {1 / cfg.dt:.0f} Hz)")
    s = collect(cfg, args.batches, repo_id=args.repo_id, root=args.root or None,
                dry_run=args.dry_run)
    print(f"\nepisodes kept  {s['episodes']}  (dropped {s['dropped']} failed)")
    print(f"frames         {s['frames']}")
    print(f"throughput     {s['eps_per_min']:.1f} episodes/min "
          f"({s['wall'] / 60:.1f} min total)")


if __name__ == "__main__":
    main()
