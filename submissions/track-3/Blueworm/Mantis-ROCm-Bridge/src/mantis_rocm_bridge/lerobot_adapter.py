"""Pure Mantis LeRobot feature adapters shared by Genesis and deployment code."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from .contracts import ContractError
from .gripper import physical_to_virtual, virtual_to_physical


def _ordered_feature_vector(
    features: Mapping[str, float], names: Sequence[str], context: str
) -> list[float]:
    if set(features) != set(names):
        missing = sorted(set(names) - set(features))
        extra = sorted(set(features) - set(names))
        raise ContractError(f"{context} feature mismatch: missing={missing}, extra={extra}")
    values = [float(features[name]) for name in names]
    if not all(math.isfinite(value) for value in values):
        raise ContractError(f"{context} contains non-finite values")
    return values


def policy_vector_to_features(
    values: Sequence[float], interface: dict[str, Any], *, kind: str
) -> dict[str, float]:
    if kind not in ("state", "action"):
        raise ContractError("LeRobot feature kind must be state or action")
    names = interface[f"{kind}_names"]
    if len(values) != len(names):
        raise ContractError(f"Mantis {kind} vector length must be {len(names)}")
    vector = [float(value) for value in values]
    if not all(math.isfinite(value) for value in vector):
        raise ContractError(f"Mantis {kind} vector contains non-finite values")
    return dict(zip(names, vector))


def features_to_policy_vector(
    features: Mapping[str, float], interface: dict[str, Any], *, kind: str
) -> list[float]:
    if kind not in ("state", "action"):
        raise ContractError("LeRobot feature kind must be state or action")
    return _ordered_feature_vector(features, interface[f"{kind}_names"], kind)


def physical_qpos_to_lerobot_state(
    physical_qpos: Sequence[float],
    port: dict[str, Any],
    interface: dict[str, Any],
    *,
    allow_unverified_gripper: bool = False,
    gripper_pair_tolerance: float = 1e-5,
    gripper_range_tolerance: float = 1e-7,
) -> dict[str, float]:
    virtual = physical_to_virtual(
        physical_qpos,
        port,
        allow_unverified=allow_unverified_gripper,
        pair_tolerance=gripper_pair_tolerance,
        range_tolerance=gripper_range_tolerance,
    )
    return policy_vector_to_features(virtual, interface, kind="state")


def lerobot_action_to_physical_qpos(
    action: Mapping[str, float],
    port: dict[str, Any],
    interface: dict[str, Any],
    *,
    allow_unverified_gripper: bool = False,
) -> list[float]:
    virtual = features_to_policy_vector(action, interface, kind="action")
    return virtual_to_physical(
        virtual,
        port,
        allow_unverified=allow_unverified_gripper,
    )


def pack_policy_observation(
    state: Mapping[str, float],
    images: Mapping[str, Any],
    interface: dict[str, Any],
) -> dict[str, Any]:
    """Bind named robot features and exact camera roles to policy input keys."""

    state_vector = features_to_policy_vector(state, interface, kind="state")
    expected_cameras = interface["camera_features"]
    if set(images) != set(expected_cameras):
        missing = sorted(set(expected_cameras) - set(images))
        extra = sorted(set(images) - set(expected_cameras))
        raise ContractError(
            f"Mantis camera feature mismatch: missing={missing}, extra={extra}"
        )
    return {"observation.state": state_vector, **dict(images)}
