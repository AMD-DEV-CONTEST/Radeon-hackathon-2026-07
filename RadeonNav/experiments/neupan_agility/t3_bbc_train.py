#!/usr/bin/env python3
"""NAG-901: BBC retrain for stairs (riser 0.05-0.20) with skill retention.

Single loco policy: the BBC actor is unfrozen (warm-start) and trained
with two interleaved episode types:
  terrain: stairs rungs, commands SAMPLED in trot-mode ranges (source
           BBC recipe), reward = velocity tracking + alive - fall;
  retain:  flat/tire via frozen TSC commands, stage rewards, BC anchor
           to the frozen BBC, floors + rollback (T2 machinery).
History contract: REAL rolling 570-D history in both training and eval
(deviation from the zero-history deployment convention, preregistered;
final acceptance re-runs the full frozen suite under the new contract).
BBC consumes no scan/depth latent, so the retrained policy slots into
the deployed student chain without the T2 perception-transfer break.
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
from t2_env import _yaw_from_quat  # noqa: E402
from t2_ppo import STAGES, TrainStack  # noqa: E402
from unilab.algos.torch.quadrupedal_agility import (  # noqa: E402
    agility_action_to_unilab,
)

RESULTS_ROOT = ROOT / "experiment-results/quadrupedal-agility/NAG-901"
STD_FLOOR = 0.1
BC_BETA = 1.0
GAMMA, LAM = 0.99, 0.95
CHUNK = 48
TROT_ONEHOT = (1.0, 0.0, 0.0)
LOCO_H_RANGE = (0.25, 0.34)  # column 4 = locomotion height (measured from TSC)
VX_RANGE = (0.5, 1.5)
WZ_GAIN_Y, WZ_GAIN_YAW = 1.0, 1.5

# terrain rung name -> (stage key for env geometry, riser for logging)
TERRAIN_RUNGS = {
    "r005": ("S3e", 0.05),
    "r0625": ("S3f", 0.0625),
    "r0075": ("S3a", 0.075),
    "r00875": ("S3g", 0.0875),
    "r010": ("S3b", 0.10),
}
RETAIN = (("S0", 0.90), ("S1a", 0.25))


class HistStack(TrainStack):
    """TrainStack with a real rolling BBC history (NAG-901 contract)."""

    def reset_indices(self, indices: np.ndarray) -> None:
        super().reset_indices(indices)
        if not hasattr(self, "bbc_history"):
            self.bbc_history = np.zeros((self.num_envs, 570), dtype=np.float32)
        self.bbc_history[indices] = 0.0
        # Commands are held constant per episode (legged-gym recipe); only
        # the heading-hold wz term stays live. Per-step resampling never
        # lets the gait lock onto a speed (phase-1 v2/v3 plateau).
        if not hasattr(self, "held_command"):
            self.held_command = np.zeros((self.num_envs, 9), dtype=np.float32)
            self.held_command[:, 6:9] = TROT_ONEHOT
        n = len(indices)
        self.held_command[indices, 0] = self.rng.uniform(*VX_RANGE, size=n)
        self.held_command[indices, 4] = self.rng.uniform(*LOCO_H_RANGE, size=n)
        self.held_command[indices, 5] = self.rng.uniform(-1.0, 1.0, size=n)

    def low_input_with_history(self, obs, command: torch.Tensor) -> torch.Tensor:
        t = lambda a: torch.as_tensor(a, device=self.device, dtype=torch.float32)
        proprio = t(obs["proprio"])
        with torch.no_grad():
            explicit = self.adapter.bbc.estimator(proprio)
        low = torch.cat(
            (
                proprio,
                explicit,
                torch.zeros((self.num_envs, 29), device=self.device),
                t(self.bbc_history),
                command,
            ),
            dim=1,
        )
        return low

    def roll_history(self, obs) -> None:
        self.bbc_history[:, :-57] = self.bbc_history[:, 57:]
        self.bbc_history[:, -57:] = obs["proprio"]

    def env_step_with_source_action(self, source_action: np.ndarray) -> None:
        self.previous_action = source_action
        self.state = self.env.step(
            agility_action_to_unilab(source_action, self.contract)
        )


def sample_trot_command(stack: HistStack, obs, rng) -> torch.Tensor:
    """Trot-mode command with a heading-hold steering term (training data
    distribution only; matches the source command layout [5,eps,onehot])."""
    base = stack.backend.get_base_pos().copy()
    yaw = _yaw_from_quat(stack.backend.get_base_quat().copy().astype(np.float64))
    cmd = stack.held_command.copy()
    cmd[:, 2] = np.clip(
        -WZ_GAIN_Y * base[:, 1] - WZ_GAIN_YAW * yaw, -1.2, 1.2
    ).astype(np.float32)
    return torch.as_tensor(cmd, device=stack.device)


class BbcTrainer:
    def __init__(self, args):
        self.device = _device(args.device)
        torch.manual_seed(args.seed)
        np.random.seed(args.seed)
        self.rng = np.random.default_rng(args.seed)
        self.args = args
        rungs = [r for r in args.rungs if r in TERRAIN_RUNGS]
        self.terrain = {
            r: HistStack(STAGES[TERRAIN_RUNGS[r][0]], args.num_envs, self.device, args.seed)
            for r in rungs
        }
        self.retain = {
            name: (floor, HistStack(STAGES[name], args.num_envs, self.device, args.seed))
            for name, floor in RETAIN
        }
        any_stack = next(iter(self.terrain.values()))
        self.ref_bbc = any_stack.adapter.bbc.model
        self.bbc = copy.deepcopy(self.ref_bbc).float().train()
        if args.init_bbc is not None:
            self.bbc.load_state_dict(
                torch.load(args.init_bbc, map_location=self.device, weights_only=True)
            )
        for name, p in self.bbc.named_parameters():
            p.requires_grad_(not name.startswith("critic"))
        warm = self.ref_bbc.std.detach().float().clamp(min=STD_FLOOR)
        self.log_std = torch.nn.Parameter(torch.log(warm.to(self.device)))
        self.actor_opt = torch.optim.Adam(
            [
                {"params": [p for p in self.bbc.parameters() if p.requires_grad],
                 "lr": args.actor_lr},
                {"params": [self.log_std], "lr": args.actor_lr},
            ]
        )
        self.critic = copy.deepcopy(self.ref_bbc).float()
        for name, p in self.critic.named_parameters():
            p.requires_grad_(name.startswith("critic"))
        self.critic_opt = torch.optim.Adam(
            [p for p in self.critic.parameters() if p.requires_grad], lr=1e-3
        )
        # episode cycle: difficulty-weighted terrain slots, retains woven in
        weights = (
            [int(w) for w in args.rung_weights.split(",")]
            if getattr(args, "rung_weights", "")
            else [1] * len(rungs)
        )
        weights += [1] * (len(rungs) - len(weights))
        cycle = []
        retains = list(self.retain.items())
        slot = 0
        for i, r in enumerate(rungs):
            for _ in range(max(weights[i], 1)):
                cycle.append(("terrain", r))
                name, (floor, stack) = retains[slot % len(retains)]
                cycle.append(("retain", name))
                slot += 1
        self.cycle = cycle
        self.history: list[dict] = []
        self.best = {"score": -1e9, "state": None}
        # First evaluate() after construction is invalid (cold-start artifact,
        # bisect3 2026-08-01); burn one throwaway eval so all real reads are warm.
        self.evaluate("tsc", rungs[0])

    # -- shared policy utils -------------------------------------------
    def mean_action(self, module, low):
        return module.act_inference(low, hist_encoding=True)

    def value(self, low):
        return self.critic.critic_head(self.critic.critic_trunk(low)).squeeze(-1)

    # -- rollouts --------------------------------------------------------
    def rollout_terrain(self, stack: HistStack):
        buf = {k: [] for k in ("low", "act", "logp", "rew", "done", "val")}
        stats = {"success": 0, "episodes": 0, "fell": 0}
        std = torch.exp(self.log_std)
        for _ in range(CHUNK):
            obs = stack.observe()
            command = sample_trot_command(stack, obs, self.rng)
            low = stack.low_input_with_history(obs, command)
            with torch.no_grad():
                mean = self.mean_action(self.bbc, low)
                action = torch.distributions.Normal(mean, std).sample()
                logp = torch.distributions.Normal(mean, std).log_prob(action).sum(-1)
                val = self.value(low)
            stack.roll_history(obs)
            source = action.cpu().numpy().astype(np.float32)
            prev = stack.prev_source_action.copy()
            stack.env_step_with_source_action(source)
            stack.prev_source_action = source
            stack.episode_steps += 1
            base = stack.backend.get_base_pos().copy().astype(np.float64)
            quat = stack.backend.get_base_quat().copy().astype(np.float64)
            vel = stack.env.get_local_linvel().copy()
            w, xq, yq, zq = quat.T
            roll = np.arctan2(2 * (w * xq + yq * zq), 1 - 2 * (xq**2 + yq**2))
            fell = (base[:, 2] < 0.18) | (np.abs(roll) > 1.0)
            prev_prog = stack.progress.copy()
            stack.progress = (base[:, :2] - stack.start_xy) @ stack.axis
            success = (
                np.linalg.norm(base[:, :2] - stack.goal_xy, axis=1) < 0.4
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
                - 2.0 * fell.astype(np.float64)
                + 5.0 * success.astype(np.float64)
            )
            done = fell | success | timeout
            buf["low"].append(low)
            buf["act"].append(action)
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
        return self._finish(buf), stats

    def rollout_retain(self, stack: HistStack):
        buf = {k: [] for k in ("low", "act", "logp", "rew", "done", "val")}
        stats = {"success": 0, "episodes": 0, "fell": 0}
        std = torch.exp(self.log_std)
        actor = stack.adapter.high_model
        pending = {}

        def hook(low):
            with torch.no_grad():
                mean = self.mean_action(self.bbc, low)
                action = torch.distributions.Normal(mean, std).sample()
                pending["low"] = low.detach()
                pending["act"] = action
                pending["logp"] = (
                    torch.distributions.Normal(mean, std).log_prob(action).sum(-1)
                )
                pending["val"] = self.value(low)
            return action

        stack.bbc_forward = hook
        for _ in range(CHUNK):
            obs = stack.observe()
            high_input = stack.high_input(obs)
            with torch.no_grad():
                emb = actor(high_input, hist_encoding=True, scandots_latent=None)
                skill = torch.argmax(actor.actor_d(emb), -1)
                cont = actor.actor_c(emb)
            stack.roll_history(obs)
            reward, done, info = stack.step_train(obs, skill, cont)
            for k_from, k_to in (("low", "low"), ("act", "act"), ("logp", "logp"), ("val", "val")):
                buf[k_to].append(pending[k_from])
            buf["rew"].append(
                torch.as_tensor(reward, device=self.device, dtype=torch.float32)
            )
            buf["done"].append(
                torch.as_tensor(done.astype(np.float32), device=self.device)
            )
            stats["success"] += int(info["success"].sum())
            stats["fell"] += int(info["fell"].sum())
            stats["episodes"] += int(done.sum())
        stack.bbc_forward = None
        return self._finish(buf), stats

    def _finish(self, buf):
        stacked = {k: torch.stack(v) for k, v in buf.items()}
        T = stacked["rew"].shape[0]
        adv = torch.zeros_like(stacked["rew"])
        gae = torch.zeros_like(stacked["val"][0])
        for t in reversed(range(T)):
            nxt = stacked["val"][t + 1] if t < T - 1 else stacked["val"][t]
            mask = 1.0 - stacked["done"][t]
            delta = stacked["rew"][t] + GAMMA * nxt * mask - stacked["val"][t]
            gae = delta + GAMMA * LAM * mask * gae
            adv[t] = gae
        stacked["adv"] = adv
        stacked["ret"] = adv + stacked["val"]
        return stacked

    def update(self, buf, anchor_beta: float, critic_only: bool = False):
        T, N = buf["rew"].shape
        flat = {k: v.reshape(T * N, *v.shape[2:]) for k, v in buf.items()}
        adv = (flat["adv"] - flat["adv"].mean()) / (flat["adv"].std() + 1e-8)
        idx = torch.randperm(T * N, device=self.device)
        out = {"pi": 0.0, "bc": 0.0, "n": 0}
        for _ in range(4):
            for mb in idx.chunk(4):
                low = flat["low"][mb]
                v_loss = F.mse_loss(self.value(low), flat["ret"][mb])
                self.critic_opt.zero_grad()
                v_loss.backward()
                self.critic_opt.step()
                mean = self.mean_action(self.bbc, low)
                std = torch.exp(self.log_std)
                dist = torch.distributions.Normal(mean, std)
                logp = dist.log_prob(flat["act"][mb]).sum(-1)
                ratio = torch.exp(logp - flat["logp"][mb])
                surr = torch.min(
                    ratio * adv[mb], torch.clamp(ratio, 0.8, 1.2) * adv[mb]
                )
                loss = -surr.mean()
                bc = torch.zeros((), device=self.device)
                if anchor_beta > 0:
                    with torch.no_grad():
                        ref = self.mean_action(self.ref_bbc, low).float()
                    bc = ((mean - ref) ** 2 / (2 * std.detach() ** 2)).sum(-1).mean()
                    loss = loss + anchor_beta * bc
                if critic_only:
                    out["bc"] += float(bc)
                    out["n"] += 1
                    continue
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
                out["bc"] += float(bc)
                out["n"] += 1
        for k in ("pi", "bc"):
            out[k] /= max(out["n"], 1)
        return out

    # -- evaluation ------------------------------------------------------
    def evaluate(
        self,
        kind: str,
        key: str,
        cmd_overrides: dict | None = None,
        module=None,
    ) -> float:
        policy = module if module is not None else self.bbc
        stack = (
            self.terrain[key] if key in self.terrain else self.retain[key][1]
        )
        n = stack.num_envs
        stack.reset_indices(np.arange(n))
        outcome = np.full(n, -1, dtype=np.int64)
        steps = 0
        actor = stack.adapter.high_model
        stack.bbc_forward = lambda low: self.mean_action(policy, low)
        while np.any(outcome < 0) and steps < stack.cfg.max_steps + 50:
            obs = stack.observe()
            if kind == "terrain":
                command = sample_trot_command(stack, obs, np.random.default_rng(0))
                command[:, 0] = 1.0  # deterministic eval speed
                for col, val in (cmd_overrides or {}).items():
                    command[:, col] = val
                low = stack.low_input_with_history(obs, command)
                with torch.no_grad():
                    src = self.mean_action(policy, low).cpu().numpy()
                stack.roll_history(obs)
                prev_prog = stack.progress.copy()
                stack.env_step_with_source_action(src.astype(np.float32))
                stack.episode_steps += 1
                base = stack.backend.get_base_pos().copy().astype(np.float64)
                stack.progress = (base[:, :2] - stack.start_xy) @ stack.axis
                fell = base[:, 2] < 0.18
                success = np.linalg.norm(base[:, :2] - stack.goal_xy, axis=1) < 0.4
                done = fell | success | (stack.episode_steps >= stack.cfg.max_steps)
                info_success = success
                if np.any(done):
                    stack.reset_indices(np.nonzero(done)[0])
                del prev_prog
            else:
                high_input = stack.high_input(obs)
                with torch.no_grad():
                    emb = actor(high_input, hist_encoding=True, scandots_latent=None)
                    skill = torch.argmax(actor.actor_d(emb), -1)
                    cont = actor.actor_c(emb)
                stack.roll_history(obs)
                _, done, info = stack.step_train(obs, skill, cont)
                info_success = info["success"]
            newly = (outcome < 0) & done
            outcome[newly] = info_success[newly].astype(np.int64)
            steps += 1
        stack.bbc_forward = None
        stack.reset_indices(np.arange(n))
        finished = outcome >= 0
        return float(outcome[finished].sum()) / max(int(finished.sum()), 1)

    # -- main loop -------------------------------------------------------
    def train(self, out_dir: Path, iters: int) -> dict:
        started = time.monotonic()
        status = "BUDGET_EXHAUSTED"
        for it in range(1, iters + 1):
            kind, key = self.cycle[(it - 1) % len(self.cycle)]
            warmup = it <= 15
            if kind == "terrain":
                buf, stats = self.rollout_terrain(self.terrain[key])
                update = self.update(
                    buf, anchor_beta=self.args.terrain_beta, critic_only=warmup
                )
            else:
                buf, stats = self.rollout_retain(self.retain[key][1])
                update = self.update(buf, anchor_beta=BC_BETA, critic_only=warmup)
            row = {"iter": it, "kind": kind, "key": key,
                   "pi": round(update["pi"], 4), "bc": round(update["bc"], 4),
                   **stats}
            if it % 20 == 0:
                evals = {r: self.evaluate("tsc", r) for r in self.terrain}
                floors = {n: self.evaluate("retain", n) for n in self.retain}
                row["evals"] = evals
                row["floors"] = floors
                floors_ok = all(
                    floors[n] >= f for n, (f, _) in self.retain.items()
                )
                score = min(evals.values()) + 0.1 * sum(evals.values())
                if floors_ok and score > self.best["score"]:
                    self.best = {
                        "score": score,
                        "state": copy.deepcopy(self.bbc.state_dict()),
                        "iter": it,
                        "evals": evals,
                        "floors": floors,
                    }
                    torch.save(self.best["state"], out_dir / "nag901_bbc_best.pt")
                with (out_dir / "progress.jsonl").open("a") as fh:
                    import json as _json

                    fh.write(_json.dumps({"iter": it, "evals": evals, "floors": floors}) + "\n")
                if floors_ok and all(v >= self.args.rung_gate for v in evals.values()):
                    status = "PASSED"
                    self.history.append(row)
                    break
            self.history.append(row)
        state = self.best["state"] or self.bbc.state_dict()
        torch.save(state, out_dir / "nag901_bbc.pt")
        return {
            "status": status,
            "iters_run": len(self.history),
            "best": {k: v for k, v in self.best.items() if k != "state"},
            "wall_time_sec": time.monotonic() - started,
            "eval_rows": [r for r in self.history if "evals" in r][-20:],
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rungs", nargs="+", default=["r005", "r0625"])
    parser.add_argument("--rung-gate", type=float, default=0.8)
    parser.add_argument("--num-envs", type=int, default=64)
    parser.add_argument("--iters", type=int, default=2000)
    parser.add_argument("--actor-lr", type=float, default=1e-4)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--init-bbc", type=Path, default=None)
    parser.add_argument("--tag", default="phase1")
    parser.add_argument("--terrain-beta", type=float, default=0.3)
    parser.add_argument("--rung-weights", default="")
    parser.add_argument("--baseline-only", action="store_true")
    parser.add_argument("--bisect", action="store_true")
    parser.add_argument("--eval-ckpt", type=Path, default=None)
    args = parser.parse_args()
    out = RESULTS_ROOT / args.tag
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    trainer = BbcTrainer(args)
    if args.eval_ckpt is not None:
        trainer.bbc.load_state_dict(
            torch.load(args.eval_ckpt, map_location=trainer.device, weights_only=True)
        )
        trainer.bbc.eval()
        report = {}
        for r in trainer.terrain:
            report[f"{r}_fixed_vx"] = trainer.evaluate("terrain", r)
            report[f"{r}_tsc_deploy"] = trainer.evaluate("tsc", r)
        for n in trainer.retain:
            report[f"floor_{n}"] = trainer.evaluate("tsc", n)
        print("CKPT_EVAL:", report)
        _write_json(out / f"ckpt_eval_{stamp}.json", report)
        return 0
    if args.bisect:
        rung = args.rungs[0]
        trainer.bbc.eval()
        stack = trainer.terrain[rung]
        report = {"first_copy_tsc": trainer.evaluate("tsc", rung)}
        report["second_copy_tsc"] = trainer.evaluate("tsc", rung)
        report["copy_sampled_realhist"] = trainer.evaluate("terrain", rung)
        original_roll = stack.roll_history
        stack.roll_history = lambda obs: None
        stack.bbc_history[:] = 0.0
        report["copy_sampled_zerohist"] = trainer.evaluate("terrain", rung)
        # capture the commands the frozen TSC actually emits on this rung
        from t2_env import vector_set_commands

        stack.reset_indices(np.arange(stack.num_envs))
        actor = stack.adapter.high_model
        commands = []
        for _ in range(150):
            obs = stack.observe()
            high_input = stack.high_input(obs)
            with torch.no_grad():
                emb = actor(high_input, hist_encoding=True, scandots_latent=None)
                skill = torch.argmax(actor.actor_d(emb), -1)
                cont = actor.actor_c(emb)
                command = vector_set_commands(stack.adapter.commander, skill, cont)
            commands.append(command.cpu().numpy())
            stack.step_train(obs, skill, cont)
        arr = np.concatenate(commands, axis=0)
        report["tsc_command_mean"] = np.round(arr.mean(axis=0), 3).tolist()
        report["tsc_command_std"] = np.round(arr.std(axis=0), 3).tolist()
        stack.roll_history = original_roll
        print("BISECT:", report)
        _write_json(out / f"bisect_{stamp}.json", report)
        return 0
    if args.baseline_only:
        baseline = {
            "terrain": {r: trainer.evaluate("terrain", r) for r in trainer.terrain},
            "floors": {n: trainer.evaluate("retain", n) for n in trainer.retain},
        }
        print("BASELINE:", baseline)
        _write_json(out / f"baseline_{stamp}.json", baseline)
        return 0
    summary = trainer.train(out, args.iters)
    payload = {
        "run_id": f"NAG-901-{args.tag}",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "evaluation_type": "simulation_only",
        "scope": "NAG-901 BBC retrain (terrain command-sampling + skill retention)",
        "seed": args.seed,
        "rungs": args.rungs,
        "rung_gate": args.rung_gate,
        "retain_floors": {n: f for n, f in RETAIN},
        "history_contract": "real rolling 570-D history (train + eval)",
        "contracts": {
            "std_floor": STD_FLOOR, "bc_beta": BC_BETA,
            "vx_range": VX_RANGE, "runner_sha256": _sha256(Path(__file__)),
        },
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
