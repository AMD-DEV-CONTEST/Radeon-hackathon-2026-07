"""Train the humanoid-soccer policy on AMD Radeon (ROCm) via Genesis + rsl-rl.

Run on the cloud instance (after `gs.init` is available):
    python scripts/train.py --task chase
    python scripts/train.py --task shoot --num_envs 4096 --max_iterations 2000

Monitor:  tensorboard --logdir runs/<exp_name>
"""
import argparse
import os
import pickle
import shutil
import sys

# allow running `python scripts/train.py` from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yaml

import genesis as gs
from rsl_rl.runners import OnPolicyRunner

from envs.soccer_env import SoccerEnv


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", type=str, default=None, help="balance|chase|dribble|shoot|coop")
    parser.add_argument("-e", "--exp_name", type=str, default=None)
    parser.add_argument("-B", "--num_envs", type=int, default=None)
    parser.add_argument("--max_iterations", type=int, default=None)
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()

    with open("configs/soccer_agent.yaml") as f:
        cfg = yaml.safe_load(f)

    task = args.task or cfg.get("task", "chase")
    exp_name = args.exp_name or f"{cfg.get('exp_name', 'booster_soccer')}_{task}"
    num_envs = args.num_envs or cfg.get("num_envs", 2048)
    seed = args.seed or cfg.get("seed", 42)

    env_cfg = dict(cfg["env"])
    env_cfg["task"] = task
    obs_cfg = cfg["obs"]
    reward_cfg = cfg["reward"]
    command_cfg = cfg["command"]
    train_cfg = cfg["train"]
    train_cfg["run_name"] = exp_name
    if args.max_iterations:
        train_cfg["max_iterations"] = args.max_iterations

    log_dir = f"runs/{exp_name}"
    if os.path.exists(log_dir):
        shutil.rmtree(log_dir)
    os.makedirs(log_dir, exist_ok=True)
    with open(f"{log_dir}/cfgs.pkl", "wb") as f:
        pickle.dump([env_cfg, obs_cfg, reward_cfg, command_cfg, train_cfg], f)

    gs.init(backend=gs.gpu, precision="32", logging_level="warning", seed=seed)

    env = SoccerEnv(
        num_envs=num_envs,
        env_cfg=env_cfg,
        obs_cfg=obs_cfg,
        reward_cfg=reward_cfg,
        command_cfg=command_cfg,
        show_viewer=cfg.get("show_viewer", False),
    )

    runner = OnPolicyRunner(env, train_cfg, log_dir, device=gs.device)
    runner.learn(num_learning_iterations=train_cfg["max_iterations"], init_at_random_ep_len=True)


if __name__ == "__main__":
    main()
