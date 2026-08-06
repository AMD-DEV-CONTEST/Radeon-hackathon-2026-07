"""Record an English-overlay MP4 demonstration of visual residual control."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
import torch
import yaml

from algorithms.ppo_trainer import CleanRLPPOTrainer, PPOConfig
from experiments.train_visual_residual import _factory
from simulation.task_factory import initialize_genesis


def _panel(frame: np.ndarray, *, episode: int, phase: str, info: dict, residual: np.ndarray) -> np.ndarray:
    height, width = frame.shape[:2]
    panel_width = 420
    canvas = np.full((height, width + panel_width, 3), (14, 18, 28), dtype=np.uint8)
    canvas[:, :width] = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
    x, y = width + 28, 52
    lines = [
        ("CONTACT-CONFIRMED VISUAL PICK & PLACE", (105, 224, 255), 0.64),
        (f"Episode {episode + 1}", (220, 230, 240), 0.58),
        (f"Phase: {phase.upper()}", (105, 255, 170), 0.70),
        (f"Distance: {float(info.get('distance_to_goal', np.nan)) * 100:.2f} cm", (220, 230, 240), 0.54),
        (f"Contact verified: {'YES' if info.get('grasp_verified', False) else 'NO'}", (105, 255, 170), 0.54),
        (f"Dual-finger steps: {int(info.get('consecutive_dual_finger_contact_steps', 0))}", (220, 230, 240), 0.54),
        (f"Residual L2: {float(np.linalg.norm(residual)):.5f}", (220, 230, 240), 0.54),
        (f"Object lifted: {'YES' if info.get('object_was_lifted', False) else 'NO'}", (220, 230, 240), 0.54),
        ("AMD Radeon GPU | ROCm / HIP | Genesis", (160, 184, 255), 0.48),
    ]
    for index, (text, color, scale) in enumerate(lines):
        cv2.putText(canvas, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, color, 2, cv2.LINE_AA)
        y += 48 if index == 0 else 42
    status = "SUCCESS" if info.get("is_success", False) else "RUNNING"
    color = (105, 255, 170) if status == "SUCCESS" else (255, 210, 105)
    cv2.rectangle(canvas, (x, height - 110), (width + panel_width - 28, height - 50), color, thickness=2)
    cv2.putText(canvas, status, (x + 14, height - 70), cv2.FONT_HERSHEY_SIMPLEX, 0.75, color, 2, cv2.LINE_AA)
    return canvas


def main() -> None:
    parser = argparse.ArgumentParser(description="Record a reproducible headless MP4 demo.")
    parser.add_argument("--config", type=Path, default=Path("configs/demo_visual_residual.yaml"))
    parser.add_argument("--output", type=Path, default=Path("demo/outputs/visual_residual_demo.mp4"))
    parser.add_argument("--metadata", type=Path, default=Path("demo/outputs/visual_residual_demo.json"))
    parser.add_argument("--fps", type=int, default=30)
    args = parser.parse_args()
    config = yaml.safe_load(args.config.read_text())
    task_yaml = yaml.safe_load(Path(config["task_config"]).read_text())
    initialize_genesis(backend=task_yaml["genesis_backend"])
    env = _factory(config, worker_index=0)
    writer = None
    summaries = []
    try:
        payload = torch.load(config["checkpoint"], map_location=config["device"], weights_only=False)
        trainer = CleanRLPPOTrainer(
            int(np.prod(env.observation_space.shape)), int(np.prod(env.action_space.shape)),
            config=PPOConfig(**payload["config"]),
            residual_scale=float(payload.get("extra", {}).get("residual_scale", config["residual_scale"])),
            device=config["device"], log_dir=config["log_dir"],
        )
        trainer.load_checkpoint(config["checkpoint"])
        args.output.parent.mkdir(parents=True, exist_ok=True)
        for episode in range(int(config["episodes"])):
            observation, _ = env.reset(seed=int(config["seed"]) + episode)
            terminated = truncated = False
            info: dict = {}
            steps = 0
            while not (terminated or truncated):
                with torch.inference_mode():
                    tensor = torch.as_tensor(observation, dtype=torch.float32, device=trainer.device).unsqueeze(0)
                    residual = trainer.agent.actor_mean(tensor).squeeze(0).cpu().numpy()
                observation, _, terminated, truncated, info = env.step(residual)
                info["grasp_verified"] = bool(env.controller.contact_verifier.grasp_verified)
                frame = env.unwrapped.render_presentation()
                if frame is None:
                    raise RuntimeError("presentation camera is unavailable; set presentation_camera_enabled: true")
                composed = _panel(frame, episode=episode, phase=env.controller.expert.phase, info=info, residual=residual)
                if writer is None:
                    height, width = composed.shape[:2]
                    writer = cv2.VideoWriter(str(args.output), cv2.VideoWriter_fourcc(*"mp4v"), args.fps, (width, height))
                    if not writer.isOpened():
                        raise RuntimeError("OpenCV could not open an MP4 writer in this environment")
                writer.write(composed)
                steps += 1
            summaries.append({
                "episode": episode, "seed": int(config["seed"]) + episode, "steps": steps,
                "success": bool(info.get("is_success", False)),
                "final_distance_m": float(info.get("distance_to_goal", np.nan)),
            })
    finally:
        if writer is not None:
            writer.release()
        env.close()
    args.metadata.parent.mkdir(parents=True, exist_ok=True)
    args.metadata.write_text(json.dumps({"config": str(args.config), "video": str(args.output), "episodes": summaries}, indent=2) + "\n")
    print(json.dumps({"video": str(args.output), "metadata": str(args.metadata), "episodes": summaries}, indent=2))


if __name__ == "__main__":
    main()
