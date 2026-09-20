#!/usr/bin/env python3
"""Shared closed-loop utilities for DM0.5 BiGym evaluation."""

from __future__ import annotations

import argparse
import os
import random
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

os.environ.setdefault("MUJOCO_GL", "egl")

import numpy as np
import torch

from bigym.utils.observation_config import CameraConfig, ObservationConfig
from demonstrations.demo import Demo

CAMERAS = ("head", "left_wrist", "right_wrist")


def ffmpeg_executable() -> str:
    configured = os.environ.get("FFMPEG_EXE")
    if configured:
        return configured
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


class FfmpegWriter:
    def __init__(self, path: Path, width: int, height: int, fps: int):
        self.process = subprocess.Popen(
            [
                ffmpeg_executable(),
                "-loglevel",
                "error",
                "-y",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                "-s:v",
                f"{width}x{height}",
                "-r",
                str(fps),
                "-i",
                "pipe:0",
                "-an",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                str(path),
            ],
            stdin=subprocess.PIPE,
        )

    def append_data(self, frame: np.ndarray) -> None:
        if self.process.stdin is None:
            raise RuntimeError("ffmpeg stdin is closed")
        self.process.stdin.write(frame.tobytes())

    def close(self) -> None:
        if self.process.stdin is not None:
            self.process.stdin.close()
        return_code = self.process.wait()
        if return_code:
            raise RuntimeError(f"ffmpeg exited with status {return_code}")


def make_env(
    demo: Demo,
    resolution: int,
    task_name: str,
    control_frequency: int,
    camera_resolutions: dict[str, tuple[int, int]] | None = None,
):
    if demo.metadata.env_name != task_name:
        raise ValueError(f"Expected {task_name}, got {demo.metadata.env_name}")
    return demo.metadata.env_cls(
        action_mode=demo.metadata.get_action_mode(),
        observation_config=ObservationConfig(
            cameras=[
                CameraConfig(
                    name=name,
                    rgb=True,
                    depth=False,
                    resolution=(
                        camera_resolutions[name]
                        if camera_resolutions is not None
                        else (resolution, resolution)
                    ),
                )
                for name in CAMERAS
            ],
            proprioception=True,
            privileged_information=False,
        ),
        control_frequency=control_frequency,
        render_mode=None,
        robot_cls=demo.metadata.robot_cls,
    )


def controlled_state(env, observation: dict[str, np.ndarray]) -> np.ndarray:
    """Build the action-aligned state; task evaluators may replace this hook."""
    arm_positions = []
    for actuator in env.robot.limb_actuators:
        if actuator.joint is None:
            raise RuntimeError("Tendon limb actuators are not supported")
        qpos = np.asarray(env._mojo.physics.bind(actuator.joint).qpos).reshape(-1)
        arm_positions.append(float(qpos[0]))
    return np.concatenate(
        [
            observation["proprioception_floating_base_actions"],
            np.asarray(arm_positions, dtype=np.float32),
            observation["proprioception_grippers"],
        ]
    ).astype(np.float32)


def rgb_hwc(image: np.ndarray) -> np.ndarray:
    image = np.asarray(image)
    if image.ndim != 3:
        raise ValueError(f"Expected a 3D RGB image, got {image.shape}")
    if image.shape[-1] == 3:
        return np.ascontiguousarray(image)
    if image.shape[0] == 3:
        return np.ascontiguousarray(np.moveaxis(image, 0, -1))
    raise ValueError(f"Cannot identify RGB channel axis for {image.shape}")


def policy_observation(env, observation: dict[str, np.ndarray]) -> dict:
    return {
        "state": controlled_state(env, observation),
        "camera_top": rgb_hwc(observation["rgb_head"]),
        "camera_wrist_left": rgb_hwc(observation["rgb_left_wrist"]),
        "camera_wrist_right": rgb_hwc(observation["rgb_right_wrist"]),
    }


def rollout(
    policy: Any,
    source: Demo,
    episode_name: str,
    seed: int,
    output_dir: Path,
    args: argparse.Namespace,
) -> dict:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)

    camera_resolutions = getattr(args, "camera_resolutions", None)
    env = make_env(
        source,
        args.resolution,
        args.task_name,
        args.control_frequency,
        camera_resolutions=camera_resolutions,
    )
    if hasattr(policy, "reset"):
        policy.reset()
    video_path = output_dir / f"{episode_name}.mp4"
    if camera_resolutions is None:
        video_width = args.resolution
        video_height = args.resolution
    else:
        video_height, video_width = camera_resolutions["head"]
    writer = FfmpegWriter(
        video_path,
        width=video_width,
        height=video_height,
        fps=args.policy_frequency,
    )
    if args.control_frequency % args.policy_frequency:
        raise ValueError("Policy frequency must divide the control frequency")
    repeat = args.control_frequency // args.policy_frequency
    start = time.time()
    policy_steps = 0
    control_steps = 0
    inference_calls = 0
    inference_seconds = 0.0
    clipped_values = 0
    total_values = 0
    success = False
    try:
        observation, _ = env.reset(seed=seed)
        while policy_steps < args.max_policy_steps and not success:
            inference_start = time.perf_counter()
            chunk = policy.infer(policy_observation(env, observation))
            inference_seconds += time.perf_counter() - inference_start
            if chunk.ndim != 2 or chunk.shape[1] != env.action_space.shape[0]:
                raise ValueError(f"Unexpected action chunk shape: {chunk.shape}")
            if not np.isfinite(chunk).all():
                raise FloatingPointError("Policy returned non-finite actions")
            inference_calls += 1
            for action in chunk[: args.execute_actions]:
                if policy_steps >= args.max_policy_steps or success:
                    break
                step_action = action.copy()
                floating_base_dims = int(getattr(args, "floating_base_dims", 0))
                if floating_base_dims:
                    interval_scale = float(
                        getattr(args, "floating_base_interval_scale", 1.0)
                    )
                    step_action[:floating_base_dims] *= interval_scale / repeat
                clipped = np.clip(
                    step_action,
                    env.action_space.low,
                    env.action_space.high,
                )
                clipped_values += int(np.count_nonzero(clipped != step_action))
                total_values += int(step_action.size)
                writer.append_data(rgb_hwc(observation["rgb_head"]))
                for _ in range(repeat):
                    observation, _, _, _, _ = env.step(clipped)
                    control_steps += 1
                    if env.success:
                        success = True
                        break
                policy_steps += 1
    finally:
        writer.close()
        env.close()
    return {
        "episode": episode_name,
        "seed": int(seed),
        "success": bool(success),
        "policy_steps": policy_steps,
        "control_steps": control_steps,
        "inference_calls": inference_calls,
        "inference_seconds": inference_seconds,
        "mean_inference_ms": 1000.0 * inference_seconds / max(inference_calls, 1),
        "clip_fraction": clipped_values / max(total_values, 1),
        "elapsed_seconds": time.time() - start,
        "video": str(video_path),
    }
