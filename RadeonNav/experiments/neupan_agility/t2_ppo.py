#!/usr/bin/env python3
"""T2 trainer: KL-anchored hybrid-action PPO on the frozen agility stack.

Per the frozen T2 detail prereg (2026-07-31 12:40 UTC): trains
actor_trunk/actor_d/actor_c only (input encoders frozen -> deployment
compatibility by construction), fresh critic (source critic is 800-D
privileged, ours is 771-D deployment obs) with critic-only warmup,
adaptive KL anchor to the frozen reference actor, deterministic mini-gate
with rollback every 10 iters. Reward per prereg; progress implemented as
displacement along the start->goal axis (all stage tasks are +x
corridors) — recorded in the run contract.
"""

from __future__ import annotations

import argparse
import copy
import shutil
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "experiments/cpp_adapter"))

import mujoco  # noqa: E402

from cpp_loco_sanity import _sha256  # noqa: E402
from run_bbc_sanity import _device, _write_json  # noqa: E402
from run_source_task import HIGH_CHECKPOINT  # noqa: E402
from t2_env import (  # noqa: E402
    FROZEN_MODULES,
    RESULTS_ROOT,
    TRAINABLE_MODULES,
    VectorAgilityStack,
    _yaw_from_quat,
)

ASSETS = Path(__file__).resolve().parent / "assets"
CTRL_DT = 0.02
CLEARANCE_MARGIN_M = 0.06
BASE_POINTS = np.asarray(  # body-frame proxy points (x, y)
    [(0.0, 0.0), (0.19, 0.09), (0.19, -0.09), (-0.19, 0.09), (-0.19, -0.09)],
    dtype=np.float64,
)


def _segment_hits_box_xy(a: np.ndarray, b: np.ndarray, box: np.ndarray) -> bool:
    """2D slab test: does segment a->b cross the box footprint?"""
    lo = box[:2] - box[3:5]
    hi = box[:2] + box[3:5]
    d = b - a
    t0, t1 = 0.0, 1.0
    for k in range(2):
        if abs(d[k]) < 1e-12:
            if a[k] < lo[k] or a[k] > hi[k]:
                return False
            continue
        ta = (lo[k] - a[k]) / d[k]
        tb = (hi[k] - a[k]) / d[k]
        ta, tb = min(ta, tb), max(ta, tb)
        t0, t1 = max(t0, ta), min(t1, tb)
        if t0 > t1:
            return False
    return True


class _FlatSampler:
    @staticmethod
    def sample_height(xy: np.ndarray) -> np.ndarray:
        return np.zeros(np.asarray(xy).shape[:-1], dtype=np.float64)


class _StairsSampler:
    """Analytic proxy heights for assets/stairs*.xml geometry."""

    def __init__(self, riser: float, treads: int = 4, tread: float = 0.30,
                 platform: float = 0.6, width: float = 1.2):
        self.riser, self.treads, self.tread = riser, treads, tread
        self.platform, self.width = platform, width
        self.ascent = treads * tread
        self.total = 2 * self.ascent + platform  # x span, centred at 0

    def sample_height(self, xy: np.ndarray) -> np.ndarray:
        points = np.asarray(xy, dtype=np.float64).reshape(-1, 2)
        x = points[:, 0] + self.total / 2.0  # 0 at stairs west edge
        inside = (np.abs(points[:, 1]) <= self.width / 2.0) & (x >= 0) & (
            x <= self.total
        )
        up = np.clip(np.ceil(x / self.tread), 0, self.treads) * self.riser
        top = self.treads * self.riser
        down_x = x - self.ascent - self.platform
        down = top - np.clip(np.ceil(down_x / self.tread), 0, self.treads) * self.riser
        h = np.where(x <= self.ascent, up, np.where(down_x <= 0, top, down))
        return np.where(inside, h, 0.0).reshape(np.asarray(xy).shape[:-1])


@dataclass(frozen=True)
class StageCfg:
    name: str
    task: str                      # TASKS key or pseudo task
    fragment: str | None           # asset file for pseudo tasks
    sampler: Any                   # None -> proxy_sampler(task)
    spec: Any                      # None -> TASKS[task]
    max_steps: int
    iters: int
    yaw_jitter: float = 0.0
    x_jitter: float = 0.0
    success_gate: float = 0.95
    kl_target: float = 0.02
    explore_std: float = 0.0  # >0: floor the Gaussian std for exploration


def _pseudo_spec(name, goals, obstacle_index):
    return SimpleNamespace(
        name=name, goals=tuple(goals), obstacle_index=obstacle_index
    )


