#!/usr/bin/env python
"""Export trained actor network to TorchScript .pt for booster_deploy.

booster_deploy expects a torch.jit module that takes a plain observation tensor
and returns an action tensor. This script wraps the rsl-rl actor (which expects
a TensorDict) in a simple module that accepts plain tensors.

Usage:
    python scripts/export_policy.py -e t1_chase
    python scripts/export_policy.py -e t1_shoot -o models/t1_soccer.pt
"""
import argparse
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import torch

try:
    from safe_load import safe_jit_load
except ImportError:
    import sys as _sys
    _dir = os.path.dirname(os.path.abspath(__file__))
    for _ in range(5):
        _cand = os.path.join(_dir, "scripts")
        if os.path.isfile(os.path.join(_cand, "safe_load.py")):
            _sys.path.insert(0, _cand)
            break
        _dir = os.path.dirname(_dir)
    from safe_load import safe_jit_load
import torch.nn as nn
import yaml
from rsl_rl.runners import OnPolicyRunner

import genesis as gs


class PolicyWrapper(nn.Module):
    """Wraps rsl-rl actor to accept plain tensor input/output for deployment."""

    def __init__(self, actor, obs_key="policy"):
        super().__init__()
        self.actor = actor
        self.obs_key = obs_key

    def forward(self, obs: torch.Tensor) -> torch.Tensor:
        # rsl-rl expects TensorDict; we simulate it with a plain dict
        obs_dict = {self.obs_key: obs}
        return self.actor(obs_dict)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-e", "--exp_name", required=True)
    parser.add_argument("-o", "--output", default=None)
    parser.add_argument("--config", default="configs/soccer_agent.yaml")
    args = parser.parse_args()

    with open(args.config) as f:
        cfg = yaml.safe_load(f)

    train_cfg = cfg["train"]
    log_dir = f"runs/{args.exp_name}"

    model_files = sorted(glob.glob(f"{log_dir}/model_*.pt"), key=os.path.getmtime)
    if not model_files:
        raise FileNotFoundError(f"No model_*.pt found in {log_dir}")
    latest = model_files[-1]
    print(f"Loading checkpoint: {latest}")

    gs.init(backend=gs.gpu, precision="32", logging_level="warning", seed=42)

    from envs.soccer_env import SoccerEnv

    env_cfg = dict(cfg["env"])
    env_cfg["task"] = cfg.get("task", "chase")
    env = SoccerEnv(
        num_envs=1,
        env_cfg=env_cfg,
        obs_cfg=cfg["obs"],
        reward_cfg=cfg["reward"],
        command_cfg=cfg["command"],
        show_viewer=False,
    )
    runner = OnPolicyRunner(env, train_cfg, log_dir, device=gs.device)
    runner.load(latest)

    actor = runner.alg.actor
    actor.eval()

    # Wrap for plain-tensor deployment
    wrapper = PolicyWrapper(actor)
    wrapper.eval()

    out_path = args.output or f"models/{args.exp_name}_policy.pt"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    # Trace on the same device as the model, save directly
    example_obs = torch.zeros(1, env.obs_buf.shape[1], device=gs.device)
    with torch.no_grad():
        traced = torch.jit.trace(wrapper, example_obs)
    traced.save(out_path)
    print(f"Exported TorchScript policy: {out_path}")
    print(f"  obs_dim: {env.obs_buf.shape[1]}")
    print(f"  action_dim: {env.num_actions}")
    print(f"  history_length: {env.obs_history_length}")

    # Verify
    loaded = safe_jit_load(out_path, map_location="cpu", require_trusted=False)
    loaded.eval()
    test_obs = torch.zeros(1, env.obs_buf.shape[1])
    test_action = loaded(test_obs)
    print(f"  test inference: obs{test_obs.shape} -> action{test_action.shape}")
    print("Done. Use this .pt with booster_deploy.")


if __name__ == "__main__":
    main()
