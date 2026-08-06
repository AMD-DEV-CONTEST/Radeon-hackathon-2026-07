#!/usr/bin/env python
"""CPU smoke test for the RL machinery (no GPU, no Genesis).

Purpose: validate reward tensor math, policy forward/evaluate, GAE and the
PPO update loop *before* you get cloud GPU access. This catches shape bugs,
NaNs and logic errors in the parts that are pure code (not simulation).

Run on macOS CPU:
    python scripts/smoke_test_cpu.py

If torch isn't installed locally, it prints SKIP and exits 0.
"""
from __future__ import annotations

import os
import sys

try:
    import torch
except ImportError:
    print("SKIP: torch not installed locally (expected on macOS without ROCm).")
    print("      Run this on the AMD cloud instance, or `pip install torch` (CPU) to validate early.")
    sys.exit(0)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rewards.reward import compute_reward
from policies.ppo_runner import build_policy


class DummyEnv:
    """Stands in for SoccerEnv: same reset/step contract, random obs, fake reward inputs."""

    def __init__(self, num_obs: int, num_actions: int, num_envs: int = 64, max_steps: int = 50):
        self.num_obs = num_obs
        self.num_actions = num_actions
        self.num_envs = num_envs
        self.max_steps = max_steps
        self._step = 0

    def reset(self):
        self._step = 0
        return torch.randn(self.num_envs, self.num_obs)

    def step(self, action: torch.Tensor):
        self._step += 1
        obs = torch.randn(self.num_envs, self.num_obs)
        raw = {
            "torso_up": torch.rand(self.num_envs),
            "fallen": torch.zeros(self.num_envs, dtype=torch.bool),
            "dist_to_ball": torch.rand(self.num_envs),
            "prev_dist_to_ball": torch.rand(self.num_envs),
            "ball_vel_to_goal": torch.rand(self.num_envs),
            "scored": torch.zeros(self.num_envs, dtype=torch.bool),
            "just_recovered": torch.zeros(self.num_envs, dtype=torch.bool),
        }
        w = {
            "upright": 1.0, "alive": 0.1, "approach_ball": 2.0, "ball_control": 1.5,
            "ball_to_goal": 3.0, "goal_scored": 50.0, "fall_penalty": -5.0,
            "recovery_bonus": 2.0, "energy_penalty": -0.001, "_ball_radius": 0.11,
        }
        reward = compute_reward(raw, action, w, "shoot")
        done = torch.zeros(self.num_envs, dtype=torch.bool)
        return obs, reward, done, {}


def gae(rewards, values, dones, last_value, gamma, lam):
    adv = torch.zeros_like(rewards)
    gae_sum = torch.zeros_like(rewards[0])
    for t in reversed(range(rewards.shape[0])):
        nv = last_value if t == rewards.shape[0] - 1 else values[t + 1]
        nonterm = 1.0 - dones[t].float()
        delta = rewards[t] + gamma * nv * nonterm - values[t]
        gae_sum = delta + gamma * lam * nonterm * gae_sum
        adv[t] = gae_sum
    return adv, adv + values


def main():
    cfg = {
        "experiment": {"device": "cpu", "seed": 0},
        "ppo": {"discount": 0.99, "lambda": 0.95, "lr": 1.5e-4,
                "learning_epochs": 2, "mini_batches": 2, "value_loss_coef": 1.0,
                "entropy_coef": 0.005, "grad_norm_clip": 1.0, "hidden": [64, 32]},
    }
    torch.manual_seed(cfg["experiment"]["seed"])

    num_obs, num_actions, n = 32, 12, 64
    env = DummyEnv(num_obs, num_actions, num_envs=n)
    policy = build_policy(cfg, num_obs, num_actions)
    opt = torch.optim.Adam(policy.parameters(), lr=cfg["ppo"]["lr"])
    p = cfg["ppo"]

    obs = env.reset()
    # one short PPO iteration
    rollouts = 16
    obs_b = torch.zeros(rollouts, n, num_obs)
    act_b = torch.zeros(rollouts, n, num_actions)
    logp_b = torch.zeros(rollouts, n)
    val_b = torch.zeros(rollouts, n)
    rew_b = torch.zeros(rollouts, n)
    done_b = torch.zeros(rollouts, n)
    for t in range(rollouts):
        with torch.no_grad():
            a, lp, v = policy.act(obs)
        o2, r, d, _ = env.step(a)
        obs_b[t], act_b[t], logp_b[t], val_b[t], rew_b[t], done_b[t] = obs, a, lp, v, r, d.float()
        obs = o2

    with torch.no_grad():
        _, _, last_v = policy.act(obs)
    adv, ret = gae(rew_b, val_b, done_b, last_v, p["discount"], p["lambda"])
    adv = (adv - adv.mean()) / (adv.std() + 1e-8)

    b_obs = obs_b.reshape(-1, num_obs)
    b_act = act_b.reshape(-1, num_actions)
    b_logp = logp_b.reshape(-1)
    b_adv = adv.reshape(-1)
    b_ret = ret.reshape(-1)

    before = [x.clone() for x in policy.parameters()]
    mb = b_obs.shape[0] // p["mini_batches"]
    for _ in range(p["learning_epochs"]):
        for s in range(0, b_obs.shape[0], mb):
            j = slice(s, s + mb)
            new_logp, ent, val = policy.evaluate(b_obs[j], b_act[j])
            ratio = (new_logp - b_logp[j]).exp()
            surr1 = ratio * b_adv[j]
            surr2 = torch.clamp(ratio, 0.8, 1.2) * b_adv[j]
            loss = -torch.min(surr1, surr2).mean() + p["value_loss_coef"] * (b_ret[j] - val).pow(2).mean() - p["entropy_coef"] * ent.mean()
            opt.zero_grad(); loss.backward(); opt.step()

    # assertions
    assert torch.isfinite(loss).all(), "loss is NaN/Inf"
    changed = any(not torch.allclose(a, b) for a, b in zip(before, policy.parameters()))
    assert changed, "params did not update"
    assert rew_b.shape == (rollouts, n), "reward shape mismatch"
    print(f"PASS  loss={loss.item():.4f}  reward_mean={rew_b.mean():.3f}  params_updated={changed}")
    print("RL machinery (reward + policy + GAE + PPO) is logically sound on CPU.")


if __name__ == "__main__":
    main()