STAGES: dict[str, StageCfg] = {
    "S0": StageCfg(
        "S0", "flat", None, _FlatSampler(),
        _pseudo_spec("flat", [(-3.0, 0.0, 0.3), (3.0, 0.0, 0.3)], 1),
        max_steps=500, iters=300,
    ),
    # Amendment A1 (2026-07-31, documented): S1 KL target loosened to 0.05
    # after the 0.02 trust region showed no sustained climb over 600 iters
    # (best 0.516 vs ~0.5 jittered baseline); non-forgetting remains gated
    # by the deterministic regression suite, the anchor is a tuning knob.
    "S1a": StageCfg(
        "S1a", "tire_jump", None, None, None, max_steps=400, iters=600,
        x_jitter=0.15, success_gate=0.9, kl_target=0.05,
    ),
    "S1b": StageCfg(
        "S1b", "seesaw", None, None, None, max_steps=500, iters=600,
        x_jitter=0.15, success_gate=0.9,
    ),
    "S2": StageCfg(
        "S2", "tire_jump", None, None, None, max_steps=400, iters=600,
        yaw_jitter=0.3, x_jitter=0.3, success_gate=0.85,
    ),
    "S3z": StageCfg(  # diagnostic: frozen baseline on riser 0.05 (stage-A pass)
        "S3z", "stairs_r005", str(ASSETS / "stairs.xml"), _StairsSampler(0.05),
        _pseudo_spec("stairs", [(-3.0, 0.0, 0.3), (3.0, 0.0, 0.3)], 1),
        max_steps=700, iters=10, success_gate=0.5,
    ),
    "S3c": StageCfg(  # curriculum ground floor: train where baseline is 0.61
        "S3c", "stairs_r005", str(ASSETS / "stairs.xml"), _StairsSampler(0.05),
        _pseudo_spec("stairs", [(-3.0, 0.0, 0.3), (3.0, 0.0, 0.3)], 1),
        max_steps=700, iters=600, success_gate=0.9, kl_target=0.05,
    ),
    "S3e": StageCfg(  # E1 probe: near-unanchored + exploration floor
        "S3e", "stairs_r005", str(ASSETS / "stairs.xml"), _StairsSampler(0.05),
        _pseudo_spec("stairs", [(-3.0, 0.0, 0.3), (3.0, 0.0, 0.3)], 1),
        max_steps=700, iters=600, success_gate=0.9, kl_target=0.2,
        explore_std=0.15,
    ),
    "S3f": StageCfg(  # riser curriculum rung 2
        "S3f", "stairs_r00625", str(ASSETS / "stairs_r00625.xml"),
        _StairsSampler(0.0625),
        _pseudo_spec("stairs", [(-3.0, 0.0, 0.3), (3.0, 0.0, 0.3)], 1),
        max_steps=700, iters=1500, success_gate=0.9, kl_target=0.2,
        explore_std=0.15,
    ),
    "S3a": StageCfg(  # rung 3
        "S3a", "stairs_r0075", str(ASSETS / "stairs_r0075.xml"),
        _StairsSampler(0.075),
        _pseudo_spec("stairs", [(-3.0, 0.0, 0.3), (3.0, 0.0, 0.3)], 1),
        max_steps=950, iters=1500, success_gate=0.85, kl_target=0.2,
        explore_std=0.15,
    ),
    "S3g": StageCfg(  # rung 4
        "S3g", "stairs_r00875", str(ASSETS / "stairs_r00875.xml"),
        _StairsSampler(0.0875),
        _pseudo_spec("stairs", [(-3.0, 0.0, 0.3), (3.0, 0.0, 0.3)], 1),
        max_steps=1000, iters=1500, success_gate=0.8, kl_target=0.2,
        explore_std=0.15,
    ),
    "S3b": StageCfg(  # target rung: competition-relevant riser 0.10
        "S3b", "stairs_r010", str(ASSETS / "stairs_r010.xml"), _StairsSampler(0.10),
        _pseudo_spec("stairs", [(-3.0, 0.0, 0.3), (3.0, 0.0, 0.3)], 1),
        max_steps=1100, iters=2000, success_gate=0.7, kl_target=0.2,
        explore_std=0.15,
    ),
}


