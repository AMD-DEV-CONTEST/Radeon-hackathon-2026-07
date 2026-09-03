"""PPO training, with the simulator and the policy update on the same GPU.

There is no CPU in the inner loop. Genesis steps `num_envs` robots on the
Radeon, the observations are already device tensors, and rsl_rl's PPO reads them
without a transfer. The only thing that crosses back to the host is the log
line at the end of an iteration.

The config below is the standard PPO setup for velocity-tracking locomotion.
The values that matter for this project are `num_envs` and `num_steps_per_env`,
because their product is the batch of experience each iteration collects, and
that is the knob `chaal bench` sweeps against GPU throughput.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import torch

from .config import RobotConfig, RunConfig, TaskConfig
from .env import Go2LocomotionEnv


def train_config(max_iterations: int, experiment: str = "chaal-go2") -> dict:
    return {
        "num_steps_per_env": 24,
        "save_interval": 100,
        "experiment_name": experiment,
        "obs_groups": {"actor": ["policy"], "critic": ["policy"]},
        "algorithm": {
            "class_name": "PPO",
            "num_learning_epochs": 5,
            "num_mini_batches": 4,
            "clip_param": 0.2,
            "gamma": 0.99,
            "lam": 0.95,
            "value_loss_coef": 1.0,
            "entropy_coef": 0.01,
            "learning_rate": 1e-3,
            "max_grad_norm": 1.0,
            "use_clipped_value_loss": True,
            "schedule": "adaptive",
            "desired_kl": 0.01,
        },
        "actor": {
            "class_name": "MLPModel",
            "hidden_dims": [512, 256, 128],
            "activation": "elu",
            "obs_normalization": True,
            # Without this the actor is deterministic, PPO has no log-prob to
            # differentiate, and training dies on the first update. Only the
            # actor gets one: the critic outputs a value, not a distribution.
            "distribution_cfg": {"class_name": "GaussianDistribution", "init_std": 1.0},
        },
        "critic": {
            "class_name": "MLPModel",
            "hidden_dims": [512, 256, 128],
            "activation": "elu",
            "obs_normalization": True,
        },
        "max_iterations": max_iterations,
    }


def run(
    num_envs: int = 4096,
    max_iterations: int = 300,
    seed: int = 1,
    log_dir: str = "runs/go2",
    backend: str = "amdgpu",
) -> dict:
    import genesis as gs
    from rsl_rl.runners import OnPolicyRunner

    gs.init(backend=getattr(gs, backend), logging_level="warning", seed=seed)

    out = Path(log_dir)
    out.mkdir(parents=True, exist_ok=True)

    env = Go2LocomotionEnv(num_envs=num_envs, robot_cfg=RobotConfig(), task_cfg=TaskConfig())
    cfg = train_config(max_iterations)
    runner = OnPolicyRunner(env, cfg, log_dir=str(out), device=str(env.device))

    steps_per_iter = num_envs * cfg["num_steps_per_env"]
    torch.cuda.synchronize()
    t0 = time.time()
    runner.learn(num_learning_iterations=max_iterations, init_at_random_ep_len=True)
    torch.cuda.synchronize()
    wall = time.time() - t0

    total_steps = steps_per_iter * max_iterations
    summary = {
        "num_envs": num_envs,
        "iterations": max_iterations,
        "steps_per_iter": steps_per_iter,
        "total_env_steps": total_steps,
        "wall_seconds": round(wall, 2),
        "env_steps_per_second": round(total_steps / wall, 1),
        "seconds_per_iteration": round(wall / max_iterations, 3),
        "mean_episode_return": round(env.mean_episode_return, 3),
        "device": torch.cuda.get_device_properties(0).gcnArchName,
        "torch": torch.__version__,
        "genesis": gs.__version__,
        "seed": seed,
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    print("CHAAL_DONE")
    return summary
