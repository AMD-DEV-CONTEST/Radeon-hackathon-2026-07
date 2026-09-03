"""How much of the Radeon does a locomotion workload actually use?

Two numbers per environment count, because they answer different questions and
only one of them is the one people usually quote:

`sim` is physics stepping alone. It says how fast the GPU can advance the world.
`train` is a full PPO iteration, so it includes the rollout, the advantage
computation and the gradient steps. That is the number that decides how long a
policy takes to train, and it is always the lower of the two.

Reporting only `sim` would flatter the hardware. Both are written to JSON so the
report cannot quote a number that is not in the evidence.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import torch

from .config import TaskConfig
from .env import Go2LocomotionEnv


def _fresh(backend: str):
    import genesis as gs

    try:
        gs.destroy()
    except Exception:
        pass
    gs.init(backend=getattr(gs, backend), logging_level="warning")
    return gs


def sim_throughput(num_envs: int, steps: int = 200, backend: str = "amdgpu") -> dict:
    """Physics stepping only, with the policy replaced by a zero action."""
    gs = _fresh(backend)
    env = Go2LocomotionEnv(num_envs=num_envs)
    action = torch.zeros((num_envs, env.num_actions), device=env.device)

    for _ in range(20):
        env.step(action)
    torch.cuda.synchronize()
    torch.cuda.reset_peak_memory_stats()

    t0 = time.time()
    for _ in range(steps):
        env.step(action)
    torch.cuda.synchronize()
    dt = time.time() - t0

    return {
        "num_envs": num_envs,
        "steps": steps,
        "wall_seconds": round(dt, 3),
        "env_steps_per_second": round(num_envs * steps / dt, 1),
        "peak_torch_gb": round(torch.cuda.max_memory_allocated() / 2**30, 3),
    }


def train_throughput(num_envs: int, iterations: int = 10, backend: str = "amdgpu") -> dict:
    """A full PPO iteration, rollout plus update, which is what training costs."""
    from rsl_rl.runners import OnPolicyRunner

    from .train import train_config

    gs = _fresh(backend)
    env = Go2LocomotionEnv(num_envs=num_envs)
    cfg = train_config(iterations)
    runner = OnPolicyRunner(env, cfg, log_dir=None, device=str(env.device))

    torch.cuda.synchronize()
    torch.cuda.reset_peak_memory_stats()
    t0 = time.time()
    runner.learn(num_learning_iterations=iterations, init_at_random_ep_len=True)
    torch.cuda.synchronize()
    dt = time.time() - t0

    steps = num_envs * cfg["num_steps_per_env"] * iterations
    return {
        "num_envs": num_envs,
        "iterations": iterations,
        "num_steps_per_env": cfg["num_steps_per_env"],
        "wall_seconds": round(dt, 3),
        "seconds_per_iteration": round(dt / iterations, 3),
        "env_steps_per_second": round(steps / dt, 1),
        "peak_torch_gb": round(torch.cuda.max_memory_allocated() / 2**30, 3),
    }


def sweep(
    env_counts: tuple[int, ...] = (256, 512, 1024, 2048, 4096, 8192),
    out: str = "bench-results/scaling.json",
    backend: str = "amdgpu",
) -> dict:
    import genesis as gs

    rows = []
    for n in env_counts:
        sim = sim_throughput(n, backend=backend)
        train = train_throughput(n, backend=backend)
        rows.append({"num_envs": n, "sim": sim, "train": train})
        print(
            f"n_envs={n:<6} sim={sim['env_steps_per_second']:>12,.0f}/s  "
            f"train={train['env_steps_per_second']:>12,.0f}/s  "
            f"{train['seconds_per_iteration']:.2f}s/iter  peak={train['peak_torch_gb']:.2f}GB",
            flush=True,
        )

    result = {
        "device": torch.cuda.get_device_properties(0).gcnArchName,
        "vram_gb": round(torch.cuda.get_device_properties(0).total_memory / 2**30, 1),
        "torch": torch.__version__,
        "genesis": gs.__version__,
        "dt": TaskConfig().dt,
        "rows": rows,
    }
    p = Path(out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(result, indent=2) + "\n")
    print(f"wrote {p}")
    print("CHAAL_DONE")
    return result
