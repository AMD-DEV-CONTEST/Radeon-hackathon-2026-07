"""Sensor-only, route-conditioned TidyBot base policy.

The runtime boundary in this module is intentionally small: inference reads
only relative odometry from ``TidyBotSensorPacket`` and a fixed route expressed
in the robot's spawn frame.  World poses, MuJoCo state, geometric teachers, and
collision truth are not policy inputs.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import torch
from torch import nn

from realtime_cleanup.types import TidyBotBaseVelocityCommand, TidyBotSensorPacket


CHECKPOINT_FORMAT = "tidybot-route-policy-v1"
ACTION_NAMES = ("base.vx_body", "base.vy_body", "base.wz_body")
FEATURE_NAMES = (
    "base.x_spawn",
    "base.y_spawn",
    "base.yaw_sin",
    "base.yaw_cos",
    "base.vx_body",
    "base.vy_body",
    "base.wz_body",
    "waypoint.dx_body",
    "waypoint.dy_body",
    "waypoint.distance",
    "segment.heading_error_sin",
    "segment.heading_error_cos",
    "route.progress",
    "route.waypoint_index_fraction",
)
POLICY_OBSERVATION_FIELDS = (
    "packet.base_position",
    "packet.base_velocity",
    "fixed_route_spawn_frame",
    "route_progress",
    "waypoint_index",
)

# This is the same fixed, trailer-safe loop used by the option-D room preview.
WORLD_ROUTE = (
    (0.0, -2.70),
    (-1.00, -1.50),
    (-2.40, -1.50),
    (-2.80, -1.10),
    (-2.80, 0.80),
    (-2.50, 1.50),
    (-1.40, 2.40),
    (0.0, 2.50),
    (1.40, 2.40),
    (2.50, 1.50),
    (2.80, 0.80),
    (2.80, -1.10),
    (2.40, -1.50),
    (1.00, -1.50),
    (0.0, -2.50),
)
DEFAULT_SPAWN_WORLD_POSE = (0.0, -2.70, math.pi / 2.0)


def wrap_angle(angle: float) -> float:
    """Wrap an angle to ``[-pi, pi]``."""

    return math.atan2(math.sin(angle), math.cos(angle))


def _finite_vector(value: Any, size: int, name: str) -> np.ndarray:
    result = np.asarray(value, dtype=np.float32)
    if result.shape != (size,) or not np.isfinite(result).all():
        raise ValueError(f"{name} must be a finite {size}-vector")
    return result


def world_xy_to_spawn(
    point_world: tuple[float, float],
    spawn_world_pose: tuple[float, float, float],
) -> tuple[float, float]:
    """Express a world-frame point in the TidyBot spawn frame."""

    dx = float(point_world[0]) - float(spawn_world_pose[0])
    dy = float(point_world[1]) - float(spawn_world_pose[1])
    cosine = math.cos(float(spawn_world_pose[2]))
    sine = math.sin(float(spawn_world_pose[2]))
    return cosine * dx + sine * dy, -sine * dx + cosine * dy


def world_route_to_spawn(
    route_world: tuple[tuple[float, float], ...],
    spawn_world_pose: tuple[float, float, float],
) -> tuple[tuple[float, float], ...]:
    """Convert an offline world route into immutable runtime route coordinates."""

    return tuple(world_xy_to_spawn(point, spawn_world_pose) for point in route_world)


def body_relative_waypoint(
    base_position_spawn: Any,
    waypoint_spawn: tuple[float, float],
) -> np.ndarray:
    """Return spawn-frame waypoint displacement expressed in the current body frame."""

    pose = _finite_vector(base_position_spawn, 3, "base_position_spawn")
    dx = float(waypoint_spawn[0]) - float(pose[0])
    dy = float(waypoint_spawn[1]) - float(pose[1])
    cosine = math.cos(float(pose[2]))
    sine = math.sin(float(pose[2]))
    return np.asarray(
        [cosine * dx + sine * dy, -sine * dx + cosine * dy],
        dtype=np.float32,
    )


def spawn_velocity_from_body_twist(base_yaw_spawn: float, body_twist: Any) -> np.ndarray:
    """Rotate body ``vx/vy`` into spawn-frame velocity without changing ``wz``."""

    twist = _finite_vector(body_twist, 3, "body_twist")
    cosine = math.cos(float(base_yaw_spawn))
    sine = math.sin(float(base_yaw_spawn))
    return np.asarray(
        [
            cosine * float(twist[0]) - sine * float(twist[1]),
            sine * float(twist[0]) + cosine * float(twist[1]),
            float(twist[2]),
        ],
        dtype=np.float32,
    )


def integrate_body_twist(base_position_spawn: Any, body_twist: Any, dt: float) -> np.ndarray:
    """Kinematic integration used only by the offline data generator."""

    if not math.isfinite(dt) or dt <= 0.0:
        raise ValueError("dt must be positive and finite")
    pose = _finite_vector(base_position_spawn, 3, "base_position_spawn")
    velocity_spawn = spawn_velocity_from_body_twist(float(pose[2]), body_twist)
    result = pose + velocity_spawn * float(dt)
    result[2] = wrap_angle(float(result[2]))
    return result.astype(np.float32)


@dataclass(frozen=True)
class FixedRouteConfig:
    """A fixed route represented entirely in spawn-frame coordinates."""

    waypoints_spawn: tuple[tuple[float, float], ...]
    waypoint_tolerance_m: float = 0.22
    name: str = "option_d_tidybot_room_loop_v1"
    _segment_lengths: tuple[float, ...] = field(init=False, repr=False)
    _cumulative_lengths: tuple[float, ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if len(self.waypoints_spawn) < 2:
            raise ValueError("a fixed route requires at least two waypoints")
        points: list[tuple[float, float]] = []
        for index, point in enumerate(self.waypoints_spawn):
            vector = _finite_vector(point, 2, f"waypoints_spawn[{index}]")
            points.append((float(vector[0]), float(vector[1])))
        if not math.isfinite(self.waypoint_tolerance_m) or self.waypoint_tolerance_m <= 0.0:
            raise ValueError("waypoint_tolerance_m must be positive and finite")
        if not self.name.strip():
            raise ValueError("route name must be non-empty")
        lengths = tuple(math.dist(start, end) for start, end in zip(points, points[1:]))
        if any(length <= 1e-6 for length in lengths):
            raise ValueError("consecutive route waypoints must be distinct")
        cumulative = [0.0]
        for length in lengths:
            cumulative.append(cumulative[-1] + length)
        object.__setattr__(self, "waypoints_spawn", tuple(points))
        object.__setattr__(self, "_segment_lengths", lengths)
        object.__setattr__(self, "_cumulative_lengths", tuple(cumulative))

    @property
    def total_length_m(self) -> float:
        return self._cumulative_lengths[-1]

    @property
    def sha256(self) -> str:
        encoded = json.dumps(
            self.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def segment_heading(self, target_index: int) -> float:
        if not 1 <= target_index < len(self.waypoints_spawn):
            raise IndexError(f"target waypoint index out of range: {target_index}")
        start = self.waypoints_spawn[target_index - 1]
        target = self.waypoints_spawn[target_index]
        return math.atan2(target[1] - start[1], target[0] - start[0])

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "frame": "spawn",
            "waypoints": [list(point) for point in self.waypoints_spawn],
            "waypoint_tolerance_m": self.waypoint_tolerance_m,
        }

    @classmethod
    def from_dict(cls, value: Any) -> FixedRouteConfig:
        if not isinstance(value, dict):
            raise TypeError("route config must be a dictionary")
        if value.get("frame") != "spawn":
            raise ValueError("route config frame must be spawn")
        waypoints = value.get("waypoints")
        if not isinstance(waypoints, (list, tuple)):
            raise TypeError("route config waypoints must be a sequence")
        parsed_waypoints = []
        for index, point in enumerate(waypoints):
            if not isinstance(point, (list, tuple)) or len(point) != 2:
                raise ValueError(f"route waypoint {index} must have two coordinates")
            parsed_waypoints.append((float(point[0]), float(point[1])))
        return cls(
            name=str(value.get("name", "")),
            waypoints_spawn=tuple(parsed_waypoints),
            waypoint_tolerance_m=float(value.get("waypoint_tolerance_m", 0.0)),
        )


def default_route_config() -> FixedRouteConfig:
    return FixedRouteConfig(
        waypoints_spawn=world_route_to_spawn(WORLD_ROUTE, DEFAULT_SPAWN_WORLD_POSE)
    )


@dataclass
class RouteTracker:
    """Ordered waypoint state updated exclusively from spawn-frame odometry."""

    config: FixedRouteConfig
    waypoint_index: int = 1
    reached_waypoints: int = 1
    completed: bool = False
    tolerance_margin_m: float = 0.0
    heading_tolerance_rad: float | None = None

    def __post_init__(self) -> None:
        if (
            not math.isfinite(self.tolerance_margin_m)
            or self.tolerance_margin_m < 0.0
        ):
            raise ValueError("tolerance_margin_m must be finite and non-negative")
        if self.heading_tolerance_rad is not None and (
            not math.isfinite(self.heading_tolerance_rad)
            or self.heading_tolerance_rad <= 0.0
        ):
            raise ValueError("heading_tolerance_rad must be positive when provided")

    def reset(self) -> None:
        self.waypoint_index = 1
        self.reached_waypoints = 1
        self.completed = False

    @property
    def target_index(self) -> int:
        return min(self.waypoint_index, len(self.config.waypoints_spawn) - 1)

    @property
    def current_waypoint(self) -> tuple[float, float]:
        return self.config.waypoints_spawn[self.target_index]

    @property
    def waypoint_index_fraction(self) -> float:
        if self.completed:
            return 1.0
        return self.target_index / (len(self.config.waypoints_spawn) - 1)

    def update(self, base_position_spawn: Any) -> bool:
        pose = _finite_vector(base_position_spawn, 3, "base_position_spawn")
        advanced = False
        while not self.completed:
            target = self.config.waypoints_spawn[self.waypoint_index]
            if math.dist((float(pose[0]), float(pose[1])), target) > (
                self.config.waypoint_tolerance_m + self.tolerance_margin_m
            ):
                break
            if self.heading_tolerance_rad is not None:
                yaw_error = abs(
                    wrap_angle(
                        self.config.segment_heading(self.waypoint_index)
                        - float(pose[2])
                    )
                )
                if yaw_error > self.heading_tolerance_rad:
                    break
            self.reached_waypoints = self.waypoint_index + 1
            self.waypoint_index += 1
            advanced = True
            if self.waypoint_index >= len(self.config.waypoints_spawn):
                self.completed = True
        return advanced

    def progress(self, base_position_spawn: Any) -> float:
        if self.completed:
            return 1.0
        pose = _finite_vector(base_position_spawn, 3, "base_position_spawn")
        index = self.target_index
        start = np.asarray(self.config.waypoints_spawn[index - 1], dtype=np.float64)
        target = np.asarray(self.config.waypoints_spawn[index], dtype=np.float64)
        delta = target - start
        projection = float(np.dot(pose[:2] - start, delta) / np.dot(delta, delta))
        projection = float(np.clip(projection, 0.0, 1.0))
        travelled = (
            self.config._cumulative_lengths[index - 1]
            + projection * self.config._segment_lengths[index - 1]
        )
        return float(np.clip(travelled / self.config.total_length_m, 0.0, 1.0))


def route_policy_features(
    base_position_spawn: Any,
    base_velocity_body: Any,
    config: FixedRouteConfig,
    tracker: RouteTracker,
) -> np.ndarray:
    """Build the complete allowed policy input vector."""

    if tracker.config.sha256 != config.sha256:
        raise ValueError("tracker route does not match policy route")
    pose = _finite_vector(base_position_spawn, 3, "base_position_spawn")
    velocity = _finite_vector(base_velocity_body, 3, "base_velocity_body")
    target_index = tracker.target_index
    relative = body_relative_waypoint(pose, tracker.current_waypoint)
    heading_error = wrap_angle(config.segment_heading(target_index) - float(pose[2]))
    features = np.asarray(
        [
            float(pose[0]),
            float(pose[1]),
            math.sin(float(pose[2])),
            math.cos(float(pose[2])),
            float(velocity[0]),
            float(velocity[1]),
            float(velocity[2]),
            float(relative[0]),
            float(relative[1]),
            float(np.linalg.norm(relative)),
            math.sin(heading_error),
            math.cos(heading_error),
            tracker.progress(pose),
            tracker.waypoint_index_fraction,
        ],
        dtype=np.float32,
    )
    if features.shape != (len(FEATURE_NAMES),) or not np.isfinite(features).all():
        raise RuntimeError("route policy features are invalid")
    return features


def packet_route_policy_features(
    packet: TidyBotSensorPacket,
    config: FixedRouteConfig,
    tracker: RouteTracker,
) -> np.ndarray:
    """Read only the two odometry fields allowed at policy runtime."""

    return route_policy_features(
        packet.base_position,
        packet.base_velocity,
        config,
        tracker,
    )


@dataclass(frozen=True)
class RouteMLPConfig:
    input_dimension: int = len(FEATURE_NAMES)
    hidden_dimensions: tuple[int, ...] = (128, 128)
    action_scale: tuple[float, float, float] = (0.50, 0.50, 1.20)

    def __post_init__(self) -> None:
        if self.input_dimension != len(FEATURE_NAMES):
            raise ValueError("MLP input dimension does not match route features")
        if not self.hidden_dimensions or any(value <= 0 for value in self.hidden_dimensions):
            raise ValueError("hidden dimensions must be positive")
        scale = _finite_vector(self.action_scale, len(ACTION_NAMES), "action_scale")
        if np.any(scale <= 0.0):
            raise ValueError("action scales must be positive")

    def to_dict(self) -> dict[str, object]:
        return {
            "input_dimension": self.input_dimension,
            "hidden_dimensions": list(self.hidden_dimensions),
            "action_scale": list(self.action_scale),
            "activation": "SiLU",
            "output": "tanh_scaled_body_twist",
        }

    @classmethod
    def from_dict(cls, value: Any) -> RouteMLPConfig:
        if not isinstance(value, dict):
            raise TypeError("model config must be a dictionary")
        return cls(
            input_dimension=int(value["input_dimension"]),
            hidden_dimensions=tuple(int(item) for item in value["hidden_dimensions"]),
            action_scale=tuple(float(item) for item in value["action_scale"]),
        )


class RoutePolicyMLP(nn.Module):
    """A small learned policy; no route action table is stored in the model."""

    def __init__(self, config: RouteMLPConfig | None = None) -> None:
        super().__init__()
        self.config = config or RouteMLPConfig()
        layers: list[nn.Module] = []
        previous = self.config.input_dimension
        for hidden in self.config.hidden_dimensions:
            layers.extend((nn.Linear(previous, hidden), nn.SiLU()))
            previous = hidden
        layers.append(nn.Linear(previous, len(ACTION_NAMES)))
        self.network = nn.Sequential(*layers)
        self.register_buffer(
            "action_scale",
            torch.tensor(self.config.action_scale, dtype=torch.float32),
        )

    def forward(self, features: torch.Tensor) -> torch.Tensor:
        return torch.tanh(self.network(features)) * self.action_scale


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class TidyBotRoutePolicy:
    """Loaded PyTorch route policy with a sensor-only inference API."""

    def __init__(
        self,
        model: RoutePolicyMLP,
        route: FixedRouteConfig,
        feature_mean: torch.Tensor,
        feature_std: torch.Tensor,
        *,
        device: torch.device,
        checkpoint_path: Path,
        checkpoint_metadata: dict[str, object],
    ) -> None:
        self.model = model.to(device).eval()
        self.route = route
        self.feature_mean = feature_mean.to(device=device, dtype=torch.float32)
        self.feature_std = feature_std.to(device=device, dtype=torch.float32)
        self.device = device
        self.checkpoint_path = checkpoint_path
        self.checkpoint_sha256 = sha256_file(checkpoint_path)
        self.checkpoint_metadata = checkpoint_metadata

    @classmethod
    def load(cls, checkpoint_path: Path, *, device: str = "cpu") -> TidyBotRoutePolicy:
        path = Path(checkpoint_path)
        target_device = torch.device(device)
        payload = torch.load(path, map_location="cpu", weights_only=True)
        if not isinstance(payload, dict) or payload.get("format") != CHECKPOINT_FORMAT:
            raise ValueError(f"not a {CHECKPOINT_FORMAT} checkpoint")
        if tuple(payload.get("feature_names", ())) != FEATURE_NAMES:
            raise ValueError("checkpoint feature contract does not match runtime")
        if tuple(payload.get("action_names", ())) != ACTION_NAMES:
            raise ValueError("checkpoint action contract does not match runtime")
        if tuple(payload.get("policy_observation_fields", ())) != POLICY_OBSERVATION_FIELDS:
            raise ValueError("checkpoint policy observation boundary does not match runtime")
        route = FixedRouteConfig.from_dict(payload.get("route_config"))
        if payload.get("route_sha256") != route.sha256:
            raise ValueError("checkpoint route hash is invalid")
        model_config = RouteMLPConfig.from_dict(payload.get("model_config"))
        model = RoutePolicyMLP(model_config)
        state = payload.get("model_state_dict")
        if not isinstance(state, dict):
            raise TypeError("checkpoint has no model state dictionary")
        model.load_state_dict(state, strict=True)
        mean = torch.as_tensor(payload.get("feature_mean"), dtype=torch.float32)
        std = torch.as_tensor(payload.get("feature_std"), dtype=torch.float32)
        expected = (len(FEATURE_NAMES),)
        if mean.shape != expected or std.shape != expected:
            raise ValueError("checkpoint feature normalizer has the wrong shape")
        if not torch.isfinite(mean).all() or not torch.isfinite(std).all() or torch.any(std <= 0):
            raise ValueError("checkpoint feature normalizer is invalid")
        metadata = payload.get("training")
        if not isinstance(metadata, dict):
            raise TypeError("checkpoint training metadata is missing")
        return cls(
            model,
            route,
            mean,
            std,
            device=target_device,
            checkpoint_path=path,
            checkpoint_metadata=metadata,
        )

    @torch.inference_mode()
    def action(self, packet: TidyBotSensorPacket, tracker: RouteTracker) -> np.ndarray:
        if tracker.config.sha256 != self.route.sha256:
            raise ValueError("tracker route does not match loaded checkpoint")
        features = packet_route_policy_features(packet, self.route, tracker)
        tensor = torch.from_numpy(features).to(self.device)
        normalized = (tensor - self.feature_mean) / self.feature_std
        action = self.model(normalized.unsqueeze(0)).squeeze(0).cpu().numpy()
        if action.shape != (len(ACTION_NAMES),) or not np.isfinite(action).all():
            raise RuntimeError("route policy produced an invalid body twist")
        return action.astype(np.float32, copy=False)

    def command(
        self,
        packet: TidyBotSensorPacket,
        tracker: RouteTracker,
    ) -> TidyBotBaseVelocityCommand:
        return TidyBotBaseVelocityCommand(
            body_twist=self.action(packet, tracker),
            trace_id=f"route-policy:{packet.frame_id}:{tracker.target_index}",
        )
