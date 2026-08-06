"""Reproducible episode-level domain randomization for the pick-place task."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import numpy as np


@dataclass(frozen=True)
class TaskRandomizationConfig:
    """Ranges chosen to remain reachable by the default Panda workspace."""

    mass_range: tuple[float, float] = (0.05, 0.25)
    friction_range: tuple[float, float] = (0.5, 1.2)
    object_position_low: tuple[float, float, float] = (0.56, -0.12, 0.04)
    object_position_high: tuple[float, float, float] = (0.70, 0.12, 0.04)
    goal_position_low: tuple[float, float, float] = (0.40, 0.16, 0.04)
    goal_position_high: tuple[float, float, float] = (0.54, 0.30, 0.04)


def make_domain_randomizer(
    config: TaskRandomizationConfig, *, seed: int
) -> Callable[[], dict[str, Any]]:
    """Return a deterministic sampler with independent samples per reset."""
    generator = np.random.default_rng(seed)
    object_low = np.asarray(config.object_position_low, dtype=np.float32)
    object_high = np.asarray(config.object_position_high, dtype=np.float32)
    goal_low = np.asarray(config.goal_position_low, dtype=np.float32)
    goal_high = np.asarray(config.goal_position_high, dtype=np.float32)

    def sample() -> dict[str, Any]:
        return {
            "mass": float(generator.uniform(*config.mass_range)),
            "friction": float(generator.uniform(*config.friction_range)),
            "object_position": generator.uniform(object_low, object_high).astype(np.float32),
            "goal_position": generator.uniform(goal_low, goal_high).astype(np.float32),
        }

    return sample
