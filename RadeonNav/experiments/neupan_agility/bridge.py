"""Minimal contract between a NeuPAN path and quadrupedal-agility TSC."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from math import atan2, pi

import numpy as np


def wrap_to_pi(angle: float) -> float:
    return (angle + pi) % (2 * pi) - pi


@dataclass(frozen=True)
class WaypointCommand:
    current_xy: tuple[float, float]
    next_xy: tuple[float, float]
    delta_yaw: float
    delta_next_yaw: float
    yaw_clipped: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def path_to_tsc_waypoints(
    path: np.ndarray,
    pose: np.ndarray,
    current_lookahead: float = 0.35,
    next_lookahead: float = 0.70,
    max_abs_yaw: float = 0.60,
) -> WaypointCommand:
    """Select TSC-style current/next goal headings from a planar path."""
    if current_lookahead <= 0 or next_lookahead <= current_lookahead:
        raise ValueError("lookaheads must satisfy 0 < current < next")
    if max_abs_yaw <= 0:
        raise ValueError("max_abs_yaw must be positive")

    points = np.asarray(path, dtype=float)
    if points.ndim != 2 or points.shape[1] not in (2, 3) or len(points) == 0:
        raise ValueError("path must be point-major (N,2) or (N,3)")

    robot_pose = np.asarray(pose, dtype=float).reshape(-1)
    if robot_pose.size < 3:
        raise ValueError("pose must contain x, y, yaw")

    xy = points[:, :2]
    polyline = np.vstack([robot_pose[:2], xy])
    cumulative = np.concatenate(
        [[0.0], np.cumsum(np.linalg.norm(np.diff(polyline, axis=0), axis=1))]
    )

    def select(distance: float) -> np.ndarray:
        index = min(int(np.searchsorted(cumulative, distance)), len(polyline) - 1)
        return polyline[index]

    current = select(current_lookahead)
    following = select(next_lookahead)
    raw_yaws = [
        wrap_to_pi(atan2(point[1] - robot_pose[1], point[0] - robot_pose[0]) - robot_pose[2])
        for point in (current, following)
    ]
    clipped_yaws = [float(np.clip(yaw, -max_abs_yaw, max_abs_yaw)) for yaw in raw_yaws]
    return WaypointCommand(
        current_xy=(float(current[0]), float(current[1])),
        next_xy=(float(following[0]), float(following[1])),
        delta_yaw=clipped_yaws[0],
        delta_next_yaw=clipped_yaws[1],
        yaw_clipped=not np.allclose(raw_yaws, clipped_yaws),
    )


class ManeuverPhase(str, Enum):
    NORMAL = "NORMAL"
    PREPARE = "PREPARE"
    COMMITTED = "COMMITTED"
    RECOVERY = "RECOVERY"


class ManeuverWaypointGate:
    """Freeze planner intent while a non-interruptible maneuver is committed."""

    def __init__(self) -> None:
        self._accepted: WaypointCommand | None = None
        self._committed: WaypointCommand | None = None

    def apply(
        self,
        candidate: WaypointCommand,
        phase: ManeuverPhase,
        *,
        corridor_safe: bool = True,
        recovered: bool = False,
    ) -> WaypointCommand:
        # ponytail: phase is a simulator oracle until the G6 oracle baseline passes.
        if phase is ManeuverPhase.NORMAL:
            self._committed = None
            self._accepted = candidate
        elif phase is ManeuverPhase.PREPARE:
            if corridor_safe or self._accepted is None:
                self._accepted = candidate
        elif phase is ManeuverPhase.COMMITTED:
            if self._committed is None:
                self._committed = self._accepted or candidate
            self._accepted = self._committed
        elif phase is ManeuverPhase.RECOVERY:
            if recovered:
                self._committed = None
                self._accepted = candidate
            elif self._committed is not None:
                self._accepted = self._committed
        else:
            raise ValueError(f"unsupported phase: {phase}")
        return self._accepted or candidate
