"""Closed-loop evaluation of the fine-tuned SmolVLA on the multi-fruit sort task.

Loads the trained checkpoint, builds a fresh Genesis scene, and runs the policy
autonomously for each fruit (plum, banana). Reports success/failure per fruit
and saves a rollout video.

Usage (on remote):
    cd /workspace/franka_fruit_pick_demo
    .venv/bin/python franka_fruit_pick/eval_sort_smolvla.py
"""
from __future__ import annotations

import argparse
import os
import sys
import json
from pathlib import Path

import numpy as np
import torch

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

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
    pick_order,
    sort_task_description,
)

# Reuse the same home/reset helper as record_sort_dataset.py.
from record_sort_dataset import _go_home


def _load_rename_map(pretrained_model_dir: Path) -> dict:
    """Read training-time camera rename_map from the checkpoint's train_config.json.

    SmolVLA was pretrained with camera1/2/3 keys; our dataset uses world/wrist.
    Training baked the rename into the preprocessor, but make_policy's feature-
    consistency check needs the same map to accept the raw dataset keys.
    """
    p = pretrained_model_dir / "train_config.json"
    if p.is_file():
        try:
            return json.loads(p.read_text()).get("rename_map") or {}
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def load_policy_and_processors(checkpoint_dir: str, device: str = "cuda"):
    """Load the fine-tuned SmolVLA policy + pre/post processors from a checkpoint."""
    ckpt = Path(checkpoint_dir)
    pretrained_model_dir = ckpt / "pretrained_model"

    print(f"[load] checkpoint: {pretrained_model_dir}")

    # Load dataset metadata (provides stats + features for the processors)
    ds_meta = LeRobotDatasetMetadata("local/sort_fruit")
    print(f"[load] dataset: {ds_meta.repo_id}, fps={ds_meta.fps}")

    # Load policy config from the checkpoint
    policy_cfg = PreTrainedConfig.from_pretrained(str(pretrained_model_dir))
    policy_cfg.pretrained_path = str(pretrained_model_dir)
    policy_cfg.device = device
    print(f"[load] policy type: {policy_cfg.type}")

    # Recover training-time camera rename_map (world->camera1, wrist->camera2)
    rename_map = _load_rename_map(pretrained_model_dir)
    if rename_map:
        print(f"[load] rename_map: {rename_map}")

    # Build policy (loads weights from pretrained_path); pass rename_map so the
    # feature-consistency check accepts raw dataset keys (world/wrist).
    policy = make_policy(policy_cfg, ds_meta=ds_meta, rename_map=rename_map)
    print(f"[load] policy loaded: {type(policy).__name__}")

    # Build pre/post processors (loads from checkpoint, uses dataset stats)
    preprocessor, postprocessor = make_pre_post_processors(
        policy_cfg,
        pretrained_path=str(pretrained_model_dir),
        dataset_meta=ds_meta,
    )
    print(f"[load] processors loaded")

    return policy, preprocessor, postprocessor, ds_meta


def capture_observation(bundle) -> dict:
    """Capture current observation as a dict of numpy arrays (LeRobot format).

    Returns:
        - observation.state: (9,) float32 — 7 arm joints + 2 fingers
        - observation.images.world: (224, 224, 3) uint8
        - observation.images.wrist: (224, 224, 3) uint8
    """
    import cv2

    # State: 9 DOF (7 joints + 2 fingers)
    state = bundle.franka.get_qpos().cpu().numpy().reshape(-1).astype(np.float32)

    # Images: world + wrist cameras. cam.render() returns a list/tuple; [0] is the image.
    world_img = np.asarray(bundle.world_cam.render(rgb=True)[0])
    wrist_img = np.asarray(bundle.wrist_cam.render(rgb=True)[0])

    world_np = np.ascontiguousarray(world_img, dtype=np.uint8)
    wrist_np = np.ascontiguousarray(wrist_img, dtype=np.uint8)

    # Resize to 224x224 if needed
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
    """Run the full inference pipeline using LeRobot's canonical predict_action helper.

    Delegates to lerobot.common.control_utils.predict_action, which uses
    prepare_observation_for_inference to convert uint8 images -> float32 in [0,1]
    (the format the preprocessor's normalizer expects).

    Returns: (9,) numpy array — 7 arm joints + 2 fingers (both fingers same value).
    """
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
    """Execute a 9-DOF action on the Franka arm.

    action: [joint1..7, finger1, finger2] — the recorded action format from
    grasp_demo (both fingers get the same target value).
    """
    arm = action[:7].astype(np.float64)
    # Both fingers get the same value; use action[7] (or mean of 7,8).
    finger_val = float(np.clip(action[7], 0.0, 0.04))

    # Clip arm to safe joint limits
    arm = np.clip(arm, -2.8973, 2.8973)

    bundle.franka.control_dofs_position(arm, MOTORS_DOF)
    bundle.franka.control_dofs_position(
        np.array([finger_val, finger_val]), FINGERS_DOF,
    )
    bundle.scene.step()
    bundle.update_wrist_cam()


