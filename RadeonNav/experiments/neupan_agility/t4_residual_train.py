#!/usr/bin/env python3
"""NAG-902: gated-residual blind terrain policy over the frozen BBC.

a = a_frozen(obs) + g * delta(obs); g=1 on terrain/free segments, g=0 in
jump-class intervals (same scheduling layer as CM / scheduled history).
The frozen BBC checkpoint is untouched, so every existing skill-domain
validation remains literally valid; the residual starts at zero (bitwise
frozen behaviour) and is bounded (0.5*tanh).

Asymmetric actor-critic: the residual actor stays blind (669-D real-
history obs); the critic additionally sees the 132-point analytic terrain
scan (training-only privilege, never deployed).
"""

from __future__ import annotations

import argparse
import copy
import json as _json
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "experiments/cpp_adapter"))

from cpp_loco_sanity import _sha256  # noqa: E402
from run_bbc_sanity import _device, _write_json  # noqa: E402
from t2_ppo import STAGES  # noqa: E402
from t3_bbc_train import (  # noqa: E402
    CHUNK,
    GAMMA,
    LAM,
    HistStack,
    sample_trot_command,
)

RESULTS_ROOT = ROOT / "experiment-results/quadrupedal-agility/NAG-902"
DELTA_SCALE = 0.5
STD_FLOOR = 0.04
RUNGS = {
    "r005": "S3e",
    "r0625": "S3f",
    "r0075": "S3a",
    "r00875": "S3g",
    "r010": "S3b",
}


class ResidualPolicy(nn.Module):
    def __init__(self, obs_dim: int = 669, act_dim: int = 12, scan_dim: int = 0):
        super().__init__()
        self.scan_dim = scan_dim
        obs_dim = obs_dim + scan_dim
        self.net = nn.Sequential(
            nn.Linear(obs_dim, 256), nn.ELU(),
            nn.Linear(256, 128), nn.ELU(),
        )
        self.head = nn.Linear(128, act_dim)
        nn.init.zeros_(self.head.weight)
        nn.init.zeros_(self.head.bias)

    def forward(self, low: torch.Tensor, scan: torch.Tensor | None = None) -> torch.Tensor:
        x = low if self.scan_dim == 0 else torch.cat((low, scan), dim=1)
        return DELTA_SCALE * torch.tanh(self.head(self.net(x)))


class PrivilegedCritic(nn.Module):
    def __init__(self, obs_dim: int = 669 + 132):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(obs_dim, 512), nn.ELU(),
            nn.Linear(512, 256), nn.ELU(),
            nn.Linear(256, 1),
        )

    def forward(self, low: torch.Tensor, scan: torch.Tensor) -> torch.Tensor:
        return self.net(torch.cat((low, scan), dim=1)).squeeze(-1)