class TrainStack(VectorAgilityStack):
    """Adds resets, termination, and the preregistered reward."""

    def __init__(self, cfg: StageCfg, num_envs, device, seed):
        super().__init__(
            cfg.task if cfg.spec is None else cfg.task,
            num_envs,
            device,
            seed,
            spec=cfg.spec,
            sampler=cfg.sampler,
            fragment_file=Path(cfg.fragment) if cfg.fragment else None,
        )
        self.cfg = cfg
        self.rng = np.random.default_rng(seed)
        goals = np.asarray(self.spec.goals, dtype=np.float64)
        axis = goals[-1, :2] - goals[0, :2]
        self.axis = axis / np.linalg.norm(axis)
        self.start_xy = goals[0, :2]
        self.goal_xy = goals[-1, :2]
        self.episode_steps = np.zeros(num_envs, dtype=np.int64)
        self.progress = np.zeros(num_envs, dtype=np.float64)
        self.prev_source_action = np.zeros((num_envs, 12), dtype=np.float32)
        self.obstacle_boxes = self._collect_obstacle_boxes()
        self.reset_indices(np.arange(num_envs))

    def _collect_obstacle_boxes(self) -> np.ndarray:
        """World AABBs of static non-robot collision geoms (auto, per task)."""
        model = self.backend.model
        data = mujoco.MjData(model)
        mujoco.mj_setState(
            model, data,
            np.asarray(self.backend._physics_state[0], dtype=np.float64),
            mujoco.mjtState.mjSTATE_FULLPHYSICS,
        )
        mujoco.mj_forward(model, data)
        robot_bodies = set(
            self.backend.get_body_subtree_ids(
                self.backend.get_body_id("base")
            ).tolist()
        )
        boxes = []
        for geom_id in range(model.ngeom):
            body_id = int(model.geom_bodyid[geom_id])
            name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, geom_id) or ""
            if "floor" in name or model.geom_type[geom_id] in (
                mujoco.mjtGeom.mjGEOM_HFIELD,
                mujoco.mjtGeom.mjGEOM_PLANE,
            ):
                continue
            if body_id in robot_bodies:
                continue
            if model.geom_contype[geom_id] == 0 and model.geom_conaffinity[geom_id] == 0:
                continue
            aabb = model.geom_aabb[geom_id].reshape(2, 3)
            centre_local, half = aabb[0], aabb[1]
            xmat = data.geom_xmat[geom_id].reshape(3, 3)
            centre = data.geom_xpos[geom_id] + xmat @ centre_local
            world_half = np.abs(xmat) @ half
            boxes.append(np.concatenate((centre, world_half)))
        boxes = (
            np.asarray(boxes, dtype=np.float64)
            if boxes
            else np.zeros((0, 6), dtype=np.float64)
        )
        # Passage boxes (tire ring, seesaw plank, stair treads, frame panels)
        # are traversal surfaces the goal chain deliberately crosses; their
        # AABBs contain the intended path, so penalizing proximity to them
        # would punish the correct behaviour (S1a dry-run lesson). Keep only
        # side obstacles: boxes the goal polyline does not cross in xy, or
        # tall boxes starting above the passage height.
        goals = np.asarray(self.spec.goals, dtype=np.float64)[:, :2]
        keep = np.ones(len(boxes), dtype=bool)
        for i, box in enumerate(boxes):
            z_low = box[2] - box[5]
            if z_low >= 0.6:
                continue
            for a, b in zip(goals[:-1], goals[1:]):
                if _segment_hits_box_xy(a, b, box):
                    keep[i] = False
                    break
        self.dropped_passage_boxes = int((~keep).sum())
        return boxes[keep]

    def reset_indices(self, indices: np.ndarray) -> None:
        if len(indices) == 0:
            return
        n = len(indices)
        qpos = np.tile(
            np.asarray(self.env._init_qpos, dtype=np.float32).reshape(1, -1), (n, 1)
        )
        qvel = np.zeros((n, np.asarray(self.env._init_qvel).size), dtype=np.float32)
        x = self.start_xy[0] + self.rng.uniform(-self.cfg.x_jitter, 0.0, size=n)
        yaw = self.rng.uniform(-self.cfg.yaw_jitter, self.cfg.yaw_jitter, size=n)
        qpos[:, 0], qpos[:, 1], qpos[:, 2] = x, self.start_xy[1], 0.42
        qpos[:, 3] = np.cos(yaw / 2.0)
        qpos[:, 6] = np.sin(yaw / 2.0)
        from run_source_task import ROBOT_JOINTS

        idx = self.backend.get_joint_dof_pos_indices(ROBOT_JOINTS) + 7
        qpos[:, idx] = self.contract.source_default_dof
        from t2_env import OBSTACLE_JOINTS

        for joint, value in OBSTACLE_JOINTS.get(self.task, ()):
            j = self.backend.get_joint_dof_pos_indices((joint,))[0] + 7
            qpos[:, int(j)] = value
        self.backend.set_state(indices.astype(np.int32), qpos, qvel)
        self.state = self.env.update_state(self.state)
        self.previous_action[indices] = 0.0
        self.previous_contact[indices] = 0.0
        self.prev_source_action[indices] = 0.0
        self.goal_index[indices] = 1
        self.goal_timer[indices] = 0
        self.episode_steps[indices] = 0
        self.progress[indices] = (
            (np.stack((x, np.full(n, self.start_xy[1])), axis=1) - self.start_xy)
            @ self.axis
        )

    def clearance_violation(self, base_pos: np.ndarray, yaw: np.ndarray) -> np.ndarray:
        if not len(self.obstacle_boxes):
            return np.zeros(self.num_envs, dtype=np.float64)
        c, s = np.cos(yaw), np.sin(yaw)
        rot = np.stack((np.stack((c, -s), 1), np.stack((s, c), 1)), axis=1)
        pts_xy = (BASE_POINTS[None] @ rot.transpose(0, 2, 1)) + base_pos[:, None, :2]
        pts = np.concatenate(
            (pts_xy, np.broadcast_to(base_pos[:, None, 2:3], pts_xy[:, :, :1].shape)),
            axis=2,
        )  # (N, P, 3)
        centre = self.obstacle_boxes[None, None, :, :3]
        half = self.obstacle_boxes[None, None, :, 3:]
        d = np.abs(pts[:, :, None, :] - centre) - half
        dist = np.linalg.norm(np.maximum(d, 0.0), axis=-1)  # (N, P, B)
        violation = np.maximum(CLEARANCE_MARGIN_M - dist, 0.0)
        return violation.max(axis=(1, 2))

    def step_train(
        self, obs: dict[str, Any], skill: torch.Tensor, continuous: torch.Tensor
    ) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
        prev_progress = self.progress.copy()
        prev_action = self.prev_source_action.copy()
        self.step_with_action(obs, skill, continuous)
        self.prev_source_action = self.previous_action.copy()
        self.episode_steps += 1
        base_pos = self.backend.get_base_pos().copy().astype(np.float64)
        base_quat = self.backend.get_base_quat().copy().astype(np.float64)
        yaw = _yaw_from_quat(base_quat)
        self.progress = (base_pos[:, :2] - self.start_xy) @ self.axis
        progress_delta = self.progress - prev_progress
        w, xq, yq, zq = base_quat.T
        roll = np.arctan2(2 * (w * xq + yq * zq), 1 - 2 * (xq**2 + yq**2))
        pitch = np.arcsin(np.clip(2 * (w * yq - zq * xq), -1, 1))
        fell = (base_pos[:, 2] < 0.22) | (np.abs(roll) > 1.0) | (np.abs(pitch) > 1.2)
        success = np.linalg.norm(base_pos[:, :2] - self.goal_xy, axis=1) < 0.4
        timeout = self.episode_steps >= self.cfg.max_steps
        violation = self.clearance_violation(base_pos, yaw)
        action_rate = np.sum(
            (self.prev_source_action - prev_action) ** 2, axis=1
        )
        reward = (
            2.0 * progress_delta
            + 0.5 * CTRL_DT
            - 0.5 * violation
            - 0.01 * action_rate
            - 2.0 * fell.astype(np.float64)
            + 5.0 * success.astype(np.float64)
        )
        done = fell | success | timeout
        info = {
            "success": success,
            "fell": fell,
            "timeout": timeout,
            "violation": violation,
        }
        if np.any(done):
            self.reset_indices(np.nonzero(done)[0])
        return reward.astype(np.float32), done, info


