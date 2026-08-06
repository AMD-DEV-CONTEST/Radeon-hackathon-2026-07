"""Time-to-collision instrumentation and reward shaping for HighwayEnv.

The stock highway-env reward runs with ``normalize_reward=True``, which maps
the per-step reward onto [0, 1]. A collision therefore yields a reward of
*zero* rather than a negative value: the only cost of crashing is the loss of
future reward. At ``policy_frequency=5`` and ``gamma=0.95`` the agent only
looks about four seconds ahead, so maximising speed outweighs staying alive.

This module makes safety explicit. ``SafetyRewardWrapper`` always measures
time-to-collision and time headway so that every run -- shaped or not -- can
be scored on the same safety metrics, and optionally adds a penalty term that
trains the agent to keep a survivable gap.
"""

from __future__ import annotations

from dataclasses import dataclass

import gymnasium as gym
from highway_env.vehicle.kinematics import Vehicle


INFINITE = float("inf")

# Closing speeds below this are treated as non-converging, otherwise TTC
# explodes into meaningless values when both vehicles travel at one speed.
MIN_CLOSING_SPEED = 1e-3

# A step below this TTC counts as an unsafe-following violation when scoring.
TTC_VIOLATION_THRESHOLD = 1.5

# TTC is unbounded, so averages are taken over values clipped to this cap.
TTC_REPORTING_CAP = 30.0

REWARD_PROFILES: dict[str, dict] = {
    # Original-demo baseline: collision is worth 0 after normalisation.
    "baseline": {
        "normalize_reward": True,
        "collision_reward": -1.0,
        "shaping": False,
    },
    # Collision becomes a genuine negative reward, no shaping yet.
    "penalty": {
        "normalize_reward": False,
        "collision_reward": -5.0,
        "shaping": False,
    },
    # Collision penalty plus dense TTC / headway shaping.
    "ttc": {
        "normalize_reward": False,
        "collision_reward": -5.0,
        "shaping": True,
    },
}


@dataclass(frozen=True)
class SafetyMeasurement:
    """Safety state of the ego vehicle relative to the car in front."""

    ttc: float
    time_headway: float
    front_gap: float
    speed: float


def measure_safety(env: gym.Env) -> SafetyMeasurement:
    """Measure TTC and headway against the leading vehicle in the ego lane."""
    unwrapped = env.unwrapped
    ego = getattr(unwrapped, "vehicle", None)
    road = getattr(unwrapped, "road", None)

    if ego is None or road is None or ego.lane_index is None:
        return SafetyMeasurement(INFINITE, INFINITE, INFINITE, 0.0)

    speed = float(ego.speed)
    front, _ = road.neighbour_vehicles(ego, ego.lane_index)
    if front is None:
        return SafetyMeasurement(INFINITE, INFINITE, INFINITE, speed)

    # lane_distance_to is centre-to-centre; subtract one car length to get the
    # bumper-to-bumper gap.
    gap = max(float(ego.lane_distance_to(front)) - Vehicle.LENGTH, 0.0)
    closing_speed = speed - float(front.speed)

    if gap <= 0.0:
        ttc = 0.0
    elif closing_speed <= MIN_CLOSING_SPEED:
        ttc = INFINITE
    else:
        ttc = gap / closing_speed

    time_headway = gap / speed if speed > MIN_CLOSING_SPEED else INFINITE

    return SafetyMeasurement(ttc, time_headway, gap, speed)


class SafetyRewardWrapper(gym.Wrapper):
    """Expose TTC metrics in ``info`` and optionally penalise unsafe gaps.

    With ``shaping=False`` the reward is passed through untouched, so the
    wrapper can be attached to baseline and evaluation environments purely as
    instrumentation.
    """

    def __init__(
        self,
        env: gym.Env,
        *,
        shaping: bool = True,
        ttc_threshold: float = 4.0,
        ttc_weight: float = 0.75,
        headway_target: float = 1.2,
        headway_weight: float = 0.25,
    ) -> None:
        super().__init__(env)
        self.shaping = shaping
        self.ttc_threshold = ttc_threshold
        self.ttc_weight = ttc_weight
        self.headway_target = headway_target
        self.headway_weight = headway_weight

    def safety_penalty(self, measurement: SafetyMeasurement) -> float:
        """Return a penalty in [-(ttc_weight + headway_weight), 0]."""
        penalty = 0.0

        if measurement.ttc < self.ttc_threshold:
            severity = 1.0 - measurement.ttc / self.ttc_threshold
            penalty -= self.ttc_weight * severity

        if measurement.time_headway < self.headway_target:
            severity = 1.0 - measurement.time_headway / self.headway_target
            penalty -= self.headway_weight * severity

        return penalty

    def step(self, action):
        observation, reward, terminated, truncated, info = self.env.step(action)

        measurement = measure_safety(self.env)
        penalty = self.safety_penalty(measurement)

        info = dict(info)
        info["base_reward"] = float(reward)
        info["ttc"] = measurement.ttc
        info["time_headway"] = measurement.time_headway
        info["front_gap"] = measurement.front_gap
        info["safety_penalty"] = penalty

        if self.shaping:
            reward = float(reward) + penalty
        info["shaped_reward"] = float(reward)

        return observation, reward, terminated, truncated, info
