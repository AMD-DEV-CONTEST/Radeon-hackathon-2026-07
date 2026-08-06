"""Validation and exclusive persistence for WP-G3-CORR-015 boundary traces."""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = 1
WORK_PACKAGE_ID = "WP-G3-CORR-015"
DIAGNOSTIC_SEED = 1630
PHYSICAL_DOF_COUNT = 18
TARGET_PAIR = (
    "bowl2:bowl_link <> "
    "mantis:left_clamp_left_link:competition_rim_support_collision"
)
SNAPSHOT_LABELS = (
    "final_pre_release",
    "immediate_post_release",
    "pre_retreat",
    "retreat_step_1",
    "retreat_step_2",
)
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
SAME_CACHE_KEYS = (
    "physics_step",
    "policy_step",
    "command_segment",
    "commanded_qpos",
    "robot_qpos",
    "active_tcp_pose",
    "left_clamp_poses",
    "bowl2_pose",
    "bowl3_pose",
    "robot_bowl2_contact_pairs",
    "robot_bowl2_contact_pair_count",
    "target_pair_present",
    "robot_bowl2_contact_diagnostics",
    "bowl3_bowl2_contact_pairs",
    "bowl3_bowl2_contact_pair_count",
    "bowl3_bowl2_contact_diagnostics",
    "contact_cache_source_physics_step",
    "contact_cache_semantics",
    "observer_policy_step_delta",
    "observer_physics_step_delta",
)


def _require_integer(value: Any, *, name: str, minimum: int) -> int:
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
    for key in POSE_KEYS:
        if key not in value:
            raise ValueError(f"{name} is missing {key}")
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


def _validate_pairs(value: Any, *, name: str) -> list[str]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError(f"{name} must be a string sequence")
    pairs = list(value)
    if any(not isinstance(pair, str) or not pair for pair in pairs):
        raise ValueError(f"{name} contains a malformed pair")
    if pairs != sorted(pairs):
        raise ValueError(f"{name} must be sorted")
    return pairs


def _validate_contact_diagnostics(value: Any, *, name: str) -> None:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    for key in CONTACT_DIAGNOSTIC_KEYS:
        diagnostic = value.get(key)
        if not isinstance(diagnostic, Mapping):
            raise ValueError(f"{name}.{key} must be an object")
        shape = diagnostic.get("shape")
        if (
            isinstance(shape, (str, bytes))
            or not isinstance(shape, Sequence)
            or not shape
        ):
            raise ValueError(f"{name}.{key}.shape must be nonempty")
        dimensions = [
            _require_integer(
                dimension,
                name=f"{name}.{key}.shape",
                minimum=0,
            )
            for dimension in shape
        ]
        values = _finite_vector(
            diagnostic.get("values"),
            name=f"{name}.{key}.values",
        )
        if len(values) != math.prod(dimensions):
            raise ValueError(f"{name}.{key} shape/value length drift")


def _validate_command_segment(value: Any, *, name: str) -> None:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    if not isinstance(value.get("stage"), str) or not value["stage"]:
        raise ValueError(f"{name}.stage must be a nonempty string")
    if value.get("phase") not in {"interpolation", "settle"}:
        raise ValueError(f"{name}.phase drift")
    step = _require_integer(
        value.get("step_index"),
        name=f"{name}.step_index",
        minimum=1,
    )
    total = _require_integer(
        value.get("total_steps"),
        name=f"{name}.total_steps",
        minimum=1,
    )
    if step > total:
        raise ValueError(f"{name}.step_index exceeds total_steps")
    fraction = float(value.get("interpolation_fraction", float("nan")))
    if not math.isfinite(fraction) or not 0.0 <= fraction <= 1.0:
        raise ValueError(f"{name}.interpolation_fraction drift")
    for key in ("start_qpos", "target_qpos"):
        _finite_vector(
            value.get(key),
            name=f"{name}.{key}",
            length=PHYSICAL_DOF_COUNT,
        )


