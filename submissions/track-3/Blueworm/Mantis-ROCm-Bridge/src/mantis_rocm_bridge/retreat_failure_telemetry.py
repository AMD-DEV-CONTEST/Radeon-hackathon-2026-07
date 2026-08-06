"""Validation and exclusive persistence for WP-G3-CORR-014 telemetry."""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = 1
WORK_PACKAGE_ID = "WP-G3-CORR-014"
DIAGNOSTIC_SEED = 1630
PHYSICAL_DOF_COUNT = 18
POSE_KEYS = ("position_xyz_m", "quaternion_wxyz")
CONTACT_DIAGNOSTIC_KEYS = (
    "position",
    "penetration",
    "normal",
    "force_a",
    "force_b",
)
LEFT_CLAMP_LINKS = (
    "left_clamp_left_link",
    "left_clamp_right_link",
)


def _require_integer(
    value: Any,
    *,
    name: str,
    minimum: int,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return value


def _finite_vector(
    value: Any,
    *,
    name: str,
    length: int | None = None,
) -> list[float]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError(f"{name} must be a numeric sequence")
    result = [float(item) for item in value]
    if length is not None and len(result) != length:
        raise ValueError(
            f"{name} must contain {length} values, got {len(result)}"
        )
    if not all(math.isfinite(item) for item in result):
        raise ValueError(f"{name} contains a non-finite value")
    return result


def _validate_pose(value: Any, *, name: str) -> None:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    if tuple(key for key in POSE_KEYS if key not in value):
        raise ValueError(f"{name} is missing a required pose field")
    _finite_vector(
        value["position_xyz_m"],
        name=f"{name}.position_xyz_m",
        length=3,
    )
    quaternion = _finite_vector(
        value["quaternion_wxyz"],
        name=f"{name}.quaternion_wxyz",
        length=4,
    )
    norm = math.sqrt(sum(component * component for component in quaternion))
    if not math.isclose(norm, 1.0, rel_tol=0.0, abs_tol=1e-6):
        raise ValueError(f"{name}.quaternion_wxyz is not normalized")


def _validate_contact_diagnostics(value: Any) -> None:
    if not isinstance(value, Mapping):
        raise ValueError("contact_diagnostics must be an object")
    for key in CONTACT_DIAGNOSTIC_KEYS:
        diagnostic = value.get(key)
        if not isinstance(diagnostic, Mapping):
            raise ValueError(
                f"contact_diagnostics.{key} must be an object"
            )
        shape = diagnostic.get("shape")
        if (
            isinstance(shape, (str, bytes))
            or not isinstance(shape, Sequence)
            or not shape
        ):
            raise ValueError(
                f"contact_diagnostics.{key}.shape must be a nonempty sequence"
            )
        dimensions = [
            _require_integer(
                dimension,
                name=f"contact_diagnostics.{key}.shape",
                minimum=0,
            )
            for dimension in shape
        ]
        values = _finite_vector(
            diagnostic.get("values"),
            name=f"contact_diagnostics.{key}.values",
        )
        expected = math.prod(dimensions)
        if len(values) != expected:
            raise ValueError(
                f"contact_diagnostics.{key}.values length {len(values)} "
                f"does not match shape product {expected}"
            )


def validate_failure_telemetry(payload: Mapping[str, Any]) -> None:
    """Fail closed if a first-failure telemetry payload is incomplete."""

    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("failure telemetry schema_version drift")
    if payload.get("work_package_id") != WORK_PACKAGE_ID:
        raise ValueError("failure telemetry work_package_id drift")
    if payload.get("seed") != DIAGNOSTIC_SEED:
        raise ValueError("failure telemetry seed drift")
    for name in ("stage", "kind"):
        if not isinstance(payload.get(name), str) or not payload[name]:
            raise ValueError(f"{name} must be a nonempty string")
    for name in ("selected_bowl", "nonselected_bowl"):
        value = payload.get(name)
        if value is not None and (
            not isinstance(value, str) or not value
        ):
            raise ValueError(f"{name} must be null or a nonempty string")
    pairs = payload.get("pairs")
    if (
        isinstance(pairs, (str, bytes))
        or not isinstance(pairs, Sequence)
        or not pairs
        or any(not isinstance(pair, str) or not pair for pair in pairs)
    ):
        raise ValueError("pairs must be a nonempty string sequence")
    _require_integer(payload.get("sim_step"), name="sim_step", minimum=1)
    _require_integer(
        payload.get("policy_step"),
        name="policy_step",
        minimum=0,
    )
    policy_time = float(payload.get("policy_time_s", float("nan")))
    if not math.isfinite(policy_time) or policy_time < 0.0:
        raise ValueError("policy_time_s must be finite and nonnegative")
    if payload.get("observer_step_delta") != 0:
        raise ValueError("observer_step_delta must equal zero")

    segment = payload.get("command_segment")
    if not isinstance(segment, Mapping):
        raise ValueError("command_segment must be an object")
    if segment.get("stage") != payload["stage"]:
        raise ValueError("command_segment.stage must match stage")
    if segment.get("phase") not in {"interpolation", "settle"}:
        raise ValueError(
            "command_segment.phase must be interpolation or settle"
        )
    step_index = _require_integer(
        segment.get("step_index"),
        name="command_segment.step_index",
        minimum=1,
    )
    total_steps = _require_integer(
        segment.get("total_steps"),
        name="command_segment.total_steps",
        minimum=1,
    )
    if step_index > total_steps:
        raise ValueError(
            "command_segment.step_index exceeds total_steps"
        )
    fraction = float(
        segment.get("interpolation_fraction", float("nan"))
    )
    if not math.isfinite(fraction) or not 0.0 <= fraction <= 1.0:
        raise ValueError(
            "command_segment.interpolation_fraction must be in [0, 1]"
        )
    for name in ("start_qpos", "target_qpos"):
        _finite_vector(
            segment.get(name),
            name=f"command_segment.{name}",
            length=PHYSICAL_DOF_COUNT,
        )

    for name in ("commanded_qpos", "robot_qpos"):
        _finite_vector(
            payload.get(name),
            name=name,
            length=PHYSICAL_DOF_COUNT,
        )
    _validate_pose(payload.get("active_tcp_pose"), name="active_tcp_pose")
    clamp_poses = payload.get("left_clamp_poses")
    if not isinstance(clamp_poses, Mapping):
        raise ValueError("left_clamp_poses must be an object")
    if set(clamp_poses) != set(LEFT_CLAMP_LINKS):
        raise ValueError("left_clamp_poses link identity drift")
    for link_name in LEFT_CLAMP_LINKS:
        _validate_pose(
            clamp_poses[link_name],
            name=f"left_clamp_poses.{link_name}",
        )
    _validate_pose(payload.get("bowl2_pose"), name="bowl2_pose")
    _validate_pose(payload.get("bowl3_pose"), name="bowl3_pose")
    _validate_contact_diagnostics(payload.get("contact_diagnostics"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_failure_telemetry_exclusive(
    path: Path,
    payload: Mapping[str, Any],
) -> str:
    """Validate and durably create one telemetry artifact without overwrite."""

    validate_failure_telemetry(payload)
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o664)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            descriptor = -1
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    return sha256_file(path)