class Critic(nn.Module):
    def __init__(self, obs_dim: int = 771):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(obs_dim, 512), nn.ELU(),
            nn.Linear(512, 256), nn.ELU(),
            nn.Linear(256, 128), nn.ELU(),
            nn.Linear(128, 1),
        )

    def forward(self, obs: torch.Tensor) -> torch.Tensor:
        return self.net(obs).squeeze(-1)


@dataclass
class PpoCfg:
    rollout_steps: int = 48
    epochs: int = 4
    minibatches: int = 4
    clip: float = 0.2
    gamma: float = 0.99
    lam: float = 0.95
    actor_lr: float = 3e-5
    critic_lr: float = 1e-3
    entropy_coef: float = 0.003
    kl_beta: float = 0.5
    kl_target: float = 0.02
    grad_norm: float = 1.0
    warmup_iters: int = 10
    gate_every: int = 10
    eval_episodes: int = 8
    max_rollbacks: int = 3


# Mixed-task training (prereg "多任务混采" anti-forgetting): 50% target
# rollouts, retention tasks interleaved; floors gate best-selection.
# Tire floor 0.25: the jittered-tire baseline is itself a noisy ~0.4
# (measured 0.20-0.52 band); the floor guards against the measured
# catastrophic-forgetting mode (collapse to ~0), not the knife edge.
# (target, retains-with-floors, floorless extra training tasks)
# Extras give in-batch riser diversity: single-height stages overfit a
# stepping rhythm instead of reading the scan (M2/S3f finding).
MIXES: dict[str, tuple[str, tuple[tuple[str, float], ...], tuple[str, ...]]] = {
    "M1": ("S3e", (("S1a", 0.25), ("S0", 0.95)), ()),
    "M2": ("S3f", (("S1a", 0.25), ("S0", 0.95)), ()),
    "M2R": ("S3f", (("S1a", 0.25), ("S0", 0.95)), ("S3e",)),
    "M3R": ("S3a", (("S1a", 0.25), ("S0", 0.95)), ("S3e", "S3f")),
    "M4R": ("S3g", (("S1a", 0.25), ("S0", 0.95)), ("S3f", "S3a")),
    "M5R": ("S3b", (("S1a", 0.25), ("S0", 0.95)), ("S3a", "S3g")),
}


