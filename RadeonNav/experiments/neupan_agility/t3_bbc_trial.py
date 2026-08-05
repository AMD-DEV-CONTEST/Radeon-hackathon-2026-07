#!/usr/bin/env python3
"""T3-P0 probe 2: unfrozen-BBC PPO trial on the stairs-0.0625 wall.

Preregistered gates: within 800 iters, deterministic eval >=0.7 on stairs
0.0625 (the measured trunk-RL wall is ~0.5) AND flat retention >=0.9 with
the trained BBC. Policy = warm-started BBC (12-D Gaussian, std floor 0.1),
frozen TSC supplies commands; BC anchor to the frozen BBC mean.
"""

from __future__ import annotations

import argparse
import copy
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "experiments/cpp_adapter"))

from cpp_loco_sanity import _sha256  # noqa: E402
from run_bbc_sanity import _device, _write_json  # noqa: E402
from t2_env import RESULTS_ROOT as T2_ROOT  # noqa: E402
from t2_ppo import STAGES, TrainStack  # noqa: E402

RESULTS_ROOT = ROOT / "experiment-results/quadrupedal-agility/NAG-T3-P0"
GATE_TARGET = 0.7
GATE_FLAT = 0.9
STD_FLOOR = 0.1
BC_BETA = 1.0
del T2_ROOT


