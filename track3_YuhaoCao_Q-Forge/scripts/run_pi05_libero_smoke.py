#!/usr/bin/env python3
"""Run two deterministic PI0.5 episodes on one LIBERO task."""

import argparse
import collections
import json
import math
from pathlib import Path
import time

import imageio.v2 as imageio
import numpy as np
import torch
from libero.libero import benchmark, get_libero_path
from libero.libero.envs import OffScreenRenderEnv

from toolkits.standalone_eval_scripts.openpi import setup_policy


def quat_to_axis_angle(quat: np.ndarray) -> np.ndarray:
    quat = quat.copy()
    quat[3] = np.clip(quat[3], -1.0, 1.0)
    denominator = np.sqrt(1.0 - quat[3] ** 2)
    if math.isclose(denominator, 0.0):
        return np.zeros(3)
    return quat[:3] * 2.0 * math.acos(quat[3]) / denominator


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--task-id", type=int, default=0)
    parser.add_argument("--episodes", type=int, default=2)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--max-steps", type=int, default=220)
    parser.add_argument("--action-chunk", type=int, default=5)
    parser.add_argument("--num-steps", type=int, default=3)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    torch.cuda.reset_peak_memory_stats()

    policy_args = argparse.Namespace(
        config_name="pi05_libero",
        pretrained_path=args.checkpoint,
        num_steps=args.num_steps,
    )
    load_start = time.perf_counter()
    policy = setup_policy(policy_args)
    model_load_seconds = time.perf_counter() - load_start

    suite = benchmark.get_benchmark("libero_spatial")()
    task = suite.get_task(args.task_id)
    initial_states = suite.get_task_init_states(args.task_id)
    bddl = Path(get_libero_path("bddl_files")) / task.problem_folder / task.bddl_file
    env = OffScreenRenderEnv(
        bddl_file_name=str(bddl), camera_heights=256, camera_widths=256
    )
    env.seed(args.seed)

    episode_results = []
    for episode in range(args.episodes):
        policy.reset()
        env.reset()
        obs = env.set_init_state(initial_states[episode])
        action_plan: collections.deque[np.ndarray] = collections.deque()
        frames = []
        inference_seconds = 0.0
        inference_calls = 0
        reward_sum = 0.0
        success = False
        start = time.perf_counter()

        for step in range(args.max_steps + 10):
            if step < 10:
                obs, reward, done, _ = env.step([0.0] * 6 + [-1.0])
                reward_sum += float(reward)
                continue

            image = np.ascontiguousarray(obs["agentview_image"][::-1, ::-1])
            wrist = np.ascontiguousarray(
                obs["robot0_eye_in_hand_image"][::-1, ::-1]
            )
            frames.append(image)
            if not action_plan:
                state = np.concatenate(
                    (
                        obs["robot0_eef_pos"],
                        quat_to_axis_angle(obs["robot0_eef_quat"]),
                        obs["robot0_gripper_qpos"],
                    )
                )
                infer_start = time.perf_counter()
                actions = policy.infer(
                    {
                        "observation/image": image,
                        "observation/wrist_image": wrist,
                        "observation/state": state,
                        "prompt": str(task.language),
                    }
                )["actions"]
                inference_seconds += time.perf_counter() - infer_start
                inference_calls += 1
                action_plan.extend(actions[: args.action_chunk])

            obs, reward, done, _ = env.step(action_plan.popleft().tolist())
            reward_sum += float(reward)
            if done:
                success = True
                break

        elapsed = time.perf_counter() - start
        video_path = output_dir / f"native_rlinf_episode_{episode}.mp4"
        imageio.mimwrite(video_path, frames[::5], fps=6)
        result = {
            "episode": episode,
            "success": success,
            "reward_sum": reward_sum,
            "steps": step + 1,
            "elapsed_seconds": elapsed,
            "rollout_fps": (step + 1) / elapsed,
            "inference_calls": inference_calls,
            "mean_inference_seconds": inference_seconds / max(inference_calls, 1),
            "video": str(video_path),
        }
        episode_results.append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)

    env.close()
    report = {
        "model": "PI0.5 LIBERO (locally converted OpenPI checkpoint)",
        "checkpoint": str(Path(args.checkpoint).resolve()),
        "suite": "libero_spatial",
        "task_id": args.task_id,
        "task": task.language,
        "seed": args.seed,
        "model_load_seconds": model_load_seconds,
        "torch": torch.__version__,
        "torch_cuda": torch.version.cuda,
        "gpu": torch.cuda.get_device_name(),
        "peak_vram_mib": torch.cuda.max_memory_allocated() / 2**20,
        "successes": sum(item["success"] for item in episode_results),
        "episodes": episode_results,
    }
    (output_dir / "metrics.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
