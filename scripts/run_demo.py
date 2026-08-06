"""End-to-end Radeon-VLA-SO101 demo: instruction -> VLA -> SO-101 -> pick-place.

Loads a fine-tuned SmolVLA checkpoint and runs closed-loop episodes in the Genesis
SO-101 scene, saving an mp4 that shows the world + wrist views. This is the artifact
for ``demo/demo.mp4``.

Pipeline per episode:
    reset (random cube layout + target) -> observe (RGB + state + instruction)
    -> VLA.predict -> env.step -> ... -> success check -> save video

Usage (on the Radeon machine, after fine-tuning):
    python scripts/run_demo.py \\
        --checkpoint outputs/train/smolvla_cube_pick/checkpoints/last/pretrained_model \\
        --repo-id so101/cube_pick --dataset-root datasets/cube_pick \\
        --episodes 3 --target red --save-video

NOTE: Requires Genesis + lerobot + a trained checkpoint; run on the AMD GPU.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from paths import DEMO_DIR, EVAL_VIDEOS_DIR


def _save_video(frames: list, path: Path, fps: int) -> None:
    if not frames:
        return
    import imageio.v2 as imageio

    path.parent.mkdir(parents=True, exist_ok=True)
    h, w = frames[0].shape[:2]
    h_even, w_even = h - (h % 2), w - (w % 2)
    writer = imageio.get_writer(
        str(path), fps=fps, codec="libx264", format="ffmpeg",
        pixelformat="yuv420p", macro_block_size=None,
    )
    try:
        for f in frames:
            writer.append_data(np.ascontiguousarray(f[:h_even, :w_even]))
    finally:
        writer.close()


def _compose_frame(obs: dict) -> np.ndarray:
    """World + wrist side by side (wrist resized to the world panel height)."""
    import cv2

    world = obs["image"]
    if "wrist_image" not in obs:
        return world.copy()
    h, w = world.shape[:2]
    wrist = cv2.resize(obs["wrist_image"], (w, h), interpolation=cv2.INTER_AREA)
    return np.ascontiguousarray(np.hstack([world, wrist]))


def main() -> None:
    parser = argparse.ArgumentParser(description="End-to-end SO-101 VLA pick-place demo.")
    parser.add_argument("--checkpoint", required=True, help="Fine-tuned policy checkpoint dir.")
    parser.add_argument("--repo-id", required=True, help="Dataset repo id the policy trained on.")
    parser.add_argument("--dataset-root", default=None)
    parser.add_argument("--backend", default="smolvla")
    parser.add_argument("--device", default="cuda", help="cuda (=AMD GPU on ROCm) | cpu.")
    parser.add_argument("-c", "--cpu", action="store_true", help="Genesis CPU backend.")
    parser.add_argument("--episodes", type=int, default=3)
    parser.add_argument("--target", default=None, help="Force a cube color (default: random per episode).")
    parser.add_argument("--max-seconds", type=float, default=15.0)
    parser.add_argument("--save-video", action="store_true")
    parser.add_argument("--video-dir", default=None)
    args = parser.parse_args()

    import genesis as gs
    from simulation.genesis_env import SO101PickPlaceEnv, build_scene
    from vla.inference import load_agent, run_episode

    gs.init(backend=gs.cpu if args.cpu else gs.gpu)
    env = SO101PickPlaceEnv(bundle=build_scene())
    agent = load_agent(
        args.checkpoint, args.repo_id, args.dataset_root,
        backend=args.backend, device=args.device,
    )

    video_dir = Path(args.video_dir) if args.video_dir else EVAL_VIDEOS_DIR / args.repo_id.split("/")[-1]
    n_success = 0
    for ep in range(args.episodes):
        result = run_episode(
            env, agent, max_seconds=args.max_seconds,
            record_video=args.save_video, target_color=args.target, seed=1000 + ep,
        )
        n_success += int(result.success)
        print(f"[demo] ep {ep} target={args.target or 'random'} "
              f"steps={result.n_steps} success={result.success}")

        if args.save_video and result.frames:
            # Re-compose frames as world+wrist panels via a fresh observe would need the
            # sim; run_episode stored world frames, so save those directly here.
            tag = "success" if result.success else "fail"
            _save_video(result.frames, video_dir / f"demo_ep{ep:02d}_{tag}.mp4", getattr(agent, "fps", 30))

    print(f"[demo] success rate: {n_success}/{args.episodes}")
    if args.save_video:
        print(f"[demo] videos -> {video_dir}")
        print(f"[demo] copy your best clip to {DEMO_DIR / 'demo.mp4'} for the submission.")


if __name__ == "__main__":
    main()
