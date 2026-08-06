"""Factories that adapt a Genesis task to the vectorized RL interface."""

from __future__ import annotations

from collections.abc import Callable

import gymnasium as gym

from .genesis_env import GenesisPickPlaceEnv


def make_flattened_env(factory: Callable[[], GenesisPickPlaceEnv]) -> Callable[[], gym.Env]:
    """Return a thunk for ``SyncVectorEnv`` with deterministic flat state input.

    Visual observations should use a dedicated encoder instead of this generic
    flattening path because raw image flattening is prohibitively high-dimensional.
    """

    def build() -> gym.Env:
        return gym.wrappers.FlattenObservation(factory())

    return build
