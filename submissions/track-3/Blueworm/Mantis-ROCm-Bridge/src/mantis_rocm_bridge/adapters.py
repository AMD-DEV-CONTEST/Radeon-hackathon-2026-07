"""Pure semantic reordering helpers used before simulator-specific integration."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .contracts import ContractError


def reorder_named_vector(
    values: Sequence[float],
    source_order: Sequence[str],
    target_order: Sequence[str],
    source_to_target: Mapping[str, str],
) -> list[float]:
    """Reorder a vector by semantic names without changing units or ranges."""
    if len(values) != len(source_order):
        raise ContractError(
            f"vector length {len(values)} does not match source order length {len(source_order)}"
        )
    if set(source_to_target) != set(source_order):
        raise ContractError("semantic map must exactly cover the source order")
    if set(source_to_target.values()) != set(target_order):
        raise ContractError("semantic map must exactly cover the target order")
    by_target_name = {
        source_to_target[source_name]: float(value)
        for source_name, value in zip(source_order, values)
    }
    return [by_target_name[target_name] for target_name in target_order]


def reorder_source_state(values: Sequence[float], port: dict[str, Any]) -> list[float]:
    """Apply only the checked-in Tron-to-Mantis semantic reorder."""
    return reorder_named_vector(
        values,
        port["source"]["joint_order"],
        port["target"]["joint_order"],
        port["joint_map"],
    )


def adapt_source_action(values: Sequence[float], port: dict[str, Any]) -> list[float]:
    """Block action adaptation until unit/range and safety gates are resolved."""
    action_blockers = {
        "gripper_mapping_unverified",
        "joint_limits_not_frozen",
        "joint_limits_not_verified_in_sim",
        "normalization_stats_not_generated",
    }
    active = sorted(action_blockers.intersection(port.get("blockers", [])))
    if active:
        raise ContractError(
            "action adaptation is unsafe while these blockers remain: " + ", ".join(active)
        )
    return reorder_source_state(values, port)


def reorder_images(
    images: Mapping[str, Any],
    camera_map: Mapping[str, str],
    target_order: Sequence[str],
) -> dict[str, Any]:
    """Rename and order images without modifying pixels."""
    if set(images) != set(camera_map):
        missing = sorted(set(camera_map) - set(images))
        extra = sorted(set(images) - set(camera_map))
        raise ContractError(f"camera inputs disagree with contract; missing={missing}, extra={extra}")
    renamed = {camera_map[source_name]: image for source_name, image in images.items()}
    if set(renamed) != set(target_order):
        raise ContractError("camera map does not exactly cover target order")
    return {target_name: renamed[target_name] for target_name in target_order}
