#!/usr/bin/env python
"""GPU throughput / utilization report for the submission (Track 3: 20 pts).

Measures:
  - device name + ROCm/torch versions
  - matmul TFLOPS proxy on the Radeon GPU
  - env steps-per-second at the configured num_envs
  - peak memory

Also print `rocm-smi` alongside this to prove utilization in your writeup.

Usage:
    python scripts/benchmark_gpu.py --config configs/soccer_agent.yaml
"""
from __future__ import annotations

import argparse
import os
import sys
import time

import torch
import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def gpu_flops_proxy(device: str, n: int = 4096, iters: int = 50) -> float:
    a = torch.randn(n, n, device=device)
    b = torch.randn(n, n, device=device)
    torch.cuda.synchronize()
    t0 = time.time()
    for _ in range(iters):
        c = a @ b
    torch.cuda.synchronize()
    dt = time.time() - t0
    flop = 2 * n ** 3 * iters
    return flop / dt / 1e12  # TFLOPS


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/soccer_agent.yaml")
    args = ap.parse_args()

    if not torch.cuda.is_available():
        raise SystemExit("No GPU visible to torch. On ROCm check `rocm-smi` and the torch wheel.")

    device = "cuda"
    print("=== AMD Radeon / ROCm benchmark ===")
    print(f"device        : {torch.cuda.get_device_name(0)}")
    print(f"torch         : {torch.__version__}")
    print(f"torch.version.hip : {getattr(torch.version, 'hip', None)}")

    tflops = gpu_flops_proxy(device)
    print(f"matmul TFLOPS : {tflops:.1f}")

    # env steps/sec (only if sim available)
    try:
        from envs.soccer_env import SoccerEnv
        with open(args.config) as f:
            cfg = yaml.safe_load(f)
        env = SoccerEnv(
            num_envs=cfg.get("num_envs", 2048),
            env_cfg=dict(cfg["env"]),
            obs_cfg=cfg["obs"],
            reward_cfg=cfg["reward"],
            command_cfg=cfg["command"],
            show_viewer=False,
        )
        obs = env.reset()
        action = torch.zeros(env.num_envs, env.num_actions, device=device)
        torch.cuda.synchronize(); t0 = time.time()
        for _ in range(200):
            obs, _, _, _ = env.step(action)
        torch.cuda.synchronize()
        sps = env.num_envs * 200 / (time.time() - t0)
        print(f"env steps/sec : {sps:,.0f} (num_envs={env.num_envs})")
    except Exception as e:
        print(f"env steps/sec : skipped ({e})")

    peak = torch.cuda.max_memory_allocated() / 1e9
    print(f"peak mem (GB) : {peak:.2f}")
    print("tip: run `rocm-smi --showuse` in another shell to capture utilization.")


if __name__ == "__main__":
    main()