def validate_boundary_trace(payload: Mapping[str, Any]) -> None:
    """Fail closed if a five-snapshot cached boundary trace is incomplete."""

    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("boundary trace schema_version drift")
    if payload.get("work_package_id") != WORK_PACKAGE_ID:
        raise ValueError("boundary trace work_package_id drift")
    if payload.get("seed") != DIAGNOSTIC_SEED:
        raise ValueError("boundary trace seed drift")
    if payload.get("selected_bowl") != "bowl3":
        raise ValueError("boundary trace selected bowl drift")
    if payload.get("supporting_nonselected_bowl") != "bowl2":
        raise ValueError("boundary trace supporting bowl drift")
    if payload.get("active_side") != "left":
        raise ValueError("boundary trace active side drift")
    if payload.get("target_pair") != TARGET_PAIR:
        raise ValueError("boundary trace target pair drift")

    snapshots = payload.get("snapshots")
    if not isinstance(snapshots, list):
        raise ValueError("boundary trace snapshots must be a list")
    labels = tuple(
        snapshot.get("label") if isinstance(snapshot, Mapping) else None
        for snapshot in snapshots
    )
    if labels != SNAPSHOT_LABELS:
        raise ValueError("boundary trace snapshot order drift")

    by_label: dict[str, Mapping[str, Any]] = {}
    for snapshot in snapshots:
        if not isinstance(snapshot, Mapping):
            raise ValueError("boundary trace snapshot must be an object")
        label = str(snapshot["label"])
        physics_step = _require_integer(
            snapshot.get("physics_step"),
            name=f"{label}.physics_step",
            minimum=1,
        )
        _require_integer(
            snapshot.get("policy_step"),
            name=f"{label}.policy_step",
            minimum=0,
        )
        expected_weld = label == "final_pre_release"
        if snapshot.get("weld_registered") is not expected_weld:
            raise ValueError(f"{label} weld state drift")
        _validate_command_segment(
            snapshot.get("command_segment"),
            name=f"{label}.command_segment",
        )
        for key in ("commanded_qpos", "robot_qpos"):
            _finite_vector(
                snapshot.get(key),
                name=f"{label}.{key}",
                length=PHYSICAL_DOF_COUNT,
            )
        tcp_pose = snapshot.get("active_tcp_pose")
        if not isinstance(tcp_pose, Mapping) or tcp_pose.get("side") != "left":
            raise ValueError(f"{label} active TCP side drift")
        _validate_pose(tcp_pose, name=f"{label}.active_tcp_pose")
        clamp_poses = snapshot.get("left_clamp_poses")
        if not isinstance(clamp_poses, Mapping):
            raise ValueError(f"{label} left clamp poses are missing")
        if set(clamp_poses) != set(LEFT_CLAMP_LINKS):
            raise ValueError(f"{label} left clamp identity drift")
        for link_name in LEFT_CLAMP_LINKS:
            _validate_pose(
                clamp_poses[link_name],
                name=f"{label}.left_clamp_poses.{link_name}",
            )
        _validate_pose(snapshot.get("bowl2_pose"), name=f"{label}.bowl2_pose")
        _validate_pose(snapshot.get("bowl3_pose"), name=f"{label}.bowl3_pose")

        robot_pairs = _validate_pairs(
            snapshot.get("robot_bowl2_contact_pairs"),
            name=f"{label}.robot_bowl2_contact_pairs",
        )
        if snapshot.get("robot_bowl2_contact_pair_count") != len(robot_pairs):
            raise ValueError(f"{label} robot-bowl2 pair count drift")
        if snapshot.get("target_pair_present") is not (
            TARGET_PAIR in robot_pairs
        ):
            raise ValueError(f"{label} target-pair presence drift")
        _validate_contact_diagnostics(
            snapshot.get("robot_bowl2_contact_diagnostics"),
            name=f"{label}.robot_bowl2_contact_diagnostics",
        )

        support_pairs = _validate_pairs(
            snapshot.get("bowl3_bowl2_contact_pairs"),
            name=f"{label}.bowl3_bowl2_contact_pairs",
        )
        if snapshot.get("bowl3_bowl2_contact_pair_count") != len(
            support_pairs
        ):
            raise ValueError(f"{label} bowl3-bowl2 pair count drift")
        _validate_contact_diagnostics(
            snapshot.get("bowl3_bowl2_contact_diagnostics"),
            name=f"{label}.bowl3_bowl2_contact_diagnostics",
        )
        if (
            snapshot.get("contact_cache_source_physics_step")
            != physics_step
            or snapshot.get("contact_cache_semantics")
            != "most_recent_scene_step"
        ):
            raise ValueError(f"{label} contact-cache identity drift")
        if (
            snapshot.get("observer_policy_step_delta") != 0
            or snapshot.get("observer_physics_step_delta") != 0
        ):
            raise ValueError(f"{label} observer advanced the clock")
        by_label[label] = snapshot

    pre = by_label["final_pre_release"]
    post = by_label["immediate_post_release"]
    before_retreat = by_label["pre_retreat"]
    step1 = by_label["retreat_step_1"]
    step2 = by_label["retreat_step_2"]
    if post["physics_step"] <= pre["physics_step"]:
        raise ValueError("release must advance beyond final_pre_release")
    for key in SAME_CACHE_KEYS:
        if post.get(key) != before_retreat.get(key):
            raise ValueError(
                f"immediate_post_release/pre_retreat same-cache drift: {key}"
            )
    if step1["physics_step"] != before_retreat["physics_step"] + 1:
        raise ValueError("retreat_step_1 physics-step drift")
    if step2["physics_step"] != step1["physics_step"] + 1:
        raise ValueError("retreat_step_2 physics-step drift")
    for index, snapshot in enumerate((step1, step2), start=1):
        segment = snapshot["command_segment"]
        if (
            segment.get("stage") != "bowl3:retreat"
            or segment.get("phase") != "interpolation"
            or segment.get("step_index") != index
            or segment.get("total_steps") < 2
        ):
            raise ValueError(f"retreat_step_{index} command context drift")
        expected_fraction = index / int(segment["total_steps"])
        if not math.isclose(
            float(segment["interpolation_fraction"]),
            expected_fraction,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ValueError(
                f"retreat_step_{index} interpolation fraction drift"
            )


def classify_earliest_target_pair(payload: Mapping[str, Any]) -> str:
    """Return the frozen earliest-presence terminal after validation."""

    validate_boundary_trace(payload)
    snapshots = {
        snapshot["label"]: snapshot for snapshot in payload["snapshots"]
    }
    if snapshots["final_pre_release"]["target_pair_present"]:
        return "COMPLETE_TARGET_CONTACT_PRESENT_FINAL_PRE_RELEASE"
    if snapshots["immediate_post_release"]["target_pair_present"]:
        return "COMPLETE_TARGET_CONTACT_FIRST_PRESENT_POST_RELEASE"
    if snapshots["retreat_step_1"]["target_pair_present"]:
        return "COMPLETE_TARGET_CONTACT_FIRST_PRESENT_RETREAT_STEP_1"
    if snapshots["retreat_step_2"]["target_pair_present"]:
        return "COMPLETE_TARGET_CONTACT_FIRST_PRESENT_RETREAT_STEP_2"
    return "COMPLETE_TARGET_CONTACT_ABSENT_THROUGH_RETREAT_STEP_2"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_boundary_trace_exclusive(
    path: Path,
    payload: Mapping[str, Any],
) -> str:
    """Validate and durably create one complete trace without overwrite."""

    validate_boundary_trace(payload)
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