def _save_side_by_side_video(frames: list, path: str, fps: int = 30) -> None:
    """Save a list of (world, wrist) np.uint8 frames as a side-by-side mp4."""
    import cv2
    h, w = frames[0][0].shape[:2]
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(path, fourcc, fps, (w * 2, h))
    for world, wrist in frames:
        side = np.concatenate([world, wrist], axis=1)
        writer.write(cv2.cvtColor(side, cv2.COLOR_RGB2BGR))
    writer.release()


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
) -> dict:
    """Run one fruit sort episode autonomously with the policy.

    Returns a dict with: fruit, success, steps, task.
    """
    container = SORT_MAPPING[fruit]
    task_str = sort_task_description(fruit)
    task_spec = TaskSpec(
        pick_object=fruit,
        place_target=container,
        success_tol=success_tol,
    )
    print(f"\n  [eval] fruit={fruit} -> container={container}")
    print(f"  [eval] task='{task_str}'")

    # Reset policy internal queues (clears action chunk queue between episodes)
    policy.reset()

    frames: list = []  # list of (world, wrist) uint8 tuples, only if record_frames
    success = False
    for step in range(max_steps):
        obs = capture_observation(bundle)

        try:
            action = predict_action(obs, task_str, policy, preprocessor, postprocessor, device)
        except Exception as e:
            print(f"  [step {step}] predict error: {e}")
            import traceback
            traceback.print_exc()
            break

        execute_action(bundle, action)

        # Optionally record the post-step cameras for video
        if record_frames:
            world_img = np.asarray(bundle.world_cam.render(rgb=True)[0])
            wrist_img = np.asarray(bundle.wrist_cam.render(rgb=True)[0])
            frames.append((world_img.astype(np.uint8), wrist_img.astype(np.uint8)))

        # Check success (instantaneous spatial test)
        try:
            success = check_success(bundle, task_spec)
        except Exception as e:
            print(f"  [step {step}] check_success error: {e}")
            break

        if success:
            print(f"  [step {step}] SUCCESS! fruit placed in container")
            # Record a few more frames so the video shows the object settling
            for _ in range(30):
                if record_frames:
                    world_img = np.asarray(bundle.world_cam.render(rgb=True)[0])
                    wrist_img = np.asarray(bundle.wrist_cam.render(rgb=True)[0])
                    frames.append((world_img.astype(np.uint8), wrist_img.astype(np.uint8)))
                bundle.scene.step()
                bundle.update_wrist_cam()
            break

        if step % 50 == 0:
            print(f"  [step {step}] arm={action[:3].round(3)} finger={action[7]:.3f}")

    if not success:
        print(f"  [timeout] {max_steps} steps without success")

    return {
        "fruit": fruit,
        "container": container,
        "success": success,
        "steps": step + 1,
        "task": task_str,
        "frames": frames if record_frames else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate fine-tuned SmolVLA on the sort task.")
    parser.add_argument(
        "--checkpoint",
        type=str,
        default="/workspace/franka_fruit_pick_demo/outputs/train/smolvla_lerobot/checkpoints/002000",
        help="Path to the checkpoint directory (containing pretrained_model/).",
    )
    parser.add_argument("--cpu", action="store_true", default=False, help="Force CPU sim.")
    parser.add_argument("--max-steps", type=int, default=300, help="Max policy steps per fruit.")
    parser.add_argument("--episodes", type=int, default=1, help="Number of eval episodes (each = 2 fruits).")
    parser.add_argument("--output", type=str, default="/tmp/eval_results.json", help="Output JSON path.")
    parser.add_argument(
        "--save-video",
        type=str,
        default=None,
        help="If set, save a side-by-side (world|wrist) rollout mp4 per fruit to this dir.",
    )
    args = parser.parse_args()

    save_video = bool(args.save_video)
    video_dir = Path(args.save_video) if save_video else None
    if video_dir is not None:
        video_dir.mkdir(parents=True, exist_ok=True)

    device = torch.device("cuda" if torch.cuda.is_available() and not args.cpu else "cpu")
    print(f"[main] device={device}")

    # Init Genesis
    gs.init(backend=gs.cpu if args.cpu else gs.gpu)

    # Load policy + processors
    policy, preprocessor, postprocessor, ds_meta = load_policy_and_processors(
        args.checkpoint, device=str(device),
    )

    # Run eval episodes
    all_results = []
    for ep in range(args.episodes):
        print(f"\n=== Episode {ep+1}/{args.episodes} ===")
        bundle = build_scene(layout=SORT_LAYOUT, add_world_cam=True, add_wrist_cam=True)

        episode_results = []
        first_pick = True
        for fruit in pick_order():
            if not first_pick:
                _go_home(bundle)
            first_pick = False
            result = run_eval_episode(
                bundle, fruit, policy, preprocessor, postprocessor, device,
                max_steps=args.max_steps,
                record_frames=save_video,
            )
            # Save per-fruit video
            if save_video and result.get("frames"):
                vpath = str(video_dir / f"ep{ep+1}_{fruit}.mp4")
                _save_side_by_side_video(result["frames"], vpath, fps=30)
                print(f"  [video] saved {len(result['frames'])} frames -> {vpath}")
                result.pop("frames")  # don't dump frames into JSON
            elif save_video:
                result.pop("frames", None)
            episode_results.append(result)
        all_results.extend(episode_results)

    # Summary
    print("\n=== Summary ===")
    successes = sum(1 for r in all_results if r["success"])
    total = len(all_results)
    for r in all_results:
        status = "OK" if r["success"] else "FAIL"
        print(f"  {r['fruit']:20s} -> {r['container']:25s} : {status} (steps={r['steps']})")
    print(f"\nSuccess rate: {successes}/{total} ({100*successes/total:.1f}%)" if total > 0 else "No results")

    # Save results
    with open(args.output, "w") as f:
        json.dump({
            "checkpoint": args.checkpoint,
            "successes": successes,
            "total": total,
            "success_rate": successes / total if total > 0 else 0,
            "results": all_results,
        }, f, indent=2)
    print(f"\nResults saved to {args.output}")


if __name__ == "__main__":
    main()
