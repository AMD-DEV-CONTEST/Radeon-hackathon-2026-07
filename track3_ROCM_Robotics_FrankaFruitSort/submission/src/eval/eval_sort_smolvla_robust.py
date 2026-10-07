"""Enhanced closed-loop evaluation with robustness testing.

Extends eval_sort_smolvla.py with:
  - Multi-episode statistical evaluation (10+ episodes)
  - Pose perturbation (fruit initial position jitter)
  - Multi-seed reproducibility
  - All 3 fruits (plum, banana, lemon) with configurable subset
  - Per-fruit, per-episode breakdown + aggregate statistics
  - JSON output with full provenance for reproducibility

Usage (on remote):
    cd /workspace/franka_fruit_pick_demo
    .venv/bin/python franka_fruit_pick/eval_sort_smolvla_robust.py \
        --checkpoint outputs/train/smolvla_lerobot/checkpoints/002000 \
        --episodes 10 \
        --perturb 0.02 \
        --fruits plum banana lemon \
        --output /tmp/eval_robust_results.json \
        --save-video /workspace/eval_videos_robust
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import random
from pathlib import Path

import numpy as np
import torch

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Apply ROCm compatibility patch BEFORE importing lerobot policy modules.
# This patches resize_with_pad to cast uint8->float32 before F.interpolate,
# preventing NotImplementedError on AMD ROCm GPUs.
import sys as _sys

_UTILS_DIR = str(_ROOT.parent / "utils")
if _UTILS_DIR not in _sys.path:
    _sys.path.insert(0, _UTILS_DIR)
try:
    import rocm_resize_patch  # noqa: F401 — auto-applies monkey-patch on import
except ImportError:
    pass  # If the patch file isn't found, proceed; the eval may still work on CUDA

import genesis as gs

from lerobot.common.control_utils import predict_action as lerobot_predict_action
from lerobot.policies import make_policy, make_pre_post_processors
from lerobot.configs import PreTrainedConfig
from lerobot.datasets.dataset_metadata import LeRobotDatasetMetadata

import grasp_demo as _gd
from build_scene import build_scene
from grasp_demo import (
    TaskSpec,
    check_success,
    MOTORS_DOF,
    FINGERS_DOF,
    GRIPPER_OPEN,
)
from sort_scene_config import (
    SORT_LAYOUT,
    SORT_MAPPING,
    LANE_ASSIGNMENT,
    LANE_Y,
    PICK_X,
    PLACE_X,
    sort_task_description,
)

# Reuse the same home/reset helper and overrides as the standard eval.
from record_sort_dataset import _go_home
from sort_demo import _goto_plan_with_retry


# Apply the same grasp profile overrides as sort_demo/record_sort_dataset.
# Banana: yaw_offset=-35.0 cancels the 35-degree object yaw, eliminating the
# IK-branch-crossing that caused RRTConnect to fail.
# Lemon: close_force=-30.0 for a firm grip on the small ellipsoid.
from grasp_demo import GraspProfile

_OVERRIDE_PROFILES = {
    "018_plum": GraspProfile(yaw_offset=0.0, close_force=-35.0, center_align=True),
    "011_banana": GraspProfile(yaw_offset=-35.0, close_force=-50.0, center_align=True),
    "014_lemon": GraspProfile(yaw_offset=0.0, close_force=-60.0, center_align=True),
}
for _name, _prof in _OVERRIDE_PROFILES.items():
    _gd.GRASP_PROFILES[_name] = _prof

_gd._goto_plan = _goto_plan_with_retry
# v9: keep original _descend_vertical (step-wise z descent) — no override needed
_gd.GRASP_CENTER_DROP_FRAC = 1.0
_gd.PALM_CLEARANCE = 0.01
# v10: import the run_pick_place override from sort_demo
from sort_demo import _run_pick_place_v10, _settle_grasp  # noqa: E402

_gd.run_pick_place = _run_pick_place_v10


# All available fruits for evaluation.
ALL_FRUITS = ["018_plum", "011_banana", "014_lemon"]


def _load_rename_map(pretrained_model_dir: Path) -> dict:
    p = pretrained_model_dir / "train_config.json"
    if p.is_file():
        try:
            return json.loads(p.read_text()).get("rename_map") or {}
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def load_policy_and_processors(checkpoint_dir: str, device: str = "cuda"):
    ckpt = Path(checkpoint_dir)
    pretrained_model_dir = ckpt / "pretrained_model"
    print(f"[load] checkpoint: {pretrained_model_dir}")
    ds_meta = LeRobotDatasetMetadata("local/sort_fruit")
    print(f"[load] dataset: {ds_meta.repo_id}, fps={ds_meta.fps}")
    policy_cfg = PreTrainedConfig.from_pretrained(str(pretrained_model_dir))
    policy_cfg.pretrained_path = str(pretrained_model_dir)
    policy_cfg.device = device
    print(f"[load] policy type: {policy_cfg.type}")
    rename_map = _load_rename_map(pretrained_model_dir)
    if rename_map:
        print(f"[load] rename_map: {rename_map}")
    policy = make_policy(policy_cfg, ds_meta=ds_meta, rename_map=rename_map)
    print(f"[load] policy loaded: {type(policy).__name__}")
    preprocessor, postprocessor = make_pre_post_processors(
        policy_cfg,
        pretrained_path=str(pretrained_model_dir),
        dataset_meta=ds_meta,
    )
    print(f"[load] processors loaded")
    return policy, preprocessor, postprocessor, ds_meta


def capture_observation(bundle) -> dict:
    import cv2

    state = bundle.franka.get_qpos().cpu().numpy().reshape(-1).astype(np.float32)
    world_img = np.asarray(bundle.world_cam.render(rgb=True)[0])
    wrist_img = np.asarray(bundle.wrist_cam.render(rgb=True)[0])
    world_np = np.ascontiguousarray(world_img, dtype=np.uint8)
    wrist_np = np.ascontiguousarray(wrist_img, dtype=np.uint8)
    if world_np.shape[:2] != (224, 224):
        world_np = cv2.resize(world_np, (224, 224), interpolation=cv2.INTER_AREA)
    if wrist_np.shape[:2] != (224, 224):
        wrist_np = cv2.resize(wrist_np, (224, 224), interpolation=cv2.INTER_AREA)
    return {
        "observation.state": state,
        "observation.images.world": world_np,
        "observation.images.wrist": wrist_np,
    }


def predict_action(
    observation: dict,
    task: str,
    policy,
    preprocessor,
    postprocessor,
    device,
) -> np.ndarray:
    action = lerobot_predict_action(
        observation=observation,
        policy=policy,
        device=device,
        preprocessor=preprocessor,
        postprocessor=postprocessor,
        use_amp=False,
        task=task,
        robot_type="franka",
    )
    if action.dim() > 1:
        action = action.squeeze(0)
    return action.cpu().numpy()


def execute_action(bundle, action: np.ndarray) -> None:
    arm = action[:7].astype(np.float64)
    finger_val = float(np.clip(action[7], 0.0, 0.04))
    arm = np.clip(arm, -2.8973, 2.8973)
    bundle.franka.control_dofs_position(arm, MOTORS_DOF)
    bundle.franka.control_dofs_position(
        np.array([finger_val, finger_val]),
        FINGERS_DOF,
    )
    bundle.scene.step()
    bundle.update_wrist_cam()


def _save_side_by_side_video(frames: list, path: str, fps: int = 30) -> None:
    import cv2

    h, w = frames[0][0].shape[:2]
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(path, fourcc, fps, (w * 2, h))
    for world, wrist in frames:
        side = np.concatenate([world, wrist], axis=1)
        writer.write(cv2.cvtColor(side, cv2.COLOR_RGB2BGR))
    writer.release()


def make_perturbed_layout(perturb: float, rng: random.Random) -> dict:
    """Create a SORT_LAYOUT copy with fruit positions perturbed by +/- perturb meters.

    Bowls stay fixed (they are place targets, not pick targets).
    Perturbation is applied to x and y of each fruit, keeping it within the
    empirically verified reachable workspace.
    """
    layout = {}
    for fruit, base_pos in LANE_ASSIGNMENT.items():
        dx = rng.uniform(-perturb, perturb)
        dy = rng.uniform(-perturb, perturb)
        new_x = PICK_X + dx
        new_y = base_pos + dy
        # Clamp to safe workspace
        new_x = max(0.20, min(0.40, new_x))
        new_y = max(-0.30, min(0.30, new_y))
        layout[fruit] = {
            "pos": (new_x, new_y, 0.0),
            "euler": (0.0, 0.0, 35.0 if fruit == "011_banana" else 0.0),
            "friction": 1.0,
        }
    # Bowls stay at fixed positions
    for container, color in [
        ("024_bowl_yellow", (1.0, 0.85, 0.10, 1.0)),
        ("024_bowl_green", (0.20, 0.70, 0.25, 1.0)),
        ("024_bowl_purple", (0.55, 0.20, 0.65, 1.0)),
    ]:
        lane_y = {
            "024_bowl_yellow": LANE_Y[0],
            "024_bowl_green": LANE_Y[1],
            "024_bowl_purple": LANE_Y[2],
        }[container]
        layout[container] = {
            "pos": (PLACE_X, lane_y, 0.0),
            "euler": (0.0, 0.0, 0.0),
            "color": color,
        }
    return layout


def run_eval_episode(
    bundle,
    fruit: str,
    policy,
    preprocessor,
    postprocessor,
    device,
    *,
    max_steps: int = 300,
    success_tol: float = 0.06,
    record_frames: bool = False,
    episode_id: int = 0,
) -> dict:
    container = SORT_MAPPING[fruit]
    task_str = sort_task_description(fruit)
    task_spec = TaskSpec(
        pick_object=fruit,
        place_target=container,
        success_tol=success_tol,
    )
    print(f"\n  [eval ep{episode_id}] fruit={fruit} -> container={container}")
    print(f"  [eval ep{episode_id}] task='{task_str}'")

    policy.reset()

    frames: list = []
    success = False
    start_time = time.time()
    for step in range(max_steps):
        obs = capture_observation(bundle)
        try:
            action = predict_action(
                obs, task_str, policy, preprocessor, postprocessor, device
            )
        except Exception as e:
            print(f"  [step {step}] predict error: {e}")
            import traceback

            traceback.print_exc()
            break
        execute_action(bundle, action)

        if record_frames:
            world_img = np.asarray(bundle.world_cam.render(rgb=True)[0])
            wrist_img = np.asarray(bundle.wrist_cam.render(rgb=True)[0])
            frames.append((world_img.astype(np.uint8), wrist_img.astype(np.uint8)))

        try:
            success = check_success(bundle, task_spec)
        except Exception as e:
            print(f"  [step {step}] check_success error: {e}")
            break

        if success:
            print(f"  [step {step}] SUCCESS! fruit placed in container")
            for _ in range(30):
                if record_frames:
                    world_img = np.asarray(bundle.world_cam.render(rgb=True)[0])
                    wrist_img = np.asarray(bundle.wrist_cam.render(rgb=True)[0])
                    frames.append(
                        (world_img.astype(np.uint8), wrist_img.astype(np.uint8))
                    )
                bundle.scene.step()
                bundle.update_wrist_cam()
            break

        if step % 50 == 0:
            print(f"  [step {step}] arm={action[:3].round(3)} finger={action[7]:.3f}")

    if not success:
        print(f"  [timeout] {max_steps} steps without success")

    elapsed = time.time() - start_time
    return {
        "fruit": fruit,
        "container": container,
        "success": success,
        "steps": step + 1,
        "task": task_str,
        "elapsed_s": round(elapsed, 1),
        "frames": frames if record_frames else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Enhanced closed-loop evaluation with robustness testing."
    )
    parser.add_argument(
        "--checkpoint",
        type=str,
        default="/workspace/franka_fruit_pick_demo/outputs/train/smolvla_lerobot/checkpoints/002000",
        help="Path to the checkpoint directory (containing pretrained_model/).",
    )
    parser.add_argument(
        "--cpu", action="store_true", default=False, help="Force CPU sim."
    )
    parser.add_argument(
        "--max-steps", type=int, default=400, help="Max policy steps per fruit."
    )
    parser.add_argument(
        "--episodes",
        type=int,
        default=10,
        help="Number of eval episodes (each episode = 1 scene build + all fruits).",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="/tmp/eval_robust_results.json",
        help="Output JSON path.",
    )
    parser.add_argument(
        "--save-video",
        type=str,
        default=None,
        help="If set, save side-by-side (world|wrist) rollout mp4 per fruit per episode.",
    )
    parser.add_argument(
        "--fruits",
        type=str,
        nargs="+",
        default=["018_plum", "011_banana"],
        help="Fruits to evaluate. Options: 018_plum 011_banana 014_lemon",
    )
    parser.add_argument(
        "--perturb",
        type=float,
        default=0.0,
        help="Positional perturbation magnitude in meters (applied to fruit x,y). 0 = no perturbation.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for perturbation reproducibility. If not set, uses system entropy.",
    )
    parser.add_argument(
        "--success-tol",
        type=float,
        default=0.06,
        help="Success tolerance in meters (distance from fruit COM to bowl center).",
    )
    args = parser.parse_args()

    # Validate fruit selection
    for f in args.fruits:
        if f not in ALL_FRUITS:
            parser.error(f"Unknown fruit '{f}'. Valid options: {ALL_FRUITS}")

    save_video = bool(args.save_video)
    video_dir = Path(args.save_video) if save_video else None
    if video_dir is not None:
        video_dir.mkdir(parents=True, exist_ok=True)

    # Seed setup
    if args.seed is not None:
        random.seed(args.seed)
        np.random.seed(args.seed)
        torch.manual_seed(args.seed)
        print(f"[seed] Using seed={args.seed} for reproducibility")
    rng = random.Random(args.seed)

    device = torch.device(
        "cuda" if torch.cuda.is_available() and not args.cpu else "cpu"
    )
    print(f"[main] device={device}")
    print(
        f"[main] episodes={args.episodes}, fruits={args.fruits}, perturb={args.perturb}m"
    )

    # Init Genesis
    gs.init(backend=gs.cpu if args.cpu else gs.gpu)

    # Load policy + processors
    policy, preprocessor, postprocessor, ds_meta = load_policy_and_processors(
        args.checkpoint,
        device=str(device),
    )

    # Run eval episodes
    all_results = []
    for ep in range(args.episodes):
        print(f"\n{'=' * 60}")
        print(f"=== Episode {ep + 1}/{args.episodes} ===")
        print(f"{'=' * 60}")

        # Build perturbed layout if requested
        if args.perturb > 0:
            layout = make_perturbed_layout(args.perturb, rng)
            print(f"[ep{ep + 1}] perturbed layout (perturb={args.perturb}m):")
            for fruit in args.fruits:
                pos = layout[fruit]["pos"]
                print(f"  {fruit}: ({pos[0]:.3f}, {pos[1]:.3f}, {pos[2]:.3f})")
        else:
            layout = SORT_LAYOUT
            print(f"[ep{ep + 1}] using nominal layout (no perturbation)")

        bundle = build_scene(layout=layout, add_world_cam=True, add_wrist_cam=True)

        episode_results = []
        first_pick = True
        for fruit in args.fruits:
            if not first_pick:
                _go_home(bundle)
            first_pick = False
            result = run_eval_episode(
                bundle,
                fruit,
                policy,
                preprocessor,
                postprocessor,
                device,
                max_steps=args.max_steps,
                success_tol=args.success_tol,
                record_frames=save_video,
                episode_id=ep + 1,
            )
            # Save per-fruit video
            if save_video and result.get("frames"):
                vpath = str(video_dir / f"ep{ep + 1}_{fruit}.mp4")
                _save_side_by_side_video(result["frames"], vpath, fps=30)
                print(f"  [video] saved {len(result['frames'])} frames -> {vpath}")
                result.pop("frames")
            elif save_video:
                result.pop("frames", None)
            episode_results.append(result)
        all_results.extend(episode_results)

    # Aggregate statistics
    print(f"\n{'=' * 60}")
    print("=== AGGREGATE STATISTICS ===")
    print(f"{'=' * 60}")

    total = len(all_results)
    successes = sum(1 for r in all_results if r["success"])

    # Per-fruit breakdown
    per_fruit_stats = {}
    for fruit in args.fruits:
        fruit_results = [r for r in all_results if r["fruit"] == fruit]
        fruit_successes = sum(1 for r in fruit_results if r["success"])
        fruit_total = len(fruit_results)
        fruit_steps = [r["steps"] for r in fruit_results if r["success"]]
        per_fruit_stats[fruit] = {
            "successes": fruit_successes,
            "total": fruit_total,
            "success_rate": fruit_successes / fruit_total if fruit_total > 0 else 0,
            "mean_steps_on_success": round(np.mean(fruit_steps), 1)
            if fruit_steps
            else None,
            "std_steps_on_success": round(np.std(fruit_steps), 1)
            if len(fruit_steps) > 1
            else 0.0,
            "min_steps": min(fruit_steps) if fruit_steps else None,
            "max_steps": max(fruit_steps) if fruit_steps else None,
        }

    # Print summary table
    print(
        f"\n  {'Fruit':<20s} {'Suc/Total':>10s} {'Rate':>8s} {'Mean Steps':>12s} {'Std':>8s}"
    )
    print(f"  {'-' * 20} {'-' * 10} {'-' * 8} {'-' * 12} {'-' * 8}")
    for fruit in args.fruits:
        s = per_fruit_stats[fruit]
        mean_str = (
            f"{s['mean_steps_on_success']:.1f}" if s["mean_steps_on_success"] else "N/A"
        )
        std_str = (
            f"{s['std_steps_on_success']:.1f}"
            if s["std_steps_on_success"] is not None
            else "N/A"
        )
        print(
            f"  {fruit:<20s} {s['successes']}/{s['total']:>3d}     {s['success_rate'] * 100:>6.1f}%  {mean_str:>12s} {std_str:>8s}"
        )

    print(
        f"\n  {'OVERALL':<20s} {successes}/{total:>3d}     {100 * successes / total if total > 0 else 0:>6.1f}%"
    )

    # Per-episode breakdown
    per_episode = {}
    for ep in range(args.episodes):
        ep_results = all_results[ep * len(args.fruits) : (ep + 1) * len(args.fruits)]
        ep_successes = sum(1 for r in ep_results if r["success"])
        per_episode[ep + 1] = {
            "successes": ep_successes,
            "total": len(ep_results),
            "all_success": ep_successes == len(ep_results),
        }

    # Save comprehensive results
    output_data = {
        "metadata": {
            "checkpoint": args.checkpoint,
            "episodes": args.episodes,
            "fruits": args.fruits,
            "perturb_m": args.perturb,
            "seed": args.seed,
            "max_steps": args.max_steps,
            "success_tol": args.success_tol,
            "device": str(device),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        },
        "summary": {
            "total_trials": total,
            "total_successes": successes,
            "overall_success_rate": successes / total if total > 0 else 0,
            "episodes_full_success": sum(
                1 for e in per_episode.values() if e["all_success"]
            ),
            "total_episodes": args.episodes,
        },
        "per_fruit": per_fruit_stats,
        "per_episode": per_episode,
        "results": all_results,
    }

    with open(args.output, "w") as f:
        json.dump(output_data, f, indent=2)
    print(f"\nResults saved to {args.output}")


if __name__ == "__main__":
    main()
