#!/usr/bin/env python3
"""Run the first FlightGuard single-Radeon stability gate."""

from __future__ import annotations

import argparse
import json
import time

import torch


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--num-envs", type=int, default=8)
    parser.add_argument("--steps", type=int, default=32)
    parser.add_argument("--seed", type=int, default=0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    import genesis as gs

    gs.init(
        backend=gs.amdgpu,
        precision="32",
        seed=args.seed,
        performance_mode=False,
        logging_level="warning",
    )
    if gs.backend != gs.amdgpu:
        raise RuntimeError(f"backend mismatch: expected gs.amdgpu, got {gs.backend}")

    from flightguard.genesis_env import FlightGuardGenesisEnv

    env = FlightGuardGenesisEnv(args.num_envs)
    action = torch.zeros((args.num_envs, 4), device=gs.device)
    observation = env.observe()
    started = time.perf_counter()
    resets = 0
    for _ in range(args.steps):
        result = env.step(action)
        observation = result.observation
        if not torch.isfinite(observation).all():
            raise RuntimeError("non-finite observation")
        done_idx = torch.nonzero(result.done, as_tuple=False).reshape(-1)
        if done_idx.numel():
            env.reset(done_idx)
            resets += int(done_idx.numel())
    if args.num_envs > 1:
        before = env.drone.get_pos()[1:].clone()
        env.reset(torch.tensor([0], device=gs.device))
        after = env.drone.get_pos()[1:]
        isolated_reset = bool(torch.equal(before, after))
    else:
        isolated_reset = True
    elapsed = time.perf_counter() - started
    metrics = {
        "backend": str(gs.backend),
        "device": str(gs.device),
        "num_envs": args.num_envs,
        "steps": args.steps,
        "transitions": args.num_envs * args.steps,
        "elapsed_s": elapsed,
        "transitions_per_s": args.num_envs * args.steps / elapsed,
        "observation_shape": list(observation.shape),
        "observation_finite": bool(torch.isfinite(observation).all()),
        "isolated_reset": isolated_reset,
        "resets": resets,
        "hover_rpm": float(env.hover_rpm),
        "torch_version": torch.__version__,
        "torch_hip": torch.version.hip,
        "gpu_name": torch.cuda.get_device_name(0),
    }
    print(json.dumps(metrics, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

