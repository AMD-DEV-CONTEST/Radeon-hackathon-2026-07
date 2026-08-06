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
from record_dataset_parallel import CONTROL_FPS, task_description
from scene_config import YCB_LAYOUT, get_ycb_names_for_split
from sk_grasp_demo import TaskSpec, check_success


def _render_video_frame(cam, wh: tuple[int, int]) -> np.ndarray:
    img = _to_np(cam.render(rgb=True)[0])
    w, h = wh
    if (img.shape[1], img.shape[0]) != (w, h):
        img = cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)
    return np.ascontiguousarray(img, dtype=np.uint8)


def _put_text(img, text, pos, scale=0.7, color=(255, 255, 255), bg=(0, 0, 0), thickness=2):
    """Draw text with a background bar for readability."""
    font = cv2.FONT_HERSHEY_SIMPLEX
    (tw, th), base = cv2.getTextSize(text, font, scale, thickness)
    x, y = pos
    cv2.rectangle(img, (x - 4, y - th - 6), (x + tw + 4, y + 6), bg, -1)
    cv2.putText(img, text, (x, y), font, scale, color, thickness, cv2.LINE_AA)
    return img


def _overlay_title(img, title, subtitle=""):
    """Top banner with project title + subtitle."""
    img = _put_text(img, title, (20, 40), scale=0.9, color=(255, 255, 255), bg=(20, 20, 40))
    if subtitle:
        img = _put_text(img, subtitle, (20, 70), scale=0.6, color=(200, 220, 255), bg=(20, 20, 40))
    return img


def _overlay_cmd(img, cmd):
    """Bottom-left terminal-style command line."""
    img = _put_text(img, f"$ {cmd}", (20, img.shape[0] - 30), scale=0.6,
                    color=(120, 255, 120), bg=(20, 40, 20), thickness=2)
    return img


def _overlay_status(img, status, color):
    """Bottom-right status badge (PLANNING / EXECUTING / SUCCESS / FAIL)."""
    img = _put_text(img, status, (img.shape[1] - 260, img.shape[0] - 30), scale=0.7,
                    color=color, bg=(40, 20, 20))
    return img


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

    def _frame_with_overlay(status, color, cmd):
        frame = _render_video_frame(bundle.video_cam, video_wh)
        frame = _overlay_title(frame, "RoboPilot YCB Color Sorting",
                               "SmolVLA + Qwen3-VL on AMD Radeon (ROCm)")
        frame = _overlay_cmd(frame, cmd)
        frame = _overlay_status(frame, status, color)
        return frame

    def _write_frames(n):
        for _ in range(n):
            writer.append_data(_frame_with_overlay(status, color, cmd))

    for ep in range(args.episodes):
        episode_seed = args.seed + ep
        # Qwen3-VL planning: perceive scene, choose target object. With --rotate,
        # cycle through the pool so the demo covers every object.
        pick_object = None
        cmd = "python eval_policy.py --qwen-plan --episodes 20"
        status, color = "PLANNING", (255, 220, 100)
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
        cmd = f"pick {pick_object} -> {pick_color}_bin"

        randomizer.reset(seed=episode_seed)
        pb.reset()
        # Brief planning banner before the arm moves.
        status, color = "PLANNING: " + pick_object, (255, 220, 100)
        _write_frames(int(1.5 * args.fps))
        # Executing the pick-place. Match the eval control rate: the policy runs
        # at pb.fps (30 Hz) while the sim steps at CONTROL_FPS (100 Hz), so each
        # action advances the sim by CONTROL_FPS/pb.fps steps (accumulated).
        status, color = "EXECUTING", (120, 200, 255)
        max_frames = int(round(args.max_seconds * pb.fps))
        steps_per_frame = CONTROL_FPS / pb.fps
        accum = 0.0
        for _ in range(max_frames):
            obs = build_observation(bundle, pb)
            action = pb.select_action(obs, task_text)
            accum += steps_per_frame
            n_sub = int(accum)
            accum -= n_sub
            apply_action(bundle, action, max(1, n_sub))
            writer.append_data(_frame_with_overlay(status, color, cmd))
            if check_success(bundle, task):
                status, color = "SUCCESS", (120, 255, 120)
                _write_frames(int(1.0 * args.fps))
                break
        else:
            status, color = "FAIL", (255, 120, 120)
            _write_frames(int(1.0 * args.fps))

    writer.close()
    print(f"[demo] done -> {out_path}")


if __name__ == "__main__":
    main()
