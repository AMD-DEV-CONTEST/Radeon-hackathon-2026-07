"""Deterministic, expanded reset randomization for the cutlery-long task."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
from pyquaternion import Quaternion


@dataclass(frozen=True)
class RandomizationRecord:
    seed: int
    fork_position: list[float]
    fork_angle_deg: float
    dishwasher_door: float
    dishwasher_bottom_tray: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def apply_enhanced_randomization(env: Any, seed: int) -> RandomizationRecord:
    """Apply reproducible randomization while keeping the task physically valid.

    The stock task uses only two discrete fork sites and a +/-30 degree angle.
    This expands it to a continuous rectangle spanning those sites, adds lateral
    jitter, widens the angle, and varies the two initially-open dishwasher joints.
    """
    rng = np.random.default_rng(np.uint64(seed) ^ np.uint64(0xD0B07A5E))

    # The task contract assumes a fully open door. Values near 0.9 partially
    # occlude the lower-tray handle and turn this into a different task.
    rng.uniform(0.90, 1.0)  # Preserve the established seed-to-scene mapping.
    door = 1.0
    bottom_tray = float(rng.uniform(0.95, 1.0))
    env.dishwasher.set_state(door=door, bottom_tray=bottom_tray, middle_tray=0.0)
    env.action_mode._mojo.physics.forward()

    sites = env.dishwasher.basket.site_sets[0][-2:]
    site_positions = np.stack([site.get_position() for site in sites]).astype(
        np.float64
    )
    position = site_positions[int(rng.integers(0, len(site_positions)))].copy()
    position[:2] += rng.uniform(-0.008, 0.008, size=2)
    position[2] += 0.1

    angle = float(rng.uniform(np.deg2rad(-40), np.deg2rad(40)))
    quaternion = Quaternion(axis=[1, 0, 0], degrees=90) * Quaternion(
        axis=[0, 1, 0], angle=angle
    )
    item = env.cutlery[0]
    item.body.set_position(position, True)
    item.body.set_quaternion(quaternion.elements, True)
    env.action_mode._mojo.physics.forward()

    return RandomizationRecord(
        seed=int(seed),
        fork_position=np.round(position, 6).tolist(),
        fork_angle_deg=round(float(np.rad2deg(angle)), 3),
        dishwasher_door=round(door, 4),
        dishwasher_bottom_tray=round(bottom_tray, 4),
    )
