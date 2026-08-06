"""Vectorized training entry points for residual-control experiments."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Callable

import gymnasium as gym
import torch

from algorithms.ppo_trainer import CleanRLPPOTrainer
from controller.residual_wrapper import IKResidualWrapper
from controller.pick_place_expert import PickPlaceIKExpert
from simulation.factories import make_flattened_env
from simulation.genesis_env import GenesisPickPlaceEnv


def make_vector_env(
    scene_factories: Sequence[Callable[[], GenesisPickPlaceEnv]],
) -> gym.vector.SyncVectorEnv:
    """Build independent Genesis environments for a PPO rollout.

    Each factory must create and build its own scene. Sharing a Genesis scene
    between vector slots would couple resets and invalidate the PPO trajectories.
    The state dictionary is flattened deterministically before it reaches PPO.
    """
    if not scene_factories:
        raise ValueError("at least one environment factory is required")
    return gym.vector.SyncVectorEnv([make_flattened_env(factory) for factory in scene_factories])


def make_residual_vector_env(
    scene_factories: Sequence[Callable[[], GenesisPickPlaceEnv]], *, residual_scale: float = 0.10
) -> gym.vector.SyncVectorEnv:
    """Build PPO workers whose actions are residuals around their local IK expert."""
    if not scene_factories:
        raise ValueError("at least one environment factory is required")

    def wrapped_factory(factory: Callable[[], GenesisPickPlaceEnv]) -> Callable[[], gym.Env]:
        def build() -> gym.Env:
            env = factory()
            return gym.wrappers.FlattenObservation(
                IKResidualWrapper(env, PickPlaceIKExpert(env), residual_scale=residual_scale)
            )
        return build

    return gym.vector.SyncVectorEnv([wrapped_factory(factory) for factory in scene_factories])


def train_residual(
    env: Any,
    trainer: CleanRLPPOTrainer,
    ik_action_fn: Callable[[torch.Tensor], torch.Tensor],
    total_timesteps: int,
) -> list[dict[str, float]]:
    """Train an IK+residual experiment and return logged PPO metrics."""
    return trainer.train(env, ik_action_fn, total_timesteps)
