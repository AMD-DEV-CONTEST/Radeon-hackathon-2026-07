#!/usr/bin/env python3
"""Render demo videos for all trained tasks."""
import sys, os, glob, time
sys.path.insert(0, "/workspace/amd-physical-ai-soccer")
os.chdir("/workspace/amd-physical-ai-soccer")

import numpy as np
import yaml
import torch
import imageio
import genesis as gs
from genesis.utils.misc import tensor_to_array
from rsl_rl.runners import OnPolicyRunner
from envs.soccer_env import SoccerEnv

for task in ["balance", "chase", "shoot"]:
    print(f"\n[render] === Starting {task} ===")
    
    with open("configs/soccer_agent.yaml") as f:
        cfg = yaml.safe_load(f)
    
    env_cfg = dict(cfg["env"])
    env_cfg["task"] = task
    train_cfg = cfg["train"]

    gs.init(backend=gs.gpu, logging_level="warning")
    
    env = SoccerEnv(
        num_envs=1,
        env_cfg=env_cfg,
        obs_cfg=cfg["obs"],
        reward_cfg=cfg["reward"],
        command_cfg=cfg["command"],
        show_viewer=False,
    )

    cam = env.scene.visualizer.cameras[0]
    env.scene.reset()

    log_dir = f"runs/booster_soccer_{task}"
    model_files = sorted(glob.glob(f"{log_dir}/model_*.pt"), key=os.path.getmtime)
    
    if not model_files:
        print(f"[render] No model found for {task}, skipping")
        gs.shutdown()
        time.sleep(2)
        continue

    print(f"[render] Loading: {model_files[-1]}")
    
    runner = OnPolicyRunner(env, train_cfg, log_dir, device=gs.device)
    runner.load(model_files[-1])
    policy = runner.get_inference_policy(device=gs.device)

    obs = env.reset()
    frames = []
    total_rew = 0

    for i in range(300):
        with torch.no_grad():
            actions = policy(obs)
        obs, rew, done, info = env.step(actions)
        total_rew += rew.mean().item()

        if i % 2 == 0:
            rgb, _, _, _ = cam.render(rgb=True)
            arr = tensor_to_array(rgb)
            if arr.ndim == 4:
                arr = arr[0]
            frames.append(arr.astype(np.uint8))

        if (i + 1) % 100 == 0:
            print(f"  {task} step {i+1}/300  rew={rew.mean().item():.3f}  frames={len(frames)}")

    os.makedirs("demo", exist_ok=True)
    video_path = f"demo/{task}_demo.mp4"
    imageio.mimsave(video_path, frames, fps=30)
    print(f"[render] {task} saved: {video_path} ({len(frames)} frames, total_rew={total_rew:.1f})")
    
    gs.shutdown()
    time.sleep(2)

print("\n[render] ALL DONE - 3 videos saved to demo/")
