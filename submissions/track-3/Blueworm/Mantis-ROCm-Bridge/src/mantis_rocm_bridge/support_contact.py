"""Pure validation helpers for WP-G3-CORR-012 support-contact evidence."""
from __future__ import annotations

import math
from typing import Any


SNAPSHOT_LABELS = (
    "contact_before_weld",
    "after_weld_registration",
    "final_pre_release",
    "immediate_post_release",
    "placed_after_stability",
)
DIAGNOSTIC_FIELDS = (
    "penetration",
    "force_a",
    "force_b",
    "normal",
    "position",
)


def _finite_numbers(values: Any, *, label: str) -> list[float]:
    if not isinstance(values, list):
        raise ValueError(f"{label} values must be a list")
    result: list[float] = []
    for raw in values:
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise ValueError(f"{label} contains a non-numeric value")
        value = float(raw)
        if not math.isfinite(value):
            raise ValueError(f"{label} contains a non-finite value")
        result.append(value)
    return result


def validate_support_contact_observation(
    observation: dict[str, Any],
    *,
    expected_level: int = 1,
) -> dict[str, Any]:
    """Validate one direct bowl-to-bowl release observation.

    This function is intentionally independent of Genesis. It verifies the
    serialized entity identity, cached-step semantics, finite contact
    diagnostics, and zero observer clock delta.
    """

    if observation.get("observability_schema") != (
        "relative_pose_robot_and_support_contact_trace_v2"
    ):
        raise ValueError("support-contact observability schema drift")
    if observation.get("level") != expected_level:
        raise ValueError("support-contact observation level drift")
    selected_name = observation.get("bowl")
    if not isinstance(selected_name, str) or not selected_name:
        raise ValueError("selected bowl name is missing")
    snapshots = observation.get("snapshots")
    if not isinstance(snapshots, list):
        raise ValueError("support-contact snapshots must be a list")
    labels = tuple(snapshot.get("label") for snapshot in snapshots)
    if labels != SNAPSHOT_LABELS:
        raise ValueError("support-contact snapshot order drift")

    by_label: dict[str, dict[str, Any]] = {}
    supporting_name: str | None = None
    for snapshot in snapshots:
        if not isinstance(snapshot, dict):
            raise ValueError("support-contact snapshot must be an object")
        label = str(snapshot["label"])
        if snapshot.get("support_contact_query_applicable") is not True:
            raise ValueError(f"{label} support query is not applicable")
        current_support = snapshot.get("supporting_bowl_name")
        if not isinstance(current_support, str) or not current_support:
            raise ValueError(f"{label} supporting bowl name is missing")
        if current_support == selected_name:
            raise ValueError(f"{label} selected and supporting bowl are identical")
        if supporting_name is None:
            supporting_name = current_support
        elif current_support != supporting_name:
            raise ValueError("supporting bowl identity changed across snapshots")

        physics_step = snapshot.get("physics_step")
        cache_step = snapshot.get("contact_cache_source_physics_step")
        if (
            isinstance(physics_step, bool)
            or not isinstance(physics_step, int)
            or physics_step < 0
            or cache_step != physics_step
        ):
            raise ValueError(f"{label} cached physics-step identity drift")
        if snapshot.get("contact_cache_semantics") != "most_recent_scene_step":
            raise ValueError(f"{label} cached-contact semantics drift")
        if (
            snapshot.get("observer_policy_step_delta") != 0
            or snapshot.get("observer_physics_step_delta") != 0
        ):
            raise ValueError(f"{label} support observation advanced the clock")

        pairs = snapshot.get("support_contact_pairs")
        if not isinstance(pairs, list) or not all(
            isinstance(pair, str) for pair in pairs
        ):
            raise ValueError(f"{label} support-contact pairs are malformed")
        if snapshot.get("support_contact_pair_count") != len(pairs):
            raise ValueError(f"{label} support-contact pair count drift")
        for pair in pairs:
            pair_labels = pair.split(" <> ")
            if len(pair_labels) != 2:
                raise ValueError(f"{label} malformed support-contact pair")
            if not any(item.startswith(f"{selected_name}:") for item in pair_labels):
                raise ValueError(f"{label} pair omits selected bowl")
            if not any(item.startswith(f"{current_support}:") for item in pair_labels):
                raise ValueError(f"{label} pair omits supporting bowl")

        diagnostics = snapshot.get("support_contact_diagnostics")
        if not isinstance(diagnostics, dict):
            raise ValueError(f"{label} support-contact diagnostics are missing")
        for field in DIAGNOSTIC_FIELDS:
            entry = diagnostics.get(field)
            if not isinstance(entry, dict):
                raise ValueError(f"{label} {field} diagnostics are missing")
            shape = entry.get("shape")
            if not isinstance(shape, list) or not all(
                isinstance(size, int) and not isinstance(size, bool) and size >= 0
                for size in shape
            ):
                raise ValueError(f"{label} {field} shape is malformed")
            _finite_numbers(entry.get("values"), label=f"{label} {field}")
        by_label[label] = snapshot

    pre = by_label["final_pre_release"]
    post = by_label["immediate_post_release"]
    if post["physics_step"] <= pre["physics_step"]:
        raise ValueError(
            "immediate_post_release must follow a physics-advanced release"
        )
    before_weld = by_label["contact_before_weld"]
    after_weld = by_label["after_weld_registration"]
    same_step_weld_pair = (
        before_weld["physics_step"] == after_weld["physics_step"]
    )
    return {
        "selected_bowl_name": selected_name,
        "supporting_bowl_name": supporting_name,
        "pre_release_support_contact_present": (
            pre["support_contact_pair_count"] > 0
        ),
        "pre_release_support_contact_pair_count": pre[
            "support_contact_pair_count"
        ],
        "post_release_support_contact_present": (
            post["support_contact_pair_count"] > 0
        ),
        "post_release_support_contact_pair_count": post[
            "support_contact_pair_count"
        ],
        "pre_release_physics_step": pre["physics_step"],
        "post_release_physics_step": post["physics_step"],
        "same_step_weld_snapshots_noncausal": same_step_weld_pair,
    }
