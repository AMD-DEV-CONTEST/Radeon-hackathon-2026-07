"""Versioned TidyBot workspace contract and simulator-independent geometry.

This module deliberately has no MuJoCo dependency.  The calibration tool may use
simulator ground truth to measure the workspace, but object poses, ``xpos``,
contacts, teacher paths, and other privileged values produced there are never
valid policy observations.  They belong only in the dataset ``annotations/``
sidecar.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


SCHEMA_VERSION = 1
CONTRACT_NAME = "tidybot_dataset_v1"
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "configs" / (
    "tidybot_dataset_v1.json"
)
CAMERA_SEMANTICS = ("nav", "workspace", "goal", "wrist", "basket")
EXPECTED_CAMERA_LAYERS = {
    "docking": ("nav", "workspace", "goal"),
    "manipulation": ("workspace", "wrist", "basket"),
    "mobile_cleanup": ("nav", "workspace", "wrist", "basket"),
}


class WorkspaceConfigError(ValueError):
    """Raised when a workspace contract is malformed or unsupported."""


def _finite_number(value: object, path: str) -> float:
    if type(value) not in (int, float):
        raise WorkspaceConfigError(f"{path} must be a JSON number")
    result = float(value)
    if not math.isfinite(result):
        raise WorkspaceConfigError(f"{path} must be finite")
    return result


def _integer(value: object, path: str) -> int:
    if type(value) is not int:
        raise WorkspaceConfigError(f"{path} must be a JSON integer")
    return value


def _string(value: object, path: str) -> str:
    if type(value) is not str or not value:
        raise WorkspaceConfigError(f"{path} must be a non-empty JSON string")
    return value


def _boolean(value: object, path: str) -> bool:
    if type(value) is not bool:
        raise WorkspaceConfigError(f"{path} must be a JSON boolean")
    return value


def _strict_object(
    value: object,
    path: str,
    expected_keys: Iterable[str],
) -> Mapping[str, Any]:
    if type(value) is not dict:
        raise WorkspaceConfigError(f"{path} must be a JSON object")
    expected = set(expected_keys)
    actual = set(value)
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    if missing or unknown:
        details = []
        if missing:
            details.append(f"missing={missing}")
        if unknown:
            details.append(f"unknown={unknown}")
        raise WorkspaceConfigError(f"{path} has invalid keys ({', '.join(details)})")
    return value


def _string_list(value: object, path: str) -> tuple[str, ...]:
    if type(value) is not list:
        raise WorkspaceConfigError(f"{path} must be a JSON array")
    result = tuple(_string(item, f"{path}[{index}]") for index, item in enumerate(value))
    if len(set(result)) != len(result):
        raise WorkspaceConfigError(f"{path} must not contain duplicate semantics")
    return result


def _require_positive(value: float, path: str, *, allow_zero: bool = False) -> None:
    valid = value >= 0.0 if allow_zero else value > 0.0
    if not valid:
        relation = "non-negative" if allow_zero else "positive"
        raise WorkspaceConfigError(f"{path} must be {relation}")


@dataclass(frozen=True)
class BaseTwistLimits:
    """Absolute body-frame velocity limits in SI units."""

    frame: str
    convention: str
    max_abs_vx_mps: float
    max_abs_vy_mps: float
    max_abs_wz_radps: float

    def __post_init__(self) -> None:
        if self.frame != "base_link":
            raise WorkspaceConfigError("base_twist_limits.frame must be 'base_link'")
        if self.convention != "x_forward_y_left_yaw_ccw":
            raise WorkspaceConfigError(
                "base_twist_limits.convention must be 'x_forward_y_left_yaw_ccw'"
            )
        for name in ("max_abs_vx_mps", "max_abs_vy_mps", "max_abs_wz_radps"):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value <= 0.0:
                raise WorkspaceConfigError(f"base_twist_limits.{name} must be finite and positive")

    def clamp(self, twist: BodyTwist | Sequence[float]) -> BodyTwist:
        """Clamp a body-frame twist without changing its coordinate semantics."""

        value = _as_twist(twist)
        return BodyTwist(
            vx_mps=max(-self.max_abs_vx_mps, min(self.max_abs_vx_mps, value.vx_mps)),
            vy_mps=max(-self.max_abs_vy_mps, min(self.max_abs_vy_mps, value.vy_mps)),
            wz_radps=max(-self.max_abs_wz_radps, min(self.max_abs_wz_radps, value.wz_radps)),
        )


@dataclass(frozen=True)
class CameraSource:
    """Source of one stable semantic RGB stream."""

    kind: str
    name: str

    def __post_init__(self) -> None:
        if self.kind not in ("model_camera", "derived_detector_crop"):
            raise WorkspaceConfigError(f"unsupported camera source kind: {self.kind!r}")
        if not self.name:
            raise WorkspaceConfigError("camera source name must not be empty")


@dataclass(frozen=True)
class CameraSemantics:
    """Semantic camera contract for all three dataset layers."""

    nav: CameraSource
    workspace: CameraSource
    goal: CameraSource
    wrist: CameraSource
    basket: CameraSource
    docking: tuple[str, ...]
    manipulation: tuple[str, ...]
    mobile_cleanup: tuple[str, ...]

    def __post_init__(self) -> None:
        sources = self.sources
        for semantic in ("nav", "workspace", "wrist", "basket"):
            if sources[semantic].kind != "model_camera":
                raise WorkspaceConfigError(f"camera_semantics.sources.{semantic} must be a camera")
        if self.goal.kind != "derived_detector_crop":
            raise WorkspaceConfigError(
                "camera_semantics.sources.goal must be a sensor-derived detector crop"
            )
        for layer, expected in EXPECTED_CAMERA_LAYERS.items():
            actual = tuple(getattr(self, layer))
            if actual != expected:
                raise WorkspaceConfigError(
                    f"camera_semantics.layers.{layer} must be {list(expected)!r}"
                )
            unknown = set(actual) - set(sources)
            if unknown:
                raise WorkspaceConfigError(
                    f"camera_semantics.layers.{layer} has unknown semantics {sorted(unknown)}"
                )

    @property
    def sources(self) -> dict[str, CameraSource]:
        return {
            "nav": self.nav,
            "workspace": self.workspace,
            "goal": self.goal,
            "wrist": self.wrist,
            "basket": self.basket,
        }

    @property
    def layers(self) -> dict[str, tuple[str, ...]]:
        return {
            "docking": self.docking,
            "manipulation": self.manipulation,
            "mobile_cleanup": self.mobile_cleanup,
        }


@dataclass(frozen=True)
class DockingEnvelope:
    """Target and settled-base tolerances expressed in the base frame."""

    forward_min_m: float
    forward_max_m: float
    lateral_tolerance_m: float
    yaw_tolerance_rad: float
    linear_speed_tolerance_mps: float
    angular_speed_tolerance_radps: float

    def __post_init__(self) -> None:
        values = {
            name: float(getattr(self, name))
            for name in (
                "forward_min_m",
                "forward_max_m",
                "lateral_tolerance_m",
                "yaw_tolerance_rad",
                "linear_speed_tolerance_mps",
                "angular_speed_tolerance_radps",
            )
        }
        if not all(math.isfinite(value) for value in values.values()):
            raise WorkspaceConfigError("docking_envelope values must be finite")
        if not 0.0 < self.forward_min_m < self.forward_max_m:
            raise WorkspaceConfigError(
                "docking_envelope requires 0 < forward_min_m < forward_max_m"
            )
        _require_positive(self.lateral_tolerance_m, "docking_envelope.lateral_tolerance_m")
        if not 0.0 < self.yaw_tolerance_rad < math.pi / 2.0:
            raise WorkspaceConfigError(
                "docking_envelope.yaw_tolerance_rad must be in (0, pi/2)"
            )
        _require_positive(
            self.linear_speed_tolerance_mps,
            "docking_envelope.linear_speed_tolerance_mps",
            allow_zero=True,
        )
        _require_positive(
            self.angular_speed_tolerance_radps,
            "docking_envelope.angular_speed_tolerance_radps",
            allow_zero=True,
        )

    @property
    def center_forward_m(self) -> float:
        return (self.forward_min_m + self.forward_max_m) / 2.0


@dataclass(frozen=True)
class GraspSuccessCriteria:
    minimum_lift_m: float
    stable_time_s: float

    def __post_init__(self) -> None:
        for name in ("minimum_lift_m", "stable_time_s"):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value <= 0.0:
                raise WorkspaceConfigError(f"grasp_success.{name} must be finite and positive")


@dataclass(frozen=True)
class FootprintEnvelope:
    """Conservative rigid base-plus-trailer rectangle in the base frame."""

    front_extent_m: float
    rear_extent_m: float
    half_width_m: float
    required_clearance_m: float

    def __post_init__(self) -> None:
        for name in ("front_extent_m", "rear_extent_m", "half_width_m"):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value <= 0.0:
                raise WorkspaceConfigError(f"footprint.{name} must be finite and positive")
        if not math.isfinite(self.required_clearance_m) or self.required_clearance_m < 0.0:
            raise WorkspaceConfigError(
                "footprint.required_clearance_m must be finite and non-negative"
            )


@dataclass(frozen=True)
class PolicyObservationBoundary:
    mujoco_truth_allowed: bool
    privileged_output: str

    def __post_init__(self) -> None:
        if self.mujoco_truth_allowed:
            raise WorkspaceConfigError(
                "MuJoCo truth is privileged and cannot enter policy observations"
            )
        if self.privileged_output != "annotations/":
            raise WorkspaceConfigError(
                "policy_observation.privileged_output must be the annotations/ sidecar"
            )


@dataclass(frozen=True)
class WorkspaceProvenance:
    model_path: str
    prototype_builder: str
    keyframe: str
    basis: str
    calibration_status: str

    def __post_init__(self) -> None:
        for name in (
            "model_path",
            "prototype_builder",
            "keyframe",
            "basis",
            "calibration_status",
        ):
            if not getattr(self, name):
                raise WorkspaceConfigError(f"provenance.{name} must not be empty")


@dataclass(frozen=True)
class TidyBotWorkspaceConfig:
    """The complete, versioned v1 workspace and dataset timing contract."""

    schema_version: int
    contract_name: str
    fps: int
    base_twist_limits: BaseTwistLimits
    camera_semantics: CameraSemantics
    docking_envelope: DockingEnvelope
    grasp_success: GraspSuccessCriteria
    footprint: FootprintEnvelope
    split_seed: int
    policy_observation: PolicyObservationBoundary
    provenance: WorkspaceProvenance

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise WorkspaceConfigError(
                f"unsupported schema_version {self.schema_version}; expected {SCHEMA_VERSION}"
            )
        if self.contract_name != CONTRACT_NAME:
            raise WorkspaceConfigError(
                f"contract_name must be {CONTRACT_NAME!r}, got {self.contract_name!r}"
            )
        if self.fps != 20:
            raise WorkspaceConfigError("tidybot_dataset_v1 is fixed at 20 Hz")
        if type(self.split_seed) is not int or not 0 <= self.split_seed < 2**32:
            raise WorkspaceConfigError("split_seed must be a uint32 JSON integer")

    @property
    def control_hz(self) -> int:
        return self.fps

    @property
    def control_period_s(self) -> float:
        return 1.0 / self.fps

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> TidyBotWorkspaceConfig:
        return _config_from_mapping(raw)

    @classmethod
    def load(cls, path: str | Path = DEFAULT_CONFIG_PATH) -> TidyBotWorkspaceConfig:
        return load_tidybot_workspace_config(path)

    def to_dict(self) -> dict[str, Any]:
        sources = {
            semantic: {"kind": source.kind, "name": source.name}
            for semantic, source in self.camera_semantics.sources.items()
        }
        return {
            "schema_version": self.schema_version,
            "contract_name": self.contract_name,
            "fps": self.fps,
            "base_twist_limits": {
                "frame": self.base_twist_limits.frame,
                "convention": self.base_twist_limits.convention,
                "max_abs_vx_mps": self.base_twist_limits.max_abs_vx_mps,
                "max_abs_vy_mps": self.base_twist_limits.max_abs_vy_mps,
                "max_abs_wz_radps": self.base_twist_limits.max_abs_wz_radps,
            },
            "camera_semantics": {
                "sources": sources,
                "layers": {
                    name: list(semantics)
                    for name, semantics in self.camera_semantics.layers.items()
                },
            },
            "docking_envelope": {
                "forward_min_m": self.docking_envelope.forward_min_m,
                "forward_max_m": self.docking_envelope.forward_max_m,
                "lateral_tolerance_m": self.docking_envelope.lateral_tolerance_m,
                "yaw_tolerance_rad": self.docking_envelope.yaw_tolerance_rad,
                "linear_speed_tolerance_mps": (
                    self.docking_envelope.linear_speed_tolerance_mps
                ),
                "angular_speed_tolerance_radps": (
                    self.docking_envelope.angular_speed_tolerance_radps
                ),
            },
            "grasp_success": {
                "minimum_lift_m": self.grasp_success.minimum_lift_m,
                "stable_time_s": self.grasp_success.stable_time_s,
            },
            "footprint": {
                "front_extent_m": self.footprint.front_extent_m,
                "rear_extent_m": self.footprint.rear_extent_m,
                "half_width_m": self.footprint.half_width_m,
                "required_clearance_m": self.footprint.required_clearance_m,
            },
            "split_seed": self.split_seed,
            "policy_observation": {
                "mujoco_truth_allowed": self.policy_observation.mujoco_truth_allowed,
                "privileged_output": self.policy_observation.privileged_output,
            },
            "provenance": {
                "model_path": self.provenance.model_path,
                "prototype_builder": self.provenance.prototype_builder,
                "keyframe": self.provenance.keyframe,
                "basis": self.provenance.basis,
                "calibration_status": self.provenance.calibration_status,
            },
        }


def _base_twist_from_raw(value: object) -> BaseTwistLimits:
    raw = _strict_object(
        value,
        "base_twist_limits",
        (
            "frame",
            "convention",
            "max_abs_vx_mps",
            "max_abs_vy_mps",
            "max_abs_wz_radps",
        ),
    )
    return BaseTwistLimits(
        frame=_string(raw["frame"], "base_twist_limits.frame"),
        convention=_string(raw["convention"], "base_twist_limits.convention"),
        max_abs_vx_mps=_finite_number(
            raw["max_abs_vx_mps"], "base_twist_limits.max_abs_vx_mps"
        ),
        max_abs_vy_mps=_finite_number(
            raw["max_abs_vy_mps"], "base_twist_limits.max_abs_vy_mps"
        ),
        max_abs_wz_radps=_finite_number(
            raw["max_abs_wz_radps"], "base_twist_limits.max_abs_wz_radps"
        ),
    )


def _camera_semantics_from_raw(value: object) -> CameraSemantics:
    raw = _strict_object(value, "camera_semantics", ("sources", "layers"))
    source_raw = _strict_object(
        raw["sources"],
        "camera_semantics.sources",
        CAMERA_SEMANTICS,
    )
    sources: dict[str, CameraSource] = {}
    for semantic in CAMERA_SEMANTICS:
        item = _strict_object(
            source_raw[semantic],
            f"camera_semantics.sources.{semantic}",
            ("kind", "name"),
        )
        sources[semantic] = CameraSource(
            kind=_string(item["kind"], f"camera_semantics.sources.{semantic}.kind"),
            name=_string(item["name"], f"camera_semantics.sources.{semantic}.name"),
        )
    layers = _strict_object(
        raw["layers"],
        "camera_semantics.layers",
        EXPECTED_CAMERA_LAYERS,
    )
    return CameraSemantics(
        **sources,
        **{
            layer: _string_list(layers[layer], f"camera_semantics.layers.{layer}")
            for layer in EXPECTED_CAMERA_LAYERS
        },
    )


def _docking_envelope_from_raw(value: object) -> DockingEnvelope:
    fields = (
        "forward_min_m",
        "forward_max_m",
        "lateral_tolerance_m",
        "yaw_tolerance_rad",
        "linear_speed_tolerance_mps",
        "angular_speed_tolerance_radps",
    )
    raw = _strict_object(value, "docking_envelope", fields)
    return DockingEnvelope(
        **{
            field: _finite_number(raw[field], f"docking_envelope.{field}")
            for field in fields
        }
    )


def _config_from_mapping(value: object) -> TidyBotWorkspaceConfig:
    fields = (
        "schema_version",
        "contract_name",
        "fps",
        "base_twist_limits",
        "camera_semantics",
        "docking_envelope",
        "grasp_success",
        "footprint",
        "split_seed",
        "policy_observation",
        "provenance",
    )
    raw = _strict_object(value, "$", fields)

    grasp_raw = _strict_object(
        raw["grasp_success"],
        "grasp_success",
        ("minimum_lift_m", "stable_time_s"),
    )
    footprint_fields = (
        "front_extent_m",
        "rear_extent_m",
        "half_width_m",
        "required_clearance_m",
    )
    footprint_raw = _strict_object(raw["footprint"], "footprint", footprint_fields)
    policy_raw = _strict_object(
        raw["policy_observation"],
        "policy_observation",
        ("mujoco_truth_allowed", "privileged_output"),
    )
    provenance_fields = (
        "model_path",
        "prototype_builder",
        "keyframe",
        "basis",
        "calibration_status",
    )
    provenance_raw = _strict_object(raw["provenance"], "provenance", provenance_fields)

    return TidyBotWorkspaceConfig(
        schema_version=_integer(raw["schema_version"], "schema_version"),
        contract_name=_string(raw["contract_name"], "contract_name"),
        fps=_integer(raw["fps"], "fps"),
        base_twist_limits=_base_twist_from_raw(raw["base_twist_limits"]),
        camera_semantics=_camera_semantics_from_raw(raw["camera_semantics"]),
        docking_envelope=_docking_envelope_from_raw(raw["docking_envelope"]),
        grasp_success=GraspSuccessCriteria(
            minimum_lift_m=_finite_number(
                grasp_raw["minimum_lift_m"], "grasp_success.minimum_lift_m"
            ),
            stable_time_s=_finite_number(
                grasp_raw["stable_time_s"], "grasp_success.stable_time_s"
            ),
        ),
        footprint=FootprintEnvelope(
            **{
                field: _finite_number(footprint_raw[field], f"footprint.{field}")
                for field in footprint_fields
            }
        ),
        split_seed=_integer(raw["split_seed"], "split_seed"),
        policy_observation=PolicyObservationBoundary(
            mujoco_truth_allowed=_boolean(
                policy_raw["mujoco_truth_allowed"],
                "policy_observation.mujoco_truth_allowed",
            ),
            privileged_output=_string(
                policy_raw["privileged_output"],
                "policy_observation.privileged_output",
            ),
        ),
        provenance=WorkspaceProvenance(
            **{
                field: _string(provenance_raw[field], f"provenance.{field}")
                for field in provenance_fields
            }
        ),
    )


def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise WorkspaceConfigError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _reject_nonfinite_json(token: str) -> None:
    raise WorkspaceConfigError(f"non-standard JSON constant {token!r} is forbidden")


def load_tidybot_workspace_config(
    path: str | Path = DEFAULT_CONFIG_PATH,
) -> TidyBotWorkspaceConfig:
    """Load a UTF-8 JSON contract with exact-key, type, and value validation."""

    config_path = Path(path)
    try:
        raw = json.loads(
            config_path.read_text(encoding="utf-8"),
            object_pairs_hook=_object_without_duplicates,
            parse_constant=_reject_nonfinite_json,
        )
    except json.JSONDecodeError as exc:
        raise WorkspaceConfigError(
            f"{config_path}: invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc
    return _config_from_mapping(raw)


@dataclass(frozen=True)
class Pose2D:
    x_m: float
    y_m: float
    yaw_rad: float

    def __post_init__(self) -> None:
        if not all(math.isfinite(float(value)) for value in (self.x_m, self.y_m, self.yaw_rad)):
            raise ValueError("Pose2D values must be finite")

    def as_tuple(self) -> tuple[float, float, float]:
        return (float(self.x_m), float(self.y_m), float(self.yaw_rad))


@dataclass(frozen=True)
class BodyTwist:
    vx_mps: float
    vy_mps: float
    wz_radps: float

    def __post_init__(self) -> None:
        if not all(
            math.isfinite(float(value)) for value in (self.vx_mps, self.vy_mps, self.wz_radps)
        ):
            raise ValueError("BodyTwist values must be finite")

    def as_tuple(self) -> tuple[float, float, float]:
        return (float(self.vx_mps), float(self.vy_mps), float(self.wz_radps))


@dataclass(frozen=True)
class DockingEvaluation:
    target_forward_m: float
    target_lateral_m: float
    bearing_error_rad: float
    linear_speed_mps: float
    angular_speed_radps: float
    forward_ok: bool
    lateral_ok: bool
    yaw_ok: bool
    linear_speed_ok: bool
    angular_speed_ok: bool

    @property
    def inside(self) -> bool:
        return all(
            (
                self.forward_ok,
                self.lateral_ok,
                self.yaw_ok,
                self.linear_speed_ok,
                self.angular_speed_ok,
            )
        )


def _values(value: object, length: int, name: str) -> tuple[float, ...]:
    try:
        result = tuple(float(item) for item in value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must contain {length} finite numbers") from exc
    if len(result) != length or not all(math.isfinite(item) for item in result):
        raise ValueError(f"{name} must contain {length} finite numbers")
    return result


def _as_pose(value: Pose2D | Sequence[float]) -> Pose2D:
    if isinstance(value, Pose2D):
        return value
    return Pose2D(*_values(value, 3, "base_pose_world"))


def _as_twist(value: BodyTwist | Sequence[float]) -> BodyTwist:
    if isinstance(value, BodyTwist):
        return value
    return BodyTwist(*_values(value, 3, "base_twist_body"))


def wrap_angle(angle_rad: float) -> float:
    """Wrap an angle to ``[-pi, pi)``."""

    if not math.isfinite(angle_rad):
        raise ValueError("angle must be finite")
    return (angle_rad + math.pi) % (2.0 * math.pi) - math.pi


def world_to_body_xy(
    point_world_xy: Sequence[float],
    base_pose_world: Pose2D | Sequence[float],
) -> tuple[float, float]:
    """Transform a world point to base ``(forward, left)`` coordinates."""

    point_x, point_y = _values(point_world_xy, 2, "point_world_xy")
    pose = _as_pose(base_pose_world)
    dx = point_x - pose.x_m
    dy = point_y - pose.y_m
    cosine = math.cos(pose.yaw_rad)
    sine = math.sin(pose.yaw_rad)
    return (cosine * dx + sine * dy, -sine * dx + cosine * dy)


def body_to_world_xy(
    point_body_xy: Sequence[float],
    base_pose_world: Pose2D | Sequence[float],
) -> tuple[float, float]:
    """Transform a base ``(forward, left)`` point to world coordinates."""

    forward, left = _values(point_body_xy, 2, "point_body_xy")
    pose = _as_pose(base_pose_world)
    cosine = math.cos(pose.yaw_rad)
    sine = math.sin(pose.yaw_rad)
    return (
        pose.x_m + cosine * forward - sine * left,
        pose.y_m + sine * forward + cosine * left,
    )


def evaluate_docking(
    target_world_xy: Sequence[float],
    base_pose_world: Pose2D | Sequence[float],
    base_twist_body: BodyTwist | Sequence[float],
    envelope: DockingEnvelope,
) -> DockingEvaluation:
    """Evaluate target placement and settled velocity against the envelope.

    The yaw error is the target bearing in the base frame.  A zero error means
    the base ``+x`` axis faces the target; this avoids requiring a privileged
    object orientation for a point-like grasp target.
    """

    forward, lateral = world_to_body_xy(target_world_xy, base_pose_world)
    twist = _as_twist(base_twist_body)
    bearing = math.atan2(lateral, forward)
    linear_speed = math.hypot(twist.vx_mps, twist.vy_mps)
    epsilon = 1e-12
    return DockingEvaluation(
        target_forward_m=forward,
        target_lateral_m=lateral,
        bearing_error_rad=bearing,
        linear_speed_mps=linear_speed,
        angular_speed_radps=abs(twist.wz_radps),
        forward_ok=(
            envelope.forward_min_m - epsilon
            <= forward
            <= envelope.forward_max_m + epsilon
        ),
        lateral_ok=abs(lateral) <= envelope.lateral_tolerance_m + epsilon,
        yaw_ok=abs(bearing) <= envelope.yaw_tolerance_rad + epsilon,
        linear_speed_ok=linear_speed <= envelope.linear_speed_tolerance_mps + epsilon,
        angular_speed_ok=(
            abs(twist.wz_radps) <= envelope.angular_speed_tolerance_radps + epsilon
        ),
    )


def target_is_in_docking_envelope(
    target_world_xy: Sequence[float],
    base_pose_world: Pose2D | Sequence[float],
    base_twist_body: BodyTwist | Sequence[float],
    envelope: DockingEnvelope,
) -> bool:
    """Return whether a sensed target is reachable and the base has settled."""

    return evaluate_docking(
        target_world_xy,
        base_pose_world,
        base_twist_body,
        envelope,
    ).inside


def generate_candidate_base_poses(
    target_world_xy: Sequence[float],
    envelope: DockingEnvelope,
    *,
    approach_yaws_rad: Sequence[float] | None = None,
    forward_offsets_m: Sequence[float] | None = None,
    lateral_offsets_m: Sequence[float] = (0.0,),
) -> tuple[Pose2D, ...]:
    """Generate deterministic base poses whose ``+x`` axes approach a target.

    ``approach_yaws_rad`` describes the base heading at the candidate.  The
    target position is then reconstructed from an in-envelope body-frame
    ``(forward, left)`` offset.  Candidates that violate the bearing/yaw
    tolerance are omitted.
    """

    target_x, target_y = _values(target_world_xy, 2, "target_world_xy")
    yaws = (
        tuple(2.0 * math.pi * index / 8.0 for index in range(8))
        if approach_yaws_rad is None
        else _values(
            approach_yaws_rad,
            len(approach_yaws_rad),
            "approach_yaws_rad",
        )
    )
    if not yaws:
        raise ValueError("approach_yaws_rad must not be empty")
    forward_values = (
        (envelope.center_forward_m,)
        if forward_offsets_m is None
        else _values(forward_offsets_m, len(forward_offsets_m), "forward_offsets_m")
    )
    lateral_values = _values(
        lateral_offsets_m,
        len(lateral_offsets_m),
        "lateral_offsets_m",
    )
    if not forward_values or not lateral_values:
        raise ValueError("candidate offsets must not be empty")
    if any(
        forward < envelope.forward_min_m or forward > envelope.forward_max_m
        for forward in forward_values
    ):
        raise ValueError("forward_offsets_m must lie inside the docking envelope")
    if any(abs(lateral) > envelope.lateral_tolerance_m for lateral in lateral_values):
        raise ValueError("lateral_offsets_m must lie inside the docking envelope")

    candidates: list[Pose2D] = []
    seen: set[tuple[float, float, float]] = set()
    for yaw in yaws:
        wrapped_yaw = wrap_angle(yaw)
        cosine = math.cos(wrapped_yaw)
        sine = math.sin(wrapped_yaw)
        for forward in forward_values:
            for lateral in lateral_values:
                pose = Pose2D(
                    x_m=target_x - (cosine * forward - sine * lateral),
                    y_m=target_y - (sine * forward + cosine * lateral),
                    yaw_rad=wrapped_yaw,
                )
                if not target_is_in_docking_envelope(
                    (target_x, target_y),
                    pose,
                    BodyTwist(0.0, 0.0, 0.0),
                    envelope,
                ):
                    continue
                key = tuple(round(value, 12) for value in pose.as_tuple())
                if key not in seen:
                    seen.add(key)
                    candidates.append(pose)
    if not candidates:
        raise ValueError("no requested offset satisfies the docking yaw tolerance")
    return tuple(candidates)


def footprint_corners_world(
    base_pose_world: Pose2D | Sequence[float],
    footprint: FootprintEnvelope,
    *,
    include_required_clearance: bool = False,
) -> tuple[tuple[float, float], ...]:
    """Return the rigid base-plus-trailer rectangle in world coordinates."""

    margin = footprint.required_clearance_m if include_required_clearance else 0.0
    body_corners = (
        (footprint.front_extent_m + margin, footprint.half_width_m + margin),
        (footprint.front_extent_m + margin, -footprint.half_width_m - margin),
        (-footprint.rear_extent_m - margin, -footprint.half_width_m - margin),
        (-footprint.rear_extent_m - margin, footprint.half_width_m + margin),
    )
    return tuple(body_to_world_xy(corner, base_pose_world) for corner in body_corners)


def minimum_footprint_clearance_m(
    base_pose_world: Pose2D | Sequence[float],
    obstacle_points_world: Iterable[Sequence[float]],
    footprint: FootprintEnvelope,
) -> float:
    """Signed minimum point clearance to the base-plus-trailer rectangle.

    Positive values are outside the physical footprint, zero lies on its edge,
    and negative values are collisions.  Occupancy-grid obstacle centers can be
    passed directly; callers should add half a grid cell to the required margin
    when they need cell-area rather than point clearance.
    """

    pose = _as_pose(base_pose_world)
    rectangle_center_x = (footprint.front_extent_m - footprint.rear_extent_m) / 2.0
    rectangle_half_x = (footprint.front_extent_m + footprint.rear_extent_m) / 2.0
    minimum = math.inf
    for point in obstacle_points_world:
        forward, lateral = world_to_body_xy(point, pose)
        qx = abs(forward - rectangle_center_x) - rectangle_half_x
        qy = abs(lateral) - footprint.half_width_m
        outside = math.hypot(max(qx, 0.0), max(qy, 0.0))
        inside = min(max(qx, qy), 0.0)
        minimum = min(minimum, outside + inside)
    return minimum


def footprint_has_clearance(
    base_pose_world: Pose2D | Sequence[float],
    obstacle_points_world: Iterable[Sequence[float]],
    footprint: FootprintEnvelope,
    *,
    required_clearance_m: float | None = None,
) -> bool:
    """Check static base, trailer, and safety-margin clearance."""

    required = (
        footprint.required_clearance_m
        if required_clearance_m is None
        else float(required_clearance_m)
    )
    if not math.isfinite(required) or required < 0.0:
        raise ValueError("required_clearance_m must be finite and non-negative")
    return minimum_footprint_clearance_m(
        base_pose_world,
        obstacle_points_world,
        footprint,
    ) + 1e-12 >= required


def path_has_footprint_clearance(
    base_poses_world: Iterable[Pose2D | Sequence[float]],
    obstacle_points_world: Iterable[Sequence[float]],
    footprint: FootprintEnvelope,
    *,
    required_clearance_m: float | None = None,
) -> bool:
    """Check sampled swept clearance for the rigid trailer footprint."""

    obstacles = tuple(tuple(point) for point in obstacle_points_world)
    return all(
        footprint_has_clearance(
            pose,
            obstacles,
            footprint,
            required_clearance_m=required_clearance_m,
        )
        for pose in base_poses_world
    )


def filter_clear_candidate_base_poses(
    candidates: Iterable[Pose2D | Sequence[float]],
    obstacle_points_world: Iterable[Sequence[float]],
    footprint: FootprintEnvelope,
    *,
    required_clearance_m: float | None = None,
) -> tuple[Pose2D, ...]:
    """Keep docking candidates with base and rear-trailer point clearance."""

    obstacles = tuple(tuple(point) for point in obstacle_points_world)
    result = []
    for candidate in candidates:
        pose = _as_pose(candidate)
        if footprint_has_clearance(
            pose,
            obstacles,
            footprint,
            required_clearance_m=required_clearance_m,
        ):
            result.append(pose)
    return tuple(result)
