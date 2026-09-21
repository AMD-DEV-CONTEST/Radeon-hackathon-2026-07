"""Per-episode randomization, sampled for all envs at once.

Pure numpy and vectorized over envs: a Python loop over `n_envs` anywhere in
the reset path would cap N regardless of how fast the sim runs.

The two drawers are geometrically identical and always in the same places
relative to the cabinet, so unlike the colour case there is nothing to permute
-- "left" is a position, and position is what the prompt names. What has to be
randomized instead is the TRAVEL STOP, and for both drawers, so the distractor
leaks nothing about the target. It is invisible: no camera can see how far a
closed drawer will open, which is what forces the stop to be felt.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .config import EnvConfig, SIDES


@dataclass
class EpisodeSetup:
    cabinet_pos: np.ndarray     # (N, 3) world pose of the cabinet body origin
    cabinet_quat: np.ndarray    # (N, 4) w,x,y,z, yaw only
    cabinet_yaw: np.ndarray     # (N,)   radians, kept for building grasp frames
    travel: np.ndarray          # (N, 2) per-drawer stop, in SIDES order
    target_idx: np.ndarray      # (N,)   which drawer the prompt names
    target_travel: np.ndarray   # (N,)   the target drawer's stop
    prompts: list[str]          # (N,)   language conditioning, one per env
    descent_residual: np.ndarray  # (N, 2) misalignment the descent leaves in


def yaw_to_quat(yaw: np.ndarray) -> np.ndarray:
    """(N,) yaw about z -> (N, 4) quaternion in Genesis's w,x,y,z order."""
    half = yaw / 2.0
    out = np.zeros((len(yaw), 4), dtype=np.float64)
    out[:, 0] = np.cos(half)
    out[:, 3] = np.sin(half)
    return out


def sample_cabinet_pose(cfg: EnvConfig, rng: np.random.Generator):
    """(N, 3) position and (N,) yaw. The body origin is the footprint centre on
    the table top; the 0.1 mm lift keeps it from spawning interpenetrating the
    table, which the solver would resolve as a shove."""
    n, cab = cfg.n_envs, cfg.cabinet
    j = cab.pos_jitter
    pos = np.empty((n, 3), dtype=np.float64)
    pos[:, 0] = cab.center_x + rng.uniform(-j, j, size=n)
    pos[:, 1] = rng.uniform(-j, j, size=n)
    pos[:, 2] = cfg.table.top_z + 0.0001
    yaw = np.radians(rng.uniform(-cab.yaw_jitter_deg, cab.yaw_jitter_deg, size=n))
    return pos, yaw


def sample_travel(cfg: EnvConfig, rng: np.random.Generator) -> np.ndarray:
    """(N, 2) how far each drawer can be pulled before it stops."""
    lo, hi = cfg.cabinet.travel_range
    return rng.uniform(lo, hi, size=(cfg.n_envs, len(SIDES)))


def sample_descent_residual(cfg: EnvConfig, rng: np.random.Generator) -> np.ndarray:
    """(N, 2) the misalignment the descent onto the rail deliberately leaves.

    Sampled as a magnitude at a uniformly random heading, so corrections in the
    data come from every direction rather than a biased subset.
    """
    lo, hi = cfg.teacher.descent_residual
    mag = rng.uniform(lo, hi, size=cfg.n_envs)
    ang = rng.uniform(0.0, 2 * np.pi, size=cfg.n_envs)
    return np.stack([mag * np.cos(ang), mag * np.sin(ang)], axis=1)


def sample_episode(cfg: EnvConfig, rng: np.random.Generator) -> EpisodeSetup:
    pos, yaw = sample_cabinet_pose(cfg, rng)
    travel = sample_travel(cfg, rng)
    target_idx = rng.integers(0, len(SIDES), size=cfg.n_envs)
    return EpisodeSetup(
        cabinet_pos=pos,
        cabinet_quat=yaw_to_quat(yaw),
        cabinet_yaw=yaw,
        travel=travel,
        target_idx=target_idx,
        target_travel=travel[np.arange(cfg.n_envs), target_idx].copy(),
        prompts=[cfg.prompt(SIDES[i]) for i in target_idx],
        descent_residual=sample_descent_residual(cfg, rng),
    )
