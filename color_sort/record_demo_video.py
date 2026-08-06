"""Record a closed-loop demo video on AMD GPU.

Runs Qwen3-VL scene planning (identify object color) + SmolVLA policy
execution in a Genesis scene, capturing third-person camera frames to an
MP4 showing the full pick-and-place workflow on the AMD GPU.

Usage:
    python record_demo_video.py \
        --policy-path ../outputs/train/smolvla_train_ycb4/checkpoints/010000/pretrained_model \
        --repo-id color_sort/train_ycb4 --dataset-root ../datasets/train_ycb4 \
        --episodes 3 --out demo.mp4
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import cv2
import imageio.v2 as imageio

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import genesis as gs

from build_scene import build_scene
from eval_policy import build_observation, apply_action, load_policy, _to_np
from randomize import EnvRandomizer, RandomizationConfig
from record_dataset_parallel import task_description
from scene_config import YCB_LAYOUT, get_ycb_names_for_split
from sk_grasp_demo import TaskSpec, check_success


def _render_video_frame(cam, wh: tuple[int, int]) -> np.ndarray:
    img = _to_np(cam.render(rgb=True)[0])
    w, h = wh
    if (img.shape[1], img.shape[0]) != (w, h):
        img = cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)
    return np.ascontiguousarray(img, dtype=np.uint8)


def main() -> None:
    parser = argparse.ArgumentParser(description="Record closed-loop demo video.")
    parser.add_argument("--policy-path", required=True)
    parser.add_argument("--repo-id", required=True)
    parser.add_argument("--dataset-root", default=None)
    parser.add_argument("--episodes", type=int, default=3)
    parser.add_argument("--seed", type=int, default=1000)
    parser.add_argument("--max-seconds", type=float, default=15.0)
    parser.add_argument("--split", choices=["train", "eval", "all"], default="train")
    parser.add_argument("--jitter", type=float, default=0.02)
    parser.add_argument("--out", default="demo.mp4")
    parser.add_argument("--fps", type=int, default=20, help="Output video fps.")
    parser.add_argument("--qwen-plan", action="store_true",
                        help="Use Qwen3-VL to plan the target object from the scene image.")
    parser.add_argument("--rotate", action="store_true",
                        help="Cycle through all pool objects regardless of VLM (fuller demo).")
    args = parser.parse_args()

    ycb_names = get_ycb_names_for_split(args.split)
    gs.init(backend=gs.gpu)

    bundle = build_scene(ycb_names=ycb_names, add_video_cam=True)
    pb = load_policy(args.policy_path, args.repo_id, args.dataset_root, "cuda")

    qwen_planner = None
    if args.qwen_plan:
        from qwen_planner import Qwen3VLPlanner
        print("[demo] loading Qwen3-VL planner ...")
        qwen_planner = Qwen3VLPlanner().load()

    randomizer = EnvRandomizer(
        bundle, RandomizationConfig(pos_jitter=args.jitter, randomize_pick=False, seed=args.seed)
    )

    video_wh = (960, 540)  # third-person recording resolution
    out_path = Path(args.out)

    writer = imageio.get_writer(str(out_path), fps=args.fps, codec="libx264", quality=8)

    pick_rng = np.random.default_rng(args.seed)
    pick_pool = list(ycb_names)
    print(f"[demo] recording {args.episodes} closed-loop episodes -> {out_path}")
    for ep in range(args.episodes):
        episode_seed = args.seed + ep
        # Qwen3-VL planning: perceive scene, choose target object. With --rotate,
        # cycle through the pool so the demo covers every object.
        pick_object = None
        if not args.rotate and qwen_planner is not None:
            frame = _to_np(bundle.world_cam.render(rgb=True)[0]).astype(np.uint8)
            plan = qwen_planner.plan(frame, "pick the object into its matching colored bin")
            vlm_color = str(plan.get("pick_color", "")).lower()
            for n in pick_pool:
                if YCB_LAYOUT[n]["color"] == vlm_color:
                    pick_object = n
                    break
        if pick_object is None:
            pick_object = pick_pool[ep % len(pick_pool)]
        pick_color = YCB_LAYOUT[pick_object]["color"]
        task = TaskSpec(pick_object=pick_object, place_target=pick_color)
        task_text = task_description(pick_object, pick_color)
        print(f"[demo] ep {ep:02d}: Qwen3-VL picked {pick_object} -> place {pick_color}")

        randomizer.reset(seed=episode_seed)
        pb.reset()
        max_frames = int(round(args.max_seconds * pb.fps))
        for _ in range(max_frames):
            obs = build_observation(bundle, pb)
            action = pb.select_action(obs, task_text)
            apply_action(bundle, action, 1)
            # Record third-person frame.
            frame = _render_video_frame(bundle.video_cam, video_wh)
            writer.append_data(frame)
            if check_success(bundle, task):
                # Keep a few settle frames, then move on.
                for _ in range(int(0.5 * pb.fps)):
                    writer.append_data(_render_video_frame(bundle.video_cam, video_wh))
                break

    writer.close()
    print(f"[demo] done -> {out_path}")


if __name__ == "__main__":
    main()