class Trainer:
    def __init__(self, stage: StageCfg, args, retain=(), extras=()):
        self.stage = stage
        self.device = _device(args.device)
        self.cfg = PpoCfg()
        self.cfg.kl_target = stage.kl_target
        torch.manual_seed(args.seed)
        np.random.seed(args.seed)
        self.stack = TrainStack(stage, args.num_envs, self.device, args.seed)
        self.retain = tuple(
            (name, floor, TrainStack(STAGES[name], args.num_envs, self.device, args.seed))
            for name, floor in retain
        )
        extra_stacks = [
            (name, TrainStack(STAGES[name], args.num_envs, self.device, args.seed))
            for name in extras
        ]
        others = extra_stacks + [
            (name, stack) for name, _, stack in self.retain
        ]
        cycle = []
        for pair in others:
            cycle.extend([(self.stage.name, self.stack), pair])
        self.cycle = cycle or [(self.stage.name, self.stack)]
        reference = self.stack.adapter.high_model
        self.reference = reference
        self.actor = copy.deepcopy(reference).float()
        if args.init_actor is not None:
            self.actor.load_state_dict(
                torch.load(args.init_actor, map_location=self.device, weights_only=True)
            )
        for name, p in self.actor.named_parameters():
            p.requires_grad_(any(name.startswith(m) for m in TRAINABLE_MODULES))
        payload = torch.load(HIGH_CHECKPOINT, map_location=self.device, weights_only=False)
        warm_std = payload["model_state_dict"]["std"].float().to(self.device)
        if stage.explore_std > 0:
            warm_std = warm_std.clamp(min=stage.explore_std)
        self.log_std = nn.Parameter(torch.log(warm_std.clamp(min=1e-3)))
        self.critic = Critic().to(self.device)
        if args.init_critic is not None:
            self.critic.load_state_dict(
                torch.load(args.init_critic, map_location=self.device, weights_only=True)
            )
        trainable = [p for p in self.actor.parameters() if p.requires_grad]
        self.actor_opt = torch.optim.Adam(
            [
                {"params": trainable, "lr": self.cfg.actor_lr},
                {"params": [self.log_std], "lr": self.cfg.actor_lr},
            ]
        )
        self.critic_opt = torch.optim.Adam(self.critic.parameters(), lr=self.cfg.critic_lr)
        self.kl_beta = self.cfg.kl_beta
        self.best = {"success": -1.0, "violation": float("inf"), "state": None}
        self.rollbacks = 0
        self._below_count = 0
        self.history: list[dict[str, Any]] = []

    # -- policy --------------------------------------------------------
    def dist(self, actor, high_input):
        emb = actor(high_input, hist_encoding=True, scandots_latent=None)
        logits = actor.actor_d(emb)
        mean = actor.actor_c(emb)
        return logits, mean

    def act(self, high_input, deterministic=False):
        logits, mean = self.dist(self.actor, high_input)
        dist_d = torch.distributions.Categorical(logits=logits)
        std = torch.exp(self.log_std)
        if deterministic:
            skill = torch.argmax(logits, dim=-1)
            cont = mean
        else:
            skill = dist_d.sample()
            cont = torch.distributions.Normal(mean, std).sample()
        log_prob = dist_d.log_prob(skill) + torch.distributions.Normal(
            mean, std
        ).log_prob(cont).sum(-1)
        return skill, cont, log_prob, logits, mean

    # -- rollout -------------------------------------------------------
    def collect(self, stack=None):
        stack = stack or self.stack
        stash, self.stack = self.stack, stack
        try:
            return self._collect_impl()
        finally:
            self.stack = stash

    def _collect_impl(self):
        T, N = self.cfg.rollout_steps, self.stack.num_envs
        buf = {
            "obs": torch.zeros((T, N, 771), device=self.device),
            "skill": torch.zeros((T, N), dtype=torch.long, device=self.device),
            "cont": torch.zeros((T, N, 18), device=self.device),
            "logp": torch.zeros((T, N), device=self.device),
            "reward": torch.zeros((T, N), device=self.device),
            "done": torch.zeros((T, N), device=self.device),
            "value": torch.zeros((T, N), device=self.device),
        }
        stats = {"success": 0, "fell": 0, "episodes": 0, "violation": 0.0}
        for t in range(T):
            obs = self.stack.observe()
            high_input = self.stack.high_input(obs)
            with torch.no_grad():
                skill, cont, logp, _, _ = self.act(high_input)
                value = self.critic(high_input)
            reward, done, info = self.stack.step_train(obs, skill, cont)
            buf["obs"][t] = high_input
            buf["skill"][t] = skill
            buf["cont"][t] = cont
            buf["logp"][t] = logp
            buf["value"][t] = value
            buf["reward"][t] = torch.as_tensor(reward, device=self.device)
            buf["done"][t] = torch.as_tensor(done.astype(np.float32), device=self.device)
            stats["success"] += int(info["success"].sum())
            stats["fell"] += int(info["fell"].sum())
            stats["episodes"] += int(done.sum())
            stats["violation"] += float(info["violation"].sum())
        with torch.no_grad():
            obs = self.stack.observe()
            last_value = self.critic(self.stack.high_input(obs))
        adv = torch.zeros_like(buf["reward"])
        gae = torch.zeros_like(last_value)
        for t in reversed(range(T)):
            next_value = last_value if t == T - 1 else buf["value"][t + 1]
            mask = 1.0 - buf["done"][t]
            delta = buf["reward"][t] + self.cfg.gamma * next_value * mask - buf["value"][t]
            gae = delta + self.cfg.gamma * self.cfg.lam * mask * gae
            adv[t] = gae
        buf["adv"] = adv
        buf["ret"] = adv + buf["value"]
        return buf, stats

    # -- update --------------------------------------------------------
    def update(self, buf, critic_only=False):
        T, N = self.cfg.rollout_steps, self.stack.num_envs
        flat = {k: v.reshape(T * N, *v.shape[2:]) for k, v in buf.items()}
        adv = (flat["adv"] - flat["adv"].mean()) / (flat["adv"].std() + 1e-8)
        idx = torch.randperm(T * N, device=self.device)
        out = {"pi": 0.0, "v": 0.0, "kl_ref": 0.0, "entropy": 0.0, "n": 0}
        for _ in range(self.cfg.epochs):
            for mb in idx.chunk(self.cfg.minibatches):
                obs = flat["obs"][mb]
                value = self.critic(obs)
                v_loss = F.mse_loss(value, flat["ret"][mb])
                self.critic_opt.zero_grad()
                v_loss.backward()
                nn.utils.clip_grad_norm_(self.critic.parameters(), self.cfg.grad_norm)
                self.critic_opt.step()
                out["v"] += float(v_loss)
                if critic_only:
                    out["n"] += 1
                    continue
                logits, mean = self.dist(self.actor, obs)
                std = torch.exp(self.log_std)
                dist_d = torch.distributions.Categorical(logits=logits)
                dist_c = torch.distributions.Normal(mean, std)
                logp = dist_d.log_prob(flat["skill"][mb]) + dist_c.log_prob(
                    flat["cont"][mb]
                ).sum(-1)
                ratio = torch.exp(logp - flat["logp"][mb])
                surrogate = torch.min(
                    ratio * adv[mb],
                    torch.clamp(ratio, 1 - self.cfg.clip, 1 + self.cfg.clip) * adv[mb],
                )
                with torch.no_grad():
                    ref_logits, ref_mean = self.dist(self.reference, obs)
                kl_ref = (
                    F.kl_div(
                        F.log_softmax(logits, -1),
                        F.softmax(ref_logits.float(), -1),
                        reduction="none",
                    ).sum(-1)
                    + (((mean - ref_mean.float()) ** 2) / (2 * std.detach() ** 2)).sum(-1)
                ).mean()
                entropy = dist_d.entropy().mean() + dist_c.entropy().sum(-1).mean()
                pi_loss = (
                    -surrogate.mean()
                    + self.kl_beta * kl_ref
                    - self.cfg.entropy_coef * entropy
                )
                self.actor_opt.zero_grad()
                pi_loss.backward()
                nn.utils.clip_grad_norm_(
                    [p for p in self.actor.parameters() if p.requires_grad]
                    + [self.log_std],
                    self.cfg.grad_norm,
                )
                self.actor_opt.step()
                if self.stage.explore_std > 0:
                    with torch.no_grad():
                        self.log_std.clamp_(min=np.log(self.stage.explore_std))
                out["pi"] += float(pi_loss)
                out["kl_ref"] += float(kl_ref)
                out["entropy"] += float(entropy)
                out["n"] += 1
        for key in ("pi", "v", "kl_ref", "entropy"):
            out[key] /= max(out["n"], 1)
        if not critic_only:
            if out["kl_ref"] > 1.5 * self.cfg.kl_target:
                self.kl_beta = min(self.kl_beta * 1.5, 50.0)
            elif out["kl_ref"] < self.cfg.kl_target / 1.5:
                self.kl_beta = max(self.kl_beta / 1.5, 0.01)
        return out

    # -- deterministic eval + rollback --------------------------------
    def evaluate(self, stack=None, max_steps=None) -> dict[str, float]:
        """One deterministic episode per env (spawn jitter = 64 distinct
        episodes); each env counts exactly once at its first done."""
        stack = stack or self.stack
        stash, self.stack = self.stack, stack
        try:
            return self._evaluate_impl(max_steps or self.stage.max_steps)
        finally:
            self.stack = stash

    def _evaluate_impl(self, max_steps: int) -> dict[str, float]:
        n = self.stack.num_envs
        self.stack.reset_indices(np.arange(n))
        outcome = np.full(n, -1, dtype=np.int64)
        violation = np.zeros(n, dtype=np.float64)
        steps = 0
        while np.any(outcome < 0) and steps < max_steps + 50:
            obs = self.stack.observe()
            high_input = self.stack.high_input(obs)
            with torch.no_grad():
                skill, cont, _, _, _ = self.act(high_input, deterministic=True)
            _, done, info = self.stack.step_train(obs, skill, cont)
            open_envs = outcome < 0
            violation[open_envs] += info["violation"][open_envs]
            newly = open_envs & done
            outcome[newly] = info["success"][newly].astype(np.int64)
            steps += 1
        finished = outcome >= 0
        rate = float(outcome[finished].sum()) / max(int(finished.sum()), 1)
        self.stack.reset_indices(np.arange(n))
        return {
            "success": rate,
            "violation": float(violation.mean()),
            "episodes": int(finished.sum()),
        }

    def maybe_rollback(self, ev: dict[str, float], floors_ok: bool = True) -> bool:
        better = floors_ok and (
            ev["success"] > self.best["success"]
            or (
                ev["success"] == self.best["success"]
                and ev["violation"] < self.best["violation"]
            )
        )
        if better:
            self.best = {
                "success": ev["success"],
                "violation": ev["violation"],
                "state": {
                    "actor": copy.deepcopy(self.actor.state_dict()),
                    "log_std": self.log_std.detach().clone(),
                    "critic": copy.deepcopy(self.critic.state_dict()),
                },
            }
            return False
        below = self.best["state"] is not None and (
            ev["success"] < self.best["success"] - 0.15 or not floors_ok
        )
        if below:
            self._below_count += 1
        else:
            self._below_count = 0
        # Debounce: the 64-episode eval carries noise and `best` is a
        # favourable draw; roll back only on three consecutive breaches.
        if self._below_count < 3:
            return False
        self._below_count = 0
        if below:
            self.actor.load_state_dict(self.best["state"]["actor"])
            with torch.no_grad():
                self.log_std.copy_(self.best["state"]["log_std"])
            self.critic.load_state_dict(self.best["state"]["critic"])
            for group in self.actor_opt.param_groups:
                group["lr"] *= 0.5
            self.rollbacks += 1
            return True
        return False

    def train(self, out_dir: Path) -> dict[str, Any]:
        started = time.monotonic()
        status = "FAILED"
        for it in range(1, self.stage.iters + 1):
            _, rollout_stack = self.cycle[(it - 1) % len(self.cycle)]
            buf, stats = self.collect(rollout_stack)
            update = self.update(buf, critic_only=it <= self.cfg.warmup_iters)
            row = {
                "iter": it,
                "kl_ref": update["kl_ref"],
                "kl_beta": self.kl_beta,
                "pi": update["pi"],
                "v": update["v"],
                **{k: stats[k] for k in ("success", "fell", "episodes")},
            }
            if it % self.cfg.gate_every == 0:
                ev = self.evaluate()
                row["eval_success"] = ev["success"]
                row["eval_violation"] = ev["violation"]
                floors_ok = True
                for name, floor, retain_stack in self.retain:
                    r = self.evaluate(retain_stack, STAGES[name].max_steps)
                    row[f"retain_{name}"] = r["success"]
                    floors_ok = floors_ok and r["success"] >= floor
                row["floors_ok"] = floors_ok
                rolled = self.maybe_rollback(ev, floors_ok)
                row["rolled_back"] = rolled
                if rolled and self.rollbacks > self.cfg.max_rollbacks:
                    status = "KILLED_ROLLBACKS"
                    self.history.append(row)
                    break
                if ev["success"] >= self.stage.success_gate and floors_ok:
                    status = "PASSED"
                    self.history.append(row)
                    break
            self.history.append(row)
        if status != "PASSED" and self.best["success"] >= self.stage.success_gate:
            status = "PASSED"
        state = self.best["state"] or {
            "actor": self.actor.state_dict(),
            "log_std": self.log_std.detach(),
            "critic": self.critic.state_dict(),
        }
        torch.save(state["actor"], out_dir / f"t2_actor_{self.stage.name}.pt")
        torch.save(state["critic"], out_dir / f"t2_critic_{self.stage.name}.pt")
        torch.save(state["log_std"], out_dir / f"t2_logstd_{self.stage.name}.pt")
        return {
            "status": status,
            "iters_run": len(self.history),
            "best_eval_success": self.best["success"],
            "best_eval_violation": self.best["violation"],
            "rollbacks": self.rollbacks,
            "final_kl_beta": self.kl_beta,
            "wall_time_sec": time.monotonic() - started,
            "history_tail": self.history[-8:],
            "evals": [r for r in self.history if "eval_success" in r],
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--stage", choices=sorted(STAGES) + sorted(MIXES), required=True
    )
    parser.add_argument("--num-envs", type=int, default=64)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--init-actor", type=Path, default=None)
    parser.add_argument("--init-critic", type=Path, default=None)
    parser.add_argument("--iters", type=int, default=0)
    args = parser.parse_args()
    from dataclasses import replace as _mix_replace

    retain: tuple = ()
    extras: tuple = ()
    if args.stage in MIXES:
        target_key, retain, extras = MIXES[args.stage]
        stage = _mix_replace(
            STAGES[target_key],
            name=args.stage,
            # rung-internal advancement criterion; final acceptance stays
            # the deterministic 0.10 probe + full regression suite
            success_gate=min(STAGES[target_key].success_gate, 0.85),
        )
    else:
        stage = STAGES[args.stage]
    if args.iters > 0:
        from dataclasses import replace as _replace

        stage = _replace(stage, iters=args.iters)
    out = RESULTS_ROOT / stage.name
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    trainer = Trainer(stage, args, retain=retain, extras=extras)
    summary = trainer.train(out)
    payload = {
        "run_id": f"NAG-T2-{stage.name}",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "evaluation_type": "simulation_only",
        "scope": f"T2 stage {stage.name} ({stage.task}) KL-anchored PPO fine-tune",
        "seed": args.seed,
        "stage": {
            "task": stage.task, "iters_cap": stage.iters,
            "max_steps": stage.max_steps, "success_gate": stage.success_gate,
            "yaw_jitter": stage.yaw_jitter, "x_jitter": stage.x_jitter,
        },
        "ppo": {k: getattr(trainer.cfg, k) for k in vars(trainer.cfg)},
        "progress_semantics": "displacement along start->goal axis",
        "init_actor": str(args.init_actor) if args.init_actor else "deployment",
        "contracts": {
            "trainable_modules": TRAINABLE_MODULES,
            "frozen_modules": FROZEN_MODULES,
            "clearance_margin_m": CLEARANCE_MARGIN_M,
            "high_checkpoint_sha256": _sha256(HIGH_CHECKPOINT),
            "runner_sha256": _sha256(Path(__file__)),
        },
        **summary,
    }
    path = out / f"result_{stamp}.json"
    _write_json(path, payload)
    shutil.copy2(path, out / "result.json")
    print(f"{payload['status']}: {path}")
    print("best eval success:", summary["best_eval_success"])
    return 0 if payload["status"] == "PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