class Trial:
    def __init__(self, args):
        self.device = _device(args.device)
        torch.manual_seed(args.seed)
        np.random.seed(args.seed)
        self.stage = STAGES["S3f"]  # stairs 0.0625 (the wall)
        self.stack = TrainStack(self.stage, args.num_envs, self.device, args.seed)
        self.frozen_tsc = self.stack.adapter.high_model
        self.ref_bbc = self.stack.adapter.bbc.model  # frozen reference
        self.bbc = copy.deepcopy(self.ref_bbc).float().train()
        for name, p in self.bbc.named_parameters():
            p.requires_grad_(not name.startswith("critic"))
        warm_std = self.ref_bbc.std.detach().float().clamp(min=STD_FLOOR)
        self.log_std = torch.nn.Parameter(torch.log(warm_std.to(self.device)))
        self.actor_opt = torch.optim.Adam(
            [
                {"params": [p for p in self.bbc.parameters() if p.requires_grad],
                 "lr": args.actor_lr},
                {"params": [self.log_std], "lr": args.actor_lr},
            ]
        )
        self.critic = copy.deepcopy(self.ref_bbc).float()  # reuse critic path
        for name, p in self.critic.named_parameters():
            p.requires_grad_(name.startswith("critic"))
        self.critic_opt = torch.optim.Adam(
            [p for p in self.critic.parameters() if p.requires_grad], lr=1e-3
        )
        self._pending: dict = {}

    # -- BBC-level policy hooks ---------------------------------------
    def _mean(self, module, low_input):
        return module.act_inference(low_input, hist_encoding=True)

    def _value(self, low_input):
        trunk = self.critic.critic_trunk(low_input)
        return self.critic.critic_head(trunk).squeeze(-1)

    def sample_hook(self, low_input):
        with torch.no_grad():
            mean = self._mean(self.bbc, low_input)
            std = torch.exp(self.log_std)
            action = torch.distributions.Normal(mean, std).sample()
            logp = (
                torch.distributions.Normal(mean, std).log_prob(action).sum(-1)
            )
            value = self._value(low_input)
        self._pending = {
            "low_input": low_input.detach(),
            "action": action,
            "logp": logp,
            "value": value,
        }
        return action

    def det_hook(self, low_input):
        with torch.no_grad():
            return self._mean(self.bbc, low_input)

    # -- frozen TSC command per step ----------------------------------
    def tsc(self, obs):
        high_input = self.stack.high_input(obs)
        with torch.no_grad():
            emb = self.frozen_tsc(high_input, hist_encoding=True, scandots_latent=None)
            skill = torch.argmax(self.frozen_tsc.actor_d(emb), -1)
            cont = self.frozen_tsc.actor_c(emb)
        return skill, cont

    # -- rollout / update ----------------------------------------------
    def collect(self, T=48):
        N = self.stack.num_envs
        buf = {k: [] for k in ("low", "act", "logp", "rew", "done", "val")}
        stats = {"success": 0, "episodes": 0, "fell": 0}
        self.stack.bbc_forward = self.sample_hook
        for _ in range(T):
            obs = self.stack.observe()
            skill, cont = self.tsc(obs)
            reward, done, info = self.stack.step_train(obs, skill, cont)
            p = self._pending
            buf["low"].append(p["low_input"])
            buf["act"].append(p["action"])
            buf["logp"].append(p["logp"])
            buf["val"].append(p["value"])
            buf["rew"].append(torch.as_tensor(reward, device=self.device))
            buf["done"].append(
                torch.as_tensor(done.astype(np.float32), device=self.device)
            )
            stats["success"] += int(info["success"].sum())
            stats["fell"] += int(info["fell"].sum())
            stats["episodes"] += int(done.sum())
        obs = self.stack.observe()
        skill, cont = self.tsc(obs)
        self.stack.bbc_forward = None
        stacked = {k: torch.stack(v) for k, v in buf.items()}
        with torch.no_grad():
            # bootstrap with the last recorded value (approximation)
            last_value = stacked["val"][-1]
        adv = torch.zeros_like(stacked["rew"])
        gae = torch.zeros(N, device=self.device)
        for t in reversed(range(T)):
            next_value = last_value if t == T - 1 else stacked["val"][t + 1]
            mask = 1.0 - stacked["done"][t]
            delta = (
                stacked["rew"][t] + 0.99 * next_value * mask - stacked["val"][t]
            )
            gae = delta + 0.99 * 0.95 * mask * gae
            adv[t] = gae
        stacked["adv"] = adv
        stacked["ret"] = adv + stacked["val"]
        return stacked, stats

    def update(self, buf):
        T, N = buf["rew"].shape
        flat = {k: v.reshape(T * N, *v.shape[2:]) for k, v in buf.items()}
        adv = (flat["adv"] - flat["adv"].mean()) / (flat["adv"].std() + 1e-8)
        out = {"pi": 0.0, "v": 0.0, "bc": 0.0, "n": 0}
        idx = torch.randperm(T * N, device=self.device)
        for _ in range(4):
            for mb in idx.chunk(4):
                low = flat["low"][mb]
                value = self._value(low)
                v_loss = F.mse_loss(value, flat["ret"][mb])
                self.critic_opt.zero_grad()
                v_loss.backward()
                self.critic_opt.step()
                mean = self._mean(self.bbc, low)
                std = torch.exp(self.log_std)
                dist = torch.distributions.Normal(mean, std)
                logp = dist.log_prob(flat["act"][mb]).sum(-1)
                ratio = torch.exp(logp - flat["logp"][mb])
                surrogate = torch.min(
                    ratio * adv[mb], torch.clamp(ratio, 0.8, 1.2) * adv[mb]
                )
                with torch.no_grad():
                    ref_mean = self._mean(self.ref_bbc, low).float()
                bc = ((mean - ref_mean) ** 2 / (2 * std.detach() ** 2)).sum(-1).mean()
                loss = -surrogate.mean() + BC_BETA * bc
                self.actor_opt.zero_grad()
                loss.backward()
                torch.nn.utils.clip_grad_norm_(
                    [p for p in self.bbc.parameters() if p.requires_grad]
                    + [self.log_std],
                    1.0,
                )
                self.actor_opt.step()
                with torch.no_grad():
                    self.log_std.clamp_(min=np.log(STD_FLOOR))
                out["pi"] += float(loss)
                out["v"] += float(v_loss)
                out["bc"] += float(bc)
                out["n"] += 1
        for k in ("pi", "v", "bc"):
            out[k] /= max(out["n"], 1)
        return out

    def evaluate(self, stack=None, max_steps=None) -> float:
        stack = stack or self.stack
        max_steps = max_steps or self.stage.max_steps
        stack.bbc_forward = self.det_hook
        n = stack.num_envs
        stack.reset_indices(np.arange(n))
        outcome = np.full(n, -1, dtype=np.int64)
        steps = 0
        actor = stack.adapter.high_model
        while np.any(outcome < 0) and steps < max_steps + 50:
            obs = stack.observe()
            high_input = stack.high_input(obs)
            with torch.no_grad():
                emb = actor(high_input, hist_encoding=True, scandots_latent=None)
                skill = torch.argmax(actor.actor_d(emb), -1)
                cont = actor.actor_c(emb)
            _, done, info = stack.step_train(obs, skill, cont)
            newly = (outcome < 0) & done
            outcome[newly] = info["success"][newly].astype(np.int64)
            steps += 1
        stack.bbc_forward = None
        stack.reset_indices(np.arange(n))
        finished = outcome >= 0
        return float(outcome[finished].sum()) / max(int(finished.sum()), 1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--num-envs", type=int, default=64)
    parser.add_argument("--iters", type=int, default=800)
    parser.add_argument("--actor-lr", type=float, default=1e-4)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--device", default="auto")
    args = parser.parse_args()
    RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    trial = Trial(args)
    started = time.monotonic()
    best = {"success": -1.0, "state": None, "iter": 0}
    evals = []
    baseline = trial.evaluate()
    for it in range(1, args.iters + 1):
        buf, stats = trial.collect()
        update = trial.update(buf)
        if it % 10 == 0:
            success = trial.evaluate()
            evals.append({"iter": it, "eval_success": round(success, 4),
                          "bc": round(update["bc"], 4)})
            if success > best["success"]:
                best = {
                    "success": success,
                    "state": copy.deepcopy(trial.bbc.state_dict()),
                    "iter": it,
                }
            if success >= GATE_TARGET:
                break
    if best["state"] is not None:
        trial.bbc.load_state_dict(best["state"])
    flat_stack = TrainStack(STAGES["S0"], args.num_envs, trial.device, args.seed)
    flat = trial.evaluate(flat_stack, STAGES["S0"].max_steps)
    flat_stack.env.close()
    checks = {
        "target_gate_0p7": best["success"] >= GATE_TARGET,
        "beats_trunk_wall_0p5": best["success"] > 0.5,
        "flat_retention_0p9": flat >= GATE_FLAT,
    }
    payload = {
        "run_id": "NAG-T3-P0-BBC-TRIAL",
        "status": "PASSED" if checks["target_gate_0p7"] and checks["flat_retention_0p9"] else "FAILED",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "evaluation_type": "simulation_only",
        "scope": "T3-P0 probe 2: unfrozen-BBC PPO on stairs 0.0625",
        "seed": args.seed,
        "checks": checks,
        "metrics": {
            "baseline_success": baseline,
            "best_success": best["success"],
            "best_iter": best["iter"],
            "flat_retention": flat,
            "evals": evals,
            "wall_time_sec": time.monotonic() - started,
        },
        "contracts": {
            "std_floor": STD_FLOOR, "bc_beta": BC_BETA,
            "gate_target": GATE_TARGET, "gate_flat": GATE_FLAT,
            "runner_sha256": _sha256(Path(__file__)),
        },
    }
    if best["state"] is not None:
        torch.save(best["state"], RESULTS_ROOT / "t3_bbc_trial_best.pt")
    path = RESULTS_ROOT / f"bbc_trial_{stamp}.json"
    _write_json(path, payload)
    shutil.copy2(path, RESULTS_ROOT / "bbc_trial.json")
    print(f"{payload['status']}: {path}")
    print("baseline", baseline, "| best", best["success"], "| flat", flat)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