class ResidualTrainer:
    def __init__(self, args):
        self.device = _device(args.device)
        torch.manual_seed(args.seed)
        np.random.seed(args.seed)
        self.rng = np.random.default_rng(args.seed)
        self.args = args
        self.stacks = {
            r: HistStack(STAGES[RUNGS[r]], args.num_envs, self.device, args.seed)
            for r in args.rungs
        }
        self.flat = HistStack(STAGES["S0"], args.num_envs, self.device, args.seed)
        any_stack = next(iter(self.stacks.values()))
        self.frozen = any_stack.adapter.bbc.model  # untouched, eval mode
        scan_dim = 132 if args.perceptive else 0
        self.delta = ResidualPolicy(scan_dim=scan_dim).to(self.device)
        if args.init_delta is not None:
            self.delta.load_state_dict(
                torch.load(args.init_delta, map_location=self.device, weights_only=True)
            )
        self.log_std = nn.Parameter(
            torch.log(torch.full((12,), 0.06, device=self.device))
        )
        self.actor_opt = torch.optim.Adam(
            [
                {"params": self.delta.parameters(), "lr": args.actor_lr},
                {"params": [self.log_std], "lr": args.actor_lr},
            ]
        )
        self.critic = PrivilegedCritic().to(self.device)
        self.critic_opt = torch.optim.Adam(self.critic.parameters(), lr=1e-3)
        weights = [int(w) for w in args.rung_weights.split(",")] if args.rung_weights else [1] * len(args.rungs)
        weights += [1] * (len(args.rungs) - len(weights))
        cycle = []
        for i, r in enumerate(args.rungs):
            cycle.extend([r] * max(weights[i], 1))
        cycle.append("flat")
        self.cycle = cycle
        self.best = {"score": -1e9, "state": None}
        self.history: list[dict] = []
        # cold-start artifact: burn one eval
        self.evaluate(args.rungs[0])

    def frozen_mean(self, low):
        with torch.no_grad():
            return self.frozen.act_inference(low, hist_encoding=True)

    def rollout(self, key: str):
        stack = self.flat if key == "flat" else self.stacks[key]
        buf = {k: [] for k in ("low", "scan", "act", "logp", "rew", "done", "val")}
        stats = {"success": 0, "episodes": 0, "fell": 0}
        std = torch.exp(self.log_std)
        for _ in range(CHUNK):
            obs = stack.observe()
            command = sample_trot_command(stack, obs, self.rng)
            low = stack.low_input_with_history(obs, command)
            scan = torch.as_tensor(
                obs["scan"], device=self.device, dtype=torch.float32
            )
            with torch.no_grad():
                base = self.frozen_mean(low)
                delta_mean = self.delta(low, scan)
                dist = torch.distributions.Normal(delta_mean, std)
                delta = dist.sample()
                logp = dist.log_prob(delta).sum(-1)
                val = self.critic(low, scan)
                action = base + delta
            stack.roll_history(obs)
            source = action.cpu().numpy().astype(np.float32)
            prev = stack.prev_source_action.copy()
            stack.env_step_with_source_action(source)
            stack.prev_source_action = source
            stack.episode_steps += 1
            base_pos = stack.backend.get_base_pos().copy().astype(np.float64)
            quat = stack.backend.get_base_quat().copy().astype(np.float64)
            vel = stack.env.get_local_linvel().copy()
            w, xq, yq, zq = quat.T
            roll = np.arctan2(2 * (w * xq + yq * zq), 1 - 2 * (xq**2 + yq**2))
            fell = (base_pos[:, 2] < 0.18) | (np.abs(roll) > 1.0)
            prev_prog = stack.progress.copy()
            stack.progress = (base_pos[:, :2] - stack.start_xy) @ stack.axis
            success = (
                np.linalg.norm(base_pos[:, :2] - stack.goal_xy, axis=1) < 0.4
            )
            timeout = stack.episode_steps >= stack.cfg.max_steps
            cmd_vx = command[:, 0].cpu().numpy()
            track = np.exp(-np.square(cmd_vx - vel[:, 0]) / 0.25)
            action_rate = np.sum((source - prev) ** 2, axis=1)
            reward = (
                1.0 * track
                + 2.0 * (stack.progress - prev_prog)
                + 0.01
                - 0.005 * action_rate
                - 0.02 * np.sum(delta.cpu().numpy() ** 2, axis=1)
                - 2.0 * fell.astype(np.float64)
                + 5.0 * success.astype(np.float64)
            )
            done = fell | success | timeout
            buf["low"].append(low)
            buf["scan"].append(scan)
            buf["act"].append(delta)
            buf["logp"].append(logp)
            buf["val"].append(val)
            buf["rew"].append(
                torch.as_tensor(reward, device=self.device, dtype=torch.float32)
            )
            buf["done"].append(
                torch.as_tensor(done.astype(np.float32), device=self.device)
            )
            stats["success"] += int(success.sum())
            stats["fell"] += int(fell.sum())
            stats["episodes"] += int(done.sum())
            if np.any(done):
                stack.reset_indices(np.nonzero(done)[0])
        stacked = {k: torch.stack(v) for k, v in buf.items()}
        T = stacked["rew"].shape[0]
        adv = torch.zeros_like(stacked["rew"])
        gae = torch.zeros_like(stacked["val"][0])
        for t in reversed(range(T)):
            nxt = stacked["val"][t + 1] if t < T - 1 else stacked["val"][t]
            mask = 1.0 - stacked["done"][t]
            delta_t = stacked["rew"][t] + GAMMA * nxt * mask - stacked["val"][t]
            gae = delta_t + GAMMA * LAM * mask * gae
            adv[t] = gae
        stacked["adv"] = adv
        stacked["ret"] = adv + stacked["val"]
        return stacked, stats

    def update(self, buf, critic_only=False):
        T, N = buf["rew"].shape
        flat = {k: v.reshape(T * N, *v.shape[2:]) for k, v in buf.items()}
        adv = (flat["adv"] - flat["adv"].mean()) / (flat["adv"].std() + 1e-8)
        idx = torch.randperm(T * N, device=self.device)
        out = {"pi": 0.0, "v": 0.0, "n": 0}
        for _ in range(4):
            for mb in idx.chunk(4):
                low, scan = flat["low"][mb], flat["scan"][mb]
                v_loss = F.mse_loss(self.critic(low, scan), flat["ret"][mb])
                self.critic_opt.zero_grad()
                v_loss.backward()
                self.critic_opt.step()
                out["v"] += float(v_loss)
                if critic_only:
                    out["n"] += 1
                    continue
                mean = self.delta(low, flat["scan"][mb])
                std = torch.exp(self.log_std)
                dist = torch.distributions.Normal(mean, std)
                logp = dist.log_prob(flat["act"][mb]).sum(-1)
                ratio = torch.exp(logp - flat["logp"][mb])
                surr = torch.min(
                    ratio * adv[mb], torch.clamp(ratio, 0.8, 1.2) * adv[mb]
                )
                loss = -surr.mean()
                self.actor_opt.zero_grad()
                loss.backward()
                nn.utils.clip_grad_norm_(
                    list(self.delta.parameters()) + [self.log_std], 1.0
                )
                self.actor_opt.step()
                with torch.no_grad():
                    self.log_std.clamp_(min=np.log(STD_FLOOR))
                out["pi"] += float(loss)
                out["n"] += 1
        for k in ("pi", "v"):
            out[k] /= max(out["n"], 1)
        return out

    def evaluate(self, key: str) -> float:
        """Deployment-shaped eval: frozen TSC commands + frozen BBC +
        residual (g=1 on these terrain stacks)."""
        stack = self.flat if key == "flat" else self.stacks[key]
        actor = stack.adapter.high_model

        def hook(low):
            scan = (
                torch.as_tensor(
                    stack._eval_obs_scan, device=self.device, dtype=torch.float32
                )
                if self.delta.scan_dim
                else None
            )
            return self.frozen_mean(low) + self.delta(low, scan)

        stack.bbc_forward = lambda low: hook(low)
        n = stack.num_envs
        stack.reset_indices(np.arange(n))
        outcome = np.full(n, -1, dtype=np.int64)
        steps = 0
        while np.any(outcome < 0) and steps < stack.cfg.max_steps + 50:
            obs = stack.observe()
            stack._eval_obs_scan = obs["scan"]
            high_input = stack.high_input(obs)
            with torch.no_grad():
                emb = actor(high_input, hist_encoding=True, scandots_latent=None)
                skill = torch.argmax(actor.actor_d(emb), -1)
                cont = actor.actor_c(emb)
            stack.roll_history(obs)
            _, done, info = stack.step_train(obs, skill, cont)
            newly = (outcome < 0) & done
            outcome[newly] = info["success"][newly].astype(np.int64)
            steps += 1
        stack.bbc_forward = None
        stack.reset_indices(np.arange(n))
        finished = outcome >= 0
        return float(outcome[finished].sum()) / max(int(finished.sum()), 1)

    def train(self, out_dir: Path, iters: int) -> dict:
        started = time.monotonic()
        status = "BUDGET_EXHAUSTED"
        for it in range(1, iters + 1):
            key = self.cycle[(it - 1) % len(self.cycle)]
            buf, stats = self.rollout(key)
            update = self.update(buf, critic_only=it <= 15)
            row = {"iter": it, "key": key, "pi": round(update["pi"], 4),
                   "v": round(update["v"], 4), **stats}
            if it % 20 == 0:
                evals = {r: self.evaluate(r) for r in self.stacks}
                flat_ok = self.evaluate("flat")
                row["evals"] = evals
                row["flat"] = flat_ok
                score = min(evals.values()) + 0.1 * sum(evals.values())
                if flat_ok >= 0.9 and score > self.best["score"]:
                    self.best = {
                        "score": score,
                        "state": copy.deepcopy(self.delta.state_dict()),
                        "iter": it,
                        "evals": evals,
                        "flat": flat_ok,
                    }
                    torch.save(self.best["state"], out_dir / "nag902_delta_best.pt")
                with (out_dir / "progress.jsonl").open("a") as fh:
                    fh.write(_json.dumps(row) + "\n")
                if flat_ok >= 0.9 and all(
                    v >= self.args.rung_gate for v in evals.values()
                ):
                    status = "PASSED"
                    self.history.append(row)
                    break
            self.history.append(row)
        state = self.best["state"] or self.delta.state_dict()
        torch.save(state, out_dir / "nag902_delta.pt")
        return {
            "status": status,
            "iters_run": len(self.history),
            "best": {k: v for k, v in self.best.items() if k != "state"},
            "wall_time_sec": time.monotonic() - started,
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rungs", nargs="+", default=["r005", "r0625", "r0075"])
    parser.add_argument("--rung-weights", default="")
    parser.add_argument("--rung-gate", type=float, default=0.6)
    parser.add_argument("--num-envs", type=int, default=64)
    parser.add_argument("--iters", type=int, default=2000)
    parser.add_argument("--actor-lr", type=float, default=3e-4)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--init-delta", type=Path, default=None)
    parser.add_argument("--perceptive", action="store_true")
    parser.add_argument("--tag", default="p0")
    args = parser.parse_args()
    out = RESULTS_ROOT / args.tag
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    trainer = ResidualTrainer(args)
    summary = trainer.train(out, args.iters)
    payload = {
        "run_id": f"NAG-902-{args.tag}",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "evaluation_type": "simulation_only",
        "scope": "NAG-902 gated-residual blind terrain policy (frozen BBC base)",
        "seed": args.seed,
        "rungs": args.rungs,
        "delta_scale": DELTA_SCALE,
        "asymmetric_critic": "669 + 132 privileged analytic scan",
        "perceptive_actor": bool(args.perceptive),
        "no_interference": "jump segments gate g=0 -> bitwise frozen stack",
        "contracts": {"runner_sha256": _sha256(Path(__file__))},
        **summary,
    }
    path = out / f"result_{stamp}.json"
    _write_json(path, payload)
    shutil.copy2(path, out / "result.json")
    print(f"{payload['status']}: {path}")
    print("best:", summary["best"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
